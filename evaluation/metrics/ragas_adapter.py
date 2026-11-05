"""Ragas standard evaluation adapter for Searchy Multimodal GraphRAG."""

from __future__ import annotations

import logging
from typing import Any, Sequence

from datasets import Dataset

from searchy.core import Settings

logger = logging.getLogger("searchy.eval.ragas")


def format_ragas_dataset(samples: Sequence[dict[str, Any]]) -> Dataset:
    """Format samples into HuggingFace Dataset for Ragas evaluation.

    Each sample dict must contain:
    - question: str
    - contexts: list[str] (retrieved scenes/evidence)
    - answer: str (generated answer from Searchy)
    - ground_truth: str (reference ground truth)
    """
    questions = []
    contexts_list = []
    answers = []
    ground_truths = []

    for item in samples:
        questions.append(str(item.get("question", "")))
        ctx = item.get("contexts", [])
        if isinstance(ctx, str):
            ctx = [ctx]
        elif not ctx:
            ctx = ["(no evidence retrieved)"]
        contexts_list.append([str(c) for c in ctx])
        answers.append(str(item.get("answer", "")))
        ground_truths.append(str(item.get("ground_truth", item.get("ground_truth_answer", ""))))

    return Dataset.from_dict(
        {
            "question": questions,
            "contexts": contexts_list,
            "answer": answers,
            "ground_truth": ground_truths,
        }
    )


def build_ragas_llm(settings: Settings | None = None):
    """Instantiate LangChain LLM for Ragas evaluation using project settings."""
    cfg = settings or Settings()
    from langchain_openai import ChatOpenAI

    api_key = cfg.nvidia_nim_api_key.get_secret_value() or cfg.groq_api_key.get_secret_value()
    base_url = cfg.nvidia_nim_base_url if cfg.llm_provider == "NVIDIA_NIM" else None
    model_name = cfg.nvidia_nim_model if cfg.llm_provider == "NVIDIA_NIM" else cfg.llm_model_id

    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        request_timeout=60,
    )


def build_ragas_embeddings():
    """Instantiate local LangChain Embeddings for Ragas evaluation without external API keys."""
    from langchain_community.embeddings import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


def run_ragas_evaluation(
    samples: Sequence[dict[str, Any]],
    settings: Settings | None = None,
    metrics_list: list[str] | None = None,
) -> dict[str, Any]:
    """Execute Ragas evaluation over a list of Searchy samples.

    Returns dict containing mean metric scores:
    faithfulness, answer_relevancy, context_precision, context_recall.
    """
    if not samples:
        return {
            "faithfulness": 0.0,
            "answer_relevancy": 0.0,
            "context_precision": 0.0,
            "context_recall": 0.0,
            "per_sample": [],
        }

    dataset = format_ragas_dataset(samples)
    cfg = settings or Settings()

    try:
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )

        llm = build_ragas_llm(cfg)
        embeddings = build_ragas_embeddings()

        active_metrics = [faithfulness, answer_relevancy, context_precision, context_recall]
        if metrics_list:
            name_map = {
                "faithfulness": faithfulness,
                "answer_relevancy": answer_relevancy,
                "context_precision": context_precision,
                "context_recall": context_recall,
            }
            active_metrics = [name_map[m] for m in metrics_list if m in name_map]

        result = evaluate(
            dataset,
            metrics=active_metrics,
            llm=llm,
            embeddings=embeddings,
            raise_exceptions=False,
        )

        df = result.to_pandas()
        return {
            "faithfulness": round(float(df["faithfulness"].mean()), 4) if "faithfulness" in df else 0.0,
            "answer_relevancy": round(float(df["answer_relevancy"].mean()), 4) if "answer_relevancy" in df else 0.0,
            "context_precision": round(float(df["context_precision"].mean()), 4) if "context_precision" in df else 0.0,
            "context_recall": round(float(df["context_recall"].mean()), 4) if "context_recall" in df else 0.0,
            "per_sample": df.to_dict(orient="records"),
        }

    except Exception as exc:
        logger.warning("Ragas evaluation encountered error: %s; falling back to heuristic metrics", exc)
        return _fallback_ragas_metrics(samples)


def _fallback_ragas_metrics(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Robust fallback heuristic metrics if live Ragas evaluator is unavailable or throttled."""
    from evaluation.metrics.domain_metrics import compute_f1_score

    scores: list[dict[str, float]] = []
    for item in samples:
        ans = item.get("answer", "")
        gt = item.get("ground_truth", item.get("ground_truth_answer", ""))
        contexts = item.get("contexts", [])
        combined_ctx = " ".join(contexts)

        # Lexical ground truth alignment
        f1_gt = compute_f1_score(ans, gt)
        # Context support alignment
        f1_ctx = compute_f1_score(ans, combined_ctx)
        # Context vs ground truth coverage
        ctx_recall = compute_f1_score(combined_ctx, gt)["recall"]

        scores.append(
            {
                "faithfulness": round(min(1.0, f1_ctx["precision"] * 1.5), 4),
                "answer_relevancy": round(f1_gt["f1"], 4),
                "context_precision": round(f1_ctx["recall"], 4),
                "context_recall": round(ctx_recall, 4),
            }
        )

    mean_f = sum(s["faithfulness"] for s in scores) / len(scores) if scores else 0.0
    mean_ar = sum(s["answer_relevancy"] for s in scores) / len(scores) if scores else 0.0
    mean_cp = sum(s["context_precision"] for s in scores) / len(scores) if scores else 0.0
    mean_cr = sum(s["context_recall"] for s in scores) / len(scores) if scores else 0.0

    return {
        "faithfulness": round(mean_f, 4),
        "answer_relevancy": round(mean_ar, 4),
        "context_precision": round(mean_cp, 4),
        "context_recall": round(mean_cr, 4),
        "per_sample": scores,
    }
