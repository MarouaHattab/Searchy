export interface SceneOrigin {
  href: string
  query: string
  sceneIds: string[]
  scroll: number
  tab: 'scenes' | 'graph'
  at: number
}

export function safeOrigin(href: string | null): string | null {
  if (!href) return null
  try {
    const url = new URL(href, window.location.origin)
    return url.origin === window.location.origin && url.pathname === '/search'
      ? `${url.pathname}${url.search}`
      : null
  } catch {
    return null
  }
}

export function rememberOrigin(origin: Omit<SceneOrigin, 'at'>) {
  const href = safeOrigin(origin.href)
  if (!href) return
  try {
    sessionStorage.setItem(
      `searchy:origin:${href}`,
      JSON.stringify({ ...origin, sceneIds: origin.sceneIds.slice(0, 100), at: Date.now() })
    )
  } catch {
    /* Browsers may disable session storage. */
  }
}

export function readOrigin(href: string | null): SceneOrigin | null {
  const safe = safeOrigin(href)
  if (!safe) return null
  try {
    const parsed = JSON.parse(sessionStorage.getItem(`searchy:origin:${safe}`) ?? 'null')
    if (
      !parsed ||
      parsed.href !== safe ||
      !Number.isFinite(parsed.at) ||
      !Number.isFinite(parsed.scroll) ||
      parsed.scroll < 0 ||
      !Array.isArray(parsed.sceneIds) ||
      !parsed.sceneIds.every((s: unknown) => typeof s === 'string') ||
      Date.now() - parsed.at > 86400000
    )
      return null
    return parsed
  } catch {
    return null
  }
}

export function rankingPosition(origin: SceneOrigin | null, sceneId: string) {
  const index = origin?.sceneIds.indexOf(sceneId) ?? -1
  if (!origin || index < 0) return null
  return {
    position: index + 1,
    total: origin.sceneIds.length,
    previous: origin.sceneIds[index - 1] ?? null,
    next: origin.sceneIds[index + 1] ?? null,
  }
}

export function sceneHref(sceneId: string, start: number | null, origin?: string) {
  const params = new URLSearchParams()
  if (start != null) params.set('t', String(start))
  const safe = safeOrigin(origin ?? null)
  if (safe) params.set('from', safe)
  return `/scenes/${encodeURIComponent(sceneId)}${params.size ? `?${params}` : ''}`
}

const LAST_SEARCH = 'searchy:last-search'

export function rememberSearch(href: string) {
  const safe = safeOrigin(href)
  if (!safe) return
  try {
    sessionStorage.setItem(LAST_SEARCH, JSON.stringify({ href: safe, at: Date.now() }))
  } catch {
    /* Navigation still retains context through scene URLs. */
  }
}

export function clearSearch() {
  try {
    sessionStorage.removeItem(LAST_SEARCH)
  } catch {
    /* Optional browser storage. */
  }
}

export function searchDestination(pathname: string, search: string): string {
  if (pathname === '/search' && search) return `/search${search}`
  const from = safeOrigin(new URLSearchParams(search).get('from'))
  if (pathname.startsWith('/scenes/') && from) return from
  try {
    const saved = JSON.parse(sessionStorage.getItem(LAST_SEARCH) ?? 'null')
    if (saved && Number.isFinite(saved.at) && Date.now() - saved.at < 86400000)
      return safeOrigin(saved.href) ?? '/search'
  } catch {
    /* A fresh search is always available. */
  }
  return '/search'
}
