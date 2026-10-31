import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  Captions,
  Check,
  FileText,
  Info,
  Play,
  RotateCcw,
} from 'lucide-react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { Badge, Button, ErrorState, Loading } from '../../components/ui'
import { api, apiUrl, subtitleUrl, thumbnailUrl } from '../../services/api'
import { episodeTitle, sceneTitle, timestamp } from '../../lib/format'
import type { Dialogue } from '../../types'
import { SceneInformation, SceneSidebar } from './SceneDetails'
import { readOrigin, rankingPosition, sceneHref, safeOrigin } from './navigation'

export function initialPlaybackOffset(
  requestedTime: number | null,
  sceneStart: number | null,
  sceneEnd: number | null,
  mediaStart: number,
  duration: number
) {
  const fileEnd = Number.isFinite(duration) && duration > 0 ? duration : Infinity
  const sceneLength =
    sceneStart != null && sceneEnd != null ? Math.max(0, sceneEnd - sceneStart) : null
  const end = sceneLength == null ? fileEnd : Math.min(mediaStart + sceneLength, fileEnd)
  const start = Math.min(Math.max(0, mediaStart), end)
  const offset =
    requestedTime != null && Number.isFinite(requestedTime) && sceneStart != null
      ? requestedTime - sceneStart + mediaStart
      : start
  return Math.min(Math.max(offset, start), end)
}

