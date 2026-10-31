import type { EvidenceEdge, EvidenceGraph, EvidenceNode } from '../../types'

export const typeLabels: Record<string, string> = {
  Scene: 'Scenes',
  Character: 'People',
  Location: 'Places',
  Object: 'Objects',
  Action: 'Activities',
  Clothing: 'Outfits',
  Dialogue: 'Dialogue',
  Observation: 'Observations',
  Episode: 'Episodes',
  Video: 'Videos',
}
export const singularLabels: Record<string, string> = {
  Character: 'Person',
  Location: 'Place',
  Action: 'Activity',
  Clothing: 'Outfit',
}
export const entityLabel = (type: string) => singularLabels[type] ?? type
export const overviewHidden = ['Episode', 'Video', 'Observation', 'Dialogue', 'Action', 'Clothing']
const labels: Record<string, string> = {
  APPEARS_IN: 'Appears in',
  HAS_OBSERVATION: 'Has observation',
  HAS_DIALOGUE: 'Has dialogue',
  DESCRIBES: 'Describes',
  SUBJECT: 'Observed person',
  SPOKEN_BY: 'Spoken by',
  CONTAINS: 'Contains',
  OCCURS_AT: 'Takes place at',
  PART_OF: 'Part of',
}
export const relationshipLabel = (type: string) =>
  labels[type] ?? type.replaceAll('_', ' ').toLowerCase()

export function mergeGraphs(graphs: EvidenceGraph[]): EvidenceGraph {
  const nodes = new Map<string, EvidenceNode>()
  const edges = new Map<string, EvidenceEdge>()
  for (const graph of graphs) {
    for (const node of graph.nodes) {
      const prior = nodes.get(node.id)
      nodes.set(
        node.id,
        prior
          ? {
              ...prior,
              scene_ids: [...new Set([...prior.scene_ids, ...node.scene_ids])],
              evidence: [...new Set([...prior.evidence, ...node.evidence])],
            }
          : node
      )
    }
    for (const edge of graph.edges) {
      const prior = edges.get(edge.id)
      edges.set(
        edge.id,
        prior
          ? {
              ...prior,
              scene_ids: [...new Set([...prior.scene_ids, ...edge.scene_ids])],
              evidence: [...new Set([...prior.evidence, ...edge.evidence])],
            }
          : edge
      )
    }
  }
  const retained = [...nodes.values()].slice(0, 300)
  const ids = new Set(retained.map((n) => n.id))
  return {
    nodes: retained,
    edges: [...edges.values()].filter((e) => ids.has(e.source) && ids.has(e.target)).slice(0, 500),
    scene_ids: [...new Set(graphs.flatMap((g) => g.scene_ids))],
    warnings: [...new Set(graphs.flatMap((g) => g.warnings))],
    truncated: nodes.size > 300 || edges.size > 500 || graphs.some((g) => g.truncated),
  }
}

export function visibleGraph(
  graph: EvidenceGraph,
  sceneIds: string[],
  hidden: string[],
  hiddenEdges: string[]
) {
  const scoped = new Set(sceneIds)
  const nodes = graph.nodes.filter(
    (n) => n.scene_ids.some((s) => scoped.has(s)) && !hidden.includes(n.type)
  )
  const ids = new Set(nodes.map((n) => n.id))
  const edges = graph.edges.filter(
    (e) =>
      e.scene_ids.some((s) => scoped.has(s)) &&
      ids.has(e.source) &&
      ids.has(e.target) &&
      !hiddenEdges.includes(e.type)
  )
  const connected = new Set(edges.flatMap((e) => [e.source, e.target]))
  const retained = nodes.filter((n) => n.type === 'Scene' || connected.has(n.id)).slice(0, 60)
  const retainedIds = new Set(retained.map((n) => n.id))
  return {
    nodes: retained,
    edges: edges.filter((e) => retainedIds.has(e.source) && retainedIds.has(e.target)),
    limited:
      retained.length < nodes.filter((n) => n.type === 'Scene' || connected.has(n.id)).length,
  }
}

export function layoutGraph(
  nodes: EvidenceNode[],
  edges: EvidenceEdge[],
  sceneIds: string[],
  positions: GraphPreferences['positions'] = {}
) {
  const columnFor = (kind: string) =>
    kind === 'Character'
      ? 0
      : kind === 'Scene'
        ? 1
        : ['Observation', 'Dialogue'].includes(kind)
          ? 2
          : 3
  const columns = [...new Set(nodes.map((n) => columnFor(n.type)))].sort()
  const sceneRank = new Map(sceneIds.map((id, i) => [id, i]))
  const rank = (n: EvidenceNode) => {
    const linked = [
      ...new Set([
        ...n.scene_ids,
        ...edges.filter((e) => e.source === n.id || e.target === n.id).flatMap((e) => e.scene_ids),
      ]),
    ]
    const ranks = linked.map((s) => sceneRank.get(s) ?? sceneIds.length)
    return ranks.reduce((a, b) => a + b, 0) / Math.max(1, ranks.length)
  }
  const sorted = [...nodes].sort(
    (a, b) => columnFor(a.type) - columnFor(b.type) || rank(a) - rank(b) || a.id.localeCompare(b.id)
  )
  const counts = new Map<number, number>()
  const occupied = nodes.flatMap((node) => (positions[node.id] ? [positions[node.id]] : []))
  return sorted.map((record) => {
    const column = columnFor(record.type)
    const row = counts.get(column) ?? 0
    counts.set(column, row + 1)
    const position = positions[record.id] ?? { x: columns.indexOf(column) * 272, y: row * 144 }
    if (!positions[record.id]) {
      while (
        occupied.some(
          (other) => Math.abs(other.x - position.x) < 240 && Math.abs(other.y - position.y) < 136
        )
      )
        position.y += 144
      occupied.push(position)
    }
    return {
      id: record.id,
      type: 'evidence' as const,
      position,
      data: { record, label: record.label },
      ariaLabel: `${record.type}: ${record.label}`,
    }
  })
}

export interface GraphPreferences {
  count: number
  hidden: string[]
  hiddenEdges: string[]
  expanded: string[]
  selected: string | null
  focusedScene: string | null
  positions: Record<string, { x: number; y: number }>
  viewport?: { x: number; y: number; zoom: number }
  labels: boolean
}
export function readGraphState(key: string): GraphPreferences {
  const defaults: GraphPreferences = {
    count: 3,
    hidden: overviewHidden,
    hiddenEdges: [],
    expanded: [],
    selected: null,
    focusedScene: null,
    positions: {},
    labels: false,
  }
  try {
    const data = JSON.parse(sessionStorage.getItem(`searchy:graph-v2:${key}`) ?? 'null')
    if (
      !data ||
      !Array.isArray(data.hidden) ||
      !Array.isArray(data.hiddenEdges) ||
      !Array.isArray(data.expanded)
    )
      return defaults
    return {
      ...defaults,
      ...data,
      count: Math.min(12, Math.max(1, Number(data.count) || 3)),
      expanded: data.expanded.filter((s: unknown) => typeof s === 'string').slice(0, 3),
    }
  } catch {
    return defaults
  }
}
export function saveGraphState(key: string, state: GraphPreferences) {
  try {
    sessionStorage.setItem(`searchy:graph-v2:${key}`, JSON.stringify(state))
  } catch {
    /* Exploration remains usable without browser storage. */
  }
}
