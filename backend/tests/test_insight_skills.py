from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from services.insight_agent_contracts import AgentMemoryWriteRecord, AgentProfile, AgentTask
from services.insight_exploration_service import InsightExplorationService
from services.insight_memory_service import InsightMemoryService
from services.insight_skill_registry import InsightSkillRegistry
from services.insight_tool_gateway import InsightToolGateway


class InsightSkillsTests(unittest.TestCase):
    def test_skill_selection_prefers_context_request(self) -> None:
        registry = InsightSkillRegistry()
        profile = AgentProfile(
            profile_id="state_analyst",
            role_id="state_analyst",
            display_name_zh="现状分析师",
            display_name_en="State Analyst",
            skills=("trend_analysis", "risk_modeling", "report_composition"),
            allowed_tools=("graph_stats", "paper_catalog", "history_memory"),
        )

        selected = registry.select_skills(
            profile=profile,
            objective="请分析当前风险并给出报告",
            context={"selected_skills": ["report_composition"], "query": "大语言模型 风险"},
            limit=3,
        )

        self.assertGreaterEqual(len(selected), 1)
        self.assertEqual(selected[0], "report_composition")
        self.assertIn("risk_modeling", selected)

    def test_skill_execution_records_permission_denied_tools(self) -> None:
        registry = InsightSkillRegistry()
        gateway = InsightToolGateway()
        profile = AgentProfile(
            profile_id="state_analyst",
            role_id="state_analyst",
            display_name_zh="现状分析师",
            display_name_en="State Analyst",
            skills=("trend_analysis",),
            allowed_tools=("paper_catalog",),
        )
        context = {
            "query": "large language model",
            "objective": "summarize trend",
            "graph_stats": {"node_count": 10, "edge_count": 12, "paper_node_count": 8},
            "papers": [
                {
                    "paper_id": "p1",
                    "title": "Attention Is All You Need",
                    "year": 2017,
                    "citation_count": 100000,
                }
            ],
            "history_memory": ["关注经典论文"],
        }

        result = registry.execute(
            task_id="skill-task-1",
            profile=profile,
            skill_id="trend_analysis",
            context=context,
            tool_gateway=gateway,
        )

        denied_tools = [call.tool_name for call in result.tool_calls if call.status == "denied"]
        self.assertIn("graph_stats", denied_tools)
        self.assertIn("paper_catalog", result.tool_payloads)
        self.assertIn(result.status, {"completed", "empty"})

    def test_shared_skill_output_reuse_skips_skill_reexecution(self) -> None:
        service = InsightExplorationService(
            graph_service=object(),  # not used by _execute_orchestrated_task
            history_repository=object(),  # not used by _execute_orchestrated_task
        )
        role = next(item for item in service._ROLE_POOL if item.role_id == "state_analyst")
        target_role = next(item for item in service._ROLE_POOL if item.role_id == "feasibility_critic")
        profile = AgentProfile(
            profile_id="state_analyst",
            role_id="state_analyst",
            display_name_zh=role.title_zh,
            display_name_en=role.title_en,
            skills=("trend_analysis",),
            allowed_tools=("graph_stats", "paper_catalog"),
        )
        target_profile = AgentProfile(
            profile_id="feasibility_critic",
            role_id="feasibility_critic",
            display_name_zh=target_role.title_zh,
            display_name_en=target_role.title_en,
            skills=("execution_planning",),
            allowed_tools=("history_memory", "paper_catalog"),
        )
        task = AgentTask(
            run_id="reuse-run-1",
            task_id="reuse-task-1",
            profile_id=profile.profile_id,
            role_id=profile.role_id,
            round_index=1,
            depth=0,
            query="大语言模型",
            language="zh",
            input_type="domain",
            objective="总结领域进展并给出建议",
            context={},
        )

        with TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "insight_memory.sqlite3")
            memory_service = InsightMemoryService(db_path=db_path)
            memory_service.initialize_run(run_id=task.run_id, history_memory=[])
            memory_service.write(
                run_id=task.run_id,
                record=AgentMemoryWriteRecord(
                    task_id=task.task_id,
                    profile_id=profile.profile_id,
                    scope="session_shared",
                    key="skill::trend_analysis::output",
                    value="cached trend signal",
                ),
                worker_id="worker-1",
            )

            service.skill_registry.execute = Mock(side_effect=AssertionError("skill should be reused from cache"))
            result = asyncio.run(
                service._execute_orchestrated_task(
                    task=task,
                    worker_id="worker-1",
                    profiles_by_id={
                        profile.profile_id: profile,
                        target_profile.profile_id: target_profile,
                    },
                    role_by_profile_id={
                        profile.profile_id: role,
                        target_profile.profile_id: target_role,
                    },
                    language=task.language,
                    query=task.query,
                    papers=[
                        {
                            "paper_id": "p1",
                            "title": "Attention Is All You Need",
                            "year": 2017,
                            "citation_count": 100000,
                            "venue": "NeurIPS",
                            "abstract": "Transformers replace recurrence with attention.",
                            "authors": ["Vaswani et al."],
                        }
                    ],
                    extension_papers=[],
                    graph_stats={"node_count": 1, "edge_count": 0, "paper_node_count": 1},
                    history_memory=[],
                    memory_service=memory_service,
                )
            )

        self.assertEqual(result.status, "completed")
        self.assertIn("trend_analysis", result.extra.get("selected_skills", []))
        self.assertGreaterEqual(int(result.extra.get("skill_output_count", 0)), 1)
        self.assertFalse(
            any(write.key == "skill::trend_analysis::output" for write in result.memory_writes),
            "cached skill output should be reused without writing a new duplicate skill record",
        )
        self.assertGreaterEqual(len(result.subagent_requests), 1)
        first_patch = dict(result.subagent_requests[0].context_patch or {})
        self.assertIn("skill_outputs", first_patch)
        self.assertIn("trend_analysis", dict(first_patch.get("skill_outputs") or {}))


if __name__ == "__main__":
    unittest.main()
