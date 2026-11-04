from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from searchy.domain import Candidate, Scene

TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Conservative tokenization for lexical search."""
    return [w.lower() for w in TOKEN_PATTERN.findall(text) if len(w) > 1]


class BM25Index:
    """Okapi BM25 index over multimodal scene documents."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_len: dict[str, int] = {}
        self.avg_doc_len: float = 0.0
        self.doc_freq: dict[str, int] = defaultdict(int)
        self.term_freq: dict[str, dict[str, int]] = {}
        self.exact_corpus: dict[str, str] = {}
        self.scene_metadata: dict[str, dict[str, Any]] = {}
        self.total_docs: int = 0

    def index_scenes(self, scenes: list[Scene]) -> None:
        """Indexes all scenes into the in-memory BM25 index."""
        self.doc_len.clear()
        self.doc_freq.clear()
        self.term_freq.clear()
        self.exact_corpus.clear()
        self.scene_metadata.clear()
        self.total_docs = len(scenes)

        if self.total_docs == 0:
            self.avg_doc_len = 0.0
            return

        total_length = 0

        for scene in scenes:
            sid = scene.scene_id
            # Build unified lexical document: visual caption + summary + speaker-attributed dialogue
            dialogue_parts = [
                f"{d.speaker or 'UNKNOWN'}: {d.text}"
                for d in scene.dialogue
            ]
            doc_text = (
                f"{scene.description or ''} "
                f"{scene.scene_summary or ''} "
                f"{' '.join(dialogue_parts)}"
            )

            tokens = tokenize(doc_text)
            self.doc_len[sid] = len(tokens)
            total_length += len(tokens)

            tf = Counter(tokens)
            self.term_freq[sid] = tf

            for term in tf:
                self.doc_freq[term] += 1

            self.exact_corpus[sid] = doc_text.lower()
            self.scene_metadata[sid] = {
                "collection_id": scene.collection_id,
                "episode_id": scene.episode_id,
                "start": scene.start,
                "end": scene.end,
                "related_character_ids": scene.related_character_ids,
                "visual_characters": scene.visual_characters,
            }

        self.avg_doc_len = total_length / self.total_docs if self.total_docs else 0.0

    def idf(self, term: str) -> float:
        """Standard Robertson-Spärck Jones IDF."""
        df = self.doc_freq.get(term, 0)
        if df == 0:
            return 0.0
        return math.log(1.0 + (self.total_docs - df + 0.5) / (df + 0.5))

    def search(
        self,
        query: str,
        limit: int = 50,
        collection_id: str | None = None,
        character_ids: list[str] | None = None,
    ) -> list[Candidate]:
        """Searches the index using Okapi BM25 and returns ranked Candidate objects."""
        if self.total_docs == 0:
            return []

        q_lower = query.lower()
        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        # Check for quoted exact phrases in query
        quoted_phrases = [
            phrase.lower().strip()
            for phrase in re.findall(r'["“](.+?)["”]', query)
            if phrase.strip()
        ]

        scores: dict[str, float] = defaultdict(float)

        for sid, tf in self.term_freq.items():
            meta = self.scene_metadata[sid]
            if collection_id and meta["collection_id"] != collection_id:
                continue
            if character_ids and not (set(character_ids) & set(meta["related_character_ids"])):
                continue

            doc_len = self.doc_len[sid]
            len_norm = 1.0 - self.b + self.b * (doc_len / self.avg_doc_len) if self.avg_doc_len else 1.0

            bm25_score = 0.0
            matched_terms = []

            for term in q_tokens:
                freq = tf.get(term, 0)
                if freq > 0:
                    matched_terms.append(term)
                    numerator = freq * (self.k1 + 1.0)
                    denominator = freq + self.k1 * len_norm
                    bm25_score += self.idf(term) * (numerator / denominator)

            # Exact phrase match bonus
            exact_bonus = 0.0
            raw_doc = self.exact_corpus[sid]
            for phrase in quoted_phrases:
                if phrase in raw_doc:
                    exact_bonus += 5.0

            total_score = bm25_score + exact_bonus
            if total_score > 0.0:
                scores[sid] = total_score

        if not scores:
            return []

        # Normalize scores to [0.0, 1.0] relative to top match
        max_score = max(scores.values())
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]

        candidates = []
        for sid, raw_s in ranked:
            norm_score = raw_s / max_score if max_score > 0 else 0.0
            candidates.append(
                Candidate(
                    scene_id=sid,
                    score=norm_score,
                    channel="sparse",
                    evidence=[f"BM25 lexical match (score={norm_score:.3f})"],
                )
            )

        return candidates

