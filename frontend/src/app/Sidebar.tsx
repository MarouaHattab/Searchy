import type { RefObject } from 'react'
import { ChevronRight, Clapperboard, PanelLeftClose, ScanSearch, X } from 'lucide-react'
import { Link, NavLink, useLocation } from 'react-router'
import { navigation } from './navigation'
import { searchDestination } from '../features/player/navigation'

interface SidebarProps {
  sidebarRef: RefObject<HTMLElement | null>
  collapsed: boolean
  mobile: boolean
  smallScreen: boolean
  activeJobs: number
  onClose: () => void
  onToggleCollapsed: () => void
}

export function Sidebar({
  sidebarRef,
  collapsed,
  mobile,
  smallScreen,
  activeJobs,
  onClose,
  onToggleCollapsed,
}: SidebarProps) {
  const location = useLocation()
  const searchHref = searchDestination(location.pathname, location.search)
  return (
    <aside
      ref={sidebarRef}
      className={`app-sidebar ${mobile ? 'mobile-open' : ''}`}
      aria-label="Workspace navigation"
      role={mobile ? 'dialog' : undefined}
      aria-modal={mobile ? true : undefined}
      aria-hidden={smallScreen && !mobile}
      inert={smallScreen && !mobile}
    >
      <Link className="brand" to="/" aria-label="Searchy dashboard">
        <span className="brand-icon">
          <ScanSearch size={24} strokeWidth={1.8} />
        </span>
        <span className="brand-name">
          Searchy<span className="brand-dot">.</span>
        </span>
      </Link>
      <button
        className="icon-button mobile-nav-close"
        onClick={onClose}
        aria-label="Close navigation"
      >
        <X size={20} />
      </button>
      <div className="workspace-label">
        <span className="workspace-initial">
          <Clapperboard size={16} />
        </span>
        <div>
          <strong>Your workspace</strong>
          <span>Local video collection</span>
        </div>
      </div>
      <nav>
        {['Workspace', 'Management'].map((group) => (
          <div className="nav-group" key={group}>
            <p>{group}</p>
            {navigation
              .filter((item) => item.group === group)
              .map(({ label, to, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to === '/search' ? searchHref : to}
                  end={to === '/'}
                  title={collapsed ? label : undefined}
                  aria-label={collapsed ? label : undefined}
                  className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                >
                  <Icon size={18} strokeWidth={1.7} />
                  <span>{label}</span>
                  {to === '/jobs' && activeJobs > 0 && (
                    <span className="nav-count">{activeJobs}</span>
                  )}
                </NavLink>
              ))}
          </div>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-note">
          <span className="note-spark">
            <ScanSearch size={19} />
          </span>
          <strong>A moment away.</strong>
          <p>Your collection, connected through scene and conversation.</p>
          <Link to={searchHref}>
            Start searching
            <ChevronRight size={14} />
          </Link>
        </div>
        <button
          className="collapse-button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <ChevronRight size={18} />
          ) : (
            <>
              <PanelLeftClose size={17} />
              <span>Collapse sidebar</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
