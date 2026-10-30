import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Background,
  Controls,
  Handle,
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
  ScanSearch,
  Shirt,
  Users,
  X,
} from 'lucide-react'
import { Link } from 'react-router'
import { Button, EmptyState, ErrorState, Loading } from '../../components/ui'
import { api } from '../../services/api'
import { episodeTitle, timestamp } from '../../lib/format'
import type {
  EvidenceEdge,
  EvidenceGraph as GraphData,
  EvidenceNode,
  SceneMatch,
} from '../../types'
import '@xyflow/react/dist/style.css'

const typeLabels: Record<string, string> = {
  Scene: 'Scenes',
  Video: 'Videos',
  Episode: 'Episodes',
  Character: 'Characters',
  Observation: 'Observations',
  Clothing: 'Clothing',
  Action: 'Actions',
  Object: 'Objects',
  Location: 'Locations',
  Dialogue: 'Dialogue',
}
const icons = {
  Scene: Film,
  Video: Film,
  Episode: Film,
  Character: Users,
  Observation: ScanSearch,
  Clothing: Shirt,
  Action: GitBranch,
  Object: ScanSearch,
  Location: MapPin,
  Dialogue: MessageSquare,
}
type GraphNode = Node<{ record: EvidenceNode; label: string }, 'evidence'>

