"""Speaker attribution and screenplay sequence alignment engine.

Aligns canonical screenplay dialogue with timestamped subtitle lines, assigns
speakers only when supported by verifiable sequence and textual evidence, and
strictly preserves UNKNOWN when attribution is uncertain.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5


def stable_id(value: str) -> str:
    """Deterministic UUID5 for entity references."""
    return str(uuid5(NAMESPACE_URL, value))


# Explicit canonical character map. Unknown or choral speakers map to None.
CANONICAL_CHARACTERS: dict[str, str] = {
    # Main cast
    "ross geller": "Ross Geller",
    "rachel green": "Rachel Green",
    "monica geller": "Monica Geller",
    "chandler bing": "Chandler Bing",
    "joey tribbiani": "Joey Tribbiani",
    "phoebe buffay": "Phoebe Buffay",
    "ross": "Ross Geller",
    "rachel": "Rachel Green",
    "monica": "Monica Geller",
    "chandler": "Chandler Bing",
    "joey": "Joey Tribbiani",
    "phoebe": "Phoebe Buffay",
    # Recurring Season 1
    "joey tribbiani sr": "Joey Tribbiani Sr.",
    "joey tribbiani sr.": "Joey Tribbiani Sr.",
    "joey sr": "Joey Tribbiani Sr.",
    "joey sr.": "Joey Tribbiani Sr.",
    "mr. tribbiani": "Joey Tribbiani Sr.",
    "gloria tribbiani": "Gloria Tribbiani",
    "mrs. tribbiani": "Gloria Tribbiani",
    "carol willick": "Carol Willick",
    "carol": "Carol Willick",
    "susan bunch": "Susan Bunch",
    "susan": "Susan Bunch",
    "barry farber": "Barry Farber",
    "barry": "Barry Farber",
    "judy geller": "Judy Geller",
    "mrs. geller": "Judy Geller",
    "jack geller": "Jack Geller",
    "mr. geller": "Jack Geller",
    "janice": "Janice Litman-Goralnik",
    "janice litman goralnik": "Janice Litman-Goralnik",
    "gunther": "Gunther",
    "ursula": "Ursula Buffay",
    "ursula buffay": "Ursula Buffay",
    "paolo": "Paolo",
    "david": "David",
    "mr. heckles": "Mr. Heckles",
    "mindy": "Mindy Hunter",
    "mindy hunter": "Mindy Hunter",
    "fun bobby": "Fun Bobby",
    "bobby": "Fun Bobby",
    "paul": "Paul the Wine Guy",
    "paul the wine guy": "Paul the Wine Guy",
    "alan": "Alan",
    "ethan": "Ethan",
    "aurora": "Aurora",
    "nora tyler bing": "Nora Tyler Bing",
    "mrs. bing": "Nora Tyler Bing",
    "roger": "Roger",
    "lydia": "Lydia",
    "jill": "Jill Goodacre",
    "jill goodacre": "Jill Goodacre",
    "max": "Max",
}

NON_CHARACTER_SPEAKERS: set[str] = {
    "#all#",
    "all",
    "both",
    "group",
    "scene directions",
    "na",
    "crowd",
    "everyone",
    "everybody",
    "voice",
    "announcer",
    "commercial",
}

CONTRACTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bc'mon\b", re.I), "come on"),
    (re.compile(r"\bgonna\b", re.I), "going to"),
    (re.compile(r"\bwanna\b", re.I), "want to"),
    (re.compile(r"\bi'm\b", re.I), "i am"),
    (re.compile(r"\byou're\b", re.I), "you are"),
    (re.compile(r"\bhe's\b", re.I), "he is"),
    (re.compile(r"\bshe's\b", re.I), "she is"),
    (re.compile(r"\bit's\b", re.I), "it is"),
    (re.compile(r"\bthere's\b", re.I), "there is"),
    (re.compile(r"\bthat's\b", re.I), "that is"),
    (re.compile(r"\bwhat's\b", re.I), "what is"),
    (re.compile(r"\bwho's\b", re.I), "who is"),
    (re.compile(r"\bdon't\b", re.I), "do not"),
    (re.compile(r"\bdoesn't\b", re.I), "does not"),
    (re.compile(r"\bdidn't\b", re.I), "did not"),
    (re.compile(r"\bcan't\b", re.I), "cannot"),
    (re.compile(r"\bwon't\b", re.I), "will not"),
    (re.compile(r"\bhairpiece\b", re.I), "hair piece"),
]

FILLERS: set[str] = {
    "a", "an", "the", "and", "or", "but", "if", "in", "on", "at", "to", "for",
    "with", "by", "of", "it", "its", "that", "this", "there", "here", "i", "you",
    "he", "she", "we", "they", "me", "him", "her", "us", "them", "my", "your",
    "his", "their", "our", "is", "am", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "can", "could", "will",
    "would", "shall", "should", "not", "no", "yes", "yeah", "yep", "nope", "oh",
    "ah", "uh", "um", "ok", "okay", "hey", "hi", "hello", "well", "right", "good",
    "so", "just", "like", "what", "who", "when", "where", "why", "how", "go",
    "going", "come", "see", "all", "now", "then", "up", "out", "one", "got", "get"
}


def extract_subtitle_prefix(text: str) -> tuple[str | None, str]:
    """Extracts explicit speaker prefix if present at start of subtitle (e.g. 'CHANDLER: What...?')."""
    if text.strip().startswith("-"):
        return None, text
    m = re.match(r"^\s*([A-Za-z][A-Za-z\s\.\']{1,25}):\s*(.+)$", text)
    if m:
        prefix = m.group(1).strip()
        body = m.group(2).strip()
        return prefix, body
    return None, text


def normalize_tokens(text: str) -> list[str]:
    """Conservative token normalization for sequence matching.
    Preserves original text; this is used only for distance computation.
    """
    cleaned = text.lower()
    # Remove bracketed sound effects, stage cues, or parentheticals
    cleaned = re.sub(r"\[.*?\]|\(.*?\)", " ", cleaned)
    # Strip speaker prefixes if subtitle already has them embedded (e.g. "MONICA: ...")
    cleaned = re.sub(r"^[a-z\s]+:\s*", "", cleaned)
    # Expand contractions
    for pattern, replacement in CONTRACTIONS:
        cleaned = pattern.sub(replacement, cleaned)
    # Remove punctuation
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return [w for w in cleaned.split() if w]


@dataclass
class SpeakerAttribution:
    line_id: str
    episode_id: str
    scene_id: str
    start: float
    end: float
    subtitle_text: str
    speaker: str | None
    speaker_id: str | None
    confidence: float
    category: str  # "HIGH", "MEDIUM", "LOW"
    reason: str
    screenplay_ref: str | None = None
    matched_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpeakerAligner:
    """Multi-stage sequence aligner linking screenplay utterances with subtitle cards."""

    def __init__(
        self,
        screenplay_path: str | Path,
        collection_id: str = "friends",
        high_threshold: float = 0.90,
        med_threshold: float = 0.70,
    ):
        self.screenplay_path = Path(screenplay_path)
        self.collection_id = collection_id
        self.high_threshold = high_threshold
        self.med_threshold = med_threshold
        self._screenplay_cache: dict[int, list[dict[str, Any]]] = {}
        self._load_screenplay()

    def _load_screenplay(self) -> None:
        if not self.screenplay_path.is_file():
            raise FileNotFoundError(f"Screenplay file not found: {self.screenplay_path}")
        with open(self.screenplay_path, "r", encoding="utf-8") as f:
            all_lines = json.load(f)
        for line in all_lines:
            ep = int(line["episode"])
            if ep not in self._screenplay_cache:
                self._screenplay_cache[ep] = []
            self._screenplay_cache[ep].append(line)

    def canonicalize_name(self, raw_speaker: str | None) -> tuple[str | None, str | None]:
        """Maps raw screenplay speaker to canonical name and stable ID."""
        if not raw_speaker:
            return None, None
        key = " ".join(raw_speaker.casefold().strip().split())
        if key in NON_CHARACTER_SPEAKERS:
            return None, None
        canonical = CANONICAL_CHARACTERS.get(key)
        if not canonical:
            # Check prefix match for minor characters, strictly protecting generational suffixes
            suffix_tokens = {"sr", "sr.", "jr", "jr.", "senior", "junior", "dad", "father", "mom", "mother"}
            key_tokens = set(key.split())
            if not (key_tokens & suffix_tokens):
                for alias, target in CANONICAL_CHARACTERS.items():
                    if key == alias or key.startswith(alias + " "):
                        canonical = target
                        break
        if not canonical:
            # If not in canonical catalog, preserve as-is if not non-character
            canonical = raw_speaker.strip()
        cid = stable_id(f"character:{self.collection_id}:{' '.join(canonical.casefold().split())}")
        return canonical, cid

    def align_episode(
        self,
        episode_number: int,
        subtitle_scenes: list[dict[str, Any]],
        window_size: int = 6,
    ) -> list[SpeakerAttribution]:
        """Aligns subtitle dialogue lines of an episode monotonically against screenplay.

        Args:
            episode_number: Episode 1..24
            subtitle_scenes: List of Scene dicts in chronological order.
            window_size: Forward search lookahead window in the screenplay sequence.
        """
        screenplay = self._screenplay_cache.get(episode_number, [])
        # Filter out purely non-dialogue scene directions for alignment targets
        utterances = [
            u
            for u in screenplay
            if u.get("speaker", "").strip().lower() not in {"scene directions", "na"}
        ]

        # Extract all subtitle lines in chronological order with scene context
        flat_subs = []
        for scene in subtitle_scenes:
            s_id = scene.get("scene_id", "")
            ep_id = scene.get("episode_id", f"1x{episode_number:02d}")
            for d in scene.get("dialogue", []):
                flat_subs.append(
                    {
                        "scene_id": s_id,
                        "episode_id": ep_id,
                        "start": float(d["start"]),
                        "end": float(d["end"]),
                        "text": d["text"],
                        "line_id": f"{s_id}:{d['start']:.3f}-{d['end']:.3f}",
                    }
                )

        # Monotonic sequence alignment state
        curr_u_idx = 0
        attributions: list[SpeakerAttribution] = []

        for sub in flat_subs:
            raw_text = sub["text"]
            prefix_speaker, body_text = extract_subtitle_prefix(raw_text)
            sub_toks = normalize_tokens(raw_text)

            # 1. Reject empty, pure sound effect, or stage noise
            if not sub_toks:
                attributions.append(
                    SpeakerAttribution(
                        line_id=sub["line_id"],
                        episode_id=sub["episode_id"],
                        scene_id=sub["scene_id"],
                        start=sub["start"],
                        end=sub["end"],
                        subtitle_text=raw_text,
                        speaker=None,
                        speaker_id=None,
                        confidence=0.0,
                        category="LOW",
                        reason="Ambient audio, sound effect, or non-verbal subtitle",
                    )
                )
                continue

            # 1b. Reject composite multi-speaker cards (e.g. "- Hi. - Hey." or "ROSS: ... RACHEL: ...")
            is_composite = (
                len(re.findall(r"(?:^|\s)-\s*", raw_text)) >= 2
                or len(re.findall(r"\b[A-Za-z]{2,}:", raw_text)) >= 2
                or (raw_text.strip().startswith("-") and re.search(r"\b[A-Za-z]{2,}:", raw_text) is not None)
            )
            if is_composite:
                attributions.append(
                    SpeakerAttribution(
                        line_id=sub["line_id"],
                        episode_id=sub["episode_id"],
                        scene_id=sub["scene_id"],
                        start=sub["start"],
                        end=sub["end"],
                        subtitle_text=raw_text,
                        speaker=None,
                        speaker_id=None,
                        confidence=0.50,
                        category="LOW",
                        reason="Composite multi-speaker turn in single subtitle card",
                    )
                )
                continue

            # 2. Search candidates within lookahead window
            distinctive_toks = [w for w in sub_toks if w not in FILLERS]
            is_anchor = (
                (len(sub_toks) >= 5 and len(distinctive_toks) >= 2)
                or (len(sub_toks) >= 4 and len(distinctive_toks) >= 3)
            )

            # Short / generic phrases: narrow search window
            if len(sub_toks) == 1:
                lookahead = 2
            elif len(sub_toks) <= 2:
                lookahead = 3
            elif is_anchor:
                lookahead = 18
            else:
                lookahead = 8

            lookahead_end = min(curr_u_idx + lookahead, len(utterances))
            lookback_start = max(0, curr_u_idx - 1)

            # Rank candidate matches from distinct characters
            scored_candidates = []

            for u_idx in range(lookback_start, lookahead_end):
                if len(sub_toks) <= 2 and u_idx > curr_u_idx + 1:
                    continue

                utt = utterances[u_idx]
                u_toks = normalize_tokens(utt.get("text", ""))
                if not u_toks:
                    continue

                matched_tokens = sum(1 for w in sub_toks if w in u_toks)
                containment = matched_tokens / len(sub_toks)

                sub_str = " ".join(sub_toks)
                utt_str = " ".join(u_toks)
                seq_ratio = difflib.SequenceMatcher(None, sub_str, utt_str).ratio()

                if sub_str in utt_str:
                    score = 0.85 * containment + 0.15 * 1.0
                else:
                    score = 0.70 * containment + 0.30 * seq_ratio

                step_gap = max(0, u_idx - curr_u_idx)
                if step_gap > 3 and not is_anchor:
                    score -= 0.05 * (step_gap - 3)

                if score > 0.40:
                    scored_candidates.append({
                        "u_idx": u_idx,
                        "utt": utt,
                        "score": score,
                        "containment": containment,
                        "seq_ratio": seq_ratio,
                        "step_gap": step_gap,
                    })

            # Sort descending by score
            scored_candidates.sort(key=lambda c: c["score"], reverse=True)

            best_match = scored_candidates[0] if scored_candidates else None
            best_score = best_match["score"] if best_match else 0.0
            best_utt = best_match["utt"] if best_match else None
            best_u_idx = best_match["u_idx"] if best_match else curr_u_idx

            # 3. Check for Margin / Competing Candidates
            # If second-best candidate from a DIFFERENT character is within 0.12 margin -> ambiguous!
            is_ambiguous = False
            if best_match and len(scored_candidates) > 1:
                best_char, _ = self.canonicalize_name(best_utt.get("speaker"))
                for second in scored_candidates[1:]:
                    sec_char, _ = self.canonicalize_name(second["utt"].get("speaker"))
                    if sec_char and sec_char != best_char and second["score"] >= 0.70:
                        margin = best_score - second["score"]
                        if margin < 0.12:
                            is_ambiguous = True
                            break

            # 4. Check Subtitle Speaker Prefix
            prefix_canonical, prefix_cid = None, None
            if prefix_speaker:
                prefix_canonical, prefix_cid = self.canonicalize_name(prefix_speaker)

            # 5. Calibration Policies
            # 5a. If subtitle explicitly names speaker:
            if prefix_canonical and not is_composite:
                if best_match and self.canonicalize_name(best_utt.get("speaker"))[0] == prefix_canonical:
                    # Verified agreement between CC speaker prefix and screenplay sequence
                    best_score = max(best_score, 0.95)
                elif len(sub_toks) <= 3:
                    # Short line where token match was coincidental: prefer explicit CC speaker prefix!
                    best_score = 0.85
                    best_utt = {"speaker": prefix_canonical, "scene": 0, "utterance": 0, "text": body_text}
                elif best_score < 0.70:
                    # Low screenplay match, but CC has explicit valid character name
                    best_score = 0.85
                    best_utt = {"speaker": prefix_canonical, "scene": 0, "utterance": 0, "text": body_text}
                else:
                    best_score = min(best_score, 0.55)

            # 5b. Standalone 1-word lines: e.g. "What...?", "Hey.", "No.", "There."
            if len(sub_toks) == 1:
                if prefix_canonical:
                    best_score = min(best_score, 0.85)
                else:
                    best_score = min(best_score, 0.50)

            # 5c. 2-word lines: e.g. "Thank you.", "That was..."
            elif len(sub_toks) <= 2:
                is_continuation = (best_u_idx == curr_u_idx)
                if not is_continuation:
                    best_score = min(best_score, 0.55)
                else:
                    best_score = min(best_score, 0.80)

            # 5d. Generic conversational idioms with < 2 distinctive tokens
            # e.g. "Oh, my God.", "Yeah, I'm fine.", "No, no, no.", "Here we go."
            elif len(distinctive_toks) < 2:
                if best_match:
                    if best_match["seq_ratio"] < 0.70:
                        if best_match["step_gap"] == 0:
                            best_score = min(best_score, 0.85)
                        else:
                            best_score = min(best_score, 0.75)

            # 5e. Ambiguity penalty: if two characters competed closely
            if is_ambiguous:
                best_score = min(best_score, 0.55)

            # 6. Apply Final Categorization and State Update
            category = "LOW"
            assigned_speaker = None
            assigned_id = None
            best_reason = "No sequence match found"

            if best_utt and best_score >= self.med_threshold:
                raw_sp = best_utt.get("speaker")
                canonical_sp, canonical_cid = self.canonicalize_name(raw_sp)

                if canonical_sp is None:
                    category = "LOW"
                    best_reason = f"Screenplay denotes non-character: '{raw_sp}'"
                else:
                    if best_score >= self.high_threshold:
                        category = "HIGH"
                        if best_u_idx >= curr_u_idx:
                            curr_u_idx = best_u_idx
                    else:
                        category = "MEDIUM"
                        if best_u_idx >= curr_u_idx and len(sub_toks) >= 3:
                            curr_u_idx = best_u_idx
                    assigned_speaker = canonical_sp
                    assigned_id = canonical_cid
                    best_reason = f"Aligned with S01E{episode_number:02d} Scn{best_utt.get('scene', 0)} Utt{best_utt.get('utterance', 0)}"
            else:
                best_reason = f"Confidence below threshold ({best_score:.2f} < {self.med_threshold})"

            sp_ref = None
            matched_snippet = None
            if best_utt:
                sp_ref = f"S01E{episode_number:02d}:Scn{best_utt.get('scene', 0)}:Utt{best_utt.get('utterance', 0)}"
                matched_snippet = f"{best_utt.get('speaker')}: {best_utt.get('text', '')[:80]}"

            attributions.append(
                SpeakerAttribution(
                    line_id=sub["line_id"],
                    episode_id=sub["episode_id"],
                    scene_id=sub["scene_id"],
                    start=sub["start"],
                    end=sub["end"],
                    subtitle_text=sub["text"],
                    speaker=assigned_speaker,
                    speaker_id=assigned_id,
                    confidence=round(best_score, 4),
                    category=category,
                    reason=best_reason,
                    screenplay_ref=sp_ref,
                    matched_text=matched_snippet,
                )
            )

        return attributions
