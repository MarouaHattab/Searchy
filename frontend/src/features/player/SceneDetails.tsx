import { useState } from 'react'
import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'
import { Badge, EmptyState } from '../../components/ui'
import { excerpt, humanize, timestamp } from '../../lib/format'
import type { Dialogue, SceneDetail } from '../../types'

export function SceneInformation({
  data,
  duration,
  episodeTime,
  dialogueOffset,
  onSeek,
}: {
  data: SceneDetail
  duration: number
  episodeTime: number | null
  dialogueOffset: (line: Dialogue) => number
  onSeek: (offset: number) => void
}) {
  const [tab, setTab] = useState<'overview' | 'dialogue' | 'evidence'>('overview')
  return (
    <section className="scene-detail-panel panel">
      <div className="tabs" aria-label="Scene information">
        {(['overview', 'dialogue', 'evidence'] as const).map((item) => (
          <button
            key={item}
            className={tab === item ? 'active' : ''}
            onClick={() => setTab(item)}
            aria-pressed={tab === item}
          >
            {item === 'dialogue' ? `Dialogue (${data.dialogue.length})` : humanize(item)}
          </button>
        ))}
      </div>
      {tab === 'overview' ? (
        <div className="scene-overview">
          <h2>Inside this moment</h2>
          {data.description ? (
            data.description
              .split(/\n\s*\n/)
              .filter(Boolean)
              .map((paragraph, index) => <p key={index}>{excerpt(paragraph, 2400)}</p>)
          ) : (
            <p className="muted">No scene description is available.</p>
          )}
          <p className="small muted">
            Extracted descriptions may contain mistakes. Use the source media and dialogue to review
            details.
          </p>
        </div>
      ) : tab === 'dialogue' ? (
        <div className="transcript-list">
          {data.dialogue.length ? (
            data.dialogue.map((line, index) => {
              const offset = dialogueOffset(line)
              const canSeek =
                data.playback.available && offset >= 0 && (!duration || offset < duration)
              const active =
                data.playback.available &&
                episodeTime != null &&
                episodeTime >= line.start &&
                episodeTime < line.end
              return (
                <div
                  className={`transcript-line ${active ? 'active' : ''}`}
                  key={`${line.start}-${index}`}
                >
                  <button
                    disabled={!canSeek}
                    onClick={() => {
                      onSeek(offset)
                    }}
                    aria-label={`Play dialogue at ${timestamp(line.start)}`}
                  >
                    {timestamp(line.start)}
                  </button>
                  <p>
                    {line.speaker && <strong>{line.speaker}: </strong>}
                    {line.text}
                  </p>
                </div>
              )
            })
          ) : (
            <EmptyState title="No dialogue for this scene">
              The scene can still be searched through its visual description.
            </EmptyState>
          )}
        </div>
      ) : (
        <div className="scene-evidence">
          <h2>What the source says</h2>
          <p className="muted small">
            Observations are attached to this scene. A named subject is shown only when the stored
            evidence includes one.
          </p>
          {data.observations.length ? (
            data.observations.map((observation, index) => (
              <div className="observation" key={index}>
                <div>
                  <Badge>{humanize(observation.kind)}</Badge>
                  <Badge tone={observation.provenance.verified ? 'green' : 'amber'}>
                    {observation.provenance.verified ? 'Verified source' : 'Unverified extraction'}
                  </Badge>
                </div>
                <h3>
                  {observation.subject && `${observation.subject} · `}
                  {observation.value}
                </h3>
                <p>{observation.evidence}</p>
              </div>
            ))
          ) : (
            <p className="muted">No structured observations were stored.</p>
          )}
        </div>
      )}
    </section>
  )
}

export function SceneSidebar({
  data,
  isUpload,
  inferred,
}: {
  data: SceneDetail
  isUpload: boolean
  inferred: boolean
}) {
  return (
    <aside className="scene-sidebar">
      <section className="panel scene-info-panel">
        <h2>Scene details</h2>
        <dl className="detail-list">
          <div>
            <dt>Collection</dt>
            <dd>{data.collection_id}</dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>
              {isUpload ? 'Uploaded video' : data.episode_id ? 'Imported episode chunk' : 'Video'}
            </dd>
          </div>
          <div>
            <dt>Scene starts</dt>
            <dd>{timestamp(data.start)}</dd>
          </div>
          <div>
            <dt>Scene ends</dt>
            <dd>{timestamp(data.end)}</dd>
          </div>
          <div>
            <dt>Timing</dt>
            <dd>{inferred ? 'Inferred from chunk' : humanize(data.timestamp_basis)}</dd>
          </div>
          <div>
            <dt>Dialogue lines</dt>
            <dd>{data.dialogue.length}</dd>
          </div>
        </dl>
        <Link className="text-link" to={`/library/${data.video_id}`}>
          View video details
          <ArrowRight size={14} />
        </Link>
      </section>
      <section className="panel scene-info-panel">
        <h2>Character mentions</h2>
        {data.characters.length ? (
          <>
            <div className="chip-row">
              {data.characters.map((name) => (
                <Link
                  key={name}
                  className="character-chip"
                  to={`/search?character=${encodeURIComponent(name)}&q=${encodeURIComponent(name)}`}
                >
                  {name}
                </Link>
              ))}
            </div>
            <p className="small muted">
              Extracted associations. Review the evidence before relying on identity.
            </p>
          </>
        ) : (
          <p className="small muted">No named characters were recorded.</p>
        )}
      </section>
      <section className="scene-provenance">
        <h3>About this result</h3>
        <p>
          Searchy returns stored scenes and source evidence. A missing video or an unknown time
          stays clearly marked.
        </p>
        <p className="small">
          Scene ID <span className="monospace">{data.scene_id}</span>
        </p>
      </section>
    </aside>
  )
}
