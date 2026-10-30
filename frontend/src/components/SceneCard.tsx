import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { ArrowUpRight, Clapperboard, FileText, GitBranch, Play, Quote } from 'lucide-react'
import { episodeTitle, excerpt, sceneTitle, timestamp } from '../lib/format'
import { api, thumbnailUrl } from '../services/api'
import type { SceneDetail, SceneMatch } from '../types'
import { Badge } from './ui'

export function SceneThumbnail({
  id,
  available,
  title = 'Scene preview',
}: {
  id: string
  available: boolean
  title?: string
}) {
  const [failed, setFailed] = useState(false)
  return (
    <div className={`scene-thumbnail ${available && !failed ? '' : 'thumbnail-empty'}`}>
      {available && !failed ? (
        <img src={thumbnailUrl(id)} loading="lazy" alt={title} onError={() => setFailed(true)} />
      ) : (
        <>
          <Clapperboard size={28} strokeWidth={1.3} />
          <span>{available ? 'Preview unavailable' : 'Metadata only'}</span>
        </>
      )}
      {available && !failed && (
        <span className="thumbnail-play">
          <Play size={17} fill="currentColor" />
        </span>
      )}
    </div>
  )
}

export function SceneCard({
  scene,
  compact = false,
  rank,
  selected = false,
  onSelect,
}: {
  scene: SceneDetail | SceneMatch
  compact?: boolean
  rank?: number
  selected?: boolean
  onSelect?: (sceneId: string) => void
}) {
  const video = useQuery({
    queryKey: ['video', scene.video_id],
    queryFn: ({ signal }) => api.video(scene.video_id, signal),
    enabled: !scene.episode_id,
    staleTime: 60_000,
  })
  const match = 'evidence' in scene ? scene : null
  const characters = 'characters' in scene ? scene.characters : scene.matching_characters
  const title = scene.episode_id
    ? sceneTitle(scene.episode_id)
    : (video.data?.title ?? 'Uploaded video')
  return (
    <article
      className={`scene-card ${compact ? 'scene-card-compact' : ''} ${selected ? 'scene-card-selected' : ''}`}
    >
      <Link
        className="scene-image-link"
        to={`/scenes/${scene.scene_id}`}
        aria-label={`${scene.playback.available ? 'Play' : 'View'} ${episodeTitle(scene.episode_id)} at ${timestamp(scene.start)}`}
      >
        <SceneThumbnail
          id={scene.scene_id}
          available={scene.playback.available}
          title={`${episodeTitle(scene.episode_id)} at ${timestamp(scene.start)}`}
        />
        <span className="scene-time">
          {timestamp(scene.start)}
          {scene.end != null && ` – ${timestamp(scene.end)}`}
        </span>
      </Link>
      <div className="scene-card-content">
        <div className="scene-card-top">
          <span className="eyebrow">{scene.collection_id}</span>
          {rank !== undefined && <span className="muted small">#{rank}</span>}
        </div>
        <h3>
          <Link to={`/scenes/${scene.scene_id}`}>{title}</Link>
        </h3>
        {scene.episode_id && (
          <p className="scene-episode-label">{episodeTitle(scene.episode_id)}</p>
        )}
        <p className="scene-description">
          {excerpt(scene.description, compact ? 110 : 220) ||
            'Scene details are available in the transcript.'}
        </p>
        {!!characters.length && (
          <div className="chip-row">
            {characters.slice(0, 3).map((name) => (
              <span className="character-chip" key={name}>
                {name}
              </span>
            ))}
            {characters.length > 3 && <span className="muted small">+{characters.length - 3}</span>}
          </div>
        )}
        {match && !compact && match.dialogue[0] && (
          <blockquote className="dialogue-quote">
            <Quote size={14} />
            <span>{excerpt(match.dialogue[0].text, 140)}</span>
          </blockquote>
        )}
        {match && !compact && match.evidence.length > 0 && (
          <p className="match-evidence">{excerpt(match.evidence[0], 170)}</p>
        )}
        <div className="scene-card-footer">
          <Badge tone={scene.playback.available ? 'blue' : 'neutral'}>
            {scene.playback.available ? (
              <>
                <Play size={11} />
                Video available
              </>
            ) : (
              <>
                <FileText size={11} />
                Metadata only
              </>
            )}
          </Badge>
          {onSelect && (
            <button
              className="icon-button"
              aria-label="Explore scene evidence"
              onClick={() => onSelect(scene.scene_id)}
            >
              <GitBranch size={16} />
            </button>
          )}
          <Link className="icon-link" to={`/scenes/${scene.scene_id}`} aria-label="Open scene">
            <ArrowUpRight size={18} />
          </Link>
        </div>
        {match && match.match_status !== 'verified' && match.match_status !== 'match' && (
          <span className="small muted">
            {match.missing_terms?.length
              ? `Not evidenced: ${match.missing_terms.join(', ')}`
              : 'Extracted evidence · review scene details'}
          </span>
        )}
      </div>
    </article>
  )
}
