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
