from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from services.graphrag_service import GraphRAGService
from services.insight_agent_contracts import AgentProfile, AgentTask, AgentTaskResult, SubAgentRequest
from services.insight_exploration_service import InsightExplorationService
from services.insight_orchestrator_service import InsightOrchestratorService, OrchestratorLimits
from services.insight_worker_pool import InsightWorkerPool, WorkerPoolConfig
from services.retrieval.multi_source_retriever import MultiSourceRetriever


class GraphRAGParallelAccelerationTests(unittest.TestCase):
    def test_domain_query_variants_merge_preserves_original_query_order(self) -> None:
        service = GraphRAGService()
        service._query_variant_max_concurrency = 3
        service._query_variant_timeout_seconds = 2.0

        with patch.object(service, "_build_domain_authority_queries", return_value=["q1", "q2", "q3"]):
            def fake_search_papers(*, query: str, limit: int, preferred_provider: str) -> dict[str, object]:
                _ = limit, preferred_provider
                delay_map = {"q1": 0.06, "q2": 0.01, "q3": 0.03}
                time.sleep(delay_map.get(query, 0.0))
                return {
                    "provider": "openalex",
                    "providers_used": ["openalex"],
                    "papers": [
                        {
                            "paper_id": f"id-{query}",
                            "title": f"{query} paper",
                            "abstract": "",
                            "year": 2024,
                            "citation_count": 10,
                            "venue": "V",
                        }
                    ],
                    "status": "done",
                    "elapsed_seconds": delay_map.get(query, 0.0),
                    "used_fallback": False,
                    "source_stats": [
                        {
                            "provider": "openalex",
                            "status": "done",
                            "count": 1,
                            "elapsed_ms": int(delay_map.get(query, 0.0) * 1000),
                            "error": "",
                        }
                    ],
                }

            service.retriever.search_papers = fake_search_papers  # type: ignore[method-assign]
            payload = service._search_domain_authority_candidates(
                query="topic",
                limit=12,
                preferred_provider="openalex",
            )

        papers = list(payload.get("papers") or [])
        titles = [str(item.get("title") or "") for item in papers[:3]]
        self.assertEqual(titles, ["q1 paper", "q2 paper", "q3 paper"])

    def test_domain_query_variant_timeout_falls_back_without_crashing(self) -> None:
        service = GraphRAGService()
        service._query_variant_max_concurrency = 1
        service._query_variant_timeout_seconds = 0.01

        with patch.object(service, "_build_domain_authority_queries", return_value=["slow-query"]):
            def slow_search(*, query: str, limit: int, preferred_provider: str) -> dict[str, object]:
                _ = query, limit, preferred_provider
                time.sleep(0.08)
                return {
                    "provider": "openalex",
                    "providers_used": ["openalex"],
                    "papers": [],
                    "status": "done",
                    "elapsed_seconds": 0.08,
                    "used_fallback": False,
                    "source_stats": [],
                }

            service.retriever.search_papers = slow_search  # type: ignore[method-assign]
            payload = service._search_domain_authority_candidates(
                query="topic",
                limit=10,
                preferred_provider="openalex",
            )

        self.assertEqual(str(payload.get("provider") or ""), "mock")
        self.assertEqual(str(payload.get("status") or ""), "fallback")
        self.assertTrue(bool(payload.get("used_fallback")))

    def test_domain_query_variant_timeout_does_not_block_full_task_duration(self) -> None:
        service = GraphRAGService()
        service._query_variant_max_concurrency = 1
        service._query_variant_timeout_seconds = 2.0

        with patch.object(service, "_build_domain_authority_queries", return_value=["slow-query"]):
            def slow_search(*, query: str, limit: int, preferred_provider: str) -> dict[str, object]:
                _ = query, limit, preferred_provider
                if query == "slow-query":
                    time.sleep(4.0)
                return {
                    "provider": "openalex",
                    "providers_used": ["openalex"],
                    "papers": [],
                    "status": "done",
                    "elapsed_seconds": 4.0,
                    "used_fallback": False,
                    "source_stats": [],
                }

            service.retriever.search_papers = slow_search  # type: ignore[method-assign]
            started_at = time.perf_counter()
            payload = service._search_domain_authority_candidates(
                query="topic",
                limit=10,
                preferred_provider="openalex",
            )
            elapsed = time.perf_counter() - started_at

        self.assertLess(elapsed, 3.0)
        self.assertEqual(str(payload.get("provider") or ""), "mock")
        self.assertTrue(bool(payload.get("used_fallback")))

    def test_attach_relation_ids_handles_single_paper_failure(self) -> None:
        service = GraphRAGService()
        service._relation_enrich_max_concurrency = 4

        papers = [
            {"paper_id": "p1", "reference_ids": ["r0"], "citation_ids": ["c0"]},
            {"paper_id": "p2", "reference_ids": ["r1"], "citation_ids": []},
        ]

        def fake_fetch(paper_id: str) -> dict[str, list[str]]:
            if paper_id == "p2":
                raise RuntimeError("single-paper-failure")
            return {"references": ["r2"], "citations": ["c2"]}

        service._fetch_relation_ids = fake_fetch  # type: ignore[method-assign]
        service._attach_relation_ids(papers)

        self.assertIn("r2", list(papers[0].get("reference_ids") or []))
        self.assertIn("c2", list(papers[0].get("citation_ids") or []))
        self.assertIn("r1", list(papers[1].get("reference_ids") or []))

    def test_domain_query_variant_timeout_recovers_with_direct_query(self) -> None:
        service = GraphRAGService()
        service._query_variant_max_concurrency = 1
        service._query_variant_timeout_seconds = 2.0

        with patch.object(service, "_build_domain_authority_queries", return_value=["slow-variant"]):
            def fake_search(*, query: str, limit: int, preferred_provider: str) -> dict[str, object]:
                _ = limit, preferred_provider
                if query == "slow-variant":
                    time.sleep(2.2)
                    return {
                        "provider": "openalex",
                        "providers_used": ["openalex"],
                        "papers": [],
                        "status": "done",
                        "elapsed_seconds": 2.2,
                        "used_fallback": False,
                        "source_stats": [],
                    }
                return {
                    "provider": "openalex",
                    "providers_used": ["openalex"],
                    "papers": [
                        {
                            "paper_id": "topic-1",
                            "title": "Topic Recovery Paper",
                            "abstract": "a",
                            "year": 2024,
                            "citation_count": 12,
                            "venue": "V",
                        }
                    ],
                    "status": "done",
                    "elapsed_seconds": 0.01,
                    "used_fallback": False,
                    "source_stats": [],
                }

            service.retriever.search_papers = fake_search  # type: ignore[method-assign]
            payload = service._search_domain_authority_candidates(
                query="topic",
                limit=12,
                preferred_provider="openalex",
            )

        self.assertNotEqual(str(payload.get("provider") or ""), "mock")
        titles = [str(item.get("title") or "") for item in list(payload.get("papers") or [])]
        self.assertIn("Topic Recovery Paper", titles)


