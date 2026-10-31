import { Maximize2, Play, ScanSearch, X } from 'lucide-react'
import { Link } from 'react-router'
import { episodeTitle, excerpt, timestamp } from '../../lib/format'
import { sceneHref } from '../player/navigation'
import { relationshipLabel, entityLabel } from './model'
import type { EvidenceEdge, EvidenceNode, SceneMatch } from '../../types'

const explanations: Record<string, string> = {
  Character: 'A person linked to these scenes by appearance, speech, or an observation.',
  Scene: 'A moment from the indexed video. Play opens this timestamp.',
  Action: 'An activity recorded in a scene observation.',
  Clothing: 'An outfit recorded for a person in a scene.',
  Object: 'An object recorded in a scene.',
  Location: 'A place recorded for a scene.',
  Dialogue: 'A spoken line from the indexed transcript.',
  Observation: 'A recorded visual or scene observation.',
}
const nodeExplanation = (type: string) => explanations[type] ?? ''

export function EvidenceInspector({
  selected,
  nodes,
  scenes,
  origin,
  inContext,
  expanded,
  busy,
  onOpen,
  onClear,
  onExpand,
  onFocus,
}: {
  selected: EvidenceNode | EvidenceEdge | undefined
  nodes: EvidenceNode[]
  scenes: SceneMatch[]
  origin: string
  inContext: boolean
  expanded: string[]
  busy: boolean
  onOpen: () => void
  onClear: () => void
  onExpand: (id: string) => void
  onFocus: (id: string) => void
}) {
  if (!selected)
    return (
      <aside className="graph-inspector">
        <div className="graph-inspector-empty">
          <ScanSearch size={28} strokeWidth={1.4} />
          <h3>Explore a connection</h3>
          <p>Select a person, scene, or connection to see the indexed evidence behind it.</p>
          <p className="small muted">Play opens that moment. Expand adds more recorded detail.</p>
        </div>
      </aside>
    )
  const node = 'properties' in selected ? selected : null
  const edge = 'source' in selected ? selected : null
  const title = node ? excerpt(node.label, 160) : relationshipLabel(selected.type)
  const properties = node?.properties
  const description = properties?.description ?? properties?.text ?? properties?.value
  const evidence = [...new Set(selected.evidence)]
    .filter((text) => text !== description)
    .slice(0, 4)
  const related = selected.scene_ids.slice(0, 12)
  return (
    <aside className="graph-inspector" aria-label="Selected evidence">
      <header className="graph-inspector-header">
        <span className="eyebrow">{node ? entityLabel(node.type) : 'Connection'}</span>
        <button className="icon-button" onClick={onClear} aria-label="Clear graph selection">
          <X size={16} />
        </button>
      </header>
      <h3>{title}</h3>
      {node && nodeExplanation(node.type) && (
        <p className="graph-source-label">{nodeExplanation(node.type)}</p>
      )}
      <p className="graph-source-label">
        {inContext ? 'Selected answer context' : 'Additional indexed evidence'}
      </p>
      {node?.verified != null && (
        <span className={`graph-verification ${node.verified ? 'verified' : ''}`}>
          {node.verified ? 'Verified record' : 'Extracted · unverified'}
        </span>
      )}
      {edge && (
        <div className="graph-connection">
          <span>{excerpt(nodes.find((n) => n.id === edge.source)?.label ?? 'Source', 80)}</span>
          <span>{relationshipLabel(edge.type)}</span>
          <span>{excerpt(nodes.find((n) => n.id === edge.target)?.label ?? 'Target', 80)}</span>
        </div>
      )}
      {edge?.derived && (
        <p className="graph-source-label">
          Summarized from indexed observations in these scenes. The times and quotes below are the
          source.
        </p>
      )}
      {node?.start != null && (
        <p className="graph-time">
          {timestamp(node.start)}
          {node.end != null ? ` – ${timestamp(node.end)}` : ''}
        </p>
      )}
      {typeof description === 'string' && (
        <p className="graph-description">{excerpt(description, 420)}</p>
      )}
      {!!evidence.length && (
        <section className="graph-evidence-quotes">
          <h4>Source evidence</h4>
          {evidence.map((text) => (
            <blockquote key={text}>{excerpt(text, 360)}</blockquote>
          ))}
        </section>
      )}
      <section className="graph-related-scenes">
        <h4>
          {node?.type === 'Scene' ? 'Watch this moment' : `Supporting scenes · ${related.length}`}
        </h4>
        {related.map((id) => {
          const scene = scenes.find((s) => s.scene_id === id)
          const record = nodes.find((n) => n.type === 'Scene' && n.scene_ids.includes(id))
          const label = scene
            ? episodeTitle(scene.episode_id)
            : String(record?.properties.episode_id ?? 'Indexed scene')
          const start = scene?.start ?? record?.start ?? null
          return (
            <div className="graph-scene-item" key={id}>
              <Link to={sceneHref(id, start, origin)} onClick={onOpen} className="graph-scene-play">
                <Play size={15} />
                <span>
                  {label}
                  <small>
                    {timestamp(start)}
                    {scene
                      ? ` · ${scene.playback.available ? 'Video available' : 'Metadata only'}`
                      : ''}
                  </small>
                </span>
              </Link>
              <div className="graph-scene-actions">
                <button className="text-link" onClick={() => onFocus(id)}>
                  <Maximize2 size={12} />
                  Focus
                </button>
                <button
                  className="text-link"
                  disabled={busy || (!expanded.includes(id) && expanded.length >= 3)}
                  onClick={() => onExpand(id)}
                >
                  {expanded.includes(id) ? 'Collapse evidence' : 'Expand evidence'}
                </button>
              </div>
            </div>
          )
        })}
      </section>
      <details className="graph-technical">
        <summary>Record details</summary>
        <dl>
          <div>
            <dt>Identifier</dt>
            <dd>{selected.id}</dd>
          </div>
          {properties &&
            Object.entries(properties)
              .filter(
                ([key, value]) =>
                  value != null && !['description', 'text', 'value', 'evidence'].includes(key)
              )
              .map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replaceAll('_', ' ')}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
          {node?.confidence != null && (
            <div>
              <dt>Extraction confidence</dt>
              <dd>{node.confidence.toFixed(2)}</dd>
            </div>
          )}
        </dl>
      </details>
    </aside>
  )
}
