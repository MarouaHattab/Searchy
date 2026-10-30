import json
import re
from typing import Any

from neo4j import GraphDatabase

from searchy.core.config import Settings
from searchy.core.errors import InvalidInput, SearchyError
from searchy.domain import Candidate, ObservationKind, Scene, Video, stable_id

_SCHEMA = (
    "CREATE CONSTRAINT searchy_video_id IF NOT EXISTS FOR (n:Video) REQUIRE n.video_id IS UNIQUE",
    "CREATE CONSTRAINT searchy_episode_id IF NOT EXISTS FOR (n:Episode) REQUIRE n.episode_id IS UNIQUE",
    "CREATE CONSTRAINT searchy_scene_id IF NOT EXISTS FOR (n:Scene) REQUIRE n.scene_id IS UNIQUE",
    "CREATE CONSTRAINT searchy_observation_id IF NOT EXISTS FOR (n:Observation) REQUIRE n.observation_id IS UNIQUE",
    "CREATE CONSTRAINT searchy_dialogue_id IF NOT EXISTS FOR (n:Dialogue) REQUIRE n.dialogue_id IS UNIQUE",
    "CREATE CONSTRAINT searchy_character_key IF NOT EXISTS FOR (n:Character) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT searchy_clothing_key IF NOT EXISTS FOR (n:Clothing) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT searchy_action_key IF NOT EXISTS FOR (n:Action) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT searchy_object_key IF NOT EXISTS FOR (n:Object) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT searchy_location_key IF NOT EXISTS FOR (n:Location) REQUIRE n.key IS UNIQUE",
)

_UPSERT_BASE = """
UNWIND $rows AS row
MERGE (v:Video {video_id: row.video_id}) SET v = row.video
MERGE (s:Scene {scene_id: row.scene_id}) SET s = row.scene
"""

_DELETE_OBSERVATIONS = """
UNWIND $scene_ids AS scene_id
MATCH (:Scene {scene_id: scene_id})-[:HAS_OBSERVATION]->(o:Observation) DETACH DELETE o
"""

_DELETE_DIALOGUE = """
UNWIND $scene_ids AS scene_id
MATCH (:Scene {scene_id: scene_id})-[:HAS_DIALOGUE]->(d:Dialogue) DETACH DELETE d
"""

_RESET_SCENE_LINKS = """
UNWIND $scene_ids AS scene_id
MATCH (s:Scene {scene_id: scene_id})-[r:PART_OF|CONTAINS|OCCURS_AT]-() DELETE r
"""

_RESET_CHARACTERS = """
UNWIND $scene_ids AS scene_id
MATCH (:Character)-[r:APPEARS_IN]->(:Scene {scene_id: scene_id}) DELETE r
"""

_LINK_VIDEO = """
UNWIND $rows AS row
MATCH (s:Scene {scene_id: row.scene_id}), (v:Video {video_id: row.video_id})
MERGE (s)-[:PART_OF]->(v)
"""

_LINK_EPISODE = """
UNWIND $rows AS row
MATCH (s:Scene {scene_id: row.scene_id}), (v:Video {video_id: row.video_id})
MERGE (e:Episode {episode_id: row.episode_key})
SET e.original_id = row.episode_id, e.collection_id = row.collection_id
MERGE (s)-[:PART_OF]->(e)
MERGE (e)-[:PART_OF]->(v)
"""

_UPSERT_OBSERVATION = """
UNWIND $rows AS row
MATCH (s:Scene {scene_id: row.scene_id})
MERGE (o:Observation {observation_id: row.observation_id}) SET o = row.properties
MERGE (s)-[:HAS_OBSERVATION]->(o)
"""

_CHARACTER = """
UNWIND $rows AS row
MATCH (s:Scene {scene_id: row.scene_id}), (o:Observation {observation_id: row.observation_id})
MERGE (c:Character {key: row.key}) SET c.name = row.name, c.normalized = row.normalized
MERGE (c)-[:APPEARS_IN]->(s)
MERGE (o)-[:DESCRIBES]->(c)
"""

_SUBJECT = """
UNWIND $rows AS row
MATCH (s:Scene {scene_id: row.scene_id}), (o:Observation {observation_id: row.observation_id})
MERGE (c:Character {key: row.key}) SET c.name = row.name, c.normalized = row.normalized
MERGE (o)-[:SUBJECT]->(c)
MERGE (c)-[:APPEARS_IN]->(s)
"""

