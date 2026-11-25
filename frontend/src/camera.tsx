import { Aperture, Download, Pause, Play } from "lucide-react"
import type { FormEventHandler, Ref } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import type { FileFormat, Job } from "./api"
import type { usePreview } from "./use-preview"

export type Capture =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "acquiring"; job: Job }
  | { kind: "saved"; job: Job }
  | { kind: "failed"; message: string }

export function captureBusy(capture: Capture) {
  return capture.kind === "submitting" || capture.kind === "acquiring"
}

function captureLabel(capture: Capture) {
  switch (capture.kind) {
    case "idle": return ""
    case "submitting": return "Submitting acquisition…"
    case "acquiring": return capture.job.status === "queued" ? "Waiting for acquisition…" : "Acquiring and saving…"
    case "saved": return "Acquisition saved."
    case "failed": return capture.message
  }
}

const previewStatus = {
  paused: { label: "Paused", empty: "Preview is paused" },
  connecting: { label: "Connecting", empty: "Waiting for the first frame" },
  live: { label: "Live", empty: "Waiting for the first frame" },
  waiting: { label: "Check exposure", empty: "Enter a valid exposure to resume" },
  disconnected: { label: "Disconnected", empty: "No camera frame received." },
}

interface CameraProps {
  form: Ref<HTMLFormElement>
  preview: ReturnType<typeof usePreview>
  capture: Capture
  unavailable: boolean
  downloadError?: string
  onCapture: FormEventHandler<HTMLFormElement>
  onDownload: (job: Job, format: FileFormat) => void
}

export function Camera({ form, preview, capture, unavailable, downloadError, onCapture, onDownload }: CameraProps) {
  const busy = captureBusy(capture)
  const streaming = preview.phase !== "paused" && preview.phase !== "disconnected"
  const status = previewStatus[preview.phase]

  return (
    <Card className="camera-panel" role="region" aria-labelledby="camera-title">
      <div className="panel-heading camera-heading">
        <h2 id="camera-title" tabIndex={-1}><Aperture aria-hidden="true" size={19} /> Camera preview</h2>
        <span className="preview-state" data-phase={busy ? "acquiring" : preview.phase} role="status">
          <span className="state-dot" />{busy ? "Acquiring" : status.label}
        </span>
      </div>
      <figure className="viewfinder" aria-label="Simulator camera preview">
        {preview.frame ? <img src={preview.frame} alt="Simulated TEM camera frame" /> : (
          <div className="empty-preview">
            <Aperture size={31} strokeWidth={1.15} aria-hidden="true" />
            <span>{status.empty}</span>
          </div>
        )}
      </figure>
      {preview.error && <p className="inline-error" role="alert">{preview.error}</p>}
      <form className="camera-controls" ref={form} onSubmit={onCapture}>
        <div className="camera-fields">
          <label><span>Exposure (s)</span><Input name="exposure" type="number" min="0.01" max="2" step="any" defaultValue="0.1" required /></label>
          <label><span>Binning</span><NativeSelect name="binning" defaultValue="1">
            <NativeSelectOption value="1">1×</NativeSelectOption>
            <NativeSelectOption value="2">2×</NativeSelectOption>
            <NativeSelectOption value="4">4×</NativeSelectOption>
          </NativeSelect></label>
          <label className="note-field"><span>Acquisition note <span className="optional">(optional)</span></span>
            <Input name="comment" type="text" maxLength={500} placeholder="e.g. Grid A3" />
          </label>
        </div>
        <div className="camera-actions">
          <Button type="button" variant="outline" disabled={unavailable || busy} onClick={(event) => {
            if (streaming) preview.pause()
            else if (event.currentTarget.form?.reportValidity()) preview.start()
          }}>
            {streaming ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
            {streaming ? "Pause preview" : "Start preview"}
          </Button>
          <Button type="submit" disabled={unavailable || busy}><Aperture aria-hidden="true" /> Acquire and save</Button>
        </div>
      </form>
      <div className="capture-result">
        <p className={capture.kind === "failed" ? "inline-error" : undefined} role="status">{captureLabel(capture)}</p>
        {capture.kind === "saved" && (
          <div className="download-actions">
            <Button type="button" variant="outline" size="sm" onClick={() => onDownload(capture.job, "hspy")}>
              <Download aria-hidden="true" /> Download HSPY
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => onDownload(capture.job, "tiff")}>
              <Download aria-hidden="true" /> Download TIFF
            </Button>
          </div>
        )}
        {downloadError && <p className="inline-error" role="alert">{downloadError}</p>}
      </div>
    </Card>
  )
}
