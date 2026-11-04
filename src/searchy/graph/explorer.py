import math
import re
from collections import defaultdict

from searchy.api.exploration import (
    GraphEdge,
    GraphNode,
    GraphRequest,
    GraphResponse,
    GraphSupport,
)
from searchy.core import InvalidInput, SearchyError
from searchy.domain import stable_id, visual_description
from searchy.retrieval.search import normalized_terms

_SEEDS = """
// searchy_explorer:seeds
UNWIND $scenes AS requested
MATCH (s:Scene {scene_id: requested.scene_id, collection_id: requested.collection_id})
RETURN s.scene_id AS scene_id, {labels: labels(s), properties: properties(s)} AS node
ORDER BY scene_id LIMIT $scene_limit
"""

_LINEAGE = """
// searchy_explorer:lineage
UNWIND $scenes AS requested
MATCH (s:Scene {scene_id: requested.scene_id, collection_id: requested.collection_id})
CALL {
    WITH s
    MATCH p=(s)-[:PART_OF*1..2]->(ancestor)
    WHERE all(n IN nodes(p) WHERE (n:Scene OR n:Video OR n:Episode)
        AND n.collection_id = s.collection_id)
    RETURN p
    ORDER BY length(p), coalesce(ancestor.video_id, ancestor.episode_id)
    LIMIT $lineage_limit
}
RETURN s.scene_id AS scene_id,
    [n IN nodes(p) | {labels: labels(n), properties: properties(n)}] AS nodes,
    [r IN relationships(p) | {type: type(r),
        source: {labels: labels(startNode(r)), properties: properties(startNode(r))},
        target: {labels: labels(endNode(r)), properties: properties(endNode(r))}}] AS edges
ORDER BY scene_id
"""

_OBSERVATIONS = """
// searchy_explorer:observations
UNWIND $scenes AS requested
MATCH (s:Scene {scene_id: requested.scene_id, collection_id: requested.collection_id})
CALL {
    WITH s
    MATCH (s)-[r:HAS_OBSERVATION]->(o:Observation)
    WHERE o.scene_id = s.scene_id
        AND (size($evidence_ids) = 0 OR o.observation_id IN $evidence_ids)
    WITH r, o, reduce(score = 0, term IN $terms | score + CASE WHEN
        toLower(coalesce(o.value, '') + ' ' + coalesce(o.evidence, '')) CONTAINS term THEN 1 ELSE 0 END) AS relevance
    RETURN r, o, relevance ORDER BY relevance DESC, coalesce(o.verified, false) DESC,
        (o.character_id IS NOT NULL OR o.subject_id IS NOT NULL) DESC,
        (o.kind = 'character') DESC, o.observation_id LIMIT $observation_limit
}
RETURN s.scene_id AS scene_id, o.observation_id AS item_id, relevance,
    {labels: labels(o), properties: properties(o)} AS node,
    {type: type(r), source: {labels: labels(s), properties: properties(s)},
        target: {labels: labels(o), properties: properties(o)}} AS edge
ORDER BY scene_id, relevance DESC, coalesce(o.verified, false) DESC,
    (o.character_id IS NOT NULL OR o.subject_id IS NOT NULL) DESC,
    (o.kind = 'character') DESC, item_id
"""

_DIALOGUE = """
// searchy_explorer:dialogue
UNWIND $scenes AS requested
MATCH (s:Scene {scene_id: requested.scene_id, collection_id: requested.collection_id})
CALL {
    WITH s
    MATCH (s)-[r:HAS_DIALOGUE]->(d:Dialogue)
    WHERE d.scene_id = s.scene_id
        AND (size($evidence_ids) = 0 OR d.dialogue_id IN $evidence_ids)
    WITH r, d, reduce(score = 0, term IN $terms | score + CASE WHEN
        toLower(d.text) CONTAINS term THEN 1 ELSE 0 END) AS relevance
    RETURN r, d, relevance ORDER BY relevance DESC, d.start, d.dialogue_id LIMIT $dialogue_limit
}
RETURN s.scene_id AS scene_id, d.dialogue_id AS item_id, relevance,
    {labels: labels(d), properties: properties(d)} AS node,
    {type: type(r), source: {labels: labels(s), properties: properties(s)},
        target: {labels: labels(d), properties: properties(d)}} AS edge
ORDER BY scene_id, relevance DESC, node.properties.start, item_id
"""