_CLOTHING = """
UNWIND $rows AS row
MATCH (o:Observation {observation_id: row.observation_id})
MERGE (n:Clothing {key: row.key}) SET n.name = row.name
MERGE (o)-[:DESCRIBES]->(n)
"""

_ACTION = """
UNWIND $rows AS row
MATCH (o:Observation {observation_id: row.observation_id})
MERGE (n:Action {key: row.key}) SET n.name = row.name
MERGE (o)-[:DESCRIBES]->(n)
"""

_OBJECT = """
UNWIND $rows AS row
MATCH (s:Scene {scene_id: row.scene_id}), (o:Observation {observation_id: row.observation_id})
MERGE (n:Object {key: row.key}) SET n.name = row.name
MERGE (o)-[:DESCRIBES]->(n)
MERGE (s)-[:CONTAINS]->(n)
"""

_LOCATION = """
UNWIND $rows AS row
MATCH (s:Scene {scene_id: row.scene_id}), (o:Observation {observation_id: row.observation_id})
MERGE (n:Location {key: row.key}) SET n.name = row.name
MERGE (o)-[:DESCRIBES]->(n)
MERGE (s)-[:OCCURS_AT]->(n)
"""

_UPSERT_DIALOGUE = """
UNWIND $rows AS row
MATCH (s:Scene {scene_id: row.scene_id})
MERGE (d:Dialogue {dialogue_id: row.dialogue_id}) SET d = row.properties
MERGE (s)-[:HAS_DIALOGUE]->(d)
"""

_SPEAKER = """
UNWIND $rows AS row
MATCH (d:Dialogue {dialogue_id: row.dialogue_id})
MERGE (c:Character {key: row.key}) SET c.name = row.name, c.normalized = row.normalized
MERGE (d)-[:SPOKEN_BY]->(c)
"""

_SEARCH = """
MATCH (s:Scene)
WHERE ($collection_id IS NULL OR s.collection_id = $collection_id)
  AND all(term IN $terms WHERE term IN s.terms)
  AND all(identifier IN $character_ids WHERE
      EXISTS { MATCH (:Character {key: identifier})-[:APPEARS_IN]->(s) }
      OR EXISTS { MATCH (s)-[:HAS_DIALOGUE]->(:Dialogue)-[:SPOKEN_BY]->(:Character {key: identifier}) })
OPTIONAL MATCH (c:Character)-[:APPEARS_IN]->(s)
WITH s, collect(DISTINCT c.normalized) AS visible_characters
OPTIONAL MATCH (s)-[:HAS_DIALOGUE]->(:Dialogue)-[:SPOKEN_BY]->(speaker:Character)
WITH s, visible_characters, collect(DISTINCT speaker.normalized) AS speaking_characters
WITH s, visible_characters + speaking_characters AS characters
WHERE all(name IN $characters WHERE
    any(actual IN characters WHERE actual = name OR actual STARTS WITH name + ' '))
OPTIONAL MATCH (s)-[:HAS_OBSERVATION]->(o:Observation)
WITH s, collect(DISTINCT CASE WHEN
    any(term IN $terms WHERE toLower(o.value + ' ' + o.evidence) CONTAINS term)
    OR toLower(o.value) IN $characters OR toLower(o.subject) IN $characters
    THEN o.evidence ELSE null END) AS observations
OPTIONAL MATCH (s)-[:HAS_DIALOGUE]->(d:Dialogue)
WITH s, observations, collect(DISTINCT CASE WHEN
    any(term IN $terms WHERE toLower(d.text) CONTAINS term)
    OR any(name IN $characters WHERE toLower(d.speaker) = name
        OR toLower(d.speaker) STARTS WITH name + ' ')
    THEN d.text ELSE null END) AS dialogue
RETURN s.scene_id AS scene_id,
    $score AS score,
    CASE WHEN s.description <> '' THEN [s.description] ELSE [] END + observations + dialogue AS evidence
ORDER BY s.scene_id
LIMIT $limit
"""

_CONTEXT = """
// searchy_context
UNWIND $scenes AS requested
MATCH (s:Scene {scene_id: requested})
WHERE ($collection_id IS NULL OR s.collection_id = $collection_id)
CALL (s) {
    MATCH (s)-[:HAS_OBSERVATION]->(:Observation)-[link:DESCRIBES|SUBJECT]->(e)
    WHERE e.name IS NOT NULL
    RETURN collect(DISTINCT {kind: head(labels(e)), name: e.name, link: type(link)}) AS entities
}
CALL (s) {
    MATCH (c:Character)-[:APPEARS_IN]->(s)
    RETURN collect(DISTINCT c.name) AS appearing
}
CALL (s) {
    MATCH (s)-[:HAS_DIALOGUE]->(:Dialogue)-[:SPOKEN_BY]->(c:Character)
    RETURN collect(DISTINCT c.name) AS speaking
}
RETURN s.scene_id AS scene_id,
    entities,
    appearing + speaking AS characters
"""

