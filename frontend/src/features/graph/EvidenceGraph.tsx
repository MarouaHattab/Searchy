import { memo, useCallback, useEffect, useMemo, useState } from 'react'
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
  Shirt,
  SlidersHorizontal,
  Users,
  X,
} from 'lucide-react'
import { useNavigate } from 'react-router'
import { Button, EmptyState, ErrorState, Loading } from '../../components/ui'
import { api } from '../../services/api'
import { excerpt, timestamp } from '../../lib/format'
import { sceneHref } from '../player/navigation'
import { EvidenceInspector } from './EvidenceInspector'
import {
  entityLabel,
  layoutGraph,
  mergeGraphs,
  overviewHidden,
  readGraphState,
  relationshipLabel,
  saveGraphState,
  typeLabels,
  visibleGraph,
  type GraphPreferences,
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
  Action: GitBranch,
  Object: ScanSearch,
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
      <strong title={excerpt(title, 300)}>{excerpt(title, 110)}</strong>
      {record.type === 'Scene' && (
        <div className="graph-card-foot">
          <span>
            {timestamp(record.start)} – {timestamp(record.end)}
          </span>
          <button
            className="graph-node-play nodrag nopan"
            aria-label={`Play scene at ${timestamp(record.start)}`}
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
      mergeGraphs([
        ...(base ? [base] : []),
        ...extra.flatMap((result) => (result.data ? [result.data] : [])),
      ]),
    [base, extraSignature]
  )
  const view = useMemo(
    () => visibleGraph(graph, scope, preferences.hidden, preferences.hiddenEdges),
    [graph, scope, preferences.hidden, preferences.hiddenEdges]
  )
  const selected = [...graph.nodes, ...graph.edges].find((item) => item.id === preferences.selected)
  useEffect(() => {
    setPreferences((previous) =>
      previous.focusedScene === focusSceneId
        ? previous
        : {
            ...previous,
            focusedScene: focusSceneId,
            selected: focusSceneId ? `Scene:${focusSceneId}` : previous.selected,
          }
    )
  }, [focusSceneId])
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNode>([])
  const openScene = useCallback(
    (record: EvidenceNode) => {
      onOpen()
      navigate(sceneHref(record.scene_ids[0], record.start, origin))
    },
    [onOpen, navigate, origin]
  )
  useEffect(() => {
    const saved = readGraphState(stateKey)
    setNodes(
      layoutGraph(view.nodes, view.edges, orderedIds, saved.positions).map((node) => ({
        ...node,
        data: { ...node.data, open: openScene },
      }))
    )
  }, [view, orderedIds, setNodes, stateKey, openScene])
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
  const displayNodes = nodes.map((node) => ({
    ...node,
    selected: node.id === selected?.id,
    style: { opacity: selected && !connected.has(node.id) ? 0.4 : 1 },
  }))
  const edges = view.edges.map((edge) => ({
    ...edge,
    type: 'default',
    label:
      preferences.labels || edge.id === selected?.id ? relationshipLabel(edge.type) : undefined,
    ariaLabel: `${relationshipLabel(edge.type)}: ${graph.nodes.find((n) => n.id === edge.source)?.label ?? ''} to ${graph.nodes.find((n) => n.id === edge.target)?.label ?? ''}`,
    selected: edge.id === selected?.id,
    markerEnd: { type: MarkerType.ArrowClosed, width: 13, height: 13 },
    style: {
      stroke: edge.id === selected?.id ? 'var(--accent)' : 'var(--graph-line)',
      strokeWidth: edge.id === selected?.id ? 2 : 1.2,
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
  const reset = () => {
    const initial = {
      ...readGraphState('new'),
      hidden: [...overviewHidden],
      count: 3,
      selected: null,
      expanded: [],
      positions: {},
      viewport: undefined,
    }
    setPreferences(initial)
    saveGraphState(stateKey, initial)
    onFocus(null)
    setNodes(
      layoutGraph(view.nodes, view.edges, orderedIds).map((n) => ({
        ...n,
        data: { ...n.data, open: openScene },
      }))
    )
    window.requestAnimationFrame(
      () => void flow.fitView({ padding: 0.12, minZoom: 0.85, maxZoom: 1 })
    )
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
            <h3>Scene evidence</h3>
            <p>
              {suppliedGraph || context.data?.used_for_answer
                ? 'Selected graph context for this answer'
                : 'Related indexed evidence'}{' '}
              · {scope.length} scenes
            </p>
          </div>
        </div>
        <Button variant="ghost" onClick={reset}>
          <RotateCcw size={14} />
          Reset view
        </Button>
      </header>
      <div className="graph-controls">
        <div className="graph-scope">
          <span>
            {view.nodes.length} nodes · {view.edges.length} connections
          </span>
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
          <button
            className={`graph-tool ${preferences.labels ? 'active' : ''}`}
            aria-pressed={preferences.labels}
            onClick={() => setPreferences((p) => ({ ...p, labels: !p.labels }))}
          >
            Labels
          </button>
        </div>
      </div>
      {filtersOpen && (
        <div className="graph-filter-panel">
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
              node.data.record.type === 'Scene' && openScene(node.data.record)
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
            fitViewOptions={{ padding: 0.12, minZoom: 0.85, maxZoom: 1 }}
            minZoom={0.2}
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
              No entities match these filters. Reset the view to show the scene evidence.
            </div>
          )}
        </div>
        <EvidenceInspector
          selected={selected}
          nodes={graph.nodes}
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
