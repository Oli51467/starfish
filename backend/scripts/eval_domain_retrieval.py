from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Any


REFERENCE_PAPERS: dict[str, set[str]] = {
    "attention is all you need": {"attention is all you need"},
    "bert": {"bert: pre-training of deep bidirectional transformers for language understanding"},
    "gpt-3": {"language models are few-shot learners"},
    "scaling laws": {"scaling laws for neural language models"},
    "instructgpt": {"training language models to follow instructions with human feedback"},
    "chain-of-thought": {"chain of thought prompting elicits reasoning in large language models"},
    "chinchilla": {"training compute-optimal large language models"},
    "llama": {"llama: open and efficient foundation language models"},
    "flashattention": {"flashattention: fast and memory-efficient exact attention with io-awareness"},
    "constitutional ai": {"constitutional ai: harmlessness from ai feedback"},
}

_NON_WORD_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff\s:-]+")
_SPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    lowered = str(text or "").lower().strip()
    cleaned = _NON_WORD_RE.sub(" ", lowered)
    return _SPACE_RE.sub(" ", cleaned).strip()


@dataclass
class EvalConfig:
    query: str
    max_papers: int
    paper_range_years: int | None
    quick_mode: bool
    input_type: str = "domain"


def _matches_reference_titles(titles: list[str]) -> list[str]:
    normalized_titles = [_normalize(item) for item in titles if _normalize(item)]
    matched: list[str] = []
    for key, aliases in REFERENCE_PAPERS.items():
        found = False
        for alias in aliases:
            normalized_alias = _normalize(alias)
            if not normalized_alias:
                continue
            if any(
                normalized_title == normalized_alias
                or normalized_title.startswith(f"{normalized_alias}:")
                or normalized_title.startswith(f"{normalized_alias} ")
                for normalized_title in normalized_titles
            ):
                found = True
                break
        if found:
            matched.append(key)
    return sorted(matched)


def _run_single(config: EvalConfig) -> dict[str, Any]:
    from models.schemas import KnowledgeGraphRetrieveRequest
    from services.graphrag_service import GraphRAGService

    service = GraphRAGService()
    request = KnowledgeGraphRetrieveRequest(
        query=config.query,
        max_papers=config.max_papers,
        input_type=config.input_type,
        quick_mode=config.quick_mode,
        paper_range_years=config.paper_range_years,
    )
    response = service.retrieve_papers(request)
    titles = [paper.title for paper in response.papers]
    matched = _matches_reference_titles(titles)

    return {
        "mode": "quick" if config.quick_mode else "normal",
        "query_used": response.query,
        "provider": response.provider,
        "providers_used": response.providers_used,
        "candidate_count": response.candidate_count,
        "selected_count": response.selected_count,
        "hit_count": len(matched),
        "hits": matched,
        "top15_titles": titles[:15],
        "provider_stats": [
            {
                "provider": stat.provider,
                "status": stat.status,
                "count": stat.count,
                "error": stat.error,
                "elapsed_ms": stat.elapsed_ms,
            }
            for stat in response.provider_stats
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate domain retrieval hit rate against a fixed paper set.")
    parser.add_argument("--query", default="大语言模型")
    parser.add_argument("--max-papers", type=int, default=30)
    parser.add_argument("--paper-range-years", type=int, default=10)
    parser.add_argument("--input-type", default="domain")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument(
        "--modes",
        nargs="+",
        default=["normal", "quick"],
        choices=["normal", "quick"],
    )
    parser.add_argument(
        "--disable-llm-planner",
        action="store_true",
        help="Disable LLM query planning by clearing API_KEY for this process.",
    )
    parser.add_argument(
        "--provider-timeout",
        type=float,
        default=None,
        help="Override RETRIEVAL_PROVIDER_TIMEOUT_SECONDS for this process.",
    )
    args = parser.parse_args()

    if args.disable_llm_planner:
        os.environ["API_KEY"] = ""
        os.environ["DASHSCOPE_API_KEY"] = ""
    if args.provider_timeout is not None:
        os.environ["RETRIEVAL_PROVIDER_TIMEOUT_SECONDS"] = str(max(2.0, float(args.provider_timeout)))

    mode_flags = [mode == "quick" for mode in args.modes]
    all_runs: list[dict[str, Any]] = []
    for run_index in range(max(1, int(args.runs))):
        for quick_mode in mode_flags:
            config = EvalConfig(
                query=str(args.query),
                max_papers=max(3, min(30, int(args.max_papers))),
                paper_range_years=None if args.paper_range_years is None else max(1, min(30, int(args.paper_range_years))),
                quick_mode=quick_mode,
                input_type=str(args.input_type or "domain"),
            )
            payload = _run_single(config)
            payload["run"] = run_index + 1
            all_runs.append(payload)

    print(
        json.dumps(
            {
                "query": args.query,
                "max_papers": max(3, min(30, int(args.max_papers))),
                "paper_range_years": None if args.paper_range_years is None else max(1, min(30, int(args.paper_range_years))),
                "modes": args.modes,
                "runs": max(1, int(args.runs)),
                "disable_llm_planner": bool(args.disable_llm_planner),
                "provider_timeout_override": args.provider_timeout,
                "results": all_runs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