function EvidenceCard({ data }: NodeProps<GraphNode>) {
  const Icon = icons[data.record.type as keyof typeof icons] ?? ScanSearch
  return (
    <div className={`evidence-node evidence-node-${data.record.type.toLowerCase()}`}>
      <Handle type="target" position={Position.Left} />
      <span className="evidence-node-kind">
        <Icon size={13} />
        {data.record.type}
      </span>
      <strong>{data.label}</strong>
      {data.record.type === 'Scene' && (
        <span className="muted small">
          {timestamp(data.record.start)} – {timestamp(data.record.end)}
        </span>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}
const nodeTypes = { evidence: EvidenceCard }

function layout(nodes: EvidenceNode[]): GraphNode[] {
  const columns = {
    Character: 0,
    Scene: 1,
    Video: 3,
    Episode: 3,
    Observation: 2,
    Dialogue: 2,
    Clothing: 3,
    Action: 3,
    Object: 3,
    Location: 3,
  }
  const occupied = [
    ...new Set(nodes.map((node) => columns[node.type as keyof typeof columns] ?? 3)),
  ].sort()
  const counts = [0, 0, 0, 0]
  return nodes.map((record) => {
    const column = columns[record.type as keyof typeof columns] ?? 3
    const row = counts[column]++
    return {
      id: record.id,
      type: 'evidence',
      position: { x: occupied.indexOf(column) * 300, y: row * 116 },
      data: { record, label: record.label },
      ariaLabel: `${record.type}: ${record.label}`,
    }
  })
}

function GraphCanvas({
  graph,
  scenes,
  onSelection,
}: {
  graph: GraphData
  scenes: SceneMatch[]
  onSelection: (ids: string[]) => void
}) {
  const flow = useReactFlow()
  const [hidden, setHidden] = useState<string[]>([
    'Observation',
    'Dialogue',
    'Object',
    'Clothing',
    'Action',
  ])
  const [hiddenEdges, setHiddenEdges] = useState<string[]>([])
  const [selected, setSelected] = useState<EvidenceNode | EvidenceEdge | null>(null)
  const types = useMemo(() => [...new Set(graph.nodes.map((node) => node.type))].sort(), [graph])
  const relationshipTypes = useMemo(
    () => [...new Set(graph.edges.map((edge) => edge.type))].sort(),
    [graph]
  )
  const visible = useMemo(
    () => graph.nodes.filter((node) => !hidden.includes(node.type)),
    [graph, hidden]
  )
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNode>(layout(visible))
  useEffect(() => {
    setNodes(layout(visible))
  }, [visible, setNodes])
  const edges = useMemo(() => {
    const ids = new Set(visible.map((node) => node.id))
    return graph.edges
      .filter(
        (edge) => ids.has(edge.source) && ids.has(edge.target) && !hiddenEdges.includes(edge.type)
      )
      .map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.type.replaceAll('_', ' ').toLowerCase(),
        style: { stroke: 'var(--muted)', strokeWidth: 1 },
        labelStyle: { fill: 'var(--muted)', fontSize: 10 },
        labelBgStyle: { fill: 'var(--surface)' },
        selected: selected?.id === edge.id,
        ariaLabel: edge.type.replaceAll('_', ' ').toLowerCase(),
      }))
  }, [graph, visible, hiddenEdges, selected])

  function toggle(value: string, values: string[], set: (items: string[]) => void) {
    set(values.includes(value) ? values.filter((item) => item !== value) : [...values, value])
    setSelected(null)
    onSelection([])
  }
  function select(item: EvidenceNode | EvidenceEdge) {
    setSelected(item)
    onSelection(item.scene_ids)
  }
  return (
    <div className="evidence-explorer panel">
      <div className="evidence-toolbar">
        <span>
          <GitBranch size={16} />
          {nodes.length} of {graph.nodes.length} nodes · {edges.length} connections
        </span>
        <Button variant="ghost" onClick={() => void flow.fitView({ padding: 0.15 })}>
          <Maximize2 size={15} />
          Fit view
        </Button>
      </div>
      <details className="evidence-filters">
        <summary>Filter the graph</summary>
        <p className="muted small">
          Start with scenes and characters. Add detailed evidence below.
        </p>
        <fieldset>
          <legend>Entities</legend>
          {types.map((type) => (
            <label key={type}>
              <input
                type="checkbox"
                checked={!hidden.includes(type)}
                onChange={() => toggle(type, hidden, setHidden)}
              />
              {typeLabels[type] ?? type}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>Relationships</legend>
          {relationshipTypes.map((type) => (
            <label key={type}>
              <input
                type="checkbox"
                checked={!hiddenEdges.includes(type)}
                onChange={() => toggle(type, hiddenEdges, setHiddenEdges)}
              />
              {type.replaceAll('_', ' ').toLowerCase()}
            </label>
          ))}
        </fieldset>
      </details>
      <div className="evidence-canvas-layout">
        <div
          className="evidence-canvas"
          role="region"
          aria-label="Interactive scene evidence graph"
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onNodeClick={(_, node) => select(node.data.record)}
            onEdgeClick={(_, edge) => {
              const item = graph.edges.find((candidate) => candidate.id === edge.id)
              if (item) select(item)
            }}
            onPaneClick={() => {
              setSelected(null)
              onSelection([])
            }}
            fitView
            minZoom={0.1}
            maxZoom={1.7}
            nodesConnectable={false}
            edgesReconnectable={false}
            deleteKeyCode={null}
            proOptions={{ hideAttribution: false }}
          >
            <Background color="var(--line)" gap={22} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <aside className="evidence-inspector" aria-label="Selected evidence">
          {selected ? (
            <>
              <div className="evidence-detail-heading">
                <span className="eyebrow">{selected.type.replaceAll('_', ' ')}</span>
                <button
                  className="icon-button"
                  aria-label="Clear graph selection"
                  onClick={() => {
                    setSelected(null)
                    onSelection([])
                  }}
                >
                  <X size={15} />
                </button>
              </div>
              <h3>
                {'label' in selected
                  ? selected.label
                  : selected.type.replaceAll('_', ' ').toLowerCase()}
              </h3>
              {'verified' in selected && selected.verified != null && (
                <p className="small muted">
                  {selected.verified ? 'Verified evidence' : 'Extracted evidence · unverified'}
                </p>
              )}
              {selected.evidence.map((text, index) => (
                <blockquote key={index}>{text}</blockquote>
              ))}
              {'properties' in selected && (
                <dl className="evidence-properties">
                  {Object.entries(selected.properties)
                    .filter(
                      ([key, value]) =>
                        value != null &&
                        !key.endsWith('_id') &&
                        !['description', 'evidence', 'key', 'provenance_json', 'source'].includes(
                          key
                        )
                    )
                    .slice(0, 8)
                    .map(([key, value]) => (
                      <div key={key}>
                        <dt>{key.replaceAll('_', ' ')}</dt>
                        <dd>{String(value)}</dd>
                      </div>
                    ))}
                </dl>
              )}
              <h4>Supporting scenes</h4>
              {selected.scene_ids.map((id) => {
                const scene = scenes.find((item) => item.scene_id === id)
                return (
                  <Link className="evidence-scene-link" key={id} to={`/scenes/${id}`}>
                    <Film size={14} />
                    <span>
                      {episodeTitle(scene?.episode_id ?? null)}
                      <small>
                        {timestamp(scene?.start ?? null)} ·{' '}
                        {scene?.playback.available ? 'Video available' : 'Scene details'}
                      </small>
                    </span>
                  </Link>
                )
              })}
            </>
          ) : (
            <div className="evidence-inspector-empty">
              <ScanSearch size={27} strokeWidth={1.3} />
              <h3>Follow the evidence.</h3>
              <p>
                Select a scene, person, or connection to inspect the indexed information behind it.
              </p>
              <p className="small">
                Use Tab to navigate, Enter to select, and the controls to zoom or fit the graph.
              </p>
            </div>
          )}
        </aside>
      </div>
      {(graph.truncated || graph.warnings.length > 0) && (
        <div className="evidence-graph-notes">
          {graph.truncated && (
            <p>
              This view is limited to keep the graph readable. Focus on fewer scenes to see more of
              their evidence.
            </p>
          )}
          {graph.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      )}
    </div>
  )
}

export default function EvidenceGraph({
  scenes,
  collection,
  focusSceneId,
  onSelection,
}: {
  scenes: SceneMatch[]
  collection: string
  focusSceneId: string | null
  onSelection: (ids: string[]) => void
}) {
  const [count, setCount] = useState(4)
  const [focused, setFocused] = useState(false)
  useEffect(() => {
    setCount(4)
    setFocused(false)
  }, [scenes])
  const sceneIds =
    focused && focusSceneId ? [focusSceneId] : scenes.slice(0, count).map((scene) => scene.scene_id)
  const graph = useQuery({
    queryKey: ['evidence-graph', sceneIds, collection],
    queryFn: ({ signal }) =>
      api.graph({ scene_ids: sceneIds, collection_id: collection || undefined }, signal),
    enabled: sceneIds.length > 0,
    retry: false,
    staleTime: 60_000,
  })
  if (!sceneIds.length)
    return (
      <EmptyState title="No scene evidence to explore">
        Search for a moment to build its graph.
      </EmptyState>
    )
  return (
    <div className="graph-workspace">
      <div className="graph-context">
        <p className="muted small">
          Indexed relationships for {sceneIds.length} of {scenes.length} matches. Extracted
          observations may be uncertain.
        </p>
        <div>
          {focusSceneId && (
            <Button variant="secondary" onClick={() => setFocused(!focused)}>
              {focused ? 'Show result graph' : 'Focus selected scene'}
            </Button>
          )}
          {!focused && count < Math.min(12, scenes.length) && (
            <Button variant="secondary" onClick={() => setCount(Math.min(12, count + 4))}>
              Explore more matches
            </Button>
          )}
        </div>
      </div>
      {graph.isPending ? (
        <Loading label="Loading indexed relationships…" />
      ) : graph.isError ? (
        <ErrorState error={graph.error} retry={() => void graph.refetch()} />
      ) : !graph.data.nodes.length ? (
        <EmptyState title="No indexed relationships found">
          The scene details and search evidence remain available.
        </EmptyState>
      ) : (
        <ReactFlowProvider>
          <GraphCanvas graph={graph.data} scenes={scenes} onSelection={onSelection} />
        </ReactFlowProvider>
      )}
    </div>
  )
}