_ENTITIES = """
// searchy_explorer:entities
UNWIND $scenes AS scene_request
UNWIND $evidence AS requested
WITH scene_request, requested WHERE scene_request.scene_id = requested.scene_id
MATCH (s:Scene {scene_id: scene_request.scene_id, collection_id: scene_request.collection_id})
    -[:HAS_OBSERVATION|HAS_DIALOGUE]->(item)
WHERE (requested.kind = 'Observation' AND item:Observation
        AND item.observation_id = requested.item_id)
    OR (requested.kind = 'Dialogue' AND item:Dialogue AND item.dialogue_id = requested.item_id)
CALL {
    WITH s, item
    MATCH (item)-[detail:DESCRIBES|SUBJECT|SPOKEN_BY|MENTIONS|ABOUT]->(entity)
    WHERE ((item:Observation AND type(detail) IN ['DESCRIBES', 'SUBJECT'])
        OR (item:Dialogue AND type(detail) IN ['SPOKEN_BY', 'MENTIONS', 'ABOUT']))
        AND any(label IN labels(entity) WHERE label IN $entity_labels)
    WITH s, detail, entity ORDER BY type(detail), entity.key LIMIT $detail_limit
    CALL {
        WITH s, entity
        OPTIONAL MATCH (s)-[direct:CONTAINS|OCCURS_AT|APPEARS_IN]-(entity)
        WITH direct ORDER BY type(direct) LIMIT $direct_limit
        RETURN collect(CASE WHEN direct IS NOT NULL THEN {type: type(direct),
            source: {labels: labels(startNode(direct)), properties: properties(startNode(direct))},
            target: {labels: labels(endNode(direct)), properties: properties(endNode(direct))}}
            ELSE null END) AS direct_edges
    }
    RETURN detail, entity, direct_edges
}
RETURN s.scene_id AS scene_id, requested.item_id AS item_id,
    {labels: labels(entity), properties: properties(entity)} AS node,
    {type: type(detail), source: {labels: labels(item), properties: properties(item)},
        target: {labels: labels(entity), properties: properties(entity)}} AS edge,
    direct_edges
ORDER BY scene_id, item_id, edge.type, node.properties.key
"""

_IDENTIFIERS = {
    "Scene": "scene_id",
    "Video": "video_id",
    "Episode": "episode_id",
    "Observation": "observation_id",
    "Dialogue": "dialogue_id",
    "Character": "key",
    "Clothing": "key",
    "Action": "key",
    "Object": "key",
    "Location": "key",
    "Profession": "key",
}
_PROPERTIES = {
    "Scene": {
        "scene_id",
        "video_id",
        "collection_id",
        "episode_id",
        "source_chunk",
        "start",
        "end",
        "timestamp_basis",
        "description",
        "visual_description",
        "scene_summary",
    },
    "Video": {"video_id", "collection_id", "title", "source_kind", "duration", "original_id"},
    "Episode": {"episode_id", "collection_id", "original_id"},
    "Observation": {
        "observation_id",
        "scene_id",
        "kind",
        "value",
        "subject",
        "character_id",
        "subject_id",
        "evidence",
        "start",
        "end",
        "method",
        "model",
        "confidence",
        "verified",
        "source",
    },
    "Dialogue": {
        "dialogue_id",
        "scene_id",
        "text",
        "speaker",
        "speaker_id",
        "speaker_confidence",
        "start",
        "end",
        "source_start",
        "source_end",
        "method",
        "model",
        "confidence",
        "verified",
        "source",
    },
    **{
        kind: {"key", "name", "normalized"}
        for kind in ("Character", "Clothing", "Action", "Object", "Location", "Profession")
    },
}
_EDGE_TYPES = {
    "PART_OF",
    "HAS_OBSERVATION",
    "HAS_DIALOGUE",
    "DESCRIBES",
    "SUBJECT",
    "CONTAINS",
    "OCCURS_AT",
    "APPEARS_IN",
    "SPOKEN_BY",
    "MENTIONS",
    "ABOUT",
}
_EDGE_EXPLANATIONS = {
    "PART_OF": "The stored hierarchy links this scene, episode, or video.",
    "HAS_OBSERVATION": "This observation is stored under the scene.",
    "HAS_DIALOGUE": "This transcript segment is stored under the scene.",
    "DESCRIBES": "The observation describes this indexed entity.",
    "SUBJECT": "The observation is attributed to this indexed subject.",
    "CONTAINS": "The stored scene relationship associates this object with the scene.",
    "OCCURS_AT": "The stored scene relationship associates this place with the scene.",
    "APPEARS_IN": "The stored scene relationship associates this person with the scene.",
    "SPOKEN_BY": "The transcript associates this dialogue segment with this speaker.",
    "MENTIONS": "This dialogue segment explicitly mentions this character.",
    "ABOUT": "This dialogue segment directly identifies this character as its subject.",
}
_ORDER = {kind: index for index, kind in enumerate(_IDENTIFIERS)}


