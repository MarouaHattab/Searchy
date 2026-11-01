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
  Object: 'Object',
  Scene: 'Scene',
  Dialogue: 'Dialogue',
  Observation: 'Observation',
}
export const entityLabel = (type: string) => singularLabels[type] ?? type
export const overviewHidden = ['Episode', 'Video', 'Observation', 'Dialogue']
const labels: Record<string, string> = {
  APPEARS_IN: 'Appears in',
  HAS_OBSERVATION: 'Observed',
  HAS_DIALOGUE: 'Dialogue',
  DESCRIBES: 'Describes',
  SUBJECT: 'About',
  SPOKEN_BY: 'Spoken by',
  CONTAINS: 'Contains',
  OCCURS_AT: 'Takes place at',
  PART_OF: 'Part of',
  WEARS: 'Wears',
  PERFORMS: 'Performs',
  INTERACTS_WITH: 'Interacts with',
  LOCATED_IN: 'At',
  WITH: 'With',
  INCLUDES: 'Includes',
  SPEAKS: 'Speaks',
  OCCURS_BEFORE: 'Then',
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

export type ResearchView = 'overview' | 'detail' | 'character' | 'scene' | 'path'

export function hiddenForView(mode: ResearchView) {
  return mode === 'detail' ? ['Episode', 'Video'] : overviewHidden
}

function neighborhood(seeds: string[], edges: EvidenceEdge[]) {
  const keep = new Set(seeds)
  for (const edge of edges) {
    if (keep.has(edge.source) || keep.has(edge.target)) {
      keep.add(edge.source)
      keep.add(edge.target)
    }
  }
  return keep
}

/** Same indexed graph, restricted to the research view. No entities are created. */
export function researchGraph(
  graph: EvidenceGraph,
  mode: ResearchView,
  options: { characterId: string; focusSceneId: string | null; selectedId: string | null }
): EvidenceGraph {
  if (mode === 'overview' || mode === 'detail') return graph
  const seeds: string[] = []
  if (mode === 'character') {
    const people = graph.nodes.filter((node) => node.type === 'Character')
    const matched = options.characterId
      ? people.filter(
          (node) =>
            node.id === `Character:${options.characterId}` ||
            node.properties.key === options.characterId
        )
      : people.filter((node) => node.id === options.selectedId)
    seeds.push(...(matched.length ? matched : options.characterId ? [] : people).map((node) => node.id))
  } else if (mode === 'scene') {
    const scene = graph.nodes.find(
      (node) =>
        node.type === 'Scene' &&
        (options.focusSceneId
          ? node.scene_ids.includes(options.focusSceneId)
          : node.id === options.selectedId)
    )
    if (scene) seeds.push(scene.id)
  } else if (options.selectedId) seeds.push(options.selectedId)
  if (!seeds.length) return { ...graph, nodes: [], edges: [] }
  const keep = neighborhood(seeds, graph.edges)
  const nodes = graph.nodes.filter((node) => keep.has(node.id))
  const ids = new Set(nodes.map((node) => node.id))
  return {
    ...graph,
    nodes,
    edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
  }
}

export function evidenceClass(item: EvidenceNode | EvidenceEdge) {
  if ('source' in item && item.derived)
    return {
      tone: 'inferred' as const,
      label: 'Inferred summary',
      detail:
        'Summarized from indexed observations. This is not a separately recorded visual fact.',
    }
  if ('source' in item)
    return {
      tone: 'observed' as const,
      label: 'Indexed relationship',
      detail: 'Stored from the scene index. It is not a conclusion generated by the answer model.',
    }
  if (item.verified === true)
    return {
      tone: 'observed' as const,
      label: 'Verified record',
      detail: 'The extraction source marked this record verified.',
    }
  if (item.verified === false)
    return {
      tone: 'extracted' as const,
      label: 'Extracted, unverified',
      detail: 'Produced by a caption or model and not verified as a visual fact.',
    }
  return {
    tone: 'recorded' as const,
    label: 'Indexed record',
    detail: 'Comes from the collection index and has no separate verification flag.',
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
    (n) =>
      n.scene_ids.some((s) => scoped.has(s)) &&
      !hidden.includes(n.type) &&
      (n.type !== 'Action' || n.label.length < 90)
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

const summaryRelation: Record<string, string> = {
  clothing: 'WEARS',
  action: 'PERFORMS',
  interaction: 'INTERACTS_WITH',
  location: 'LOCATED_IN',
  object: 'WITH',
}

/** Readable links summarized from indexed observation and dialogue paths. */
export function summarizeGraph(graph: EvidenceGraph): EvidenceGraph {
  const nodes = graph.nodes
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const edges = [...graph.edges]

  function add(edge: EvidenceEdge) {
    const key = `${edge.source}|${edge.type}|${edge.target}`
    if (edge.source === edge.target || !byId.has(edge.source) || !byId.has(edge.target)) return
    const index = edges.findIndex((item) => `${item.source}|${item.type}|${item.target}` === key)
    if (index >= 0) {
      const current = edges[index]
      if (!current.derived) return
      edges[index] = {
        ...current,
        scene_ids: [...new Set([...current.scene_ids, ...edge.scene_ids])],
        evidence: [...new Set([...current.evidence, ...edge.evidence])].slice(0, 4),
      }
      return
    }
    edges.push(edge)
  }

  for (const observation of nodes) {
    if (observation.type !== 'Observation') continue
    const kind = String(observation.properties.kind ?? '')
    const relation = summaryRelation[kind]
    if (!relation) continue
    const outgoing = graph.edges.filter((edge) => edge.source === observation.id)
    const subjects = outgoing.filter((edge) => edge.type === 'SUBJECT').map((edge) => edge.target)
    const described = outgoing
      .filter((edge) => edge.type === 'DESCRIBES')
      .map((edge) => edge.target)
    for (const subject of subjects) {
      for (const target of described) {
        const targetNode = byId.get(target)
        add({
          id: `summary:${observation.id}:${subject}:${target}`,
          source: subject,
          target,
          type: targetNode?.type === 'Character' ? 'INTERACTS_WITH' : relation,
          scene_ids: observation.scene_ids,
          evidence: observation.evidence,
          derived: true,
        })
      }
    }
    for (const target of described) {
      for (const sceneId of observation.scene_ids) {
        const scene = nodes.find(
          (node) => node.type === 'Scene' && node.properties.scene_id === sceneId
        )
        if (!scene || subjects.length) continue
        const existing = graph.edges.some(
          (edge) =>
            (edge.source === scene.id && edge.target === target) ||
            (edge.target === scene.id && edge.source === target)
        )
        if (existing) continue
        add({
          id: `summary:${observation.id}:${scene.id}:${target}`,
          source: scene.id,
          target,
          type: 'INCLUDES',
          scene_ids: observation.scene_ids,
          evidence: observation.evidence,
          derived: true,
        })
      }
    }
  }

  for (const dialogue of nodes) {
    if (dialogue.type !== 'Dialogue') continue
    const speakers = graph.edges
      .filter((edge) => edge.source === dialogue.id && edge.type === 'SPOKEN_BY')
      .map((edge) => edge.target)
    for (const speaker of speakers) {
      for (const sceneId of dialogue.scene_ids) {
        const scene = nodes.find(
          (node) => node.type === 'Scene' && node.properties.scene_id === sceneId
        )
        if (!scene) continue
        add({
          id: `summary:speaks:${dialogue.id}:${speaker}`,
          source: speaker,
          target: scene.id,
          type: 'SPEAKS',
          scene_ids: dialogue.scene_ids,
          evidence: dialogue.evidence.length ? dialogue.evidence : [dialogue.label],
          derived: true,
        })
      }
    }
  }

  const scenes = nodes.filter(
    (node) => node.type === 'Scene' && typeof node.properties.video_id === 'string'
  )
  const byVideo = new Map<string, EvidenceNode[]>()
  for (const scene of scenes) {
    const videoId = String(scene.properties.video_id)
    byVideo.set(videoId, [...(byVideo.get(videoId) ?? []), scene])
  }
  for (const group of byVideo.values()) {
    const ordered = group
      .filter((scene) => scene.start != null)
      .sort((a, b) => (a.start ?? 0) - (b.start ?? 0) || a.id.localeCompare(b.id))
    for (let index = 0; index < ordered.length - 1; index += 1) {
      const earlier = ordered[index]
      const later = ordered[index + 1]
      add({
        id: `summary:before:${earlier.id}:${later.id}`,
        source: earlier.id,
        target: later.id,
        type: 'OCCURS_BEFORE',
        scene_ids: [...new Set([...earlier.scene_ids, ...later.scene_ids])],
        evidence: [],
        derived: true,
      })
    }
  }

  return { ...graph, edges }
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
        ? 2
        : ['Action', 'Object', 'Clothing', 'Location'].includes(kind)
          ? 1
          : kind === 'Dialogue' || kind === 'Observation'
            ? 3
            : 4
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
  const rowsPerColumn = 3
  const grouped = new Map<number, EvidenceNode[]>()
  for (const record of sorted) {
    const column = columnFor(record.type)
    grouped.set(column, [...(grouped.get(column) ?? []), record])
  }
  const bandWidth = 188
  let cursor = 0
  const origin = new Map<number, number>()
  for (const column of columns) {
    origin.set(column, cursor)
    const bands = Math.max(1, Math.ceil((grouped.get(column)?.length ?? 0) / rowsPerColumn))
    cursor += bands * bandWidth + 20
  }
  const occupied = nodes.flatMap((node) => (positions[node.id] ? [positions[node.id]] : []))
  const placed = new Map<string, number>()
  return sorted.map((record) => {
    const column = columnFor(record.type)
    const index = placed.get(String(column)) ?? 0
    placed.set(String(column), index + 1)
    const position = positions[record.id] ?? {
      x: (origin.get(column) ?? 0) + Math.floor(index / rowsPerColumn) * bandWidth,
      y: (index % rowsPerColumn) * 120,
    }
    if (!positions[record.id]) {
      while (
        occupied.some(
          (other) => Math.abs(other.x - position.x) < 160 && Math.abs(other.y - position.y) < 110
        )
      )
        position.y += 120
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
  mode: ResearchView
  entityQuery: string
}
const researchViews: ResearchView[] = ['overview', 'detail', 'character', 'scene', 'path']
export function readGraphState(key: string): GraphPreferences {
  const defaults: GraphPreferences = {
    count: 3,
    hidden: overviewHidden,
    hiddenEdges: [],
    expanded: [],
    selected: null,
    focusedScene: null,
    positions: {},
    labels: true,
    mode: 'overview',
    entityQuery: '',
  }
  try {
    const data = JSON.parse(sessionStorage.getItem(`searchy:graph-v4:${key}`) ?? 'null')
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
      mode: researchViews.includes(data.mode) ? data.mode : 'overview',
      entityQuery: typeof data.entityQuery === 'string' ? data.entityQuery.slice(0, 80) : '',
    }
  } catch {
    return defaults
  }
}
export function saveGraphState(key: string, state: GraphPreferences) {
  try {
    sessionStorage.setItem(`searchy:graph-v4:${key}`, JSON.stringify(state))
  } catch {
    /* Exploration remains usable without browser storage. */
  }
}
