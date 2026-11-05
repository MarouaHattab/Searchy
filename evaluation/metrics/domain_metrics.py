"""Domain-specific evaluation metrics for Searchy Multimodal GraphRAG."""

from __future__ import annotations

import re
from typing import Any, Sequence

from searchy.core import Settings
from searchy.models.verifier import ClaimVerifier


def _normalize_tokens(text: str) -> set[str]:
    """Tokenize and normalize text for lexical evaluation."""
    stopwords = {
        "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "with",
        "by", "from", "up", "about", "into", "over", "after", "is", "are", "was",
        "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "that", "this", "these", "those", "it", "its", "they", "them", "their",
    }
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in stopwords}


def compute_f1_score(prediction: str, ground_truth: str) -> dict[str, float]:
    """Compute token-level precision, recall, and F1 score."""
    pred_tokens = _normalize_tokens(prediction)
    gt_tokens = _normalize_tokens(ground_truth)
    if not pred_tokens or not gt_tokens:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    common = pred_tokens & gt_tokens
    if not common:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    precision = len(common) / len(pred_tokens)
    recall = len(common) / len(gt_tokens)
    f1 = 2 * (precision * recall) / (precision + recall)
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def evaluate_retrieval_ranking(
    results: Sequence[dict[str, Any]],
    target_episode: str,
    target_keywords: Sequence[str],
) -> dict[str, float]:
    """Evaluate retrieval ranking: MRR, Hit@1, Hit@3, Hit@5.

    A result is considered relevant if its episode matches target_episode or
    its text/snippet overlaps target keywords significantly.
    """
    if not results:
        return {"mrr": 0.0, "hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0}

    first_rank: int | None = None
    target_ep_clean = target_episode.lower().strip()
    norm_kw = {k.lower() for k in target_keywords}

    for idx, item in enumerate(results, start=1):
        ep_match = (
            target_ep_clean in item.get("episode_id", "").lower()
            or target_ep_clean in item.get("label", "").lower()
            or target_ep_clean in item.get("scene_id", "").lower()
        )
        text_content = (
            item.get("snippet", "") + " " + item.get("description", "") + " " + item.get("text", "")
        ).lower()
        kw_hits = sum(1 for kw in norm_kw if kw in text_content)
        kw_match = kw_hits >= max(1, len(norm_kw) // 2)

        if ep_match or kw_match:
            first_rank = idx
            break

    if first_rank is None:
        return {"mrr": 0.0, "hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0}

    return {
        "mrr": round(1.0 / first_rank, 4),
        "hit@1": 1.0 if first_rank == 1 else 0.0,
        "hit@3": 1.0 if first_rank <= 3 else 0.0,
        "hit@5": 1.0 if first_rank <= 5 else 0.0,
    }


def evaluate_citation_alignment(
    sources: Sequence[dict[str, Any]],
    target_episode: str,
    target_keywords: Sequence[str],
) -> dict[str, Any]:
    """Evaluate grounding quality and citation precision of cited sources."""
    if not sources:
        return {
            "citation_count": 0,
            "relevant_citations": 0,
            "citation_precision": 0.0,
            "episode_cited": False,
        }

    target_ep_clean = target_episode.lower().strip()
    norm_kw = {k.lower() for k in target_keywords}
    relevant_count = 0
    episode_cited = False

    for src in sources:
        label = src.get("label", "").lower()
        scene_id = src.get("scene_id", "").lower()
        text_content = (
            src.get("snippet", "") + " " + src.get("description", "") + " " + src.get("text", "")
        ).lower()

        ep_match = target_ep_clean in label or target_ep_clean in scene_id
        if ep_match:
            episode_cited = True

        kw_hits = sum(1 for kw in norm_kw if kw in text_content)
        kw_match = kw_hits >= max(1, len(norm_kw) // 3)

        if ep_match or kw_match:
            relevant_count += 1

    precision = relevant_count / len(sources) if sources else 0.0
    return {
        "citation_count": len(sources),
        "relevant_citations": relevant_count,
        "citation_precision": round(precision, 4),
        "episode_cited": episode_cited,
    }


def evaluate_claim_verification(
    answer: str,
    sources: Sequence[dict[str, Any]],
    verifier: ClaimVerifier | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run Searchy's Claim Verification Engine on the generated answer.

    Deconstructs the answer into factual claims, verifies entailment against
    evidence passages, and computes entailment rate.
    """
    if not answer or not sources:
        return {
            "total_claims": 0,
            "verified_claims": 0,
            "unverified_claims": 0,
            "refuted_claims": 0,
            "entailment_rate": 0.0,
            "claims": [],
        }

    active_verifier = verifier or ClaimVerifier(settings or Settings())
    _text, _warnings, results = active_verifier.verify_answer(answer, list(sources))

    total = len(results)
    verified = sum(1 for c in results if c.is_verified)
    unverified = sum(1 for c in results if not c.is_verified)
    refuted = sum(1 for c in results if c.rejection_reason and "contradict" in c.rejection_reason.lower())
    rate = verified / total if total > 0 else (1.0 if not _warnings else 0.0)

    return {
        "total_claims": total,
        "verified_claims": verified,
        "unverified_claims": unverified,
        "refuted_claims": refuted,
        "entailment_rate": round(rate, 4),
        "claims": [
            {
                "claim": c.claim_text,
                "is_verified": c.is_verified,
                "rejection_reason": c.rejection_reason,
                "citations": c.citations,
            }
            for c in results
        ],
    }