_ENTITY_QUERIES = {
    ObservationKind.CLOTHING: _CLOTHING,
    ObservationKind.ACTION: _ACTION,
    ObservationKind.INTERACTION: _ACTION,
    ObservationKind.OBJECT: _OBJECT,
    ObservationKind.LOCATION: _LOCATION,
}

_STOPWORDS = frozenset(
    """
a an and are as at be been being by can could did do does don during find for from had has
have he her here him his how i in is it its me my of on or our please said say says scene scenes
she show someone something that the their them there these they this those to us video videos
was we were what when where which who will with would you your wearing wears outfit outfits
""".split()
)


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _tokens(value: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\w+", value.casefold())))


class GraphStore:
    def __init__(self, settings: Settings, driver: Any = None):
        self.settings = settings
        self._driver = driver

    def _connection(self):
        if self._driver is None:
            if not self.settings.neo4j_password.get_secret_value():
                raise SearchyError("Set NEO4J_PASSWORD before using the knowledge graph")
            try:
                self._driver = GraphDatabase.driver(
                    self.settings.neo4j_uri,
                    auth=(
                        self.settings.neo4j_user,
                        self.settings.neo4j_password.get_secret_value(),
                    ),
                    connection_timeout=10,
                    connection_acquisition_timeout=15,
                    max_transaction_retry_time=15,
                )
            except Exception:
                raise SearchyError(
                    "Cannot configure Neo4j. Check NEO4J_URI and credentials"
                ) from None
        return self._driver

    def ready(self) -> None:
        try:
            driver = self._connection()
            driver.verify_connectivity()
            with driver.session(database=self.settings.neo4j_database) as session:
                session.execute_read(lambda tx: tx.run("RETURN 1 AS ready").consume())
        except SearchyError:
            raise
        except Exception:
            raise SearchyError(
                "Neo4j is unavailable. Check the service, credentials and NEO4J_DATABASE"
            ) from None

    def ensure_schema(self) -> None:
        def create(tx):
            for query in _SCHEMA:
                tx.run(query).consume()

        try:
            with self._connection().session(database=self.settings.neo4j_database) as session:
                session.execute_write(create)
        except SearchyError:
            raise
        except Exception:
            raise SearchyError(
                "Cannot create Neo4j constraints. Check database write permissions"
            ) from None

    def _character_parameters(self, scene: Scene, name: str, identifier: str | None = None) -> dict:
        normalized = _normalized(name)
        return {
            "key": identifier or stable_id(f"character:{scene.collection_id}:{normalized}"),
            "name": name.strip(),
            "normalized": normalized,
        }

    def upsert(self, scene: Scene, video: Video) -> None:
        self.upsert_scenes([scene], {video.video_id: video})

    def upsert_scenes(self, scenes: list[Scene], videos: dict[str, Video]) -> None:
        if not scenes:
            return
        if len({scene.scene_id for scene in scenes}) != len(scenes):
            raise InvalidInput("Scene batch contains duplicate scene identifiers")
        base_rows = []
        groups = {
            query: []
            for query in (
                _LINK_VIDEO,
                _LINK_EPISODE,
                _UPSERT_OBSERVATION,
                _CHARACTER,
                *_ENTITY_QUERIES.values(),
                _SUBJECT,
                _UPSERT_DIALOGUE,
                _SPEAKER,
            )
        }
        for scene in scenes:
            video = videos.get(scene.video_id)
            if (
                video is None
                or scene.collection_id != video.collection_id
                or scene.video_id != video.video_id
            ):
                raise InvalidInput("Scene and video identifiers or collections do not agree")
            properties = {
                "scene_id": scene.scene_id,
                "video_id": scene.video_id,
                "collection_id": scene.collection_id,
                "episode_id": scene.episode_id,
                "source_chunk": scene.source_chunk,
                "start": scene.start,
                "end": scene.end,
                "timestamp_basis": scene.timestamp_basis,
                "description": scene.description,
                "character_ids": scene.character_ids,
                "terms": _tokens(scene.search_text()),
                "provenance_json": json.dumps([p.model_dump() for p in scene.provenance]),
            }
            base_rows.append(
                {
                    "video_id": video.video_id,
                    "video": video.model_dump(),
                    "scene_id": scene.scene_id,
                    "scene": properties,
                }
            )
            groups[_LINK_VIDEO].append({"scene_id": scene.scene_id, "video_id": scene.video_id})
            if scene.episode_id:
                groups[_LINK_EPISODE].append(
                    {
                        "scene_id": scene.scene_id,
                        "video_id": scene.video_id,
                        "episode_key": stable_id(
                            f"episode:{scene.collection_id}:{scene.episode_id}"
                        ),
                        "episode_id": scene.episode_id,
                        "collection_id": scene.collection_id,
                    }
                )
            for index, observation in enumerate(scene.observations):
                observation_id = stable_id(f"observation:{scene.scene_id}:{index}")
                values = observation.model_dump(exclude={"provenance"}, mode="json")
                values.update(observation.provenance.model_dump())
                values.update(observation_id=observation_id, scene_id=scene.scene_id)
                identifiers = {"scene_id": scene.scene_id, "observation_id": observation_id}
                groups[_UPSERT_OBSERVATION].append({**identifiers, "properties": values})
                if observation.kind == ObservationKind.CHARACTER:
                    groups[_CHARACTER].append(
                        {
                            **identifiers,
                            **self._character_parameters(
                                scene, observation.value, observation.character_id
                            ),
                        }
                    )
                else:
                    groups[_ENTITY_QUERIES[observation.kind]].append(
                        {
                            **identifiers,
                            "key": stable_id(
                                f"{observation.kind.value}:{_normalized(observation.value)}"
                            ),
                            "name": observation.value,
                        }
                    )
                if observation.subject and observation.kind in (
                    ObservationKind.CLOTHING,
                    ObservationKind.ACTION,
                    ObservationKind.INTERACTION,
                ):
                    groups[_SUBJECT].append(
                        {
                            **identifiers,
                            **self._character_parameters(
                                scene, observation.subject, observation.subject_id
                            ),
                        }
                    )
            for index, dialogue in enumerate(scene.dialogue):
                dialogue_id = stable_id(f"dialogue:{scene.scene_id}:{index}")
                values = dialogue.model_dump(exclude={"provenance"})
                if dialogue.provenance:
                    values.update(dialogue.provenance.model_dump())
                values.update(dialogue_id=dialogue_id, scene_id=scene.scene_id)
                groups[_UPSERT_DIALOGUE].append(
                    {
                        "scene_id": scene.scene_id,
                        "dialogue_id": dialogue_id,
                        "properties": values,
                    }
                )
                if dialogue.speaker:
                    groups[_SPEAKER].append(
                        {
                            "dialogue_id": dialogue_id,
                            **self._character_parameters(
                                scene, dialogue.speaker, dialogue.speaker_id
                            ),
                        }
                    )

        def replace(tx):
            tx.run(_UPSERT_BASE, rows=base_rows).consume()
            for query in (
                _DELETE_OBSERVATIONS,
                _DELETE_DIALOGUE,
                _RESET_SCENE_LINKS,
                _RESET_CHARACTERS,
            ):
                tx.run(query, scene_ids=[scene.scene_id for scene in scenes]).consume()
            for query, rows in groups.items():
                if rows:
                    tx.run(query, rows=rows).consume()

        try:
            with self._connection().session(database=self.settings.neo4j_database) as session:
                session.execute_write(replace)
        except SearchyError:
            raise
        except Exception:
            raise SearchyError(
                "Neo4j scene indexing failed; the scene batch transaction was rolled back"
            ) from None

    def search(
        self,
        query: str,
        characters: list[str],
        collection_id: str | None,
        limit: int,
        character_ids: list[str] | None = None,
    ) -> list[Candidate]:
        names = list(dict.fromkeys(_normalized(name) for name in characters))
        name_tokens = {token for name in names for token in _tokens(name)}
        terms = [
            token
            for token in _tokens(query)
            if len(token) > 1 and token not in _STOPWORDS and token not in name_tokens
        ]
        if not terms and not names and not character_ids:
            return []

        def read(tx):
            records = tx.run(
                _SEARCH,
                terms=terms,
                characters=names,
                character_ids=character_ids or [],
                collection_id=collection_id,
                limit=limit,
                score=min(1.0, 0.6 + 0.05 * (len(terms) + len(names))),
            )
            return [
                Candidate(
                    scene_id=record["scene_id"],
                    score=record["score"],
                    channel="graph",
                    evidence=list(dict.fromkeys(record["evidence"])),
                )
                for record in records
            ]

        try:
            with self._connection().session(database=self.settings.neo4j_database) as session:
                return session.execute_read(read)
        except SearchyError:
            raise
        except Exception:
            raise SearchyError(
                "Neo4j search failed. Check the database connection and schema"
            ) from None

    def context(self, scene_ids: list[str], collection_id: str | None = None) -> dict[str, dict]:
        """Return the graph entities attached to each scene, for answer context.

        Read-only. The caller is responsible for deciding whether the result proves
        anything; this only reports which entity nodes the scene is linked to.
        """
        if not scene_ids:
            return {}

        seen_kinds = ("Character", "Clothing", "Action", "Object", "Location")

        def read(tx):
            records = tx.run(_CONTEXT, scenes=scene_ids[:24], collection_id=collection_id)
            context = {}
            for record in records:
                entities: dict[str, list[str]] = {kind: [] for kind in seen_kinds}
                for item in record["entities"]:
                    if not item["name"] or item["kind"] not in entities:
                        continue
                    names = entities[item["kind"]]
                    if item["name"] not in names and len(names) < 6:
                        names.append(item["name"])
                context[record["scene_id"]] = {
                    "entities": {kind: names for kind, names in entities.items() if names},
                    "characters": sorted(set(record["characters"])),
                }
            return context

        try:
            with self._connection().session(database=self.settings.neo4j_database) as session:
                return session.execute_read(read)
        except SearchyError:
            raise
        except Exception:
            raise SearchyError(
                "Neo4j context lookup failed. Check the database connection and schema"
            ) from None

    def neighbors(self, scene_ids: list[str], collection_id=None) -> list[str]:
        query = """
        UNWIND $scene_ids AS scene_id
        MATCH (s:Scene {scene_id: scene_id})
        WHERE ($collection_id IS NULL OR s.collection_id = $collection_id) AND s.start IS NOT NULL
        CALL {
            WITH s
            MATCH (n:Scene)
            WHERE n.video_id = s.video_id AND n.collection_id = s.collection_id
                AND n.scene_id <> s.scene_id AND n.start IS NOT NULL
            RETURN n ORDER BY abs(n.start - s.start), n.start LIMIT 2
        }
        RETURN DISTINCT n.scene_id AS scene_id LIMIT 4
        """
        try:
            with self._connection().session(database=self.settings.neo4j_database) as session:
                return session.execute_read(
                    lambda tx: [
                        r["scene_id"]
                        for r in tx.run(query, scene_ids=scene_ids[:4], collection_id=collection_id)
                    ]
                )
        except Exception:
            raise SearchyError("Neo4j timeline context is unavailable", 503) from None

    def delete_scenes(self, scene_ids: list[str]) -> None:
        if not scene_ids:
            return

        def remove(tx):
            tx.run(
                "MATCH (o:Observation) WHERE o.scene_id IN $scene_ids DETACH DELETE o",
                scene_ids=scene_ids,
            ).consume()
            tx.run(
                "MATCH (d:Dialogue) WHERE d.scene_id IN $scene_ids DETACH DELETE d",
                scene_ids=scene_ids,
            ).consume()
            tx.run(
                "MATCH (s:Scene) WHERE s.scene_id IN $scene_ids DETACH DELETE s",
                scene_ids=scene_ids,
            ).consume()

        try:
            with self._connection().session(database=self.settings.neo4j_database) as session:
                session.execute_write(remove)
        except SearchyError:
            raise
        except Exception:
            raise SearchyError(
                "Neo4j could not remove obsolete scenes; the transaction was rolled back"
            ) from None

    def indexed_scene_ids(self, scene_ids: list[str]) -> set[str]:
        if not scene_ids:
            return set()

        def read(tx):
            return {
                record["scene_id"]
                for record in tx.run(
                    "MATCH (s:Scene) WHERE s.scene_id IN $scene_ids RETURN s.scene_id AS scene_id",
                    scene_ids=scene_ids,
                )
            }

        try:
            with self._connection().session(database=self.settings.neo4j_database) as session:
                return session.execute_read(read)
        except SearchyError:
            raise
        except Exception:
            raise SearchyError("Neo4j could not verify indexed scene records") from None

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
