import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import {
  Background,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useReactFlow,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import {
  Box,
  Download,
  Film,
  GitBranch,
  MapPin,
  Maximize2,
  MessageSquare,
  Minus,
  Plus,
  Play,
  RotateCcw,
  ScanSearch,
  Search,
  Shirt,
  SlidersHorizontal,
  Users,
  X,
  Zap,
} from 'lucide-react'
import { useNavigate } from 'react-router'
import { Button, EmptyState, ErrorState, Loading } from '../../components/ui'
import { api } from '../../services/api'
import { excerpt, timestamp } from '../../lib/format'
import { sceneHref } from '../player/navigation'
import { EvidenceInspector } from './EvidenceInspector'
import {
  entityLabel,
  filterEvidenceGraph,
  layoutGraph,
  mergeGraphs,
  hiddenForView,
  overviewHidden,
  researchGraph,
  readGraphState,
  relationshipLabel,
  saveGraphState,
  summarizeGraph,
  typeLabels,
  visibleGraph,
  type GraphPreferences,
  type ResearchView,
} from './model'
import type { EvidenceGraph as GraphData, EvidenceNode, SceneMatch } from '../../types'
import '@xyflow/react/dist/style.css'

const icons = {
  Scene: Film,
  Video: Film,
  Episode: Film,
  Character: Users,
  Observation: ScanSearch,
  Dialogue: MessageSquare,
  Action: Zap,
  Object: Box,
  Location: MapPin,
  Clothing: Shirt,
}
type GraphNode = Node<
  { record: EvidenceNode; label: string; open?: (record: EvidenceNode) => void },
  'evidence'
>
const EvidenceCard = memo(function EvidenceCard({ data }: NodeProps<GraphNode>) {
  const record = data.record
  const Icon = icons[record.type as keyof typeof icons] ?? ScanSearch
  const title =
    record.type === 'Scene'
      ? String(record.properties.episode_id ?? record.label).replace(/^\d+x\d+\s*-\s*/, '')
      : record.type === 'Observation'
        ? String(record.properties.value ?? record.label)
        : record.label
  return (
    <div className={`graph-card graph-card-${record.type.toLowerCase()}`}>
      <Handle type="target" position={Position.Left} />
      <span className="graph-card-kind">
        <Icon size={13} />
        {entityLabel(record.type)}
      </span>
      <strong title={excerpt(title, 300)}>{excerpt(title, 72)}</strong>
      {record.verified != null && (
        <span className={`graph-card-verification ${record.verified ? 'verified' : 'unverified'}`}>
          <i aria-hidden="true" />
          {record.verified ? 'Source marked verified' : 'Unverified source'}
        </span>
      )}
      {record.start != null && (
        <div className="graph-card-foot">
          <span>
            {timestamp(record.start)} – {timestamp(record.end)}
          </span>
          <button
            className="graph-node-play nodrag nopan"
            aria-label={`Open evidence at ${timestamp(record.start)}`}
            onClick={(event) => {
              event.stopPropagation()
              data.open?.(record)
            }}
          >
            <Play size={12} />
          </button>
        </div>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  )
})
const nodeTypes = { evidence: EvidenceCard }

interface Props {
  scenes: SceneMatch[]
  answerGraph?: GraphData
  stateKey: string
  query: string
  collection: string
  characterId: string
  origin: string
  focusSceneId: string | null
  onOpen: () => void
  onFocus: (id: string | null) => void
  onSelection: (ids: string[]) => void
}

function GraphWorkspace({
  scenes,
  answerGraph,
  stateKey,
  query,
  collection,
  characterId,
  origin,
  focusSceneId,
  onOpen,
  onFocus,
  onSelection,
}: Props) {
  const flow = useReactFlow()
  const navigate = useNavigate()
  const [preferences, setPreferences] = useState<GraphPreferences>(() => readGraphState(stateKey))
  const [filtersOpen, setFiltersOpen] = useState(false)
  const suppliedGraph = answerGraph?.nodes.length ? answerGraph : undefined
  const context = useQuery({
    queryKey: ['search-context', stateKey],
    queryFn: ({ signal }) =>
      api.context(
        {
          query,
          scene_ids: scenes.slice(0, 12).map((s) => s.scene_id),
          collection_id: collection || undefined,
          character_ids: characterId ? [characterId] : undefined,
          search_id: stateKey,
        },
        signal
      ),
    enabled: !suppliedGraph && scenes.length > 0,
    retry: false,
    staleTime: Infinity,
    gcTime: 60 * 60_000,
  })
  const base = suppliedGraph ?? context.data?.graph
  const orderedIds = useMemo(() => {
    const ranked = scenes.map((s) => s.scene_id)
    const included = base?.scene_ids ?? []
    return [
      ...new Set([...ranked.filter((id) => included.includes(id)), ...included, ...ranked]),
    ].slice(0, 12)
  }, [scenes, base])
  const scope = useMemo(
    () => (focusSceneId ? [focusSceneId] : orderedIds.slice(0, preferences.count)),
    [focusSceneId, orderedIds, preferences.count]
  )
  const extraIds = [
    ...new Set([
      ...preferences.expanded,
      ...scope.filter((id) => base && !base.scene_ids.includes(id)),
    ]),
  ].slice(0, 12)
  const extra = useQueries({
    queries: extraIds.map((id) => ({
      queryKey: ['graph-expansion', stateKey, id, query],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.graph({ scene_ids: [id], collection_id: collection || undefined, query }, signal),
      enabled: !!base,
      retry: false,
      staleTime: Infinity,
      gcTime: 60 * 60_000,
    })),
  })
  const extraSignature = extra.map((result) => result.dataUpdatedAt).join(',')
  const graph = useMemo(
    () =>
      summarizeGraph(
        mergeGraphs([
          ...(base ? [base] : []),
          ...extra.flatMap((result) => (result.data ? [result.data] : [])),
        ])
      ),
    [base, extraSignature]
  )
  const recordingOptions = useMemo(() => {
    const videos = new Map<string, string>()
    for (const node of graph.nodes) {
      if (node.type === 'Video' && typeof node.properties.video_id === 'string') {
        videos.set(
          node.properties.video_id,
          String(node.properties.title ?? node.properties.video_id)
        )
      }
      if (node.type === 'Scene' && typeof node.properties.video_id === 'string') {
        const id = node.properties.video_id
        if (!videos.has(id)) videos.set(id, id)
      }
    }
    return [...videos.entries()].sort((a, b) => a[1].localeCompare(b[1]))
  }, [graph.nodes])
  const sourceOptions = useMemo(() => {
    const sources = new Map<string, string>()
    for (const edge of graph.edges) {
      for (const support of edge.supports ?? []) {
        if (support.source_reference)
          sources.set(`file:${support.source_reference}`, support.source_reference)
        if (support.method) sources.set(`method:${support.method}`, `Method · ${support.method}`)
      }
    }
    return [...sources.entries()].sort((a, b) => a[1].localeCompare(b[1]))
  }, [graph.edges])
  const filtered = useMemo(
    () =>
      filterEvidenceGraph(graph, {
        source: preferences.sourceFilter,
        recordingId: preferences.recordingFilter,
        from: preferences.timeFrom,
        to: preferences.timeTo,
        verification: preferences.verificationFilter,
      }),
    [
      graph,
      preferences.sourceFilter,
      preferences.recordingFilter,
      preferences.timeFrom,
      preferences.timeTo,
      preferences.verificationFilter,
    ]
  )
  const researched = useMemo(
    () =>
      researchGraph(filtered, preferences.mode, {
        characterId,
        focusSceneId,
        selectedId: preferences.selected,
        recordingId: preferences.recordingFilter,
      }),
    [
      filtered,
      preferences.mode,
      preferences.selected,
      preferences.recordingFilter,
      characterId,
      focusSceneId,
    ]
  )
  const view = useMemo(
    () =>
      visibleGraph(
        researched,
        scope,
        preferences.hidden,
        preferences.hiddenEdges,
        preferences.collapsedScenes
      ),
    [researched, scope, preferences.hidden, preferences.hiddenEdges, preferences.collapsedScenes]
  )
  const selected = [...graph.nodes, ...graph.edges].find((item) => item.id === preferences.selected)
  const selectedScene =
    selected && 'properties' in selected && selected.type === 'Scene' ? selected.scene_ids[0] : null
  useEffect(() => {
    const match = focusSceneId
      ? (graph.nodes.find((node) => node.type === 'Scene' && node.scene_ids.includes(focusSceneId))
          ?.id ?? `Scene:${focusSceneId}`)
      : null
    setPreferences((previous) =>
      previous.focusedScene === focusSceneId && (!match || previous.selected === match)
        ? previous
        : {
            ...previous,
            focusedScene: focusSceneId,
            selected: match ?? previous.selected,
          }
    )
  }, [focusSceneId, graph.nodes])
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNode>([])
  const openScene = useCallback(
    (record: EvidenceNode) => {
      onOpen()
      navigate(sceneHref(record.scene_ids[0], record.start, origin))
    },
    [onOpen, navigate, origin]
  )
  const openRef = useRef(openScene)
  openRef.current = openScene
  useEffect(() => {
    const saved = readGraphState(stateKey)
    setNodes(
      layoutGraph(view.nodes, view.edges, orderedIds, saved.positions, preferences.mode).map(
        (node) => ({
          ...node,
          data: { ...node.data, open: (record: EvidenceNode) => openRef.current(record) },
        })
      )
    )
  }, [view, orderedIds, setNodes, stateKey, preferences.mode])
  useEffect(() => saveGraphState(stateKey, preferences), [stateKey, preferences])
  const selectionSignature = selected?.scene_ids.join(',') ?? ''
  useEffect(() => {
    onSelection(selectionSignature ? selectionSignature.split(',') : [])
  }, [selectionSignature, onSelection])
  const connected = new Set(
    selected
      ? [
          'source' in selected ? selected.source : selected.id,
          ...('target' in selected ? [selected.target] : []),
          ...view.edges
            .filter((e) => e.source === selected.id || e.target === selected.id)
            .flatMap((e) => [e.source, e.target]),
        ]
      : []
  )
  const entityQuery = preferences.entityQuery.trim().toLowerCase()
  const displayNodes = nodes.map((node) => ({
    ...node,
    selected: node.id === selected?.id,
    style: {
      opacity:
        entityQuery && !node.data.label.toLowerCase().includes(entityQuery)
          ? 0.28
          : selected && !connected.has(node.id)
            ? 0.4
            : 1,
    },
  }))
  const edges = view.edges.map((edge) => ({
    ...edge,
    type: 'smoothstep',
    label:
      preferences.labels || edge.id === selected?.id ? relationshipLabel(edge.type) : undefined,
    ariaLabel: `${relationshipLabel(edge.type)}: ${graph.nodes.find((n) => n.id === edge.source)?.label ?? ''} to ${graph.nodes.find((n) => n.id === edge.target)?.label ?? ''}`,
    selected: edge.id === selected?.id,
    markerEnd: { type: MarkerType.ArrowClosed, width: 13, height: 13 },
    style: {
      stroke: edge.id === selected?.id ? 'var(--accent)' : 'var(--graph-line)',
      strokeWidth: edge.id === selected?.id ? 2 : 1.2,
      strokeDasharray: edge.derived ? '5 4' : undefined,
      opacity: selected && !connected.has(edge.source) && !connected.has(edge.target) ? 0.25 : 1,
    },
    labelStyle: { fill: 'var(--text)', fontSize: 11 },
    labelBgStyle: { fill: 'var(--surface)' },
    labelBgPadding: [6, 3] as [number, number],
  }))
  const busy = extra.some((result) => result.isFetching)
  const expand = (id: string) => {
    const collapsing = preferences.expanded.includes(id)
    onFocus(collapsing ? null : id)
    setPreferences((previous) => ({
      ...previous,
      expanded: previous.expanded.includes(id)
        ? previous.expanded.filter((s) => s !== id)
        : [...previous.expanded, id].slice(0, 3),
      hidden: collapsing
        ? [...new Set([...previous.hidden, 'Observation', 'Dialogue', 'Action', 'Clothing'])]
        : previous.hidden.filter(
            (type) => !['Observation', 'Dialogue', 'Action', 'Clothing'].includes(type)
          ),
    }))
  }
  const setMode = (mode: ResearchView) =>
    setPreferences((current) => ({
      ...current,
      mode,
      hidden: [...hiddenForView(mode)],
      viewport: mode === current.mode ? current.viewport : undefined,
    }))
  const collapseScene = (sceneId: string) =>
    setPreferences((current) => ({
      ...current,
      collapsedScenes: current.collapsedScenes.includes(sceneId)
        ? current.collapsedScenes.filter((id) => id !== sceneId)
        : [...current.collapsedScenes, sceneId].slice(-12),
    }))
  const exportEvidence = (format: 'json' | 'csv') => {
    const rows = view.edges.map((edge) => ({
      source: graph.nodes.find((node) => node.id === edge.source)?.label ?? edge.source,
      source_id: edge.source,
      relationship: relationshipLabel(edge.type),
      relationship_type: edge.type,
      target: graph.nodes.find((node) => node.id === edge.target)?.label ?? edge.target,
      target_id: edge.target,
      scene_ids: edge.scene_ids.join(' '),
      status: edge.derived ? 'inferred' : 'indexed',
      recording_ids: [
        ...new Set((edge.supports ?? []).map((support) => support.recording_id).filter(Boolean)),
      ].join(' '),
      evidence_ids: [...new Set((edge.supports ?? []).map((support) => support.evidence_id))].join(
        ' '
      ),
      intervals: (edge.supports ?? [])
        .map((support) =>
          support.start != null && support.end != null ? `${support.start}-${support.end}` : ''
        )
        .filter(Boolean)
        .join(' '),
      sources: [
        ...new Set(
          (edge.supports ?? []).map((support) => support.source_reference).filter(Boolean)
        ),
      ].join(' '),
      methods: [
        ...new Set((edge.supports ?? []).map((support) => support.method).filter(Boolean)),
      ].join(' '),
      evidence: edge.evidence.join(' | '),
    }))
    const content =
      format === 'json'
        ? JSON.stringify({ nodes: view.nodes, edges: view.edges }, null, 2)
        : [
            Object.keys(rows[0] ?? { source: '', relationship: '', target: '' }).join(','),
            ...rows.map((row) =>
              Object.values(row)
                .map((value) => `"${String(value).replaceAll('"', '""')}"`)
                .join(',')
            ),
          ].join('\n')
    const file = new Blob([content], { type: format === 'json' ? 'application/json' : 'text/csv' })
    const url = URL.createObjectURL(file)
    const link = document.createElement('a')
    link.href = url
    link.download = `searchy-evidence.${format}`
    link.click()
    URL.revokeObjectURL(url)
  }
  const reset = () => {
    const initial = {
      ...readGraphState('new'),
      hidden: [...overviewHidden],
      count: 3,
      mode: 'overview' as const,
      entityQuery: '',
      selected: null,
      expanded: [],
      collapsedScenes: [],
      sourceFilter: '',
      recordingFilter: '',
      timeFrom: null,
      timeTo: null,
      verificationFilter: 'all' as const,
      positions: {},
      viewport: undefined,
    }
    setPreferences(initial)
    saveGraphState(stateKey, initial)
    onFocus(null)
    setNodes(
      layoutGraph(view.nodes, view.edges, orderedIds, {}, 'overview').map((n) => ({
        ...n,
        data: { ...n.data, open: openScene },
      }))
    )
    window.requestAnimationFrame(() => void flow.fitView({ padding: 0.14, maxZoom: 1 }))
  }
  if (!base && context.isPending) return <Loading label="Loading the indexed scene evidence…" />
  if (!base && context.isError)
    return <ErrorState error={context.error} retry={() => void context.refetch()} />
  if (!base?.nodes.length)
    return (
      <EmptyState title="No graph evidence is available">
        <p>Scene results remain available. Check service status or retry the graph.</p>
        <Button variant="secondary" onClick={() => void context.refetch()}>
          Retry graph
        </Button>
      </EmptyState>
    )
  return (
    <div className="graph-workspace graph-workspace-v2">
      <header className="graph-heading">
        <div>
          <span className="graph-heading-icon">
            <GitBranch size={19} />
          </span>
          <div>
            <h3>Graph evidence</h3>
            <p>
              Indexed evidence for this search
              {scope.length ? ` · ${scope.length} ${scope.length === 1 ? 'scene' : 'scenes'}` : ''}
            </p>
          </div>
        </div>
        <Button variant="ghost" onClick={reset}>
          <RotateCcw size={14} />
          Reset view
        </Button>
      </header>
      <div className="graph-view-switch" role="tablist" aria-label="Evidence graph views">
        {(
          [
            ['overview', 'Overview'],
            ['evidence', 'Evidence'],
            ['timeline', 'Timeline'],
            ['recording', 'Recording'],
            ['activity', 'Activity'],
            ['character', 'Character'],
            ['scene', 'Scene'],
            ['relationship', 'Relationship'],
          ] as const
        ).map(([mode, label]) => (
          <button
            key={mode}
            role="tab"
            aria-selected={preferences.mode === mode}
            className={preferences.mode === mode ? 'active' : ''}
            onClick={() => setMode(mode)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="graph-controls">
        <div className="graph-scope">
          <label className="graph-search">
            <Search size={14} />
            <span className="sr-only">Search entities in this graph</span>
            <input
              value={preferences.entityQuery}
              maxLength={80}
              placeholder="Find an entity"
              onChange={(event) =>
                setPreferences((current) => ({ ...current, entityQuery: event.target.value }))
              }
            />
          </label>
          <span>
            {view.nodes.length} nodes · {view.edges.length} connections
          </span>
          {preferences.mode === 'timeline' && (
            <span className="graph-timeline-note">
              Chronological order · spacing is not duration scale
            </span>
          )}
          {busy && <span className="small muted">Loading evidence…</span>}
          {focusSceneId && (
            <button className="text-link" onClick={() => onFocus(null)}>
              Show all matches <X size={12} />
            </button>
          )}
          {!focusSceneId && preferences.count < orderedIds.length && (
            <button
              className="text-link"
              disabled={busy}
              onClick={() => setPreferences((p) => ({ ...p, count: Math.min(12, p.count + 3) }))}
            >
              Add next {Math.min(3, orderedIds.length - preferences.count)} scenes{' '}
              <Plus size={13} />
            </button>
          )}
        </div>
        <div>
          <button
            className={`graph-tool ${filtersOpen ? 'active' : ''}`}
            aria-expanded={filtersOpen}
            onClick={() => setFiltersOpen(!filtersOpen)}
          >
            <SlidersHorizontal size={14} />
            Filters
          </button>
          {selectedScene && (
            <button
              className={`graph-tool ${preferences.collapsedScenes.includes(selectedScene) ? 'active' : ''}`}
              aria-pressed={preferences.collapsedScenes.includes(selectedScene)}
              onClick={() => collapseScene(selectedScene)}
            >
              {preferences.collapsedScenes.includes(selectedScene)
                ? 'Expand scene'
                : 'Collapse scene'}
            </button>
          )}
          <button
            className={`graph-tool ${preferences.labels ? 'active' : ''}`}
            aria-pressed={preferences.labels}
            onClick={() => setPreferences((p) => ({ ...p, labels: !p.labels }))}
          >
            Labels
          </button>
          <button className="graph-tool" onClick={() => exportEvidence('json')}>
            <Download size={14} />
            JSON
          </button>
          <button className="graph-tool" onClick={() => exportEvidence('csv')}>
            CSV
          </button>
        </div>
      </div>
      <div className="graph-legend" aria-label="Evidence graph legend">
        {[
          ['Sources', ['Video', 'Episode']],
          ['Scenes', ['Scene']],
          ['Evidence records', ['Observation', 'Dialogue']],
          ['Entities', ['Character', 'Action', 'Clothing', 'Object', 'Location']],
        ].map(([group, types]) => {
          const shown = (types as string[]).filter((type) =>
            view.nodes.some((node) => node.type === type)
          )
          if (!shown.length) return null
          return (
            <div className="graph-legend-group" key={String(group)}>
              <span className="graph-legend-layer">{group}</span>
              {shown.map((type) => (
                <span key={type} className={`graph-legend-item graph-legend-${type.toLowerCase()}`}>
                  {typeLabels[type]}
                </span>
              ))}
            </div>
          )
        })}
        <span className="graph-edge-legend">
          <i /> Stored relationship
        </span>
        {view.edges.some((edge) => edge.derived) && (
          <span className="graph-edge-legend inferred">
            <i /> Summary with supporting evidence
          </span>
        )}
      </div>
      <p className="graph-schema-note">
        This index has no camera/session, reviewer, or conflict records. Missing source times remain
        unset.
      </p>
      {filtersOpen && (
        <div className="graph-filter-panel">
          <fieldset className="graph-provenance-filters">
            <legend>Evidence scope</legend>
            <label>
              Source
              <select
                value={preferences.sourceFilter}
                onChange={(event) =>
                  setPreferences((current) => ({ ...current, sourceFilter: event.target.value }))
                }
              >
                <option value="">All indexed sources</option>
                {sourceOptions.map(([value, label]) => (
                  <option value={value} key={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Recording
              <select
                value={preferences.recordingFilter}
                onChange={(event) =>
                  setPreferences((current) => ({
                    ...current,
                    recordingFilter: event.target.value,
                    mode: event.target.value ? 'recording' : current.mode,
                  }))
                }
              >
                <option value="">All recordings</option>
                {recordingOptions.map(([id, title]) => (
                  <option value={id} key={id}>
                    {title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              From (seconds)
              <input
                aria-label="Start of evidence time range in seconds"
                type="number"
                min="0"
                step="0.1"
                value={preferences.timeFrom ?? ''}
                onChange={(event) =>
                  setPreferences((current) => ({
                    ...current,
                    timeFrom: event.target.value === '' ? null : Number(event.target.value),
                  }))
                }
              />
            </label>
            <label>
              To (seconds)
              <input
                aria-label="End of evidence time range in seconds"
                type="number"
                min="0"
                step="0.1"
                value={preferences.timeTo ?? ''}
                onChange={(event) =>
                  setPreferences((current) => ({
                    ...current,
                    timeTo: event.target.value === '' ? null : Number(event.target.value),
                  }))
                }
              />
            </label>
            <label>
              Verification
              <select
                value={preferences.verificationFilter}
                onChange={(event) =>
                  setPreferences((current) => ({
                    ...current,
                    verificationFilter: event.target
                      .value as GraphPreferences['verificationFilter'],
                  }))
                }
              >
                <option value="all">All evidence states</option>
                <option value="verified">Source marked verified</option>
                <option value="unverified">Marked unverified</option>
                <option value="unreviewed">No verification flag</option>
                <option value="inferred">Inferred summaries</option>
              </select>
            </label>
            <button
              className="text-link"
              onClick={() =>
                setPreferences((current) => ({
                  ...current,
                  sourceFilter: '',
                  recordingFilter: '',
                  timeFrom: null,
                  timeTo: null,
                  verificationFilter: 'all',
                }))
              }
            >
              Clear evidence filters
            </button>
          </fieldset>
          {preferences.timeFrom != null &&
            preferences.timeTo != null &&
            preferences.timeFrom > preferences.timeTo && (
              <p className="graph-filter-error" role="alert">
                The start time must be before the end time.
              </p>
            )}
          <fieldset>
            <legend>Show entities</legend>
            {Object.entries(typeLabels)
              .filter(([type]) => graph.nodes.some((n) => n.type === type))
              .map(([type, label]) => (
                <label key={type}>
                  <input
                    type="checkbox"
                    checked={!preferences.hidden.includes(type)}
                    onChange={() =>
                      setPreferences((p) => ({
                        ...p,
                        hidden: p.hidden.includes(type)
                          ? p.hidden.filter(
                              (t) =>
                                t !== type &&
                                (!['Action', 'Clothing'].includes(type) || t !== 'Observation')
                            )
                          : [...p.hidden, type],
                      }))
                    }
                  />
                  {label}
                </label>
              ))}
          </fieldset>
          <fieldset>
            <legend>Show connections</legend>
            {[...new Set(graph.edges.map((e) => e.type))].map((type) => (
              <label key={type}>
                <input
                  type="checkbox"
                  checked={!preferences.hiddenEdges.includes(type)}
                  onChange={() =>
                    setPreferences((p) => ({
                      ...p,
                      hiddenEdges: p.hiddenEdges.includes(type)
                        ? p.hiddenEdges.filter((t) => t !== type)
                        : [...p.hiddenEdges, type],
                    }))
                  }
                />
                {relationshipLabel(type)}
              </label>
            ))}
          </fieldset>
        </div>
      )}
      <div className="graph-stage">
        <div className="graph-viewport" role="region" aria-label="Interactive scene evidence graph">
          <ReactFlow
            nodes={displayNodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onNodeClick={(_, node) => setPreferences((p) => ({ ...p, selected: node.id }))}
            onNodeDoubleClick={(_, node) =>
              node.data.record.start != null && openScene(node.data.record)
            }
            onEdgeClick={(_, edge) => setPreferences((p) => ({ ...p, selected: edge.id }))}
            onPaneClick={() => setPreferences((p) => ({ ...p, selected: null }))}
            onNodeDragStop={(_, node) =>
              setPreferences((p) => ({
                ...p,
                positions: { ...p.positions, [node.id]: node.position },
              }))
            }
            onMoveEnd={(_, viewport) => setPreferences((p) => ({ ...p, viewport }))}
            defaultViewport={preferences.viewport}
            fitView={!preferences.viewport}
            fitViewOptions={{ padding: 0.16, minZoom: 0.4, maxZoom: 1 }}
            minZoom={0.25}
            maxZoom={1.6}
            nodesConnectable={false}
            edgesReconnectable={false}
            deleteKeyCode={null}
          >
            <Background color="var(--line)" gap={24} />
            <div className="graph-zoom-controls">
              <button
                className="icon-button"
                aria-label="Zoom out graph"
                onClick={() => void flow.zoomOut()}
              >
                <Minus size={16} />
              </button>
              <button
                className="icon-button"
                aria-label="Zoom in graph"
                onClick={() => void flow.zoomIn()}
              >
                <Plus size={16} />
              </button>
              <button
                className="icon-button"
                aria-label="Fit graph to view"
                onClick={() => void flow.fitView({ padding: 0.12 })}
              >
                <Maximize2 size={16} />
              </button>
            </div>
          </ReactFlow>
          {!view.nodes.length && (
            <div className="graph-no-nodes">
              {preferences.mode === 'path' || preferences.mode === 'relationship'
                ? 'Select a node or connection to inspect its supporting evidence.'
                : preferences.mode === 'timeline'
                  ? 'No scene, observation, or dialogue records have exact intervals for this view.'
                  : preferences.mode === 'activity'
                    ? 'No indexed activity observations are available for these scenes.'
                    : preferences.mode === 'recording'
                      ? 'No indexed scenes are available for this recording selection.'
                      : preferences.mode === 'scene'
                        ? 'Select a scene to see the people, objects, and observations recorded in it.'
                        : preferences.mode === 'character'
                          ? 'No indexed person matches this character filter.'
                          : 'No entities match these filters. Reset the view to show the scene evidence.'}
            </div>
          )}
        </div>
        <EvidenceInspector
          selected={selected}
          nodes={graph.nodes}
          edges={graph.edges}
          scenes={scenes}
          origin={origin}
          inContext={
            (!!selected && !!base.nodes.some((n) => n.id === selected.id)) ||
            (!!selected && !!base.edges.some((e) => e.id === selected.id))
          }
          expanded={preferences.expanded}
          busy={busy}
          onOpen={onOpen}
          onClear={() => setPreferences((p) => ({ ...p, selected: null }))}
          onExpand={expand}
          onFocus={onFocus}
        />
      </div>
      {extra.some((r) => r.isError) && (
        <div className="graph-retry">
          <span>Some expanded evidence could not be loaded.</span>
          <button
            className="text-link"
            onClick={() => extra.filter((r) => r.isError).forEach((r) => void r.refetch())}
          >
            Try again
          </button>
        </div>
      )}
      {(graph.truncated || view.limited || !!graph.warnings.length) && (
        <details className="graph-limits">
          <summary>This view is bounded to keep evidence readable</summary>
          <p>
            Focus a scene or expand its evidence to inspect more records. A connection records an
            indexed association; it does not establish causality.
          </p>
          {graph.warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
        </details>
      )}
    </div>
  )
}

export default function EvidenceGraph(props: Props) {
  return (
    <ReactFlowProvider>
      <GraphWorkspace key={props.stateKey} {...props} />
    </ReactFlowProvider>
  )
}
