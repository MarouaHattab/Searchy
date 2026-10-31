import { Suspense, useEffect, useLayoutEffect } from 'react'
import { Outlet, useLocation, useParams } from 'react-router'
import { Loading } from '../../components/ui'
import { safeOrigin } from '../player/navigation'
import SearchPage from './SearchPage'

export function SearchLayout() {
  const location = useLocation()
  const { id: sceneId } = useParams()
  const onScene = location.pathname.startsWith('/scenes/')
  const from = onScene ? safeOrigin(new URLSearchParams(location.search).get('from')) : null
  const live = safeOrigin(`${location.pathname}${location.search}`)
  const retain = location.pathname === '/search' || (!!from && from !== '/search')
  const searchHref = onScene ? from : live

  useLayoutEffect(() => {
    if (!onScene || !from) return
    const y = window.scrollY
    const previous = document.body.style.cssText
    document.body.style.position = 'fixed'
    document.body.style.top = `-${y}px`
    document.body.style.left = '0'
    document.body.style.right = '0'
    document.body.style.width = '100%'
    return () => {
      document.body.style.cssText = previous
      window.scrollTo(0, y)
    }
  }, [onScene, from])

  useEffect(() => {
    if (!onScene || !from) return
    const frame = window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>('.scene-overlay .back-link')?.focus()
    })
    return () => window.cancelAnimationFrame(frame)
  }, [onScene, from, sceneId])

  if (!retain || !searchHref) return <Outlet />

  return (
    <>
      <div className={onScene ? 'search-retained' : undefined} inert={onScene || undefined}>
        <Suspense fallback={<Loading label="Opening search…" />}>
          <SearchPage href={searchHref} frozen={onScene} />
        </Suspense>
      </div>
      {onScene && (
        <div className="scene-overlay" role="dialog" aria-modal="true" aria-label="Scene player">
          <div className="scene-overlay-body">
            <Suspense fallback={<Loading label="Opening scene…" />}>
              <Outlet />
            </Suspense>
          </div>
        </div>
      )}
    </>
  )
}
