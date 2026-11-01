import type { EvidenceEdge, EvidenceGraph, EvidenceNode, GraphSupport } from '../../types'

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
  ASSOCIATED_WITH: 'Associated in same observation',
  LOCATED_IN: 'At',
  WITH: 'With',
  INCLUDES: 'Includes',
  DESCRIBED_IN: 'Described in',
  SPEAKS: 'Speaks',
  PRECEDES: 'Before',
}
export const relationshipLabel = (type: string) =>
  labels[type] ?? type.replaceAll('_', ' ').toLowerCase()

function mergeSupports(...groups: GraphSupport[][]): GraphSupport[] {
  const items = new Map<string, GraphSupport>()
  for (const support of groups.flat()) {
    const key = [support.evidence_id, support.scene_id, support.start, support.end].join('|')
    items.set(key, support)
  }
  return [...items.values()]
}

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
              supports: mergeSupports(prior.supports ?? [], edge.supports ?? []),
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

export type ResearchView =
  | 'overview'
  | 'detail'
  | 'evidence'
  | 'timeline'
  | 'recording'
  | 'activity'
  | 'character'
  | 'scene'
  | 'path'
  | 'relationship'

export type VerificationFilter = 'all' | 'verified' | 'unverified' | 'unreviewed' | 'inferred'

export interface EvidenceFilters {
  source: string
  recordingId: string
  from: number | null
  to: number | null
  verification: VerificationFilter
}

