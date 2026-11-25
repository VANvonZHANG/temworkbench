import { useCallback, useEffect, useRef, useState } from "react"
import { errorMessage, previewError } from "./api"
import type { Exposure, WorkbenchClient } from "./api"

type PreviewPhase = "paused" | "connecting" | "live" | "waiting" | "disconnected"

interface Stream {
  socket: WebSocket
  timer?: number
}

export function usePreview(client: WorkbenchClient, readExposure: () => Exposure | undefined) {
  const [phase, setPhase] = useState<PreviewPhase>("paused")
  const [frame, setFrame] = useState<string>()
  const [error, setError] = useState<string>()
  const stream = useRef<Stream | undefined>(undefined)
  const frameUrl = useRef<string | undefined>(undefined)

  const close = useCallback(() => {
    const active = stream.current
    if (!active) return false
    stream.current = undefined
    window.clearTimeout(active.timer)
    active.socket.close()
    return true
  }, [])

  const pause = useCallback(() => {
    if (!close()) return false
    setPhase("paused")
    setError(undefined)
    return true
  }, [close])

  const disconnect = useCallback(() => {
    if (close()) setPhase("disconnected")
  }, [close])

  function start() {
    if (stream.current || document.hidden) return
    setError(undefined)
    let socket: WebSocket
    try {
      socket = client.openPreview()
    } catch (cause) {
      setPhase("disconnected")
      setError(errorMessage(cause))
      return
    }
    const active: Stream = { socket }
    stream.current = active
    setPhase("connecting")

    function requestFrame() {
      if (stream.current !== active || socket.readyState !== WebSocket.OPEN) return
      const settings = readExposure()
      if (!settings || document.hidden) {
        if (!settings) setPhase("waiting")
        active.timer = window.setTimeout(requestFrame, 250)
        return
      }
      socket.send(JSON.stringify(settings))
    }

    socket.addEventListener("open", requestFrame)
    socket.addEventListener("message", (message) => {
      if (stream.current !== active) return
      if (message.data instanceof Blob) {
        if (frameUrl.current) URL.revokeObjectURL(frameUrl.current)
        frameUrl.current = URL.createObjectURL(message.data)
        setFrame(frameUrl.current)
        setPhase("live")
        setError(undefined)
      } else if (typeof message.data === "string") {
        try {
          const raw: unknown = JSON.parse(message.data)
          setError(previewError.parse(raw).error)
        } catch {
          setError("The workbench returned an unexpected preview response.")
        }
        setPhase("connecting")
      }
      active.timer = window.setTimeout(requestFrame, 250)
    })
    socket.addEventListener("close", () => {
      if (stream.current !== active) return
      stream.current = undefined
      window.clearTimeout(active.timer)
      setPhase("disconnected")
      setError("The preview connection closed.")
    })
  }

  useEffect(() => () => {
    close()
    if (frameUrl.current) URL.revokeObjectURL(frameUrl.current)
  }, [close])

  return { phase, frame, error, pause, start, disconnect }
}
