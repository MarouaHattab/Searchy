import { useState } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ExternalLink, X } from 'lucide-react'
import { Link } from 'react-router'
import { SceneThumbnail } from '../../components/SceneCard'
import { Badge, Button, EmptyState, ErrorState, Loading, SectionHeading } from '../../components/ui'
import { message, timestamp } from '../../lib/format'
import { api, apiUrl } from '../../services/api'
import { characterApi } from './api'
import type { CustomCharacter } from './types'

function ScenePreview({ id }: { id: string }) {
  const scene = useQuery({
    queryKey: ['scene', id],
    queryFn: ({ signal }) => api.scene(id, signal),
    staleTime: 60_000,
  })
  if (scene.isPending) return <div className="character-preview-loading">Loading preview…</div>
  if (scene.isError) return <div className="character-preview-loading">Preview unavailable</div>
  return <SceneThumbnail id={id} available={scene.data.playback.available} title="Scene context" />
}

function MatchPreview({ sceneId, frameUrl }: { sceneId: string; frameUrl: string | null }) {
  const [failed, setFailed] = useState(false)
  if (frameUrl && !failed) {
    return (
      <>
        <div className="scene-thumbnail">
          <img
            src={apiUrl(frameUrl)}
            alt="Frame used for appearance comparison"
            loading="lazy"
            onError={() => setFailed(true)}
          />
        </div>
        <span>Matched frame</span>
      </>
    )
  }
  return (
    <>
      <ScenePreview id={sceneId} />
      <span>{failed ? 'Scene context · evidence frame unavailable' : 'Scene context'}</span>
    </>
  )
}

export function AppearanceReview({ character }: { character: CustomCharacter }) {
  const client = useQueryClient()
  const [filter, setFilter] = useState<'pending' | 'accepted' | 'rejected'>('pending')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const matches = useInfiniteQuery({
    queryKey: ['character-matches', character.id, character.revision],
    queryFn: ({ signal, pageParam }) => characterApi.matches(character.id, signal, pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) =>
      lastPage.length === 100 ? pages.length * 100 : undefined,
    refetchInterval: ['queued', 'processing'].includes(character.recognition_status) ? 4000 : false,
  })
  async function review(id: string, status: 'accepted' | 'rejected') {
    if (busy) return
    setBusy(id)
    setError('')
    try {
      await characterApi.review(character.id, id, status)
      await Promise.all(
        [
          'character-matches',
          'character-detail',
          'characters',
          'character-scenes',
          'search',
          'search-answer',
          'evidence-graph',
          'workspace',
        ].map((key) => client.invalidateQueries({ queryKey: [key] }))
      )
    } catch (failure) {
      setError(message(failure))
    } finally {
      setBusy('')
    }
  }
  const loaded = [...new Map(matches.data?.pages.flat().map((match) => [match.id, match])).values()]
  const visible = loaded.filter((match) => match.status === filter)
  return (
    <section className="stack character-section">
      <SectionHeading
        title="Appearance review"
        count={matches.hasNextPage ? undefined : matches.data ? loaded.length : undefined}
      />
      <p className="character-evidence-note">
        Review the cited frame or scene before accepting an identity. A suggested match is uncertain
        until confirmed; rejecting it preserves the original scene evidence.
      </p>
      <div className="character-review-tabs" role="group" aria-label="Filter appearance matches">
        {(['pending', 'accepted', 'rejected'] as const).map((status) => (
          <button key={status} aria-pressed={status === filter} onClick={() => setFilter(status)}>
            {status === 'pending'
              ? 'Needs review'
              : status === 'accepted'
                ? 'Accepted'
                : 'Rejected'}{' '}
            <span>{loaded.filter((match) => match.status === status).length}</span>
          </button>
        ))}
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {matches.isPending ? (
        <Loading label="Loading appearance evidence…" />
      ) : matches.isError && !matches.data ? (
        <ErrorState error={matches.error} retry={() => void matches.refetch()} />
      ) : !visible.length ? (
        <EmptyState
          title={
            matches.hasNextPage
              ? `No ${filter === 'pending' ? 'pending' : filter} matches on loaded pages`
              : filter === 'pending'
                ? 'No matches awaiting review'
                : `No ${filter} matches`
          }
        >
          {character.recognition_status === 'unprocessed'
            ? 'Prepare reference images, then choose Find appearances to check available video frames.'
            : 'Only matches supported by available evidence appear here.'}
        </EmptyState>
      ) : (
        <div className="character-match-list">
          {visible.map((match) => {
            const sceneUrl = `/scenes/${encodeURIComponent(match.scene_id)}${
              match.timestamp == null ? '' : `?t=${match.timestamp}`
            }`
            return (
              <article className="character-match panel" key={match.id}>
                <Link
                  to={sceneUrl}
                  className="character-match-preview"
                  aria-label={`Review scene at ${timestamp(match.timestamp)}`}
                >
                  <MatchPreview
                    key={match.frame_url}
                    sceneId={match.scene_id}
                    frameUrl={match.frame_url}
                  />
                </Link>
                <div className="character-match-copy">
                  <Badge tone={match.status === 'accepted' ? 'green' : 'neutral'}>
                    {match.verified
                      ? 'Confirmed by review'
                      : match.status === 'pending'
                        ? 'Suggested identity'
                        : match.status === 'rejected'
                          ? 'Rejected identity'
                          : 'Accepted association'}
                  </Badge>
                  <p>{match.evidence}</p>
                  <span className="muted small">
                    Evidence observed at {timestamp(match.timestamp)}
                  </span>
                  <span className="muted small">
                    {match.method.replaceAll('_', ' ')} · Reference revision {match.revision}
                  </span>
                  <Link className="text-link" to={sceneUrl}>
                    Review scene <ExternalLink size={13} />
                  </Link>
                </div>
                <div className="character-match-actions">
                  {match.status !== 'accepted' && (
                    <Button
                      variant="secondary"
                      disabled={!!busy}
                      onClick={() => void review(match.id, 'accepted')}
                    >
                      <Check size={14} />
                      {busy === match.id ? 'Saving…' : 'Accept'}
                    </Button>
                  )}
                  {match.status !== 'rejected' && (
                    <Button
                      variant="ghost"
                      disabled={!!busy}
                      onClick={() => void review(match.id, 'rejected')}
                    >
                      <X size={14} />
                      Reject
                    </Button>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      )}
      {matches.hasNextPage && (
        <div className="character-inline-actions">
          <p className="muted small">
            {loaded.length} matches loaded. Counts apply to the loaded pages.
          </p>
          <Button
            variant="secondary"
            disabled={matches.isFetchingNextPage}
            onClick={() => void matches.fetchNextPage()}
          >
            {matches.isFetchingNextPage ? 'Loading more appearances…' : 'Load more appearances'}
          </Button>
        </div>
      )}
      {matches.isFetchNextPageError && (
        <p className="form-error" role="alert">
          More appearances could not load. Your loaded matches remain available; try loading more
          again.
        </p>
      )}
    </section>
  )
}
