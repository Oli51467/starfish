from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