def _identity(raw: dict) -> tuple[str, str] | None:
    for kind, key in _IDENTIFIERS.items():
        identifier = raw.get("properties", {}).get(key)
        if kind in raw.get("labels", []) and isinstance(identifier, str) and identifier:
            return kind, f"{kind}:{identifier}"
    return None


def _number(value) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def _evidence(properties: dict) -> list[str]:
    text = properties.get("evidence") or properties.get("text") or properties.get("description")
    return [text] if isinstance(text, str) and text else []


def _source_reference(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    reference = value.strip().split("?", 1)[0].split("#", 1)[0]
    name = reference.replace("\\", "/").rsplit("/", 1)[-1]
    if name in {"", ".", ".."}:
        return None
    return "".join(character for character in name if character.isprintable())[:160] or None


def _uploaded_sha256(value) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9]{64}", value):
        return value.lower()
    return None


class _Subgraph:
    def __init__(self, scene_ids: list[str]):
        self.scene_ids = scene_ids
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[str, GraphEdge] = {}

    def node(self, raw: dict, scene_id: str):
        identity = _identity(raw)
        if identity is None:
            return
        kind, identifier = identity
        properties = raw["properties"]
        if kind == "Scene" and properties["scene_id"] not in self.scene_ids:
            return
        if kind in {"Observation", "Dialogue"} and properties.get("scene_id") != scene_id:
            return
        if identifier in self.nodes:
            current = self.nodes[identifier]
            current.scene_ids = sorted(set(current.scene_ids + [scene_id]))
            return
        safe = {
            key: value
            for key, value in properties.items()
            if key in _PROPERTIES[kind]
            and (value is None or isinstance(value, (str, int, float, bool)))
        }
        if kind == "Scene" and isinstance(safe.get("description"), str):
            safe["description"] = visual_description(safe["description"])
            safe["visual_description"] = safe["description"]
        source = safe.pop("source", None)
        source_chunk = safe.pop("source_chunk", None)
        source_reference = _source_reference(source)
        if source_reference is None and kind == "Scene":
            source_reference = _source_reference(source_chunk)
        if source_reference is not None:
            safe["source_reference"] = source_reference
        if kind == "Video":
            digest = _uploaded_sha256(safe.pop("original_id", None))
            if digest:
                safe["content_sha256"] = digest
        label = (
            safe.get("name")
            or safe.get("value")
            or safe.get("text")
            or safe.get("title")
            or safe.get("original_id")
        )
        if kind == "Scene":
            chunk_reference = _source_reference(properties.get("source_chunk"))
            label = (
                " · ".join(
                    str(value)
                    for value in (properties.get("episode_id"), chunk_reference)
                    if value
                )
                or properties.get("description")
                or "Scene"
            )
        confidence = _number(properties.get("confidence"))
        self.nodes[identifier] = GraphNode(
            id=identifier,
            type=kind,
            label=str(label or kind)[:120],
            scene_ids=[scene_id],
            properties=safe,
            evidence=_evidence(properties),
            start=_number(properties.get("start")),
            end=_number(properties.get("end")),
            confidence=confidence if confidence is not None and 0 <= confidence <= 1 else None,
            verified=properties.get("verified")
            if isinstance(properties.get("verified"), bool)
            else None,
        )

    def support(self, raw: dict | None, scene_id: str) -> GraphSupport | None:
        scene = self.nodes.get(f"Scene:{scene_id}")
        if scene is None:
            return None
        identity = _identity(raw or {})
        kind = identity[0] if identity else "Scene"
        if kind not in {"Scene", "Observation", "Dialogue"}:
            kind = "Scene"
            raw = None
        properties = (raw or {}).get("properties", {})
        identity = _identity(raw or {}) if raw else None
        evidence_id = identity[1] if identity else scene.id
        start = _number(properties.get("start"))
        end = _number(properties.get("end"))
        confidence = _number(properties.get("confidence"))
        return GraphSupport(
            evidence_id=evidence_id,
            kind=kind,
            scene_id=scene_id,
            recording_id=scene.properties.get("video_id")
            if isinstance(scene.properties.get("video_id"), str)
            else None,
            source_reference=_source_reference(
                properties.get("source") or properties.get("source_chunk")
            ),
            start=start,
            end=end,
            timestamp_basis=(
                scene.properties.get("timestamp_basis")
                if isinstance(scene.properties.get("timestamp_basis"), str)
                else None
            ),
            method=properties.get("method") if isinstance(properties.get("method"), str) else None,
            model=properties.get("model") if isinstance(properties.get("model"), str) else None,
            confidence=confidence if confidence is not None and 0 <= confidence <= 1 else None,
            verified=properties.get("verified")
            if isinstance(properties.get("verified"), bool)
            else None,
        )

    def edge(
        self,
        raw: dict,
        scene_id: str,
        evidence: list[str] | None = None,
        support_raw: dict | None = None,
    ):
        source, target = _identity(raw.get("source", {})), _identity(raw.get("target", {}))
        kind = raw.get("type")
        if not source or not target or kind not in _EDGE_TYPES:
            return
        identifier = stable_id(f"exploration-edge:{source[1]}:{kind}:{target[1]}")
        support = self.support(support_raw, scene_id)
        if identifier in self.edges:
            current = self.edges[identifier]
            current.scene_ids = sorted(set(current.scene_ids + [scene_id]))
            current.evidence = sorted(set(current.evidence + (evidence or [])))
            if support and support not in current.supports:
                current.supports.append(support)
        else:
            self.edges[identifier] = GraphEdge(
                id=identifier,
                source=source[1],
                target=target[1],
                type=kind,
                scene_ids=[scene_id],
                evidence=evidence or [],
                explanation=_EDGE_EXPLANATIONS[kind],
                supports=[support] if support else [],
            )

    def response(self, request: GraphRequest, truncated: bool) -> GraphResponse:
        nodes = sorted(self.nodes.values(), key=lambda item: (_ORDER[item.type], item.id))
        truncated |= len(nodes) > request.max_nodes
        nodes = nodes[: request.max_nodes]
        identifiers = {item.id for item in nodes}
        edges = sorted(self.edges.values(), key=lambda item: (item.source, item.type, item.target))
        connected = [
            item for item in edges if item.source in identifiers and item.target in identifiers
        ]
        truncated |= len(connected) < len(edges) or len(connected) > request.max_edges
        warnings = []
        if truncated:
            warnings.append(
                "The graph is bounded: some evidence or links were omitted. Select fewer scenes or increase the graph limits."
            )
        if any(
            support.kind in {"Observation", "Dialogue"}
            and (support.start is None or support.end is None)
            for edge in connected
            for support in edge.supports
        ):
            warnings.append(
                "Some evidence records have no exact interval; the parent scene interval is not substituted."
            )
        warnings.append(
            "Camera IDs, recording sessions, ingestion times, reviewer history, and conflict records are not stored in this graph index."
        )
        return GraphResponse(
            nodes=nodes,
            edges=connected[: request.max_edges],
            truncated=truncated,
            scene_ids=self.scene_ids,
            warnings=warnings,
        )


