import { useCallback, useLayoutEffect, useRef, useState } from "react"
import { ArrowRight, ClipboardCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { errorMessage, jobKey } from "./api"
import type { Approval, Device, Job } from "./api"

function change(command: Approval["command"], device: Device, stale: boolean) {
  const value = (text: string | number) => stale ? "Unavailable" : text
  switch (command.kind) {
    case "set_magnification":
      return { title: "Set magnification", rows: [["Magnification", value(`${device.magnification}×`), `${command.value}×`]] }
    case "set_brightness":
      return { title: "Set brightness", rows: [["Brightness", value(device.brightness), command.value]] }
    case "set_defocus":
      return { title: "Set defocus", rows: [["Defocus", value(`${device.defocus_ticks} ticks`), `${command.ticks} ticks`]] }
    case "move_stage":
      return {
        title: "Move stage",
        rows: [
          ["X", value(`${device.stage.x_nm} nm`), `${command.x_nm} nm`],
          ["Y", value(`${device.stage.y_nm} nm`), `${command.y_nm} nm`],
        ],
      }
  }
}

function decisionMessage(job: Job) {
  switch (job.status) {
    case "queued": return "Approved. Waiting for execution."
    case "running": return "Approved. Executing."
    case "succeeded": return "Approved and executed."
    case "rejected": return job.error ?? "The request was rejected."
    case "canceled": return job.error ?? "The request was canceled."
    case "failed": return job.error ?? "The command failed."
    case "pending_approval": return "The request is still awaiting approval."
  }
}

interface ApprovalsProps {
  approvals: Approval[]
  device: Device
  stale: boolean
  disabled: boolean
  announcement?: string
  decide: (request: Approval, allow: boolean) => Promise<Job>
}

interface ApprovalCardProps extends Pick<ApprovalsProps, "device" | "stale" | "disabled" | "decide"> {
  request: Approval
  onFocusedRemoval: (key: string) => void
  announce: (message: string) => void
}

function ApprovalCard({ request, device, stale, disabled, decide, onFocusedRemoval, announce }: ApprovalCardProps) {
  const key = jobKey(request)
  const [phase, setPhase] = useState<"ready" | "submitting" | "settled">("ready")
  const element = useRef<HTMLElement | null>(null)
  const setElement = useCallback((node: HTMLElement | null) => {
    if (!node && element.current?.contains(document.activeElement)) onFocusedRemoval(key)
    element.current = node
  }, [key, onFocusedRemoval])
  const { title, rows } = change(request.command, device, stale)
  const locked = disabled || phase !== "ready"

  async function submit(allow: boolean) {
    if (locked) return
    setPhase("submitting")
    try {
      const result = await decide(request, allow)
      setPhase(result.status === "pending_approval" ? "ready" : "settled")
      announce(decisionMessage(result))
    } catch (error) {
      setPhase("ready")
      announce(errorMessage(error))
    }
  }

  return (
    <article className="approval-card" ref={setElement} data-approval-key={key} aria-busy={phase === "submitting"}>
      <div className="approval-heading">
        <h3>{title}</h3>
        <span className="approval-session" title={request.session_id}>Session {request.session_id}</span>
      </div>
      <table className="approval-values" aria-label={`${title} values`}>
        <thead>
          <tr><th scope="col"><span className="sr-only">Parameter</span></th><th scope="col">Current</th><th scope="col">Requested</th></tr>
        </thead>
        <tbody>
          {rows.map(([label, current, target]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td>{current}</td>
              <td><ArrowRight aria-hidden="true" size={12} /><strong>{target}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="approval-actions">
        <Button variant="outline" size="sm" disabled={locked} focusableWhenDisabled onClick={() => void submit(false)}>Reject</Button>
        <Button variant="secondary" size="sm" disabled={locked} focusableWhenDisabled onClick={() => void submit(true)} data-approve>Approve</Button>
      </div>
    </article>
  )
}

export function Approvals({ approvals, device, stale, disabled, announcement, decide }: ApprovalsProps) {
  const [feedback, setFeedback] = useState<string>()
  const section = useRef<HTMLElement>(null)
  const title = useRef<HTMLHeadingElement>(null)
  const previous = useRef<string[]>([])
  const removedFocus = useRef<string | undefined>(undefined)
  const onFocusedRemoval = useCallback((key: string) => { removedFocus.current = key }, [])

  useLayoutEffect(() => {
    if (removedFocus.current) {
      const index = previous.current.indexOf(removedFocus.current)
      const following = new Set(previous.current.slice(index + 1))
      const cards = section.current?.querySelectorAll<HTMLElement>("[data-approval-key]") ?? []
      const next = Array.from(cards).find((card) => following.has(card.dataset.approvalKey ?? ""))
      const target = next?.querySelector<HTMLElement>('[data-approve]:not([aria-disabled="true"])') ?? title.current
      target?.focus()
      removedFocus.current = undefined
    }
    previous.current = approvals.map(jobKey)
  }, [approvals])

  return (
    <section className="glass-panel side-panel" aria-labelledby="approvals" ref={section}>
      <div className="panel-heading">
        <h2 id="approvals" ref={title} tabIndex={-1}><ClipboardCheck aria-hidden="true" size={17} /> Operator approvals</h2>
        <span className="count" aria-label={`${approvals.length} pending requests`}>{approvals.length}</span>
      </div>
      <p className="approval-feedback" role="status">{feedback}</p>
      <p className="approval-feedback" role="status">{announcement}</p>
      {approvals.length === 0 ? <p className="empty-approvals">No pending approvals.</p> : (
        <div className="approval-list">
          {approvals.map((request) => (
            <ApprovalCard key={jobKey(request)} request={request} device={device} stale={stale}
              decide={decide} disabled={disabled} onFocusedRemoval={onFocusedRemoval} announce={setFeedback} />
          ))}
        </div>
      )}
    </section>
  )
}