class MultiSourceRetrieverTimeoutTests(unittest.TestCase):
    def test_provider_timeout_does_not_wait_for_full_slow_call(self) -> None:
        retriever = MultiSourceRetriever()
        retriever.provider_timeout_seconds = 0.05
        retriever.max_workers = 1

        class _SlowProvider:
            def search_papers(self, query: str, *, limit: int, offset: int = 0) -> list[dict[str, object]]:
                _ = query, limit, offset
                time.sleep(0.4)
                return []

            def fetch_seed_paper(
                self,
                *,
                input_type: str,
                input_value: str,
                reference_limit: int,
                citation_limit: int,
            ) -> dict[str, object] | None:
                _ = input_type, input_value, reference_limit, citation_limit
                return None

            def supports_seed_input(self, input_type: str) -> bool:
                _ = input_type
                return True

        retriever.providers = {"slow": _SlowProvider()}  # type: ignore[assignment]
        started_at = time.perf_counter()
        executions = retriever._search_parallel(
            provider_order=["slow"],
            query="q",
            limit=10,
            offset=0,
        )
        elapsed = time.perf_counter() - started_at

        self.assertLess(elapsed, 0.25)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0].error, "timeout")


class InsightBudgetAndRoundTests(unittest.IsolatedAsyncioTestCase):
    def test_round_budget_respects_quick_mode(self) -> None:
        self.assertEqual(
            InsightExplorationService._resolve_round_budget(exploration_depth=5, quick_mode=True),
            2,
        )
        self.assertEqual(
            InsightExplorationService._resolve_round_budget(exploration_depth=1, quick_mode=False),
            2,
        )
        self.assertEqual(
            InsightExplorationService._resolve_round_budget(exploration_depth=5, quick_mode=False),
            4,
        )

    async def test_orchestrator_respects_dynamic_parent_spawn_override(self) -> None:
        orchestrator = InsightOrchestratorService(
            limits=OrchestratorLimits(
                max_subagent_depth=2,
                max_subtasks_per_round=24,
                max_subtasks_per_parent=2,
                max_batch_size=8,
            ),
            worker_pool=InsightWorkerPool(
                config=WorkerPoolConfig(worker_count=2, task_timeout_seconds=15.0),
            ),
        )

        parent_profile = AgentProfile(
            profile_id="parent",
            role_id="parent",
            display_name_zh="parent",
            display_name_en="parent",
            max_subagents=2,
        )
        child_profile = AgentProfile(
            profile_id="child",
            role_id="child",
            display_name_zh="child",
            display_name_en="child",
            max_subagents=2,
        )
        base_task = AgentTask(
            run_id="run-1",
            task_id="task-root",
            profile_id=parent_profile.profile_id,
            role_id=parent_profile.role_id,
            round_index=1,
            depth=0,
            query="q",
            language="zh",
            input_type="domain",
            objective="obj",
        )

        async def executor(task: AgentTask, worker_id: str) -> AgentTaskResult:
            _ = worker_id
            if task.depth == 0:
                return AgentTaskResult(
                    task_id=task.task_id,
                    profile_id=task.profile_id,
                    role_id=task.role_id,
                    status="completed",
                    output="root",
                    subagent_requests=[
                        SubAgentRequest(objective="sub-a", profile_id="child"),
                        SubAgentRequest(objective="sub-b", profile_id="child"),
                    ],
                )
            return AgentTaskResult(
                task_id=task.task_id,
                profile_id=task.profile_id,
                role_id=task.role_id,
                status="completed",
                output="child",
            )

        result = await orchestrator.execute_round(
            round_index=1,
            base_tasks=[base_task],
            profiles_by_id={
                parent_profile.profile_id: parent_profile,
                child_profile.profile_id: child_profile,
            },
            executor=executor,
            max_subtasks_per_round=8,
            max_subtasks_per_parent=1,
        )
        self.assertEqual(result.spawned_task_count, 1)


if __name__ == "__main__":
    unittest.main()