export function hiddenForView(mode: ResearchView) {
  if (mode === 'detail' || mode === 'evidence') return ['Episode', 'Video']
  if (mode === 'timeline')
    return ['Character', 'Location', 'Object', 'Action', 'Clothing', 'Episode', 'Video']
  if (mode === 'activity') return ['Dialogue', 'Episode', 'Video']
  if (mode === 'recording') return []
  return overviewHidden
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
  options: {
    characterId: string
    focusSceneId: string | null
    selectedId: string | null
    recordingId?: string
  }
): EvidenceGraph {
  if (mode === 'overview' || mode === 'detail') return graph
  if (mode === 'timeline') {
    const nodes = graph.nodes.filter(
      (node) =>
        ['Scene', 'Observation', 'Dialogue'].includes(node.type) &&
        node.start != null &&
        node.end != null
    )
    const ids = new Set(nodes.map((node) => node.id))
    return {
      ...graph,
      nodes,
      edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
    }
  }
  if (mode === 'recording') {
    const selected = graph.nodes.find((node) => node.id === options.selectedId)
    const recordingId =
      options.recordingId ||
      (selected?.type === 'Video' ? String(selected.properties.video_id ?? '') : '')
    const sceneIds = new Set(
      graph.nodes
        .filter(
          (node) =>
            node.type === 'Scene' && (!recordingId || node.properties.video_id === recordingId)
        )
        .map((node) => node.scene_ids[0])
    )
    const nodes = graph.nodes.filter((node) =>
      node.type === 'Video'
        ? !recordingId ||
          node.properties.video_id === recordingId ||
          node.id === `Video:${recordingId}`
        : node.scene_ids.some((sceneId) => sceneIds.has(sceneId))
    )
    const ids = new Set(nodes.map((node) => node.id))
    return {
      ...graph,
      nodes,
      edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
    }
  }
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
    seeds.push(
      ...(matched.length ? matched : options.characterId ? [] : people).map((node) => node.id)
    )
  } else if (mode === 'scene') {
    const scene = graph.nodes.find(
      (node) =>
        node.type === 'Scene' &&
        (options.focusSceneId
          ? node.scene_ids.includes(options.focusSceneId)
          : node.id === options.selectedId)
    )
    if (scene) seeds.push(scene.id)
  } else if (mode === 'activity') {
    seeds.push(...graph.nodes.filter((node) => node.type === 'Action').map((node) => node.id))
  } else if (mode === 'evidence') {
    seeds.push(
      ...graph.nodes
        .filter((node) => node.type === 'Observation' || node.type === 'Dialogue')
        .map((node) => node.id)
    )
  } else if (mode === 'path' || mode === 'relationship') {
    const selectedEdge = graph.edges.find((edge) => edge.id === options.selectedId)
    if (selectedEdge) {
      seeds.push(selectedEdge.source, selectedEdge.target)
      for (const support of selectedEdge.supports ?? []) seeds.push(support.evidence_id)
    } else if (options.selectedId) {
      seeds.push(options.selectedId)
    }
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

export function filterEvidenceGraph(graph: EvidenceGraph, filters: EvidenceFilters): EvidenceGraph {
  const supportFilterActive =
    !!filters.source || !!filters.recordingId || filters.from != null || filters.to != null
  const anyFilterActive = supportFilterActive || filters.verification !== 'all'
  if (!anyFilterActive) return graph
  if (filters.from != null && filters.to != null && filters.from > filters.to)
    return { ...graph, nodes: [], edges: [] }

  const matches = (support: GraphSupport) => {
    if (filters.recordingId && support.recording_id !== filters.recordingId) return false
    if (filters.source) {
      const sourceMatches = filters.source.startsWith('file:')
        ? support.source_reference === filters.source.slice(5)
        : filters.source.startsWith('method:')
          ? support.method === filters.source.slice(7)
          : support.source_reference === filters.source || support.method === filters.source
      if (!sourceMatches) return false
    }
    if (filters.from != null || filters.to != null) {
      if (support.start == null || support.end == null) return false
      if (filters.from != null && support.end < filters.from) return false
      if (filters.to != null && support.start > filters.to) return false
    }
    if (filters.verification === 'verified' && support.verified !== true) return false
    if (filters.verification === 'unverified' && support.verified !== false) return false
    if (filters.verification === 'unreviewed' && support.verified != null) return false
    return true
  }
  const edges = graph.edges.filter((edge) => {
    if (filters.verification === 'inferred' && !edge.derived) return false
    if (
      !supportFilterActive &&
      (filters.verification === 'all' || filters.verification === 'inferred')
    )
      return true
    return (edge.supports ?? []).some(matches)
  })
  const ids = new Set(edges.flatMap((edge) => [edge.source, edge.target]))
  const recordingScenes = new Set(
    graph.nodes
      .filter(
        (node) =>
          node.type === 'Scene' &&
          (!filters.recordingId || node.properties.video_id === filters.recordingId)
      )
      .map((node) => node.scene_ids[0])
  )
  const nodes = graph.nodes.filter(
    (node) =>
      ids.has(node.id) ||
      (!!filters.recordingId &&
        ((node.type === 'Video' &&
          (node.properties.video_id === filters.recordingId ||
            node.id === `Video:${filters.recordingId}`)) ||
          (node.type === 'Scene' && recordingScenes.has(node.scene_ids[0]))))
  )
  const retained = new Set(nodes.map((node) => node.id))
  return {
    ...graph,
    nodes,
    edges: edges.filter((edge) => retained.has(edge.source) && retained.has(edge.target)),
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
  hiddenEdges: string[],
  collapsedScenes: string[] = []
) {
  const scoped = new Set(sceneIds)
  const collapsed = new Set(collapsedScenes)
  const nodes = graph.nodes.filter(
    (n) =>
      n.scene_ids.some((s) => scoped.has(s)) &&
      (n.type === 'Scene' || n.scene_ids.some((s) => !collapsed.has(s))) &&
      !hidden.includes(n.type) &&
      (n.type !== 'Action' || n.label.length < 90)
  )
  const ids = new Set(nodes.map((n) => n.id))
  const edges = graph.edges.filter(
    (e) =>
      e.scene_ids.some((s) => scoped.has(s)) &&
      (e.type === 'PART_OF' || e.scene_ids.some((s) => !collapsed.has(s))) &&
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
  location: 'LOCATED_IN',
  object: 'ASSOCIATED_WITH',
}

const summaryExplanations: Record<string, string> = {
  WEARS: 'Summarized from a clothing observation that names this subject and outfit.',
  PERFORMS: 'Summarized from an activity observation that names this subject and action.',
  INTERACTS_WITH: 'Summarized from an observation explicitly categorized as an interaction.',
  LOCATED_IN: 'Summarized from a location observation that names this subject and place.',
  ASSOCIATED_WITH:
    'Both entities are linked by the same observation; this does not establish ownership.',
  DESCRIBED_IN: 'The entity is described by an observation indexed in this scene.',
  SPEAKS: 'Summarized from a transcript segment linked to this speaker.',
  PRECEDES: 'The indexed time intervals do not overlap and this scene ends before the next begins.',
}

function supportsFor(edges: EvidenceEdge[], predicate: (edge: EvidenceEdge) => boolean) {
  return mergeSupports(...edges.filter(predicate).map((edge) => edge.supports ?? []))
}

function timeRange(node: EvidenceNode) {
  return node.start != null && node.end != null ? ([node.start, node.end] as const) : null
}

/** Readable summaries retain their source records and remain visibly derived. */
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
        supports: mergeSupports(current.supports ?? [], edge.supports ?? []),
      }
      return
    }
    edges.push(edge)
  }

  for (const observation of nodes) {
    if (observation.type !== 'Observation') continue
    const kind = String(observation.properties.kind ?? '')
    const outgoing = graph.edges.filter((edge) => edge.source === observation.id)
    const subjects = outgoing.filter((edge) => edge.type === 'SUBJECT').map((edge) => edge.target)
    const described = outgoing
      .filter((edge) => edge.type === 'DESCRIBES')
      .map((edge) => edge.target)
    for (const subject of subjects) {
      for (const target of described) {
        const subjectNode = byId.get(subject)
        const targetNode = byId.get(target)
        if (subjectNode?.type !== 'Character' || !targetNode) continue
        const relation =
          kind === 'interaction' && targetNode.type === 'Character'
            ? 'INTERACTS_WITH'
            : summaryRelation[kind]
        if (!relation) continue
        const expectedTarget: Record<string, string> = {
          clothing: 'Clothing',
          action: 'Action',
          location: 'Location',
          object: 'Object',
        }
        if (expectedTarget[kind] && targetNode.type !== expectedTarget[kind]) continue
        const supports = supportsFor(
          graph.edges,
          (edge) => edge.source === observation.id && ['SUBJECT', 'DESCRIBES'].includes(edge.type)
        )
        if (!supports.length) continue
        add({
          id: `summary:${observation.id}:${subject}:${target}`,
          source: subject,
          target,
          type: relation,
          scene_ids: observation.scene_ids,
          evidence: observation.evidence,
          explanation: summaryExplanations[relation],
          supports,
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
        const supports = supportsFor(
          graph.edges,
          (edge) => edge.source === observation.id && edge.type === 'DESCRIBES'
        )
        if (!supports.length) continue
        add({
          id: `summary:${observation.id}:${scene.id}:${target}`,
          source: scene.id,
          target,
          type: 'DESCRIBED_IN',
          scene_ids: observation.scene_ids,
          evidence: observation.evidence,
          explanation: summaryExplanations.DESCRIBED_IN,
          supports,
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
        const supports = supportsFor(
          graph.edges,
          (edge) => edge.source === dialogue.id && edge.type === 'SPOKEN_BY'
        )
        if (!supports.length) continue
        add({
          id: `summary:speaks:${dialogue.id}:${speaker}`,
          source: speaker,
          target: scene.id,
          type: 'SPEAKS',
          scene_ids: dialogue.scene_ids,
          evidence: dialogue.evidence.length ? dialogue.evidence : [dialogue.label],
          explanation: summaryExplanations.SPEAKS,
          supports,
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
      .filter((scene) => timeRange(scene))
      .sort((a, b) => (a.start ?? 0) - (b.start ?? 0) || a.id.localeCompare(b.id))
    for (let index = 0; index < ordered.length; index += 1) {
      const earlier = ordered[index]
      const earlierRange = timeRange(earlier)
      if (!earlierRange) continue
      const later = ordered
        .slice(index + 1)
        .find((candidate) => (candidate.start ?? 0) >= earlierRange[1])
      if (!later) continue
      const supports = supportsFor(
        graph.edges,
        (edge) =>
          edge.type === 'PART_OF' && (edge.source === earlier.id || edge.source === later.id)
      )
      const earlierSupport = supports.find((support) => support.scene_id === earlier.scene_ids[0])
      const laterSupport = supports.find((support) => support.scene_id === later.scene_ids[0])
      if (!earlierSupport?.start && earlierSupport?.start !== 0) continue
      if (!laterSupport?.start && laterSupport?.start !== 0) continue
      add({
        id: `summary:precedes:${earlier.id}:${later.id}`,
        source: earlier.id,
        target: later.id,
        type: 'PRECEDES',
        scene_ids: [...new Set([...earlier.scene_ids, ...later.scene_ids])],
        evidence: [],
        explanation: summaryExplanations.PRECEDES,
        supports: [earlierSupport, laterSupport],
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
  positions: GraphPreferences['positions'] = {},
  mode: ResearchView = 'overview'
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
  const sorted = [...nodes].sort((a, b) =>
    mode === 'timeline'
      ? (a.start ?? Number.MAX_SAFE_INTEGER) - (b.start ?? Number.MAX_SAFE_INTEGER) ||
        a.id.localeCompare(b.id)
      : columnFor(a.type) - columnFor(b.type) || rank(a) - rank(b) || a.id.localeCompare(b.id)
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
    const timelineLane: Record<string, number> = { Scene: 0, Observation: 1, Dialogue: 2 }
    const chronologicalIndex = sorted.findIndex((node) => node.id === record.id)
    const position =
      mode === 'timeline'
        ? { x: chronologicalIndex * 198, y: (timelineLane[record.type] ?? 1) * 144 }
        : (positions[record.id] ?? {
            x: (origin.get(column) ?? 0) + Math.floor(index / rowsPerColumn) * bandWidth,
            y: (index % rowsPerColumn) * 120,
          })
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
  collapsedScenes: string[]
  selected: string | null
  focusedScene: string | null
  positions: Record<string, { x: number; y: number }>
  viewport?: { x: number; y: number; zoom: number }
  labels: boolean
  mode: ResearchView
  entityQuery: string
  sourceFilter: string
  recordingFilter: string
  timeFrom: number | null
  timeTo: number | null
  verificationFilter: VerificationFilter
}
const researchViews: ResearchView[] = [
  'overview',
  'detail',
  'evidence',
  'timeline',
  'recording',
  'activity',
  'character',
  'scene',
  'path',
  'relationship',
]
const verificationFilters: VerificationFilter[] = [
  'all',
  'verified',
  'unverified',
  'unreviewed',
  'inferred',
]
export function readGraphState(key: string): GraphPreferences {
  const defaults: GraphPreferences = {
    count: 3,
    hidden: overviewHidden,
    hiddenEdges: [],
    expanded: [],
    collapsedScenes: [],
    selected: null,
    focusedScene: null,
    positions: {},
    labels: true,
    mode: 'overview',
    entityQuery: '',
    sourceFilter: '',
    recordingFilter: '',
    timeFrom: null,
    timeTo: null,
    verificationFilter: 'all',
  }
  try {
    const data = JSON.parse(
      sessionStorage.getItem(`searchy:graph-v5:${key}`) ??
        sessionStorage.getItem(`searchy:graph-v4:${key}`) ??
        'null'
    )
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
      collapsedScenes: Array.isArray(data.collapsedScenes)
        ? data.collapsedScenes.filter((s: unknown) => typeof s === 'string').slice(0, 12)
        : [],
      mode:
        data.mode === 'detail'
          ? 'evidence'
          : data.mode === 'path'
            ? 'relationship'
            : researchViews.includes(data.mode)
              ? data.mode
              : 'overview',
      entityQuery: typeof data.entityQuery === 'string' ? data.entityQuery.slice(0, 80) : '',
      sourceFilter: typeof data.sourceFilter === 'string' ? data.sourceFilter.slice(0, 180) : '',
      recordingFilter:
        typeof data.recordingFilter === 'string' ? data.recordingFilter.slice(0, 120) : '',
      timeFrom: Number.isFinite(data.timeFrom) && data.timeFrom >= 0 ? data.timeFrom : null,
      timeTo: Number.isFinite(data.timeTo) && data.timeTo >= 0 ? data.timeTo : null,
      verificationFilter: verificationFilters.includes(data.verificationFilter)
        ? data.verificationFilter
        : 'all',
    }
  } catch {
    return defaults
  }
}
export function saveGraphState(key: string, state: GraphPreferences) {
  try {
    sessionStorage.setItem(`searchy:graph-v5:${key}`, JSON.stringify(state))
  } catch {
    /* Exploration remains usable without browser storage. */
  }
}
