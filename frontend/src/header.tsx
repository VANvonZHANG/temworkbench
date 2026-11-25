import { LogOut, Microscope, Moon, Sun } from "lucide-react"
import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"

export type Theme = "dark" | "light"

interface HeaderProps {
  theme: Theme
  toggleTheme: () => void
  session?: string
  connection?: string
  online?: boolean
  disconnect?: () => void
  stop?: ReactNode
  shortcut?: ReactNode
}

export function Header({ theme, toggleTheme, session, connection, online, disconnect, stop, shortcut }: HeaderProps) {
  const themeLabel = theme === "dark" ? "Use light theme" : "Use dark theme"
  return (
    <header className="console-header">
      <div className="header-inner content-width">
        <div className="brand">
          <span className="brand-mark"><Microscope size={20} strokeWidth={1.65} aria-hidden="true" /></span>
          <h1>TEM Workbench</h1>
        </div>
        <div className="header-session">
          <span className="connection" data-online={Boolean(online)} role="status">
            <span className="state-dot" />{connection ?? "Simulator"}
          </span>
          {session && <span className="session-id" title={`Session ${session}`}>Session <strong>{session}</strong></span>}
        </div>
        <div className="header-actions">
          {stop}
          {shortcut}
          <Button variant="ghost" size="icon" aria-label={themeLabel} title={themeLabel} onClick={toggleTheme}>
            {theme === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
          </Button>
          {disconnect && <Button variant="ghost" size="icon" aria-label="Disconnect" title="Disconnect" onClick={disconnect}>
            <LogOut aria-hidden="true" />
          </Button>}
        </div>
      </div>
    </header>
  )
}
