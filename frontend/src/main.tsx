import { useEffect, useRef, useState } from "react"
import type { FormEvent } from "react"
import { ArrowRight } from "lucide-react"
import { createRoot } from "react-dom/client"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { createClient, errorMessage } from "./api"
import type { Dashboard, WorkbenchClient } from "./api"
import { Header } from "./header"
import type { Theme } from "./header"
import { Workbench } from "./workbench"
import "./styles.css"

interface Connection {
  client: WorkbenchClient
  controller: AbortController
  initial: Dashboard
}

const themeKey = "temworkbench-theme"

function savedTheme(): Theme {
  try {
    if (localStorage.getItem(themeKey) === "light") return "light"
  } catch {
    return "dark"
  }
  return "dark"
}

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark")
  document.documentElement.style.colorScheme = theme
}

function App() {
  const [theme, setTheme] = useState(savedTheme)
  const [connection, setConnection] = useState<Connection>()
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState<string>()
  const tokenInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!connection) tokenInput.current?.focus()
    return () => connection?.controller.abort()
  }, [connection])

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark"
    applyTheme(next)
    setTheme(next)
    try {
      localStorage.setItem(themeKey, next)
    } catch {
      return
    }
  }

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (connecting) return
    const fields = new FormData(event.currentTarget)
    const token = String(fields.get("token") ?? "").trim()
    const session = String(fields.get("session") ?? "")
    if (!token) {
      setError("Enter the operator token.")
      return
    }

    setConnecting(true)
    setError(undefined)
    const controller = new AbortController()
    const client = createClient(token, session)
    try {
      const state = await client.state(controller.signal)
      const approvals = await client.approvals(controller.signal)
      setConnection({ client, controller, initial: { state, approvals } })
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setConnecting(false)
    }
  }

  if (connection) {
    return (
      <Workbench client={connection.client} initial={connection.initial} signal={connection.controller.signal}
        theme={theme} toggleTheme={toggleTheme} disconnect={() => {
          connection.controller.abort()
          setConnection(undefined)
        }} />
    )
  }

  return (
    <>
      <Header theme={theme} toggleTheme={toggleTheme} />
      <main className="connection-page content-width">
        <Card className="connection-card">
          <h2>Connect to the simulator</h2>
          <p className="connection-help">Enter the operator token shown in the terminal.</p>
          <form className="connection-form" onSubmit={connect}>
            <label><span>Operator token</span>
              <Input ref={tokenInput} name="token" type="password" autoComplete="off" required />
            </label>
            <label><span>Session ID</span>
              <Input name="session" defaultValue="local" pattern="[a-z0-9][a-z0-9_\-]{0,63}" maxLength={64} required />
            </label>
            {error && <p className="inline-error" role="alert">{error}</p>}
            <Button type="submit" disabled={connecting}>
              {connecting ? "Connecting…" : "Connect"} <ArrowRight aria-hidden="true" />
            </Button>
          </form>
        </Card>
      </main>
    </>
  )
}

applyTheme(savedTheme())
const root = document.getElementById("root")
if (!root) throw new Error("Missing workbench root element.")
createRoot(root).render(<App />)
