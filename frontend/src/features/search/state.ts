import { useEffect, useLayoutEffect, useRef } from 'react'
import type { SceneMatch } from '../../types'

export function useResultScroll(href: string, ready: boolean) {
  const key = `searchy:scroll:${href}`
  const restored = useRef('')

  useLayoutEffect(() => {
    if (!ready || restored.current === key) return
    let saved: string | null = null
    try {
      saved = window.sessionStorage.getItem(key)
    } catch {
      return
    }
    restored.current = key
    if (!saved) return
    const target = Number(saved)
    if (!Number.isFinite(target) || target <= 0) return
    window.scrollTo({ top: target })
    const settle = window.setTimeout(() => window.scrollTo({ top: target }), 150)
    return () => window.clearTimeout(settle)
  }, [key, ready])

  useEffect(() => {
    if (!ready) return
    let frame = 0
    const record = () => {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(() => {
        if (document.body.style.position === 'fixed') return
        try {
          window.sessionStorage.setItem(key, String(window.scrollY))
        } catch {
          // Ignore storage failures; scrolling still works for this session.
        }
      })
    }
    window.addEventListener('scroll', record, { passive: true })
    return () => {
      window.removeEventListener('scroll', record)
      window.cancelAnimationFrame(frame)
    }
  }, [key, ready])
}

export function rankingOf(scenes: SceneMatch[]) {
  return scenes.map((scene) => scene.scene_id)
}