class GraphExplorer:
    def __init__(self, graph, metadata):
        self.graph, self.metadata = graph, metadata

    def explore(self, request: GraphRequest) -> GraphResponse:
        scene_ids = sorted(request.scene_ids)
        scenes = []
        for scene_id in scene_ids:
            scene = self.metadata.get_scene(scene_id)
            if scene is None or not self.metadata.is_indexed(scene_id):
                raise InvalidInput("Every graph seed must be a canonical indexed scene")
            if request.collection_id is not None and scene.collection_id != request.collection_id:
                raise InvalidInput("A graph seed is outside the requested collection")
            scenes.append({"scene_id": scene_id, "collection_id": scene.collection_id})

        def read(tx):
            graph = _Subgraph(scene_ids)
            seeds = list(tx.run(_SEEDS, scenes=scenes, scene_limit=12))
            if {row["scene_id"] for row in seeds} != set(scene_ids):
                raise SearchyError(
                    "Indexed scene graph is incomplete; reimport the requested scenes", 503
                )
            for row in seeds:
                graph.node(row["node"], row["scene_id"])
            truncated = False
            counts = defaultdict(int)
            for row in tx.run(_LINEAGE, scenes=scenes, lineage_limit=7):
                scene_id = row["scene_id"]
                counts[scene_id] += 1
                if counts[scene_id] > 6:
                    truncated = True
                    continue
                for raw in row["nodes"]:
                    graph.node(raw, scene_id)
                for raw in row["edges"]:
                    scene_record = next(
                        (item for item in row["nodes"] if _identity(item) == ("Scene", f"Scene:{scene_id}")),
                        None,
                    )
                    graph.edge(raw, scene_id, support_raw=scene_record)
            evidence = []
            evidence_text = {}
            for query, kind, cap, parameter in (
                (_OBSERVATIONS, "Observation", 8, "observation_limit"),
                (_DIALOGUE, "Dialogue", 6 if request.evidence_ids else 3, "dialogue_limit"),
            ):
                counts = defaultdict(int)
                for row in tx.run(
                    query,
                    scenes=scenes,
                    evidence_ids=request.evidence_ids,
                    terms=sorted(normalized_terms(request.query))[:40],
                    **{parameter: cap + 1},
                ):
                    scene_id = row["scene_id"]
                    counts[scene_id] += 1
                    if counts[scene_id] > cap:
                        truncated = True
                        continue
                    text = _evidence(row["node"]["properties"])
                    graph.node(row["node"], scene_id)
                    graph.edge(row["edge"], scene_id, text, row["node"])
                    evidence.append({"scene_id": scene_id, "item_id": row["item_id"], "kind": kind})
                    evidence_text[(scene_id, row["item_id"])] = text
            if evidence:
                evidence_kinds = {
                    (item["scene_id"], item["item_id"]): item["kind"] for item in evidence
                }
                counts = defaultdict(int)
                for row in tx.run(
                    _ENTITIES,
                    scenes=scenes,
                    evidence=evidence,
                    entity_labels=[
                        "Character",
                        "Clothing",
                        "Action",
                        "Object",
                        "Location",
                        "Profession",
                    ],
                    detail_limit=3,
                    direct_limit=3,
                ):
                    key = row["scene_id"], row["item_id"]
                    if key not in evidence_kinds:
                        continue
                    counts[key] += 1
                    if counts[key] > (2 if evidence_kinds[key] == "Observation" else 1):
                        truncated = True
                        continue
                    graph.node(row["node"], key[0])
                    graph.edge(
                        row["edge"],
                        key[0],
                        evidence_text[key],
                        row["edge"].get("source"),
                    )
                    if len(row["direct_edges"]) > 2:
                        truncated = True
                    for raw in row["direct_edges"][:2]:
                        graph.edge(
                            raw,
                            key[0],
                            evidence_text[key],
                            row["edge"].get("source"),
                        )
            return graph.response(request, truncated)

        try:
            with self.graph._connection().session(
                database=self.graph.settings.neo4j_database
            ) as session:
                return session.execute_read(read)
        except Exception:
            raise SearchyError(
                "Neo4j evidence graph is unavailable; check the connection and indexed scenes", 503
            ) from None
