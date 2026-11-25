import { Activity } from "lucide-react"
import type { Device } from "./api"

export function DeviceStatus({ device, stale }: { device: Device; stale: boolean }) {
  const values = [
    ["Imaging mode", device.mode],
    ["Accelerating voltage", `${device.beam_energy_kev} kV`],
    ["Magnification", `${device.magnification.toLocaleString("en-US")}×`],
    ["Brightness", device.brightness],
    ["Defocus", `${device.defocus_ticks} ticks`],
    ["Stage X / Y / Z", `${device.stage.x_nm} / ${device.stage.y_nm} / ${device.stage_z_nm} nm`],
    ["Tilt α", `${device.tilt_alpha_deg}°`],
    ["Beam (idle)", device.beam_blanked ? "Blanked" : "Unblanked"],
  ]

  return (
    <section className="glass-panel side-panel" aria-labelledby="device-title">
      <div className="panel-heading">
        <h2 id="device-title"><Activity aria-hidden="true" size={17} /> Microscope status</h2>
        {stale && <span className="stale-label">Last known</span>}
      </div>
      <dl className="device-values">
        {values.map(([label, value]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
    </section>
  )
}
