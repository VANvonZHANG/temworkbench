import { useEffect, useRef, useState } from "react"
import type { FormEvent } from "react"
import { ArrowDown, OctagonX } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Approvals } from "./approvals"
import { Camera, captureBusy } from "./camera"
import type { Capture } from "./camera"
import { DeviceStatus } from "./device-status"
import { errorMessage, exposure, jobKey } from "./api"
import type { Dashboard, Device, FileFormat, Job, WorkbenchClient } from "./api"
import { usePreview } from "./use-preview"
import { Header } from "./header"
import type { Theme } from "./header"

type Stop =
  | { kind: "ready" }
  | { kind: "stopping" }
  | { kind: "confirmed"; device: Device }
  | { kind: "error"; message: string }

interface WorkbenchProps {
  client: WorkbenchClient
  initial: Dashboard
  signal: AbortSignal
  theme: Theme
  toggleTheme: () => void
  disconnect: () => void
}

export function Workbench({ client, initial, signal, theme, toggleTheme, disconnect }: WorkbenchProps) {
  const [dashboard, setDashboard] = useState(initial)
  const latest = useRef(initial)
  const [pollError, setPollError] = useState<string>()
  const [approvalNotice, setApprovalNotice] = useState<string>()
  const [capture, setCapture] = useState<Capture>({ kind: "idle" })
  const [stop, setStop] = useState<Stop>({ kind: "ready" })
  const [downloadError, setDownloadError] = useState<string>()
  const form = useRef<HTMLFormElement>(null)
  const resumePreview = useRef(false)

  function readExposure() {
    if (!form.current) return
    const fields = new FormData(form.current)
    const parsed = exposure.safeParse({
      exposure_s: Number(fields.get("exposure")),
      binning: Number(fields.get("binning")),
    })
    return parsed.data
  }

  const preview = usePreview(client, readExposure)
  const pausePreview = preview.pause
  const disconnectPreview = preview.disconnect
  const device = stop.kind === "confirmed" ? stop.device : dashboard.state.device
  const approvals = stop.kind === "confirmed" ? [] : dashboard.approvals
  const isStopped = dashboard.state.stopped || stop.kind === "confirmed"
  const unavailable = isStopped || stop.kind === "stopping" || !dashboard.state.device_connected || Boolean(pollError)

  useEffect(() => {
    document.getElementById("camera-title")?.focus({ preventScroll: true })
  }, [])

  useEffect(() => {
    let timer: number | undefined
    let polling = false
    let active = true

    async function refresh() {
      if (!active || signal.aborted || document.hidden || polling) return
      polling = true
      try {
        const state = await client.state(signal)
        if (document.hidden || !active || signal.aborted) return
        const approvals = await client.approvals(signal)
        if (!active || signal.aborted) return
        const pendingKeys = new Set(approvals.map(jobKey))
        const removed = latest.current.approvals.filter((item) => !pendingKeys.has(jobKey(item)))
        const next = { state, approvals }
        latest.current = next
        setDashboard(next)
        setPollError(undefined)
        if (state.stopped || !state.device_connected) {
          resumePreview.current = false
          if (state.stopped) pausePreview()
          else disconnectPreview()
        }
        if (removed.length) {
          const results = await Promise.allSettled(removed.map((item) => client.job(item, signal)))
          if (!active || signal.aborted) return
          const expired = results.filter((result) => result.status === "fulfilled"
            && result.value.error === "Operator approval expired").length
          if (expired) setApprovalNotice(expired === 1 ? "An approval request expired." : `${expired} approval requests expired.`)
        }
      } catch (error) {
        if (!active || signal.aborted) return
        setPollError(errorMessage(error))
        resumePreview.current = false
        disconnectPreview()
      } finally {
        polling = false
        if (active && !signal.aborted && !document.hidden) timer = window.setTimeout(refresh, 2000)
      }
    }

    function visibilityChanged() {
      window.clearTimeout(timer)
      if (document.hidden) {
        resumePreview.current = false
        pausePreview()
      } else {
        void refresh()
      }
    }

    timer = window.setTimeout(refresh, 2000)
    document.addEventListener("visibilitychange", visibilityChanged)
    return () => {
      active = false
      window.clearTimeout(timer)
      document.removeEventListener("visibilitychange", visibilityChanged)
    }
  }, [client, disconnectPreview, pausePreview, signal])

  async function acquire(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const settings = readExposure()
    if (unavailable || captureBusy(capture) || !settings) return
    const comment = String(new FormData(event.currentTarget).get("comment") ?? "")
    resumePreview.current = pausePreview()
    setCapture({ kind: "submitting" })
    setDownloadError(undefined)
    try {
      let job = await client.acquire({ kind: "acquire_image", ...settings, comment }, signal)
      while (job.status === "queued" || job.status === "running") {
        setCapture({ kind: "acquiring", job })
        await new Promise((resolve) => window.setTimeout(resolve, 400))
        job = await client.job(job, signal)
      }
      if (job.status !== "succeeded") {
        setCapture({ kind: "failed", message: job.error ?? `Acquisition ${job.status}.` })
        return
      }
      setCapture({ kind: "saved", job })
    } catch (error) {
      if (!signal.aborted) setCapture({ kind: "failed", message: errorMessage(error) })
    } finally {
      const state = latest.current.state
      if (resumePreview.current && !signal.aborted && !document.hidden && !state.stopped && state.device_connected) {
        preview.start()
      }
      resumePreview.current = false
    }
  }

  async function stopAndBlank() {
    if (stop.kind === "stopping" || stop.kind === "confirmed") return
    resumePreview.current = false
    pausePreview()
    setStop({ kind: "stopping" })
    try {
      const result = await client.stop(signal)
      if (!result.beam_blanked) throw new Error("The workbench did not confirm that the beam was blanked.")
      setStop({ kind: "confirmed", device: result })
    } catch (error) {
      if (!signal.aborted) setStop({ kind: "error", message: errorMessage(error) })
    }
  }

  async function download(job: Job, format: FileFormat) {
    setDownloadError(undefined)
    try {
      await client.download(job, format, signal)
    } catch (error) {
      if (!signal.aborted) setDownloadError(errorMessage(error))
    }
  }

  const connection = stop.kind === "stopping" ? "Stopping"
    : isStopped ? "Stopped"
    : pollError ? "Connection lost"
    : dashboard.state.device_connected ? "Simulator online" : "Simulator offline"
  const stopStatus = stop.kind === "stopping" ? "Stopping and blanking the beam…"
    : stop.kind === "confirmed" ? "Stopped. Beam blanked. Restart the service to resume acquisition."
    : isStopped ? "Workbench stopped. Beam blanking unconfirmed." : ""

  return (
    <>
      <Header theme={theme} toggleTheme={toggleTheme} session={client.sessionId} disconnect={disconnect}
        connection={connection} online={connection === "Simulator online"}
        shortcut={approvals.length > 0 ? (
          <a className="approvals-shortcut" href="#approvals" onClick={() => document.getElementById("approvals")?.focus()}>
            {approvals.length} pending <ArrowDown aria-hidden="true" size={13} />
          </a>
        ) : undefined}
        stop={(
          <Button className="stop-button" variant="destructive"
            disabled={stop.kind === "stopping" || stop.kind === "confirmed"}
            onClick={() => void stopAndBlank()}>
            <OctagonX aria-hidden="true" /> Stop and blank beam
          </Button>
        )} />
      <main className="workbench content-width">
        {(stopStatus || stop.kind === "error" || pollError) && (
          <div className="workbench-notices glass-panel">
            <p role="status">{stopStatus}</p>
            {stop.kind === "error" && <p className="inline-error" role="alert">{stop.message}</p>}
            {pollError && <p className="inline-error" role="alert">Could not refresh workbench status. {pollError}</p>}
          </div>
        )}
        <div className="workbench-grid">
          <Camera form={form} preview={preview} capture={capture} unavailable={unavailable}
            downloadError={downloadError} onCapture={acquire} onDownload={(job, format) => void download(job, format)} />
          <aside className="workbench-sidebar" aria-label="Device and approvals">
            <Approvals approvals={approvals} device={device} stale={Boolean(pollError) || !dashboard.state.device_connected}
              disabled={unavailable} announcement={approvalNotice} decide={(item, allow) => client.decide(item, allow, signal)} />
            <DeviceStatus device={device} stale={Boolean(pollError) || !dashboard.state.device_connected} />
          </aside>
        </div>
      </main>
    </>
  )
}
