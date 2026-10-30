import { ChevronRight, Menu, Moon, Sun, Upload } from 'lucide-react'
import { Link } from 'react-router'
import { Button } from '../components/ui'

interface TopbarProps {
  currentPage: string
  mobile: boolean
  theme: string
  activeJobs: number
  connected: boolean | undefined
  connecting: boolean
  onToggleNavigation: () => void
  onToggleTheme: () => void
  onUpload: () => void
}

export function Topbar({
  currentPage,
  mobile,
  theme,
  activeJobs,
  connected,
  connecting,
  onToggleNavigation,
  onToggleTheme,
  onUpload,
}: TopbarProps) {
  return (
    <header className="topbar">
      <div className="topbar-location">
        <button
          className="icon-button mobile-nav-toggle"
          onClick={onToggleNavigation}
          aria-label="Open navigation"
          aria-expanded={mobile}
        >
          <Menu size={21} />
        </button>
        <span className="muted topbar-workspace">Workspace</span>
        <ChevronRight size={13} className="muted topbar-workspace" />
        <span>{currentPage}</span>
      </div>
      <div className="topbar-actions">
        <Link
          className={`service-indicator ${connected ? 'online' : 'offline'}`}
          to="/settings"
          title="View service status"
        >
          <span className="status-dot" />
          <span>
            {connecting ? 'Connecting' : connected ? 'Services connected' : 'Check services'}
          </span>
        </Link>
        {activeJobs > 0 && (
          <Link className="processing-indicator" to="/jobs">
            <span className="processing-pulse" />
            {activeJobs}
            <span className="processing-label"> processing</span>
          </Link>
        )}
        <button
          className="icon-button theme-toggle"
          onClick={onToggleTheme}
          aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
          title={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
        >
          {theme === 'light' ? <Moon size={17} /> : <Sun size={18} />}
        </button>
        <Button className="topbar-upload" aria-label="Upload video" onClick={onUpload}>
          <Upload size={15} />
          <span>Upload video</span>
        </Button>
      </div>
    </header>
  )
}
