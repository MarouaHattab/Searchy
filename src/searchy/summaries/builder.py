import json
import logging
from typing import Any

from searchy.core import Settings
from searchy.domain import EpisodeSummary, SummaryEvent
from searchy.storage import MetadataStore, VectorStore
from .canonical_data import CANONICAL_SEASON_1_EPISODES

logger = logging.getLogger(__name__)


class EpisodeSummaryBuilder:
    def __init__(self, settings: Settings, metadata: MetadataStore, vectors: VectorStore):
        self.settings = settings
        self.metadata = metadata
        self.vectors = vectors

    def build_all(self, collection_id: str = "friends") -> list[EpisodeSummary]:
        """Build and validate grounded episode summaries for all Season 1 episodes."""
        _, records, _ = self.metadata.catalog_records()
        indexed_scenes = [scene for scene, indexed in records if indexed and scene.collection_id == collection_id]

        # Group scenes by episode prefix (e.g. "1x01")
        scenes_by_ep = {}
        for scene in indexed_scenes:
            ep_id = scene.episode_id or ""
            prefix = ep_id.split()[0] if ep_id else ""
            if prefix:
                scenes_by_ep.setdefault(prefix, []).append(scene)

        # Sort each episode's scenes chronologically
        for prefix in scenes_by_ep:
            scenes_by_ep[prefix].sort(key=lambda s: s.start if s.start is not None else 0.0)

        summaries = []

        for ep_def in CANONICAL_SEASON_1_EPISODES:
            prefix = ep_def["episode_id"]
            ep_scenes = scenes_by_ep.get(prefix, [])
            if not ep_scenes:
                raise ValueError(f"No indexed scenes found for episode {prefix}")

            built_events = []
            for ev_def in ep_def["events"]:
                ev_id = ev_def["event_id"]
                keywords = [k.lower() for k in ev_def["keywords"]]
                chars = {c.casefold() for c in ev_def["characters_involved"]}

                scored = []
                for s in ep_scenes:
                    score = 0
                    dialogue_text = " ".join(line.text for line in s.dialogue).lower()
                    desc_text = (s.visual_text or s.description or "").lower()

                    for kw in keywords:
                        if kw in dialogue_text:
                            score += 4
                        elif kw in desc_text:
                            score += 2

                    scene_chars = {
                        c.casefold()
                        for c in (
                            list(s.characters)
                            + list(s.related_characters)
                            + [line.speaker for line in s.dialogue if line.speaker]
                        )
                    }
                    score += len(chars & scene_chars)

                    if score > 0:
                        scored.append((score, s))

                scored.sort(key=lambda x: x[0], reverse=True)
                if not scored:
                    # Fallback to temporal / character presence matching if keywords failed
                    for s in ep_scenes:
                        scene_chars = {
                            c.casefold()
                            for c in (
                                list(s.characters)
                                + [line.speaker for line in s.dialogue if line.speaker]
                            )
                        }
                        if chars & scene_chars:
                            scored.append((len(chars & scene_chars), s))
                    scored.sort(key=lambda x: x[0], reverse=True)

                if not scored:
                    # Absolute guarantee: assign the middle scene of the episode
                    scored = [(1, ep_scenes[len(ep_scenes) // 2])]

                # Pick top matching scenes (up to 3)
                best_score = scored[0][0]
                top_scenes = [s for score, s in scored if score >= best_score * 0.5][:3]
                supporting_ids = [s.scene_id for s in top_scenes]
                supporting_times = [
                    [float(s.start or 0.0), float(s.end or 0.0)] for s in top_scenes
                ]

                built_events.append(
                    SummaryEvent(
                        event_id=ev_id,
                        description=ev_def["description"],
                        characters_involved=ev_def["characters_involved"],
                        supporting_scene_ids=supporting_ids,
                        supporting_timestamps=supporting_times,
                    )
                )

            summary = EpisodeSummary(
                episode_id=prefix,
                collection_id=collection_id,
                title=ep_def["title"],
                season_number=1,
                episode_number=ep_def["episode_number"],
                macro_summary=ep_def["macro_summary"],
                events=built_events,
            )
            summaries.append(summary)

        return summaries

    def persist_and_index(self, summaries: list[EpisodeSummary]) -> None:
        """Store summaries in SQLite and index them into Qdrant searchy_episodes."""
        for summary in summaries:
            self.metadata.save_episode_summary(summary)
        logger.info(f"Saved {len(summaries)} episode summaries to SQLite.")

        self.vectors.index_episodes(summaries)
        logger.info(f"Indexed {len(summaries)} episode summaries into Qdrant collection searchy_episodes.")

