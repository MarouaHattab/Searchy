import re
from dataclasses import dataclass, field
from typing import Any

from searchy.core import Settings


@dataclass
class ClaimVerificationResult:
    claim_text: str
    citations: list[int]
    is_verified: bool
    rejection_reason: str | None = None
    entailment_score: float = 1.0
    supporting_sources: list[dict] = field(default_factory=list)


# Character alias mapping for accurate attribution checking
CHARACTER_ALIASES = {
    "rachel": ["rachel", "rachel green"],
    "monica": ["monica", "monica geller"],
    "phoebe": ["phoebe", "phoebe buffay"],
    "joey": ["joey", "joey tribbiani"],
    "chandler": ["chandler", "chandler bing"],
    "ross": ["ross", "ross geller"],
    "gunther": ["gunther", "barista"],
    "janice": ["janice"],
    "carol": ["carol", "carol willick"],
    "susan": ["susan", "susan bunch"],
    "paolo": ["paolo"],
    "barry": ["barry", "barry farber"],
    "mindy": ["mindy"],
    "paul": ["paul", "paul the wine guy"],
    "ursula": ["ursula", "ursula buffay"],
    "marcel": ["marcel", "monkey"],
    "ben": ["ben", "baby ben"],
}

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for",
    "with", "and", "or", "but", "so", "as", "by", "from", "that", "this", "it",
    "they", "he", "she", "his", "her", "their", "of", "about", "into", "out",
    "who", "what", "which", "how", "when", "where", "does", "did", "have", "has",
    "had", "been", "being", "there", "season", "episode", "described", "scene",
    "scenes", "will", "would", "can", "could", "should", "not", "no", "if",
}

GENERIC_WORDS = {
    "in", "after", "during", "before", "while", "when", "where", "what", "which",
    "how", "who", "there", "here", "this", "that", "these", "those", "season",
    "episode", "scene", "based", "according", "overall", "furthermore", "however",
    "although", "the", "a", "an", "all", "some", "both", "one", "two", "three",
    "first", "second", "third", "later", "meanwhile", "additionally", "similarly",
    "following", "initially", "eventually", "throughout", "finally", "subsequently",
    "despite", "instead", "conversely", "besides", "moreover", "ultimately",
    "specifically", "upon", "since", "until", "though", "having", "being",
    "with", "at", "by", "from", "as", "afterwards", "outside", "inside",
    "early", "earlier", "another", "other", "many", "most", "several", "various",
    "important", "significant", "certain", "indeed", "naturally", "clearly",
    "finale", "moment", "moments", "interaction", "interactions", "conversation",
    "conversations", "evolution", "culminates", "connection", "affection",
}
GENERIC_START_WORDS = GENERIC_WORDS

NARRATIVE_WORDS = {
    "relationship", "relationships", "intimate", "progress", "progresses", "progression",
    "instance", "example", "confidence", "culmination", "culminates",
    "evolution", "evolve", "evolves", "show", "shows", "shown", "showing", "stage", "stages",
    "setting", "engaged", "deliberates", "deliberate", "decides", "decide", "accompanied",
    "accompanies", "depart", "departs", "deeply", "celebrate", "celebrates", "connection",
    "affection", "moments", "moment", "interactions", "interaction", "conversation", "conversations",
    "expressing", "expresses", "express", "expressed", "admits", "admit", "admitted", "reveals",
    "reveal", "revealed", "deciding", "pursue", "pursues", "pursuing", "romance", "feelings",
    "between", "among", "them", "such", "sharing", "shares", "shared", "occurs", "occur",
    "titled", "title", "status", "presence", "inadvertently", "inadvertent", "tender",
    "because", "their", "another", "other", "develops", "development", "arc", "timeline",
    "milestone", "manner", "intimately", "gradually", "eventually",
}