export default function ScenePage() {
  const { id = '' } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const requestedTime = params.has('t') ? Number(params.get('t')) : null
  const from = safeOrigin(params.get('from'))
  const remembered = readOrigin(from)
  const sid = from ? new URLSearchParams(from.split('?')[1]).get('sid') : null
  const session = useQuery({
    queryKey: ['search-session', sid],
    queryFn: ({ signal }) => api.session(sid!, signal),
    enabled: !!sid && !remembered,
    retry: false,
    staleTime: Infinity,
  })
  const origin =
    remembered ??
    (from && session.data
      ? {
          href: from,
          query: session.data.request.query,
          sceneIds: session.data.response.results.map((s) => s.scene_id),
          scroll: 0,
          tab: 'scenes' as const,
          at: Date.now(),
        }
      : null)
  const ranking = rankingPosition(origin, id)
  const scene = useQuery({
    queryKey: ['scene', id],
    queryFn: ({ signal }) => api.scene(id, signal),
  })
  const videoInfo = useQuery({
    queryKey: ['video', scene.data?.video_id],
    queryFn: ({ signal }) => api.video(scene.data!.video_id, signal),
    enabled: !!scene.data,
  })
  const player = useRef<HTMLVideoElement>(null)
  const applied = useRef('')
  const [duration, setDuration] = useState(0)
  const [current, setCurrent] = useState(0)
  const [sceneOnly, setSceneOnly] = useState(true)
  const [playError, setPlayError] = useState('')
  const [captionsFailed, setCaptionsFailed] = useState(false)

  useEffect(() => {
    setSceneOnly(true)
    setPlayError('')
    setCaptionsFailed(false)
    setDuration(0)
    setCurrent(0)
  }, [id, requestedTime])

  useEffect(() => {
    window.scrollTo(0, 0)
    const handle = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && from) navigate(from)
    }
    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [id, from, navigate])

  const backLink = (
    <Link className="back-link" to={from ?? '/search'}>
      <ArrowLeft size={15} />
      Back to results
    </Link>
  )
  if (scene.isPending)
    return (
      <div>
        {backLink}
        <Loading label="Loading scene…" />
      </div>
    )
  if (scene.isError)
    return (
      <div>
        {backLink}
        <ErrorState error={scene.error} retry={() => void scene.refetch()} />
      </div>
    )
  const data = scene.data
  const start = data.playback.start_offset ?? 0
  const sceneLength = data.start != null && data.end != null ? data.end - data.start : null
  const end = sceneLength != null ? Math.min(start + sceneLength, duration || Infinity) : duration
  const inferred = data.timestamp_basis.includes('infer')
  const episodeTime = data.start != null ? Math.max(0, current - start + data.start) : null
  const subtitles = data.dialogue.length > 0 && data.playback.available && data.start != null
  const isUpload = videoInfo.data?.source_kind === 'upload'

  function playAt(value: number) {
    const element = player.current
    if (!element) return
    element.currentTime = Math.min(Math.max(value, 0), element.duration || Infinity)
    void element
      .play()
      .catch(() =>
        setPlayError(
          'Your browser could not play this file. Try the video controls or open the source video.'
        )
      )
  }

  function dialogueOffset(line: Dialogue) {
    return line.start - (data.start ?? 0) + start
  }

  function backToResults() {
    navigate(origin?.href ?? from ?? '/search')
  }

  return (
    <div className="scene-page">
      <div className="scene-nav">
        {origin ? (
          <button className="back-link" onClick={backToResults}>
            <ArrowLeft size={15} />
            Back to results
            <span className="scene-nav-query">“{origin.query}”</span>
          </button>
        ) : (
          <Link className="back-link" to={from ?? '/search'}>
            <ArrowLeft size={15} />
            Back to results
          </Link>
        )}
        {ranking && (
          <div className="scene-nav-steps" aria-label="Result navigation">
            <button
              className="icon-button"
              aria-label="Previous result"
              disabled={!ranking.previous}
              onClick={() =>
                ranking.previous && navigate(sceneHref(ranking.previous, null, origin?.href))
              }
            >
              <ArrowLeft size={16} />
            </button>
            <span className="scene-nav-count" aria-live="polite">
              {ranking.position} of {ranking.total}
            </span>
            <button
              className="icon-button"
              aria-label="Next result"
              disabled={!ranking.next}
              onClick={() => ranking.next && navigate(sceneHref(ranking.next, null, origin?.href))}
            >
              <ArrowRight size={16} />
            </button>
          </div>
        )}
      </div>
      <div className="scene-page-heading">
        <div>
          <p className="eyebrow">
            {data.collection_id}
            {data.episode_id && ` / ${episodeTitle(data.episode_id)}`}
          </p>
          <h1>
            {data.episode_id
              ? sceneTitle(data.episode_id)
              : (videoInfo.data?.title ?? 'Uploaded video')}
          </h1>
          <p className="muted">
            {timestamp(data.start)}
            {data.end != null && ` – ${timestamp(data.end)}`}
            {inferred ? ' · Inferred episode timing' : ' · Source timeline'}
          </p>
        </div>
        <Badge tone={data.playback.available ? 'blue' : 'neutral'}>
          {data.playback.available ? 'Video available' : 'Metadata only'}
        </Badge>
      </div>
      <div className="player-layout">
        <div className="player-main">
          {data.playback.available && data.playback.url ? (
            <>
              <div className="video-stage">
                <video
                  key={`${id}:${requestedTime ?? ''}`}
                  ref={player}
                  controls
                  playsInline
                  preload="metadata"
                  poster={thumbnailUrl(id)}
                  crossOrigin="anonymous"
                  aria-label={`Scene from ${episodeTitle(data.episode_id)}`}
                  onLoadedMetadata={(event) => {
                    const element = event.currentTarget
                    setDuration(element.duration)
                    const stamp = `${id}:${requestedTime ?? ''}`
                    if (applied.current === stamp) return
                    applied.current = stamp
                    const offset = initialPlaybackOffset(
                      requestedTime,
                      data.start,
                      data.end,
                      start,
                      element.duration
                    )
                    element.currentTime = offset
                    setCurrent(offset)
                  }}
                  onTimeUpdate={() => {
                    const element = player.current
                    if (!element) return
                    setCurrent(element.currentTime)
                    if (
                      sceneOnly &&
                      sceneLength != null &&
                      element.currentTime >= start + sceneLength
                    )
                      element.pause()
                  }}
                  onError={() =>
                    setPlayError(
                      'This video could not be played. The file may be unavailable or its format may not be supported by your browser.'
                    )
                  }
                >
                  <source src={apiUrl(data.playback.url)} />
                  {subtitles && (
                    <track
                      kind="subtitles"
                      src={subtitleUrl(id)}
                      srcLang="und"
                      label="Source transcript"
                      default
                      onError={() => setCaptionsFailed(true)}
                    />
                  )}
                </video>
              </div>
              {playError && (
                <div className="notice notice-error" role="alert">
                  {playError}
                  <a
                    className="text-link"
                    href={apiUrl(data.playback.url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open source video
                    <ArrowRight size={14} />
                  </a>
                </div>
              )}
              <div className="scene-timeline-panel">
                <div className="timeline-labels">
                  <span>
                    <span className="status-dot" />
                    Selected scene
                  </span>
                  <span>
                    {timestamp(data.start)}
                    {data.end != null && ` – ${timestamp(data.end)}`}
                  </span>
                </div>
                <div
                  className="scene-timeline"
                  aria-label="Selected scene interval in the available media"
                >
                  <div
                    className="scene-interval"
                    style={{
                      left: `${duration ? (start / duration) * 100 : 0}%`,
                      width: `${duration ? (Math.max(0, end - start) / duration) * 100 : 100}%`,
                    }}
                  />
                  <span
                    className="playhead"
                    style={{ left: `${duration ? Math.min((current / duration) * 100, 100) : 0}%` }}
                  />
                </div>
                <div className="timeline-actions">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setSceneOnly(true)
                      playAt(start)
                    }}
                  >
                    <RotateCcw size={14} />
                    Replay scene
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setSceneOnly(false)
                      playAt(
                        current >= end - 0.3 ? Math.min(end, Math.max(0, duration - 0.5)) : current
                      )
                    }}
                  >
                    {sceneOnly ? <Play size={14} /> : <Check size={14} />}
                    {isUpload ? 'Continue video' : 'Play available clip'}
                  </Button>
                  <span className="small muted">
                    {sceneOnly ? 'Pauses at scene end' : 'Full available media'}
                  </span>
                </div>
              </div>
              {inferred && (
                <p className="player-caveat">
                  <Info size={14} />
                  Episode timestamps are inferred from the original chunks. Subtitle alignment may
                  vary. This file is a clip, not a full episode.
                </p>
              )}
              {captionsFailed && (
                <p className="player-caveat">
                  <Captions size={14} />
                  Subtitles could not load. The source dialogue is available below.
                </p>
              )}
            </>
          ) : (
            <div className="missing-player">
              <FileText size={38} strokeWidth={1.2} />
              <h2>
                The scene is searchable.
                <br />
                Its video isn’t here yet.
              </h2>
              <p>
                {data.playback.reason ||
                  'Only captions and scene metadata are available in this workspace.'}
              </p>
              <Link className="button button-secondary" to="/library">
                Browse available videos
                <ArrowRight size={15} />
              </Link>
            </div>
          )}
          <SceneInformation
            key={id}
            data={data}
            duration={duration}
            episodeTime={episodeTime}
            dialogueOffset={dialogueOffset}
            onSeek={(offset) => {
              setSceneOnly(false)
              playAt(offset)
            }}
          />
        </div>
        <SceneSidebar data={data} isUpload={isUpload} inferred={inferred} />
      </div>
    </div>
  )
}
