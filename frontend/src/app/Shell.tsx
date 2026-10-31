import { Suspense, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useLocation } from 'react-router'
import { Loading } from '../components/ui'
import { UploadDialog } from '../features/library/UploadDialog'
import { jobsQuery, readinessQuery } from '../services/queries'
import { navigation } from './navigation'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

function readPreference(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

export function Shell() {
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(
    () => readPreference('searchy:sidebar', '') === 'collapsed'
  )
  const [mobile, setMobile] = useState(false)
  const [upload, setUpload] = useState(false)
  const [theme, setTheme] = useState(() => readPreference('searchy:theme', 'light'))
  const [smallScreen, setSmallScreen] = useState(
    () => window.matchMedia('(max-width: 760px)').matches
  )
  const sidebar = useRef<HTMLElement>(null)
  const jobs = useQuery(jobsQuery)
  const readiness = useQuery(readinessQuery)
  const activeJobs =
    jobs.data?.filter((job) => ['queued', 'running'].includes(job.status)).length ?? 0
  const currentPage =
    navigation.find((item) =>
      item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to)
    )?.label ?? (location.pathname.startsWith('/scenes') ? 'Scene player' : 'Workspace')

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem('searchy:theme', theme)
    } catch {
      /* Preferences are optional when browser storage is disabled. */
    }
  }, [theme])
  useEffect(() => {
    try {
      localStorage.setItem('searchy:sidebar', collapsed ? 'collapsed' : '')
    } catch {
      /* Browser storage can be disabled. */
    }
  }, [collapsed])
  useEffect(() => {
    const media = window.matchMedia('(max-width: 760px)')
    const change = () => {
      setSmallScreen(media.matches)
      if (!media.matches) setMobile(false)
    }
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])
  useEffect(() => {
    const open = () => setUpload(true)
    window.addEventListener('searchy:upload', open)
    return () => window.removeEventListener('searchy:upload', open)
  }, [])
  useEffect(() => {
    setMobile(false)
    document.title = `${currentPage} · Searchy`
  }, [location.pathname, currentPage])
  useEffect(() => {
    if (!mobile) return
    const previous = document.activeElement as HTMLElement | null
    const oldOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    sidebar.current?.querySelector<HTMLButtonElement>('.mobile-nav-close')?.focus()
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobile(false)
      if (event.key !== 'Tab') return
      const elements = Array.from(
        sidebar.current?.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)') ?? []
      ).filter((element) => element.getClientRects().length)
      const first = elements[0],
        last = elements[elements.length - 1]
      if (
        event.shiftKey &&
        (document.activeElement === first || !sidebar.current?.contains(document.activeElement))
      ) {
        event.preventDefault()
        last?.focus()
      } else if (
        !event.shiftKey &&
        (document.activeElement === last || !sidebar.current?.contains(document.activeElement))
      ) {
        event.preventDefault()
        first?.focus()
      }
    }
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('keydown', close)
      document.body.style.overflow = oldOverflow
      previous?.focus()
    }
  }, [mobile])

  return (
    <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      {mobile && (
        <button
          className="sidebar-backdrop"
          onClick={() => setMobile(false)}
          aria-label="Close navigation"
        />
      )}
      <Sidebar
        sidebarRef={sidebar}
        collapsed={collapsed}
        mobile={mobile}
        smallScreen={smallScreen}
        activeJobs={activeJobs}
        onClose={() => setMobile(false)}
        onToggleCollapsed={() => setCollapsed(!collapsed)}
      />
      <div className="app-body" inert={mobile}>
        <Topbar
          currentPage={currentPage}
          mobile={mobile}
          theme={theme}
          activeJobs={activeJobs}
          connected={readiness.data?.ready}
          connecting={readiness.isPending}
          onToggleNavigation={() => setMobile(!mobile)}
          onToggleTheme={() => setTheme(theme === 'light' ? 'dark' : 'light')}
          onUpload={() => setUpload(true)}
        />
        <main id="main-content" className="main-content" tabIndex={-1}>
          <Suspense fallback={<Loading label="Opening workspace…" />}>
            <Outlet />
          </Suspense>
        </main>
        <footer className="app-footer">
          <span>
            Searchy<span className="footer-dot">/</span>Scene by scene.
          </span>
          <span>Built around your collection</span>
        </footer>
      </div>
      <UploadDialog open={upload} onClose={() => setUpload(false)} />
    </div>
  )
}