class ClaimVerifier:
    def __init__(self, settings: Settings, llm_verifier: Any = None):
        self.settings = settings
        self.llm_verifier = llm_verifier

    @staticmethod
    def extract_claims(text: str) -> list[tuple[str, list[int]]]:
        """Split text into sentences/items and extract attached [1], [2] citation markers."""
        raw_items = re.split(r"(?:(?<=[.!?])\s+(?=[A-Z0-9\[])|\n+)", text.strip())
        claims = []
        for raw in raw_items:
            s = raw.strip()
            if not s:
                continue
            clean_s = re.sub(r"^[*\-•\d.]+\s*", "", s).strip()
            if not clean_s:
                continue
            # Ignore pure section headers ending with a colon that have no citations
            if clean_s.endswith(":") and not re.search(r"\[\d+\]", clean_s):
                continue
            citations = [int(n) for n in re.findall(r"\[(\d+)\]", clean_s)]
            cleaned = re.sub(r"\[\d+\]", "", clean_s).strip()
            if cleaned:
                claims.append((clean_s, citations))
        return claims

    def verify_claim(
        self,
        claim_text: str,
        citations: list[int],
        sources: list[dict],
    ) -> ClaimVerificationResult:
        """Verify whether a single claim is strictly entailed and properly attributed by cited sources."""
        available_numbers = {s.get("number") for s in sources if s.get("number") is not None}

        # 1. Check citation presence & validity
        if not citations:
            return ClaimVerificationResult(
                claim_text=claim_text,
                citations=[],
                is_verified=False,
                rejection_reason="No citation provided for factual claim",
                entailment_score=0.0,
            )

        invalid_citations = [c for c in citations if c not in available_numbers]
        if invalid_citations:
            return ClaimVerificationResult(
                claim_text=claim_text,
                citations=citations,
                is_verified=False,
                rejection_reason=f"Invalid citation(s) {invalid_citations} not present in sources",
                entailment_score=0.0,
            )

        cited_sources = [s for s in sources if s.get("number") in citations]

        # Extract all text from cited sources
        source_texts = []
        for src in cited_sources:
            snippet = src.get("snippet", "")
            seen = src.get("seen", "")
            said = src.get("said", "")
            desc = src.get("description", "")
            raw_text = src.get("text", "")
            label = src.get("label", "")
            source_texts.append(f"{label} {snippet} {seen} {said} {desc} {raw_text}".lower())

        combined_source_text = " ".join(source_texts)

        # 2. Character Attribution Check with Word Boundaries
        claim_lower = claim_text.lower()
        clean_claim = re.sub(r"\[[^\]]+\]", "", claim_lower).strip()

        for canonical_name, aliases in CHARACTER_ALIASES.items():
            # Check if this character is explicitly mentioned in the claim as a whole word
            if any(re.search(rf"\b{re.escape(alias)}\b", clean_claim) for alias in aliases):
                # Verify that the character appears in the cited sources as a whole word
                char_in_source = any(
                    re.search(rf"\b{re.escape(alias)}\b", combined_source_text)
                    for alias in aliases
                )
                if not char_in_source:
                    return ClaimVerificationResult(
                        claim_text=claim_text,
                        citations=citations,
                        is_verified=False,
                        rejection_reason=f"Character '{canonical_name.title()}' is asserted in claim but absent from cited source(s) {citations}",
                        entailment_score=0.1,
                        supporting_sources=cited_sources,
                    )

        # 2.5 Named Entity & Proper Noun Verification
        alias_set = {a for aliases in CHARACTER_ALIASES.values() for a in aliases}
        tokens = re.findall(r"\b[A-Za-z0-9']+\b", claim_text)
        if tokens:
            proper_candidates = []
            for t in tokens:
                tok_lower = t.lower()
                if (
                    t[0].isupper()
                    and len(t) >= 4
                    and tok_lower not in GENERIC_WORDS
                    and tok_lower not in alias_set
                    and tok_lower not in STOPWORDS
                ):
                    proper_candidates.append(t)

            for token in proper_candidates:
                tok_lower = token.lower()
                if tok_lower in alias_set or tok_lower in STOPWORDS:
                    continue
                if not re.search(rf"\b{re.escape(tok_lower)}\b", combined_source_text):
                    return ClaimVerificationResult(
                        claim_text=claim_text,
                        citations=citations,
                        is_verified=False,
                        rejection_reason=f"Named entity '{token}' is asserted in claim but absent from cited source(s) {citations}",
                        entailment_score=0.1,
                        supporting_sources=cited_sources,
                    )

        # 3. Semantic Entailment & Key Predicate Verification
        words = re.findall(r"[a-z0-9']+", clean_claim)
        content_words = [
            w for w in words
            if w not in STOPWORDS
            and w not in GENERIC_WORDS
            and w not in NARRATIVE_WORDS
            and len(w) > 2
        ]

        if content_words:
            matched_words = [w for w in content_words if w in combined_source_text]
            overlap_ratio = len(matched_words) / len(content_words)
            if overlap_ratio < 0.30 and len(matched_words) < 2:
                return ClaimVerificationResult(
                    claim_text=claim_text,
                    citations=citations,
                    is_verified=False,
                    rejection_reason=(
                        f"Claim predicates have insufficient evidence in cited sources ({overlap_ratio*100:.0f}% overlap). "
                        f"Unverified terms: {[w for w in content_words if w not in matched_words][:4]}"
                    ),
                    entailment_score=round(overlap_ratio, 2),
                    supporting_sources=cited_sources,
                )

        return ClaimVerificationResult(
            claim_text=claim_text,
            citations=citations,
            is_verified=True,
            entailment_score=1.0,
            supporting_sources=cited_sources,
        )

    def verify_answer(
        self,
        answer_text: str,
        sources: list[dict],
    ) -> tuple[str, list[str], list[ClaimVerificationResult]]:
        """
        Verify all claims in an answer against the provided sources.
        Returns:
            - filtered_or_qualified_text
            - list of warnings
            - list of ClaimVerificationResult objects
        """
        claims = self.extract_claims(answer_text)
        if not claims:
            return answer_text, [], []

        verified_claims = []
        unverified_claims = []
        results = []
        warnings = []

        for sentence, citations in claims:
            res = self.verify_claim(sentence, citations, sources)
            results.append(res)
            if res.is_verified:
                verified_claims.append(sentence)
            else:
                unverified_claims.append(res)

        if unverified_claims:
            for unv in unverified_claims:
                warnings.append(
                    f"Claim rejected: \"{unv.claim_text}\" ({unv.rejection_reason})"
                )

        if verified_claims:
            verified_text = " ".join(verified_claims)
        else:
            verified_text = "The indexed Season 1 evidence does not support the requested claims."
            warnings.append("All generated claims failed evidence verification.")

        return verified_text, warnings, results
