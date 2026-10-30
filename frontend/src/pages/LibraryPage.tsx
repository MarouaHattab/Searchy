import { useEffect, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, ArrowUpRight, Film, Play, Search, Upload, X } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'
import { SceneThumbnail } from '../components/SceneCard'
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Loading,
  PageHeading,
  StatusBadge,
} from '../components/ui'
import { count, episodeTitle } from '../lib/format'
import { api } from '../services/api'
import '../styles/catalog.css'

const pageSize = 12

export default function LibraryPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const collection = params.get('collection') ?? ''
  const requestedOffset = Number(params.get('offset'))
  const offset = Number.isFinite(requestedOffset) ? Math.max(0, Math.floor(requestedOffset)) : 0
  const [draft, setDraft] = useState(q)
  const filters = { q, collection_id: collection, limit: pageSize, offset }
  const videos = useQuery({
    queryKey: ['library', filters],
    queryFn: ({ signal }) => api.library(filters, signal),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  })
  const workspace = useQuery({
    queryKey: ['workspace'],
    queryFn: ({ signal }) => api.workspace(signal),
    staleTime: 15_000,
  })

  useEffect(() => {
    setDraft(q)
  }, [q])

  function change(values: Record<string, string | number>) {
    const next = new URLSearchParams(params)
    Object.entries(values).forEach(([key, value]) =>
      value === '' || value === 0 ? next.delete(key) : next.set(key, String(value))
    )
    setParams(next)
  }

  return (
    <div className="catalog-page stack">
      <PageHeading
        eyebrow="Video library"
        title="Every video. Every moment."
        action={
          <Button onClick={() => window.dispatchEvent(new CustomEvent('searchy:upload'))}>
            <Upload size={17} />
            Upload video
          </Button>
        }
      >
        Browse your collection and explore what’s ready to search or watch.
      </PageHeading>
      <div className="library-toolbar">
        <form
          className="library-search"
          onSubmit={(event) => {
            event.preventDefault()
            change({ q: draft.trim(), offset: 0 })
          }}
        >
          <Search size={18} />
          <input
            aria-label="Search videos by title"
            placeholder="Search videos by title…"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          {draft && (
            <button
              type="button"
              className="icon-button"
              aria-label="Clear video search"
              onClick={() => {
                setDraft('')
                change({ q: '', offset: 0 })
              }}
            >
              <X size={16} />
            </button>
          )}
          <Button variant="secondary" type="submit">
            Search
          </Button>
        </form>
        <label className="collection-filter">
          <span className="sr-only">Filter by collection</span>
          <select
            className="select"
            value={collection}
            onChange={(event) => change({ collection: event.target.value, offset: 0 })}
          >
            <option value="">All collections</option>
            {workspace.data?.collections.map((item) => (
              <option key={item.collection_id} value={item.collection_id}>
                {item.collection_id}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="library-results-heading">
        <span>
          {videos.data
            ? `${count(videos.data.total)} ${videos.data.total === 1 ? 'video' : 'videos'}${q ? ` matching “${q}”` : ''}`
            : 'Your collection'}
        </span>
        <span className="muted small">
          {videos.isFetching && !videos.isPending
            ? 'Updating…'
            : 'Source availability shown on each video'}
        </span>
      </div>
      {videos.isPending ? (
        <Loading label="Loading your video library…" />
      ) : videos.isError ? (
        <ErrorState error={videos.error} retry={() => void videos.refetch()} />
      ) : !videos.data.items.length ? (
        <EmptyState
          title={q || collection ? 'No videos match these filters' : 'Add your first video'}
          action={
            q || collection ? (
              <Button
                variant="secondary"
                onClick={() => {
                  setDraft('')
                  setParams({})
                }}
              >
                Clear filters
              </Button>
            ) : (
              <Button onClick={() => window.dispatchEvent(new CustomEvent('searchy:upload'))}>
                <Upload size={16} />
                Upload video
              </Button>
            )
          }
        >
          {q || collection
            ? 'Try a different title or collection.'
            : 'Upload a video and Searchy will process it into searchable scenes.'}
        </EmptyState>
      ) : (
        <>
          <div
            className={`library-grid ${videos.isPlaceholderData ? 'is-refreshing' : ''}`}
            aria-busy={videos.isFetching}
          >
            {videos.data.items.map((video) => (
              <article className="library-card" key={video.video_id}>
                <Link
                  className="library-card-image"
                  to={`/library/${video.video_id}`}
                  aria-label={`Open ${video.title}`}
                >
                  <SceneThumbnail
                    id={video.thumbnail_scene_id ?? video.video_id}
                    available={Boolean(video.thumbnail_scene_id)}
                    title={video.title}
                  />
                  <span className="library-source">
                    <Badge tone={video.playable_scenes ? 'blue' : 'neutral'}>
                      {video.playable_scenes ? (
                        <>
                          <Play size={11} />
                          {count(video.playable_scenes)} playable
                        </>
                      ) : (
                        <>
                          <Film size={11} />
                          Metadata only
                        </>
                      )}
                    </Badge>
                  </span>
                </Link>
                <div className="library-card-body">
                  <div className="library-card-kicker">
                    <span className="eyebrow">{video.collection_id}</span>
                    <StatusBadge status={video.status} />
                  </div>
                  <h2>
                    <Link to={`/library/${video.video_id}`}>{video.title}</Link>
                  </h2>
                  <p className="muted small">
                    {video.source_kind === 'import'
                      ? episodeTitle(video.original_id)
                      : 'Uploaded video'}
                  </p>
                  <div className="library-card-bottom">
                    <span>
                      {count(video.indexed_scenes)}
                      <span className="muted"> / {count(video.scene_count)} scenes indexed</span>
                    </span>
                    <Link
                      className="icon-link"
                      to={`/library/${video.video_id}`}
                      aria-label={`View details for ${video.title}`}
                    >
                      <ArrowUpRight size={18} />
                    </Link>
                  </div>
                </div>
              </article>
            ))}
          </div>
          <nav className="catalog-pagination" aria-label="Video library pages">
            <p className="muted small">
              Showing {count(offset + 1)}–{count(Math.min(offset + pageSize, videos.data.total))} of{' '}
              {count(videos.data.total)}
            </p>
            <div>
              <Button
                variant="secondary"
                disabled={offset === 0 || videos.isPlaceholderData}
                onClick={() => change({ offset: Math.max(0, offset - pageSize) })}
              >
                <ArrowLeft size={15} />
                Previous
              </Button>
              <Button
                variant="secondary"
                disabled={offset + pageSize >= videos.data.total || videos.isPlaceholderData}
                onClick={() => change({ offset: offset + pageSize })}
              >
                Next
                <ArrowRight size={15} />
              </Button>
            </div>
          </nav>
        </>
      )}
    </div>
  )
}
