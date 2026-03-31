from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.settings import Settings
from core.domain_explorer import DomainExplorer
from services.graphrag_service import GraphRAGService
from services.retrieval.multi_source_retriever import MultiSourceRetriever


class DomainAuthorityQueryTests(unittest.TestCase):
    def test_chinese_attention_query_normalized_to_english(self) -> None:
        explorer = DomainExplorer()
        normalized = explorer._normalize_query_for_search("注意力机制")
        self.assertEqual(normalized, "attention mechanism")

    def test_attention_query_includes_attention_is_all_you_need_variant(self) -> None:
        service = GraphRAGService()
        with patch.object(service, "_build_domain_authority_queries_with_llm", return_value=[]):
            queries = service._build_domain_authority_queries("注意力机制")
        lowered = [str(item).lower() for item in queries]
        self.assertTrue(any("attention is all you need" in item for item in lowered))

    def test_query_coverage_keeps_high_match_paper_even_when_citation_missing(self) -> None:
        service = GraphRAGService()
        ranked = [
            (
                0.82,
                0.0,
                {
                    "paper_id": "paper:review",
                    "title": "A review on the attention mechanism of deep learning",
                    "abstract": "A broad survey of attention mechanism in deep learning.",
                    "citation_count": 1200,
                    "year": 2023,
                },
            ),
            (
                0.56,
                0.0,
                {
                    "paper_id": "paper:aiayn",
                    "title": "Attention Is All You Need",
                    "abstract": "We propose the Transformer architecture based on self-attention.",
                    "citation_count": 0,
                    "year": 2017,
                },
            ),
        ]
        selected = service._select_ranked_with_query_coverage(
            ranked=ranked,
            max_papers=5,
            ranking_queries=["attention is all you need transformer vaswani 2017"],
        )
        selected_ids = {str(item.get("paper_id") or "") for item in selected}
        self.assertIn("paper:aiayn", selected_ids)

    def test_attention_anchor_is_forced_into_selected_when_present_in_ranked(self) -> None:
        service = GraphRAGService()
        ranked = [
            (
                0.96,
                0.0,
                {
                    "paper_id": "paper:review",
                    "title": "A review on the attention mechanism of deep learning",
                    "abstract": "A broad survey of attention mechanism in deep learning.",
                    "citation_count": 1200,
                    "year": 2023,
                },
            ),
            (
                0.58,
                0.0,
                {
                    "paper_id": "paper:aiayn",
                    "title": "Attention Is All You Need",
                    "abstract": "Transformer architecture relies on self-attention.",
                    "citation_count": 0,
                    "year": 2017,
                },
            ),
        ]
        selected = [
            {
                "paper_id": "paper:review",
                "title": "A review on the attention mechanism of deep learning",
                "citation_count": 1200,
                "year": 2023,
            }
        ]
        adjusted = service._ensure_seminal_attention_anchor_selected(
            query="attention mechanism",
            ranked=ranked,
            selected=selected,
            max_papers=8,
        )
        adjusted_ids = [str(item.get("paper_id") or "") for item in adjusted]
        self.assertIn("paper:aiayn", adjusted_ids)

    def test_backfill_selected_citation_count_from_openalex_for_arxiv(self) -> None:
        service = GraphRAGService()
        service.openalex.fetch_paper_by_arxiv_id = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
            "citation_count": 12345,
            "year": 2017,
            "venue": "NeurIPS",
            "url": "https://arxiv.org/abs/1706.03762",
        }
        papers = [
            {
                "paper_id": "arxiv:1706.03762",
                "title": "Attention Is All You Need",
                "year": 2017,
                "citation_count": 0,
                "venue": "arXiv",
                "url": "https://arxiv.org/abs/1706.03762",
            }
        ]
        enriched = service._backfill_selected_citation_counts(papers)
        self.assertEqual(len(enriched), 1)
        self.assertEqual(int(enriched[0].get("citation_count") or 0), 12345)

    def test_backfill_selected_citation_count_falls_back_to_crossref(self) -> None:
        service = GraphRAGService()
        service.openalex.fetch_paper_by_doi = lambda *_args, **_kwargs: {"citation_count": 0}  # type: ignore[method-assign]
        service.crossref.fetch_paper_by_doi = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
            "citation_count": 456,
            "year": 2020,
            "venue": "Journal of Testing",
            "url": "https://doi.org/10.1000/test-doi",
        }
        service.opencitations.fetch_citation_count_by_doi = lambda *_args, **_kwargs: 0  # type: ignore[method-assign]
        papers = [
            {
                "paper_id": "doi:10.1000/test-doi",
                "title": "Fallback Test Paper",
                "year": None,
                "citation_count": 0,
                "venue": "",
                "url": "",
            }
        ]
        enriched = service._backfill_selected_citation_counts(papers)
        self.assertEqual(len(enriched), 1)
        self.assertEqual(int(enriched[0].get("citation_count") or 0), 456)
        self.assertEqual(int(enriched[0].get("year") or 0), 2020)
        self.assertEqual(str(enriched[0].get("venue") or ""), "Journal of Testing")

    def test_backfill_selected_citation_count_falls_back_to_opencitations(self) -> None:
        service = GraphRAGService()
        service.openalex.fetch_paper_by_doi = lambda *_args, **_kwargs: {"citation_count": 0}  # type: ignore[method-assign]
        service.crossref.fetch_paper_by_doi = lambda *_args, **_kwargs: {"citation_count": 0}  # type: ignore[method-assign]
        service.opencitations.fetch_citation_count_by_doi = lambda *_args, **_kwargs: 89  # type: ignore[method-assign]
        papers = [
            {
                "paper_id": "doi:10.1000/opencitation-doi",
                "title": "OpenCitations Fallback Paper",
                "year": None,
                "citation_count": 0,
                "venue": "",
                "url": "",
            }
        ]
        enriched = service._backfill_selected_citation_counts(papers)
        self.assertEqual(len(enriched), 1)
        self.assertEqual(int(enriched[0].get("citation_count") or 0), 89)

    def test_multi_source_retriever_registers_crossref_provider(self) -> None:
        settings = Settings()
        settings.retrieval_enable_semantic_scholar = False
        settings.retrieval_enable_openalex = False
        settings.retrieval_enable_arxiv = False
        settings.retrieval_enable_crossref = True

        retriever = MultiSourceRetriever(settings=settings)
        self.assertIn("crossref", retriever.providers)

    def test_stage_a_empty_triggers_legacy_fallback(self) -> None:
        service = GraphRAGService()
        legacy_candidate = {
            "paper_id": "openalex:W1",
            "title": "Legacy Candidate",
            "abstract": "legacy",
            "year": datetime.now(timezone.utc).year,
            "citation_count": 100,
            "venue": "LegacyConf",
        }
        with (
            patch.object(service, "_plan_domain_seed_papers_with_llm", return_value=[]),
            patch.object(
                service,
                "_search_domain_authority_candidates",
                return_value={
                    "provider": "openalex",
                    "papers": [legacy_candidate],
                    "elapsed_seconds": 0.0,
                    "used_fallback": False,
                    "providers_used": ["openalex"],
                    "source_stats": [],
                    "query_variants": ["legacy"],
                },
            ),
            patch.object(
                service,
                "_filter_and_rank_papers",
                return_value=(
                    [legacy_candidate],
                    {"input": 1, "deduped": 1, "selected": 1, "elapsed_seconds": 0.0},
                ),
            ),
        ):
            payload = service._retrieve_papers_from_query_with_trace(
                query="attention mechanism",
                max_papers=5,
                preferred_provider="openalex",
                domain_authority_mode=True,
            )
        retrieve_steps = [step for step in payload["steps"] if step.get("phase") == "retrieve"]
        self.assertTrue(retrieve_steps)
        self.assertIn("新链路失败", str(retrieve_steps[0].get("detail") or ""))
        self.assertEqual(payload["selected_papers"][0]["paper_id"], "openalex:W1")

    def test_stage_b_resolution_drops_unresolved_and_keeps_partial_results(self) -> None:
        service = GraphRAGService()
        current_year = datetime.now(timezone.utc).year

        def fake_search_papers(*, query: str, limit: int, preferred_provider: str) -> dict[str, object]:
            index = int(query.split()[-1])
            if index >= 28:
                return {"papers": [], "providers_used": ["openalex"], "source_stats": [], "elapsed_seconds": 0.0}
            return {
                "papers": [
                    {
                        "paper_id": f"openalex:W{index}",
                        "title": query,
                        "abstract": "seed",
                        "year": current_year,
                        "citation_count": 10 + index,
                        "venue": "Conf",
                    }
                ],
                "providers_used": ["openalex"],
                "source_stats": [],
                "elapsed_seconds": 0.0,
            }

        service.retriever.search_papers = fake_search_papers  # type: ignore[method-assign]
        suggestions = [{"title": f"Seed Paper {idx}", "year": current_year} for idx in range(50)]
        resolved_payload = service._resolve_domain_seed_candidates(
            seed_suggestions=suggestions,
            preferred_provider="openalex",
            paper_range_years=None,
        )
        self.assertEqual(len(resolved_payload["resolved_seeds"]), 28)
        self.assertEqual(int(resolved_payload["unresolved_count"]), 22)

    def test_year_range_applies_in_stage_b_and_stage_c(self) -> None:
        service = GraphRAGService()
        current_year = datetime.now(timezone.utc).year
        old_year = current_year - 8

        def fake_search_stage_b(*, query: str, limit: int, preferred_provider: str) -> dict[str, object]:
            if "Old" in query:
                year = old_year
            else:
                year = current_year
            return {
                "papers": [
                    {
                        "paper_id": f"openalex:{query}",
                        "title": query,
                        "abstract": "seed",
                        "year": year,
                        "citation_count": 100,
                        "venue": "Conf",
                    }
                ],
                "providers_used": ["openalex"],
                "source_stats": [],
                "elapsed_seconds": 0.0,
            }

        service.retriever.search_papers = fake_search_stage_b  # type: ignore[method-assign]
        stage_b = service._resolve_domain_seed_candidates(
            seed_suggestions=[
                {"title": "Old Seed", "year": old_year},
                {"title": "Fresh Seed", "year": current_year},
            ],
            preferred_provider="openalex",
            paper_range_years=3,
        )
        resolved_seeds = list(stage_b["resolved_seeds"])
        self.assertEqual(len(resolved_seeds), 1)
        self.assertEqual(resolved_seeds[0]["title"], "Fresh Seed")

        def fake_search_stage_c(*, query: str, limit: int, preferred_provider: str) -> dict[str, object]:
            return {
                "papers": [
                    {
                        "paper_id": "openalex:exp-old",
                        "title": "Expansion Old",
                        "abstract": "old",
                        "year": old_year,
                        "citation_count": 99,
                        "venue": "Conf",
                    },
                    {
                        "paper_id": "openalex:exp-fresh",
                        "title": "Expansion Fresh",
                        "abstract": "fresh",
                        "year": current_year,
                        "citation_count": 120,
                        "venue": "Conf",
                    },
                ],
                "providers_used": ["openalex"],
                "source_stats": [],
                "elapsed_seconds": 0.0,
            }

        service.retriever.search_papers = fake_search_stage_c  # type: ignore[method-assign]
        stage_c = service._expand_domain_seed_candidates(
            query="fresh domain",
            resolved_seeds=resolved_seeds,
            preferred_provider="openalex",
            paper_range_years=3,
            max_expand_per_seed=10,
            candidate_cap=200,
        )
        years = [int(item.get("year") or 0) for item in stage_c["candidate_pool"]]
        self.assertTrue(all(year >= current_year - 3 for year in years))

    def test_stage_c_enforces_expand_limit_and_pool_cap(self) -> None:
        service = GraphRAGService()
        current_year = datetime.now(timezone.utc).year
        seeds = [
            {
                "paper_id": f"openalex:seed{idx}",
                "title": f"Seed {idx}",
                "abstract": "seed",
                "year": current_year,
                "citation_count": 100,
                "venue": "Conf",
            }
            for idx in range(30)
        ]

        def fake_search_stage_c(*, query: str, limit: int, preferred_provider: str) -> dict[str, object]:
            seed_idx = int(query.split()[-1])
            papers = []
            for local_idx in range(20):
                papers.append(
                    {
                        "paper_id": f"openalex:exp-{seed_idx}-{local_idx}",
                        "title": f"Expansion {seed_idx} {local_idx}",
                        "abstract": "expansion",
                        "year": current_year,
                        "citation_count": 10 + local_idx,
                        "venue": "Conf",
                    }
                )
            return {
                "papers": papers,
                "providers_used": ["openalex"],
                "source_stats": [],
                "elapsed_seconds": 0.0,
            }

        service.retriever.search_papers = fake_search_stage_c  # type: ignore[method-assign]
        stage_c = service._expand_domain_seed_candidates(
            query="domain query",
            resolved_seeds=seeds,
            preferred_provider="openalex",
            paper_range_years=None,
            max_expand_per_seed=10,
            candidate_cap=200,
        )
        self.assertEqual(int(stage_c["expanded_count"]), len(seeds) * 10)
        self.assertEqual(len(stage_c["candidate_pool"]), 200)
        self.assertEqual(int(stage_c["candidate_before_cap"]), 330)

    def test_stage_d_rejects_unknown_or_duplicate_ids(self) -> None:
        service = GraphRAGService()
        current_year = datetime.now(timezone.utc).year
        candidates = [
            {
                "paper_id": f"openalex:{idx}",
                "title": f"Candidate {idx}",
                "abstract": "candidate",
                "year": current_year,
                "citation_count": 20 + idx,
                "venue": "Conf",
            }
            for idx in range(3)
        ]
        llm_payload = {
            "ranked": [
                {"id": "P001", "relevance_score": 0.9, "representative_score": 0.8},
                {"id": "P999", "relevance_score": 0.7, "representative_score": 0.7},
                {"id": "P001", "relevance_score": 0.6, "representative_score": 0.6},
            ]
        }
        fake_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(llm_payload, ensure_ascii=False))
                )
            ]
        )
        with (
            patch("services.graphrag_service.is_configured", return_value=True),
            patch("services.graphrag_service.chat", return_value=fake_response),
        ):
            rerank_payload = service._rerank_domain_candidates_with_llm(
                query="candidate",
                candidates=candidates,
                max_papers=2,
            )
        self.assertTrue(bool(rerank_payload["success"]))
        self.assertEqual(int(rerank_payload["invalid_id_count"]), 2)
        selected_ids = {str(item.get("paper_id") or "") for item in rerank_payload["selected_papers"]}
        self.assertTrue(selected_ids.issubset({f"openalex:{idx}" for idx in range(3)}))

    def test_domain_authority_weight_formula_locked(self) -> None:
        service = GraphRAGService()
        self.assertDictEqual(
            service._DOMAIN_AUTHORITY_WEIGHTS,
            {
                "relevance": 0.46,
                "citation": 0.34,
                "recency": 0.06,
                "representative": 0.14,
            },
        )
        full_score = service._domain_authority_weighted_score(
            relevance_signal=1.0,
            citation_signal=1.0,
            recency_signal=1.0,
            representative_signal=1.0,
        )
        self.assertAlmostEqual(full_score, 1.0, places=6)

    def test_seed_candidate_match_accepts_year_tolerance_of_three(self) -> None:
        service = GraphRAGService()
        matched, score = service._match_domain_seed_candidate(
            requested_title="Attention Is All You Need",
            requested_year=2017,
            candidates=[
                {
                    "paper_id": "openalex:W-older",
                    "title": "Attention Is All You Need",
                    "abstract": "",
                    "year": 2014,
                    "citation_count": 5000,
                    "venue": "NeurIPS",
                }
            ],
        )
        self.assertIsNotNone(matched)
        self.assertGreater(score, 0.5)

    def test_seed_coverage_forces_anchor_into_topk(self) -> None:
        service = GraphRAGService()
        current_year = datetime.now(timezone.utc).year
        seed_anchor = {
            "paper_id": "openalex:seed-anchor",
            "title": "Anchor Seed Paper",
            "abstract": "classic",
            "year": current_year - 1,
            "citation_count": 9000,
            "venue": "TopConf",
            "_seed_match_score": 0.98,
            "_seed_rank_index": 0,
        }
        selected = [
            {
                "paper_id": "openalex:selected-1",
                "title": "Selected Paper 1",
                "abstract": "selected",
                "year": current_year,
                "citation_count": 200,
                "venue": "Conf",
            },
            {
                "paper_id": "openalex:selected-2",
                "title": "Selected Paper 2",
                "abstract": "selected",
                "year": current_year,
                "citation_count": 190,
                "venue": "Conf",
            },
        ]
        candidate_pool = [seed_anchor, *selected]
        anchors = service._choose_domain_seed_anchors(resolved_seeds=[seed_anchor], max_papers=2)
        adjusted, forced_count = service._ensure_domain_seed_coverage(
            selected_papers=selected,
            candidate_pool=candidate_pool,
            seed_anchors=anchors,
            max_papers=2,
        )
        adjusted_ids = [str(item.get("paper_id") or "") for item in adjusted]
        self.assertIn("openalex:seed-anchor", adjusted_ids)
        self.assertEqual(forced_count, 1)

    def test_seed_inputs_still_use_seed_retrieval_path(self) -> None:
        service = GraphRAGService()
        with patch.object(
            service,
            "_retrieve_papers_from_seed_input_with_trace",
            return_value={
                "query": "10.1000/test",
                "provider": "mock",
                "providers_used": [],
                "provider_stats": [],
                "candidate_count": 0,
                "selected_papers": [],
                "steps": [],
            },
        ) as mocked_seed:
            payload = service._retrieve_papers_with_trace(
                query="10.1000/test",
                max_papers=10,
                input_type="doi",
            )
        self.assertTrue(mocked_seed.called)
        self.assertEqual(str(payload["provider"]), "mock")


if __name__ == "__main__":
    unittest.main()
