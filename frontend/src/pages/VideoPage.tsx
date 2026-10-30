import { useState } from 'react'
import type { KeyboardEvent } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  Captions,
  Check,
  Clapperboard,
  FileText,
  Search,
} from 'lucide-react'
import { Link, useParams } from 'react-router'
import { SceneCard } from '../components/SceneCard'
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Loading,
  PageHeading,
  SectionHeading,
  StatusBadge,
} from '../components/ui'
import { count, episodeTitle, timestamp } from '../lib/format'
import { api } from '../services/api'
import '../styles/catalog.css'

export default function VideoPage() {
  const { id = '' } = useParams()
  const [page, setPage] = useState({ videoId: id, offset: 0 })
  const offset = page.videoId === id ? page.offset : 0
  const [tab, setTab] = useState<'scenes' | 'transcript'>('scenes')
  const video = useQuery({
    queryKey: ['video', id],
    queryFn: ({ signal }) => api.video(id, signal),
    refetchInterval: (query) =>
      ['processing', 'queued'].includes(query.state.data?.status ?? '') ? 10_000 : false,
  })
  const scenes = useQuery({
    queryKey: ['video-scenes', id, offset],
    queryFn: ({ signal }) => api.scenes(id, offset, signal),
    placeholderData: keepPreviousData,
    refetchInterval:
      video.data && ['processing', 'queued'].includes(video.data.status) ? 10_000 : false,
  })

  if (video.isPending) return <Loading label="Loading video details…" />
  if (video.isError) return <ErrorState error={video.error} retry={() => void video.refetch()} />

  const item = video.data
  const dialogueCount = scenes.data?.reduce((total, scene) => total + scene.dialogue.length, 0) ?? 0

  function changeTab(event: KeyboardEvent<HTMLButtonElement>) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const next =
      event.key === 'Home'
        ? 'scenes'
        : event.key === 'End'
          ? 'transcript'
          : tab === 'scenes'
            ? 'transcript'
            : 'scenes'
    setTab(next)
    document.getElementById(`${next}-tab`)?.focus()
  }

  return (
    <div className="catalog-page stack">
      <Link className="text-link video-back" to="/library">
        <ArrowLeft size={15} />
        Video library
      </Link>
      <PageHeading
        eyebrow={item.collection_id}
        title={item.title}
        action={<StatusBadge status={item.status} />}
      >
        {item.source_kind === 'import' ? episodeTitle(item.original_id) : timestamp(item.duration)}{' '}
        · {item.source_kind === 'import' ? 'Imported collection' : 'Uploaded video'}
      </PageHeading>
      <div className="video-summary panel">
        <div className="video-summary-stat">
          <Clapperboard size={20} />
          <div>
            <strong>{count(item.scene_count)}</strong>
            <span>Extracted scenes</span>
          </div>
        </div>
        <div className="video-summary-stat">
          <Check size={20} />
          <div>
            <strong>{count(item.indexed_scenes)}</strong>
            <span>Indexed for search</span>
          </div>
        </div>
        <div className="video-summary-stat">
          <FileText size={20} />
          <div>
            <strong>{count(item.playable_scenes)}</strong>
            <span>Scenes with video</span>
          </div>
        </div>
        <div className="video-summary-action">
          <Link
            className="button button-secondary"
            to={`/search?collection=${encodeURIComponent(item.collection_id)}`}
          >
            <Search size={16} />
            Search collection
          </Link>
        </div>
      </div>
      {item.duration != null && (
        <p className="muted small">Source duration: {timestamp(item.duration)}</p>
      )}
      {item.playable_scenes < item.scene_count && (
        <div className="availability-note">
          <FileText size={18} />
          <p>
            {item.playable_scenes === 0
              ? 'Source video is unavailable for this entry. You can still explore its indexed descriptions and dialogue.'
              : `${count(item.playable_scenes)} ${item.playable_scenes === 1 ? 'scene has' : 'scenes have'} source video. Other scenes are available as searchable descriptions and dialogue.`}
          </p>
        </div>
      )}
      {item.characters.length > 0 && (
        <section className="video-character-section">
          <SectionHeading title="Character mentions" />
          <div className="chip-row">
            {item.characters.map((name) => (
              <Link
                className="character-chip"
                to={`/search?character=${encodeURIComponent(name)}&q=${encodeURIComponent(name)}`}
                key={name}
              >
                {name}
                <Search size={11} />
              </Link>
            ))}
          </div>
          <p className="small muted">
            Names come from extracted descriptions and dialogue; identity is not independently
            verified.
          </p>
        </section>
      )}
      <section>
        <div className="video-content-heading">
          <div className="catalog-tabs" role="tablist" aria-label="Video content">
            <button
              type="button"
              role="tab"
              id="scenes-tab"
              aria-controls="video-content"
              aria-selected={tab === 'scenes'}
              tabIndex={tab === 'scenes' ? 0 : -1}
              onKeyDown={changeTab}
              onClick={() => setTab('scenes')}
            >
              <Clapperboard size={16} />
              Scenes<Badge>{count(item.scene_count)}</Badge>
            </button>
            <button
              type="button"
              role="tab"
              id="transcript-tab"
              aria-controls="video-content"
              aria-selected={tab === 'transcript'}
              tabIndex={tab === 'transcript' ? 0 : -1}
              onKeyDown={changeTab}
              onClick={() => setTab('transcript')}
            >
              <Captions size={16} />
              Transcript
            </button>
          </div>
          <span className="muted small">Original timestamps preserved</span>
        </div>
        <div id="video-content" role="tabpanel" aria-labelledby={`${tab}-tab`}>
          {scenes.isPending ? (
            <Loading label="Loading scenes…" />
          ) : scenes.isError ? (
            <ErrorState error={scenes.error} retry={() => void scenes.refetch()} />
          ) : !scenes.data.length ? (
            <EmptyState
              title={
                ['processing', 'queued'].includes(item.status)
                  ? 'Your scenes are on their way'
                  : 'No scenes available'
              }
              action={
                ['processing', 'queued', 'failed'].includes(item.status) ? (
                  <Link className="button button-secondary" to="/jobs">
                    View processing jobs
                  </Link>
                ) : undefined
              }
            >
              {['processing', 'queued'].includes(item.status)
                ? 'Scenes will appear after processing and indexing finish.'
                : 'There are no extracted scenes for this video yet.'}
            </EmptyState>
          ) : tab === 'scenes' ? (
            <div
              className={`scene-grid video-scene-grid ${scenes.isPlaceholderData ? 'is-refreshing' : ''}`}
              aria-busy={scenes.isFetching}
            >
              {scenes.data.map((scene) => (
                <SceneCard key={scene.scene_id} scene={scene} />
              ))}
            </div>
          ) : dialogueCount === 0 ? (
            <EmptyState title="No dialogue in these scenes">
              Descriptions and other observations are available in the scene details.
            </EmptyState>
          ) : (
            <div className="transcript-list panel">
              {scenes.data
                .filter((scene) => scene.dialogue.length > 0)
                .map((scene) => (
                  <section className="transcript-scene" key={scene.scene_id}>
                    <div className="transcript-scene-heading">
                      <Link to={`/scenes/${scene.scene_id}`} className="text-link">
                        Scene {timestamp(scene.start)}
                        {scene.end != null && ` – ${timestamp(scene.end)}`}
                        <ArrowRight size={13} />
                      </Link>
                      <span className="small muted">
                        {scene.playback.available ? 'Video available' : 'Metadata only'}
                      </span>
                    </div>
                    {scene.dialogue.map((line, index) => (
                      <div className="transcript-line" key={`${line.start}-${index}`}>
                        <Link className="transcript-time" to={`/scenes/${scene.scene_id}`}>
                          {timestamp(line.start)}
                        </Link>
                        <p>
                          {line.speaker && <strong>{line.speaker}: </strong>}
                          {line.text}
                        </p>
                      </div>
                    ))}
                  </section>
                ))}
            </div>
          )}
        </div>
        {scenes.data && item.scene_count > 50 && (
          <nav className="catalog-pagination" aria-label="Scene pages">
            <p className="muted small">
              Scenes {count(offset + 1)}–{count(Math.min(offset + 50, item.scene_count))} of{' '}
              {count(item.scene_count)}
              {tab === 'transcript' && ' · Transcript for this page'}
            </p>
            <div>
              <Button
                variant="secondary"
                disabled={offset === 0 || scenes.isPlaceholderData}
                onClick={() => setPage({ videoId: id, offset: Math.max(0, offset - 50) })}
              >
                <ArrowLeft size={15} />
                Previous
              </Button>
              <Button
                variant="secondary"
                disabled={offset + 50 >= item.scene_count || scenes.isPlaceholderData}
                onClick={() => setPage({ videoId: id, offset: offset + 50 })}
              >
                Next
                <ArrowRight size={15} />
              </Button>
            </div>
          </nav>
        )}
      </section>
    </div>
  )
}
