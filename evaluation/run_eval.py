#!/usr/bin/env python3
"""CLI runner for Searchy Multimodal GraphRAG Research & Benchmark Evaluation Suite."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from searchy.core import Settings
from searchy.models.verifier import ClaimVerifier
from searchy.services.chat import ChatService
from searchy.services.container import Services

from evaluation.metrics.domain_metrics import (
    compute_f1_score,
    evaluate_citation_alignment,
    evaluate_claim_verification,
    evaluate_retrieval_ranking,
)
from evaluation.metrics.ragas_adapter import run_ragas_evaluation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("searchy.evaluation")


def load_benchmark(data_path: Path) -> list[dict[str, Any]]:
    """Load benchmark questions from JSON file."""
    if not data_path.exists():
        raise FileNotFoundError(f"Benchmark file not found at {data_path}")
    with open(data_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_markdown_report(
    summary_stats: dict[str, Any],
    category_stats: dict[str, dict[str, Any]],
    detailed_results: list[dict[str, Any]],
    output_path: Path,
):
    """Generate publication-ready Markdown benchmark report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    num_q = summary_stats["total_questions"]

    lines = [
        "# Searchy Multimodal GraphRAG: Research & Evaluation Benchmark Report",
        "",
        f"**Date Generated**: {date_str}  ",
        f"**Evaluation Scope**: {num_q} Questions across 24 Episodes (Season 1)  ",
        f"**LLM Model**: {summary_stats.get('model', 'nvidia/nemotron-3.5-bolt-e4b')}  ",
        f"**Retrieval Pipeline**: Hybrid (Knowledge Graph + Semantic Vectors + BM25 Lexical)  ",
        "",
        "---",
        "",
        "## 1. Executive Summary: Core Metrics",
        "",
        "This evaluation establishes empirical quality across both **Method A (Standard Ragas Framework)** "
        "and **Method B (Domain-Specific Multimodal Claim Verification & Grounding)**.",
        "",
        "| Metric Dimension | Metric Name | Score | Benchmark Target | Status |",
        "| :--- | :--- | :---: | :---: | :---: |",
        f"| **Method A: Ragas** | Faithfulness | **{summary_stats['ragas']['faithfulness']:.4f}** | ≥ 0.80 | {'✅ PASS' if summary_stats['ragas']['faithfulness'] >= 0.8 else '⚠️ REVIEW'} |",
        f"| **Method A: Ragas** | Answer Relevancy | **{summary_stats['ragas']['answer_relevancy']:.4f}** | ≥ 0.75 | {'✅ PASS' if summary_stats['ragas']['answer_relevancy'] >= 0.75 else '⚠️ REVIEW'} |",
        f"| **Method A: Ragas** | Context Precision | **{summary_stats['ragas']['context_precision']:.4f}** | ≥ 0.70 | {'✅ PASS' if summary_stats['ragas']['context_precision'] >= 0.7 else '⚠️ REVIEW'} |",
        f"| **Method A: Ragas** | Context Recall | **{summary_stats['ragas']['context_recall']:.4f}** | ≥ 0.70 | {'✅ PASS' if summary_stats['ragas']['context_recall'] >= 0.7 else '⚠️ REVIEW'} |",
        f"| **Method B: Domain** | Claim Entailment Rate | **{summary_stats['domain']['claim_entailment_rate']:.4f}** | ≥ 0.85 | {'✅ PASS' if summary_stats['domain']['claim_entailment_rate'] >= 0.85 else '⚠️ REVIEW'} |",
        f"| **Method B: Domain** | Citation Precision | **{summary_stats['domain']['citation_precision']:.4f}** | ≥ 0.70 | {'✅ PASS' if summary_stats['domain']['citation_precision'] >= 0.7 else '⚠️ REVIEW'} |",
        f"| **Method B: Domain** | Target Episode Hit Rate | **{summary_stats['domain']['episode_citation_rate'] * 100:.1f}%** | ≥ 80.0% | {'✅ PASS' if summary_stats['domain']['episode_citation_rate'] >= 0.8 else '⚠️ REVIEW'} |",
        f"| **Method B: Domain** | Mean Reciprocal Rank (MRR) | **{summary_stats['domain']['mrr']:.4f}** | ≥ 0.65 | {'✅ PASS' if summary_stats['domain']['mrr'] >= 0.65 else '⚠️ REVIEW'} |",
        f"| **Method B: Domain** | Lexical Ground Truth F1 | **{summary_stats['domain']['f1']:.4f}** | ≥ 0.50 | {'✅ PASS' if summary_stats['domain']['f1'] >= 0.5 else '⚠️ REVIEW'} |",
        "",
        "---",
        "",
        "## 2. Category Performance Breakdown",
        "",
        "Performance breakdown across the four multimodal query archetypes:",
        "",
        "| Category | Questions | Claim Entailment | Citation Precision | Episode Hit Rate | Ragas Faithfulness | Ragas Relevancy |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for cat, cstats in category_stats.items():
        cq = cstats["count"]
        cer = cstats["claim_entailment_rate"]
        cp = cstats["citation_precision"]
        ehr = cstats["episode_citation_rate"] * 100
        rf = cstats["ragas_faithfulness"]
        rr = cstats["ragas_relevancy"]
        lines.append(
            f"| **{cat.replace('_', ' ').title()}** | {cq} | {cer:.4f} | {cp:.4f} | {ehr:.1f}% | {rf:.4f} | {rr:.4f} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 3. Representative Qualitative Examples",
        "",
    ])

    for ex in detailed_results[:4]:
        qid = ex["id"]
        cat = ex["category"]
        q = ex["question"]
        ans = ex["answer"]
        gt = ex["ground_truth_answer"]
        claims_v = ex.get("domain", {}).get("claims_verified", 0)
        claims_t = ex.get("domain", {}).get("claims_total", 0)
        cer = ex.get("domain", {}).get("claim_entailment_rate", 0.0)

        lines.extend([
            f"### Example {qid} ({cat})",
            f"**Question**: {q}  ",
            f"**Ground Truth**: *{gt}*  ",
            f"**Searchy Response**:  \n> {ans}  ",
            f"**Verification Outcome**: {claims_v}/{claims_t} Claims Supported ({cer * 100:.1f}% Entailment)  ",
            "",
        ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info("Markdown report written to %s", output_path)


def run_evaluation(
    benchmark_file: Path,
    output_dir: Path,
    limit: int | None = None,
    category: str = "all",
    method: str = "both",
):
    """Run full multimodal evaluation pipeline."""
    logger.info("Loading benchmark from %s...", benchmark_file)
    questions = load_benchmark(benchmark_file)

    if category != "all":
        questions = [q for q in questions if q.get("category") == category]
        logger.info("Filtered to %d questions in category '%s'", len(questions), category)

    if limit is not None and limit > 0:
        questions = questions[:limit]
        logger.info("Limited evaluation to first %d questions", len(questions))

    total_q = len(questions)
    logger.info("Beginning evaluation on %d benchmark questions...", total_q)

    settings = Settings()
    services = Services(settings)
    chat_service = ChatService(
        settings, services.metadata, services.search, services.chat, graph=services.graph
    )
    verifier = ClaimVerifier(settings)

    results: list[dict[str, Any]] = []
    ragas_samples: list[dict[str, Any]] = []

    for idx, item in enumerate(questions, start=1):
        qid = item["id"]
        ep = item["episode_id"]
        cat = item["category"]
        q = item["question"]
        gt_answer = item["ground_truth_answer"]
        gt_keywords = item.get("ground_truth_keywords", [])

        logger.info("[%d/%d] [%s] [%s] Evaluating: %s", idx, total_q, qid, cat, q[:60])
        start_t = time.perf_counter()

        reply = chat_service.respond(q, None)
        elapsed = time.perf_counter() - start_t

        answer = reply.get("answer", "")
        raw_sources = reply.get("sources", [])
        # Convert sources to dict if needed
        sources: list[dict[str, Any]] = []
        for s in raw_sources:
            if hasattr(s, "model_dump"):
                sources.append(s.model_dump())
            elif isinstance(s, dict):
                sources.append(s)
            else:
                sources.append(vars(s))

        contexts = []
        for i, s in enumerate(sources):
            content = s.get("description") or s.get("snippet") or s.get("text") or ""
            if s.get("said") and s.get("said") not in content:
                content = f"{content} Spoken: {s['said']}".strip()
            contexts.append(f"[{s.get('number', i+1)}] {s.get('label', '')}: {content}")

        # Domain Metrics (Method B)
        ver_res = evaluate_claim_verification(answer, sources, verifier=verifier)
        cit_res = evaluate_citation_alignment(sources, ep, gt_keywords)
        rank_res = evaluate_retrieval_ranking(sources, ep, gt_keywords)
        f1_res = compute_f1_score(answer, gt_answer)

        record = {
            "id": qid,
            "episode_id": ep,
            "category": cat,
            "question": q,
            "ground_truth_answer": gt_answer,
            "ground_truth_keywords": gt_keywords,
            "answer": answer,
            "elapsed_seconds": round(elapsed, 2),
            "sources_count": len(sources),
            "domain": {
                "claim_entailment_rate": ver_res["entailment_rate"],
                "claims_total": ver_res["total_claims"],
                "claims_verified": ver_res["verified_claims"],
                "claims_unverified": ver_res["unverified_claims"],
                "claims_refuted": ver_res["refuted_claims"],
                "citation_precision": cit_res["citation_precision"],
                "episode_cited": cit_res["episode_cited"],
                "mrr": rank_res["mrr"],
                "hit@1": rank_res["hit@1"],
                "hit@3": rank_res["hit@3"],
                "hit@5": rank_res["hit@5"],
                "f1": f1_res["f1"],
                "precision": f1_res["precision"],
                "recall": f1_res["recall"],
            },
        }

        results.append(record)
        ragas_samples.append(
            {
                "question": q,
                "contexts": contexts,
                "answer": answer,
                "ground_truth": gt_answer,
            }
        )

    # Ragas Metrics (Method A)
    logger.info("Computing Method A: Ragas Evaluation...")
    ragas_output = run_ragas_evaluation(ragas_samples, settings=settings)

    # Merge Ragas scores into records
    for rec, r_score in zip(results, ragas_output.get("per_sample", [])):
        rec["ragas"] = {
            "faithfulness": r_score.get("faithfulness", 0.0),
            "answer_relevancy": r_score.get("answer_relevancy", 0.0),
            "context_precision": r_score.get("context_precision", 0.0),
            "context_recall": r_score.get("context_recall", 0.0),
        }

    # Aggregate Statistics
    cer_list = [r["domain"]["claim_entailment_rate"] for r in results]
    cp_list = [r["domain"]["citation_precision"] for r in results]
    ep_hits = [1.0 if r["domain"]["episode_cited"] else 0.0 for r in results]
    mrr_list = [r["domain"]["mrr"] for r in results]
    f1_list = [r["domain"]["f1"] for r in results]

    summary_stats = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_questions": len(results),
        "model": settings.nvidia_nim_model if settings.llm_provider == "NVIDIA_NIM" else settings.llm_model_id,
        "ragas": {
            "faithfulness": ragas_output.get("faithfulness", 0.0),
            "answer_relevancy": ragas_output.get("answer_relevancy", 0.0),
            "context_precision": ragas_output.get("context_precision", 0.0),
            "context_recall": ragas_output.get("context_recall", 0.0),
        },
        "domain": {
            "claim_entailment_rate": round(sum(cer_list) / len(cer_list), 4) if cer_list else 0.0,
            "citation_precision": round(sum(cp_list) / len(cp_list), 4) if cp_list else 0.0,
            "episode_citation_rate": round(sum(ep_hits) / len(ep_hits), 4) if ep_hits else 0.0,
            "mrr": round(sum(mrr_list) / len(mrr_list), 4) if mrr_list else 0.0,
            "f1": round(sum(f1_list) / len(f1_list), 4) if f1_list else 0.0,
        },
    }

    # Category Breakdown
    cat_stats: dict[str, dict[str, Any]] = {}
    categories = sorted({r["category"] for r in results})
    for cat in categories:
        cat_recs = [r for r in results if r["category"] == cat]
        cnt = len(cat_recs)
        cat_cer = sum(r["domain"]["claim_entailment_rate"] for r in cat_recs) / cnt if cnt else 0.0
        cat_cp = sum(r["domain"]["citation_precision"] for r in cat_recs) / cnt if cnt else 0.0
        cat_ep = sum(1.0 if r["domain"]["episode_cited"] else 0.0 for r in cat_recs) / cnt if cnt else 0.0
        cat_rf = sum(r.get("ragas", {}).get("faithfulness", 0.0) for r in cat_recs) / cnt if cnt else 0.0
        cat_rr = sum(r.get("ragas", {}).get("answer_relevancy", 0.0) for r in cat_recs) / cnt if cnt else 0.0

        cat_stats[cat] = {
            "count": cnt,
            "claim_entailment_rate": round(cat_cer, 4),
            "citation_precision": round(cat_cp, 4),
            "episode_citation_rate": round(cat_ep, 4),
            "ragas_faithfulness": round(cat_rf, 4),
            "ragas_relevancy": round(cat_rr, 4),
        }

    # Save output artifacts
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "detailed_results.json"
    report_path = output_dir / "benchmark_report.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": summary_stats,
                "category_breakdown": cat_stats,
                "detailed_results": results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    logger.info("Detailed JSON saved to %s", json_path)

    build_markdown_report(summary_stats, cat_stats, results, report_path)
    logger.info("Evaluation complete! Benchmark report saved to %s", report_path)

    return summary_stats, cat_stats


def main():
    parser = argparse.ArgumentParser(description="Searchy Multimodal GraphRAG Benchmark Runner")
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("evaluation/data/benchmark_120.json"),
        help="Path to benchmark JSON",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evaluation/results"),
        help="Path to output directory",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Number of questions to evaluate (default: all)",
    )
    parser.add_argument(
        "--category",
        type=str,
        default="all",
        choices=["all", "dialogue", "visual", "graph_relationship", "temporal_milestone"],
        help="Filter by category",
    )
    parser.add_argument(
        "--method",
        type=str,
        default="both",
        choices=["both", "domain", "ragas"],
        help="Evaluation methodology",
    )

    args = parser.parse_args()
    run_evaluation(
        benchmark_file=args.data,
        output_dir=args.output_dir,
        limit=args.limit,
        category=args.category,
        method=args.method,
    )


if __name__ == "__main__":
    main()
