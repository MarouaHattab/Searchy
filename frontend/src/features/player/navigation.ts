export interface SceneOrigin {
  href: string
  query: string
  sceneIds: string[]
  scroll: number
  tab: 'scenes' | 'graph'
  at: number
}

const SEARCH_KEYS = [
  'q',
  'collection',
  'character',
  'character_id',
  'limit',
  'playable',
  'view',
  'focus',
  'sid',
] as const

/** Stable, shareable search URL. Only relative /search links are accepted. */
export function canonicalSearch(href: string | null): string | null {
  if (!href || /^[a-z][a-z0-9+.-]*:/i.test(href)) return null
  try {
    const url = new URL(href, 'http://searchy.local')
    if (url.pathname !== '/search') return null
    const incoming = new URLSearchParams(url.search)
    const ordered = new URLSearchParams()
    for (const key of SEARCH_KEYS) {
      const value = incoming.get(key)?.trim() ?? ''
      if (value) ordered.set(key, value)
    }
    const search = ordered.toString()
    return search ? `/search?${search}` : '/search'
  } catch {
    return null
  }
}

export function safeOrigin(href: string | null): string | null {
  const canonical = canonicalSearch(href)
  if (!canonical) return null
  if (typeof window === 'undefined') return canonical
  try {
    const url = new URL(href!, window.location.origin)
    return url.origin === window.location.origin && url.pathname === '/search' ? canonical : null
  } catch {
    return null
  }
}

export function rememberOrigin(origin: Omit<SceneOrigin, 'at'>) {
  const href = safeOrigin(origin.href)
  if (!href || href === '/search') return
  const sceneIds = origin.sceneIds.slice(0, 100)
  try {
    sessionStorage.setItem(
      `searchy:origin:${href}`,
      JSON.stringify({ ...origin, href, sceneIds, at: Date.now() })
    )
    sessionStorage.setItem('searchy:expect-return', '1')
    for (const id of sceneIds) sessionStorage.setItem(`searchy:scene-from:${id}`, href)
  } catch {
    /* Browsers may disable session storage. */
  }
}

export function readSceneOrigin(sceneId: string): string | null {
  try {
    return safeOrigin(sessionStorage.getItem(`searchy:scene-from:${sceneId}`))
  } catch {
    return null
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
  if (start != null && Number.isFinite(start)) params.set('t', String(start))
  const safe = safeOrigin(origin ?? null)
  if (safe && safe !== '/search') params.set('from', safe)
  const query = params.toString()
  return `/scenes/${encodeURIComponent(sceneId)}${query ? `?${query}` : ''}`
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
    sessionStorage.removeItem('searchy:expect-return')
  } catch {
    /* Optional browser storage. */
  }
}

export function searchDestination(pathname: string, search: string): string {
  const current = pathname === '/search' ? safeOrigin(`${pathname}${search}`) : null
  if (current && current !== '/search') return current
  const from = safeOrigin(new URLSearchParams(search).get('from'))
  if (pathname.startsWith('/scenes/') && from && from !== '/search') return from
  try {
    const saved = JSON.parse(sessionStorage.getItem(LAST_SEARCH) ?? 'null')
    if (saved && Number.isFinite(saved.at) && Date.now() - saved.at < 86400000)
      return safeOrigin(saved.href) ?? '/search'
  } catch {
    /* A fresh search is always available. */
  }
  return '/search'
}
