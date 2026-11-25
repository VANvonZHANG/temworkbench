import { z } from "zod"

const binning = z.union([z.literal(1), z.literal(2), z.literal(4)])
export const exposure = z.object({
  exposure_s: z.number().min(0.01).max(2),
  binning,
})

const stage = z.object({ x_nm: z.number(), y_nm: z.number() })
const device = z.object({
  microscope: z.string(),
  camera: z.string(),
  beam_energy_kev: z.number(),
  beam_blanked: z.boolean(),
  magnification: z.number(),
  brightness: z.number(),
  defocus_ticks: z.number(),
  stage,
  stage_z_nm: z.number(),
  tilt_alpha_deg: z.number(),
  mode: z.string(),
  pixel_size_nm: z.number().nullable(),
})
const state = z.object({
  device,
  stopped: z.boolean(),
  device_connected: z.boolean(),
})

const adjustment = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("set_magnification"), value: z.number() }),
  z.object({ kind: z.literal("set_brightness"), value: z.number() }),
  z.object({ kind: z.literal("set_defocus"), ticks: z.number() }),
  stage.extend({ kind: z.literal("move_stage") }),
])
const acquisition = exposure.extend({ kind: z.literal("acquire_image"), comment: z.string() })
const job = z.object({
  session_id: z.string().regex(/^[a-z0-9][a-z0-9_-]{0,63}$/),
  command_id: z.guid(),
  command: z.union([acquisition, adjustment]),
  status: z.enum(["pending_approval", "rejected", "queued", "running", "succeeded", "failed", "canceled"]),
  error: z.string().nullable(),
})
const pendingApproval = job.extend({
  command: adjustment,
  status: z.literal("pending_approval"),
})
const errorResponse = z.object({ detail: z.string() })
export const previewError = z.object({ error: z.string() })

export type Exposure = z.infer<typeof exposure>
export type Device = z.infer<typeof device>
export type DeviceState = z.infer<typeof state>
export type Job = z.infer<typeof job>
export type JobRef = Pick<Job, "session_id" | "command_id">
export type Approval = z.infer<typeof pendingApproval>
export type FileFormat = "hspy" | "tiff"

export interface Dashboard {
  state: DeviceState
  approvals: Approval[]
}

export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "The request failed."
}

const jobPath = (ref: JobRef) =>
  `/api/jobs/${encodeURIComponent(ref.session_id)}/${encodeURIComponent(ref.command_id)}`

export const jobKey = (ref: JobRef) => `${ref.session_id}/${ref.command_id}`

export function createClient(token: string, sessionId: string) {
  const authorization = `Bearer ${token}`

  async function request(path: string, options: RequestInit) {
    const headers = new Headers(options.headers)
    headers.set("Authorization", authorization)
    if (options.body) headers.set("Content-Type", "application/json")
    const response = await fetch(path, { ...options, headers })
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null)
      const parsed = errorResponse.safeParse(body)
      throw new Error(parsed.success ? parsed.data.detail : `Request failed (${response.status}).`)
    }
    return response
  }

  async function json<T>(path: string, schema: z.ZodType<T>, options: RequestInit): Promise<T> {
    const response = await request(path, options)
    const raw: unknown = await response.json()
    const parsed = schema.safeParse(raw)
    if (!parsed.success) throw new Error("The workbench returned an unexpected response.")
    return parsed.data
  }

  return {
    sessionId,
    state: (signal: AbortSignal) => json(`/api/state?session_id=${encodeURIComponent(sessionId)}`, state, { signal }),
    approvals: (signal: AbortSignal) => json("/api/operator/approvals", z.array(pendingApproval), { signal }),
    job: (ref: JobRef, signal: AbortSignal) => json(jobPath(ref), job, { signal }),
    decide: (ref: JobRef, allow: boolean, signal: AbortSignal) =>
      json(`/api/operator/approvals/${jobKey(ref)}?allow=${allow}`, job, { method: "POST", signal }),
    stop: (signal: AbortSignal) => json("/api/operator/stop", device, { method: "POST", signal }),
    async acquire(command: z.infer<typeof acquisition>, signal: AbortSignal) {
      const ref = { session_id: sessionId, command_id: crypto.randomUUID() }
      const options = { method: "POST", body: JSON.stringify({ ...ref, command }), signal }
      try {
        return await json("/api/commands", job, options)
      } catch (error) {
        if (!(error instanceof TypeError) || signal.aborted) throw error
        return json("/api/commands", job, options)
      }
    },
    async download(ref: JobRef, format: FileFormat, signal: AbortSignal) {
      const response = await request(`${jobPath(ref)}/files/${format}`, { signal })
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement("a")
      link.href = url
      link.download = `${ref.command_id}.${format}`
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    },
    openPreview() {
      const url = new URL("/api/preview", window.location.href)
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
      const socket = new WebSocket(url)
      socket.binaryType = "blob"
      socket.addEventListener("open", () => socket.send(authorization), { once: true })
      return socket
    },
  }
}

export type WorkbenchClient = ReturnType<typeof createClient>
