from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import math
from pathlib import Path
import re
from typing import Any, Awaitable, Callable

from core.llm_client import chat, is_configured
from models.schemas import KnowledgeGraphRetrieveRequest
from repositories.research_history_repository import (
    ResearchHistoryRepository,
    get_research_history_repository,
)
from services.graphrag_service import GraphRAGService, get_graphrag_service

try:  # pragma: no cover - optional runtime dependency in some envs
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    _REPORTLAB_AVAILABLE = True
except Exception:  # noqa: BLE001
    A4 = None  # type: ignore[assignment]
    pdfmetrics = None  # type: ignore[assignment]
    UnicodeCIDFont = None  # type: ignore[assignment]
    canvas = None  # type: ignore[assignment]
    _REPORTLAB_AVAILABLE = False

StreamCallback = Callable[[dict[str, Any]], Awaitable[None]]

_DEFAULT_AGENT_COUNT = 4
_DEFAULT_EXPLORATION_DEPTH = 2
_MIN_AGENT_COUNT = 2
_MAX_AGENT_COUNT = 8
_MIN_EXPLORATION_DEPTH = 1
_MAX_EXPLORATION_DEPTH = 5
_MAX_EXPANSION_PAPERS = 24
_MAX_EXPANSION_QUERIES_PER_ROUND = 2


@dataclass(frozen=True)
class _RoleSpec:
    role_id: str
    title_zh: str
    title_en: str
    focus: str


class InsightExplorationService:
    _ROLE_POOL: tuple[_RoleSpec, ...] = (
        _RoleSpec("state_analyst", "现状分析师", "State Analyst", "宏观现状与发展趋势"),
        _RoleSpec("relation_analyst", "关系分析师", "Relation Analyst", "论文关系与知识结构"),
        _RoleSpec("innovation_architect", "创新架构师", "Innovation Architect", "可行创新架构"),
        _RoleSpec("application_designer", "应用设计师", "Application Designer", "创新应用场景"),
        _RoleSpec("evidence_scout", "证据侦察员", "Evidence Scout", "增量证据检索与核对"),
        _RoleSpec("feasibility_critic", "可行性评审员", "Feasibility Critic", "实施可行性与里程碑"),
        _RoleSpec("risk_skeptic", "风险审校员", "Risk Skeptic", "风险、假设与约束"),
        _RoleSpec("synthesis_editor", "综合编辑", "Synthesis Editor", "多角色整合与表达"),
    )

    def __init__(
        self,
        *,
        graph_service: GraphRAGService | None = None,
        history_repository: ResearchHistoryRepository | None = None,
    ) -> None:
        self.graph_service = graph_service or get_graphrag_service()
        self.history_repository = history_repository or get_research_history_repository()
        self.report_root = Path(__file__).resolve().parents[1] / "cache" / "reports"

    async def generate_report(
        self,
        *,
        session_id: str,
        user_id: str,
        query: str,
        input_type: str,
        papers: list[dict[str, Any]],
        graph_payload: dict[str, Any] | None,
        agent_count: int,
        exploration_depth: int,
        stream_callback: StreamCallback | None = None,
    ) -> dict[str, Any]:
        safe_session_id = str(session_id or "").strip()
        safe_user_id = str(user_id or "").strip()
        safe_query = str(query or "").strip()
        safe_input_type = str(input_type or "domain").strip().lower()
        if not safe_session_id or not safe_query:
            raise ValueError("insight_report_requires_session_and_query")

        resolved_agent_count = self._clamp_int(
            agent_count,
            default=_DEFAULT_AGENT_COUNT,
            min_value=_MIN_AGENT_COUNT,
            max_value=_MAX_AGENT_COUNT,
        )
        resolved_depth = self._clamp_int(
            exploration_depth,
            default=_DEFAULT_EXPLORATION_DEPTH,
            min_value=_MIN_EXPLORATION_DEPTH,
            max_value=_MAX_EXPLORATION_DEPTH,
        )
        language = self._detect_language(safe_query)
        active_roles = list(self._ROLE_POOL[:resolved_agent_count])
        rounds = max(1, resolved_depth * 2)
        streamed_chars = 0

        async def emit_stream_chunk(chunk: str, *, done: bool = False) -> None:
            nonlocal streamed_chars
            if stream_callback is None:
                return
            safe_chunk = str(chunk or "")
            if safe_chunk:
                streamed_chars += len(safe_chunk)
            await stream_callback(
                {
                    "section": "insight_markdown",
                    "chunk": safe_chunk,
                    "accumulated_chars": streamed_chars,
                    "done": bool(done),
                }
            )

        normalized_papers = self._normalize_papers(papers)
        graph_stats = self._extract_graph_stats(graph_payload or {})
        history_memory = await asyncio.to_thread(self._load_history_memory, safe_user_id)
        session_memory = {
            "hypotheses": [],
            "evidence": [],
            "decisions": [],
            "critic_notes": [],
        }
        extension_notes: list[str] = []
        extension_papers: list[dict[str, Any]] = []

        await emit_stream_chunk(
            self._format_line(
                language,
                zh=(
                    f"# 探索与洞察正在生成\n"
                    f"- 查询：`{safe_query}`\n"
                    f"- 配置：{resolved_agent_count} Agents，探索深度 {resolved_depth}\n"
                ),
                en=(
                    f"# Exploration In Progress\n"
                    f"- Query: `{safe_query}`\n"
                    f"- Setup: {resolved_agent_count} agents, depth {resolved_depth}\n"
                ),
            )
        )

        for round_index in range(1, rounds + 1):
            expansion_queries = self._build_round_expansion_queries(
                base_query=safe_query,
                round_index=round_index,
                papers=normalized_papers + extension_papers,
            )
            expansion_queries = expansion_queries[:_MAX_EXPANSION_QUERIES_PER_ROUND]
            if expansion_queries and len(extension_papers) < _MAX_EXPANSION_PAPERS:
                retrieved = await self._retrieve_extension_papers(
                    query_list=expansion_queries,
                    input_type=safe_input_type,
                    remaining=max(1, _MAX_EXPANSION_PAPERS - len(extension_papers)),
                )
                if retrieved:
                    extension_papers = self._merge_papers(extension_papers, retrieved, limit=_MAX_EXPANSION_PAPERS)
                    extension_notes.append(
                        self._format_line(
                            language,
                            zh=f"第 {round_index} 轮扩展检索：新增 {len(retrieved)} 篇候选论文（累计 {len(extension_papers)}）。",
                            en=f"Round {round_index} expansion retrieved {len(retrieved)} papers ({len(extension_papers)} total).",
                        )
                    )

            role_outputs = await self._run_role_round(
                round_index=round_index,
                roles=active_roles,
                language=language,
                query=safe_query,
                papers=normalized_papers,
                extension_papers=extension_papers,
                graph_stats=graph_stats,
                history_memory=history_memory,
                session_memory=session_memory,
            )
            session_memory["decisions"].extend(role_outputs)
            await emit_stream_chunk(
                self._format_line(
                    language,
                    zh=(
                        f"\n### 轮次 {round_index} 进展\n"
                        f"- 活跃 Agents：{len(active_roles)}\n"
                        f"- 当前证据池：基础 {len(normalized_papers)} + 扩展 {len(extension_papers)}\n"
                        f"- 新增洞察片段：{max(0, len(role_outputs))}\n"
                    ),
                    en=(
                        f"\n### Round {round_index} Progress\n"
                        f"- Active agents: {len(active_roles)}\n"
                        f"- Evidence pool: base {len(normalized_papers)} + expansion {len(extension_papers)}\n"
                        f"- New insight snippets: {max(0, len(role_outputs))}\n"
                    ),
                )
            )

        markdown = await self._compose_markdown(
            language=language,
            query=safe_query,
            input_type=safe_input_type,
            base_papers=normalized_papers,
            extension_papers=extension_papers,
            graph_stats=graph_stats,
            history_memory=history_memory,
            session_memory=session_memory,
            active_roles=active_roles,
            rounds=rounds,
            extension_notes=extension_notes,
        )

        if stream_callback is not None:
            await self._stream_markdown(
                markdown=markdown,
                callback=stream_callback,
                section="insight_markdown",
                start_accumulated=streamed_chars,
            )

        artifact = await asyncio.to_thread(
            self._persist_artifacts,
            session_id=safe_session_id,
            markdown=markdown,
            language=language,
        )
        summary = self._build_summary(
            language=language,
            extension_count=len(extension_papers),
            role_count=len(active_roles),
            rounds=rounds,
            base_papers=len(normalized_papers),
        )
        return {
            "language": language,
            "markdown": markdown,
            "summary": summary,
            "artifact": artifact,
            "memory": {
                "history": history_memory,
                "session": session_memory,
            },
            "stats": {
                "base_paper_count": len(normalized_papers),
                "extension_paper_count": len(extension_papers),
                "rounds": rounds,
                "agent_count": len(active_roles),
            },
        }

    @staticmethod
    def _clamp_int(value: object, *, default: int, min_value: int, max_value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(min_value, min(max_value, parsed))

    @staticmethod
    def _detect_language(text: str) -> str:
        return "zh" if re.search(r"[\u4e00-\u9fff]", str(text or "")) else "en"

    @staticmethod
    def _normalize_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in papers or []:
            if not isinstance(item, dict):
                continue
            paper_id = str(item.get("paper_id") or "").strip()
            title = str(item.get("title") or "").strip()
            if not paper_id and not title:
                continue
            items.append(
                {
                    "paper_id": paper_id,
                    "title": title or paper_id,
                    "year": InsightExplorationService._safe_int(item.get("year"), 0),
                    "citation_count": InsightExplorationService._safe_int(item.get("citation_count"), 0),
                    "venue": str(item.get("venue") or "").strip(),
                    "abstract": str(item.get("abstract") or "").strip(),
                    "authors": [
                        str(author).strip()
                        for author in (item.get("authors") or [])
                        if str(author).strip()
                    ],
                }
            )
        return items

    @staticmethod
    def _extract_graph_stats(graph_payload: dict[str, Any]) -> dict[str, int]:
        nodes = list(graph_payload.get("nodes") or [])
        edges = list(graph_payload.get("edges") or [])
        paper_nodes = [
            node
            for node in nodes
            if str(node.get("type") or node.get("kind") or "").strip().lower() == "paper"
        ]
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "paper_node_count": len(paper_nodes),
        }

    def _load_history_memory(self, user_id: str) -> list[str]:
        safe_user_id = str(user_id or "").strip()
        if not safe_user_id:
            return []
        try:
            rows, _ = self.history_repository.list_graph_records(
                user_id=safe_user_id,
                page=1,
                page_size=5,
            )
        except Exception:  # noqa: BLE001
            return []

        memory: list[str] = []
        for row in rows:
            history_id = str(row.get("history_id") or "").strip()
            if not history_id:
                continue
            try:
                detail = self.history_repository.get_graph_record(
                    user_id=safe_user_id,
                    history_id=history_id,
                )
            except Exception:  # noqa: BLE001
                detail = None
            if not isinstance(detail, dict):
                continue
            graph_payload = detail.get("graph_payload")
            if not isinstance(graph_payload, dict):
                continue
            pipeline = graph_payload.get("pipeline")
            if not isinstance(pipeline, dict):
                continue
            insight = pipeline.get("insight")
            if not isinstance(insight, dict):
                continue
            summary = str(insight.get("summary") or "").strip()
            if summary:
                memory.append(summary)
            if len(memory) >= 3:
                break
        return memory

    def _build_round_expansion_queries(
        self,
        *,
        base_query: str,
        round_index: int,
        papers: list[dict[str, Any]],
    ) -> list[str]:
        keywords: list[str] = [base_query]
        for item in papers[: min(12, len(papers))]:
            title = str(item.get("title") or "").strip()
            if title:
                keywords.extend(self._tokenize_title(title))
        deduped: list[str] = []
        seen: set[str] = set()
        for token in keywords:
            safe = str(token or "").strip()
            if not safe:
                continue
            key = safe.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(safe)
            if len(deduped) >= 8:
                break
        if not deduped:
            deduped = [base_query]

        pivot = deduped[(round_index - 1) % len(deduped)]
        return [
            f"{base_query} {pivot} innovation",
            f"{base_query} {pivot} application",
        ]

    @staticmethod
    def _tokenize_title(title: str) -> list[str]:
        tokens = re.split(r"[^a-zA-Z0-9\u4e00-\u9fff]+", str(title or "").strip())
        cleaned = [token for token in tokens if len(token) >= 4 or re.search(r"[\u4e00-\u9fff]", token)]
        return cleaned[:3]

    async def _retrieve_extension_papers(
        self,
        *,
        query_list: list[str],
        input_type: str,
        remaining: int,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        if remaining <= 0:
            return collected
        for query in query_list:
            safe_query = str(query or "").strip()
            if not safe_query:
                continue
            request = KnowledgeGraphRetrieveRequest(
                query=safe_query,
                max_papers=max(3, min(8, remaining)),
                input_type="domain" if input_type == "domain" else "domain",
                quick_mode=True,
                paper_range_years=None,
            )
            try:
                payload = await asyncio.to_thread(self.graph_service.retrieve_papers, request)
            except Exception:  # noqa: BLE001
                continue
            papers = [paper.model_dump(mode="json") for paper in payload.papers]
            if not papers:
                continue
            collected = self._merge_papers(collected, papers, limit=remaining)
            if len(collected) >= remaining:
                break
        return collected

    async def _run_role_round(
        self,
        *,
        round_index: int,
        roles: list[_RoleSpec],
        language: str,
        query: str,
        papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
        history_memory: list[str],
        session_memory: dict[str, list[str]],
    ) -> list[str]:
        outputs: list[str] = []
        for role in roles:
            content = await self._run_single_role(
                round_index=round_index,
                role=role,
                language=language,
                query=query,
                papers=papers,
                extension_papers=extension_papers,
                graph_stats=graph_stats,
                history_memory=history_memory,
                session_memory=session_memory,
            )
            outputs.append(content)
            if role.role_id in {"risk_skeptic", "feasibility_critic"}:
                session_memory["critic_notes"].append(content)
            if role.role_id in {"innovation_architect", "application_designer"}:
                session_memory["hypotheses"].append(content)
            session_memory["evidence"].append(content[:160])
        return outputs

    async def _run_single_role(
        self,
        *,
        round_index: int,
        role: _RoleSpec,
        language: str,
        query: str,
        papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
        history_memory: list[str],
        session_memory: dict[str, list[str]],
    ) -> str:
        if not is_configured():
            return self._fallback_role_output(
                round_index=round_index,
                role=role,
                language=language,
                query=query,
                papers=papers,
                extension_papers=extension_papers,
                graph_stats=graph_stats,
            )

        prompt = self._build_role_prompt(
            round_index=round_index,
            role=role,
            language=language,
            query=query,
            papers=papers,
            extension_papers=extension_papers,
            graph_stats=graph_stats,
            history_memory=history_memory,
            session_memory=session_memory,
        )
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    chat,
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are a specialized research sub-agent. "
                                "Return one concise paragraph with actionable insights."
                            ),
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                    temperature=0.25,
                    timeout=20,
                ),
                timeout=24,
            )
            content = str(response.choices[0].message.content or "").strip()
            if content:
                return content
        except Exception:  # noqa: BLE001
            pass
        return self._fallback_role_output(
            round_index=round_index,
            role=role,
            language=language,
            query=query,
            papers=papers,
            extension_papers=extension_papers,
            graph_stats=graph_stats,
        )

    def _build_role_prompt(
        self,
        *,
        round_index: int,
        role: _RoleSpec,
        language: str,
        query: str,
        papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
        history_memory: list[str],
        session_memory: dict[str, list[str]],
    ) -> str:
        top_papers = self._top_papers_for_prompt(papers + extension_papers, limit=6)
        role_name = role.title_zh if language == "zh" else role.title_en
        context = {
            "query": query,
            "round": round_index,
            "role": role_name,
            "focus": role.focus,
            "graph_stats": graph_stats,
            "top_papers": top_papers,
            "history_memory": history_memory[:2],
            "session_hypotheses": (session_memory.get("hypotheses") or [])[-2:],
            "session_critic_notes": (session_memory.get("critic_notes") or [])[-2:],
        }
        if language == "zh":
            return (
                "请作为科研多智能体中的一个子角色，基于上下文输出一段中文洞察。"
                "内容必须包含：当前发展判断、证据指向、可行创新方向。"
                "上下文："
                f"{context}"
            )
        return (
            "Act as a sub-agent in a research multi-agent system and provide one concise insight paragraph in English. "
            "Must include: current status judgment, evidence cue, feasible innovation direction. "
            f"Context: {context}"
        )

    def _fallback_role_output(
        self,
        *,
        round_index: int,
        role: _RoleSpec,
        language: str,
        query: str,
        papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
    ) -> str:
        total_papers = len(papers) + len(extension_papers)
        if language == "zh":
            return (
                f"[R{round_index}] {role.title_zh}：围绕“{query}”，当前证据池共 {total_papers} 篇论文，"
                f"图谱节点 {graph_stats['node_count']}、关系 {graph_stats['edge_count']}。"
                f"建议优先聚焦“{role.focus}”并设计可验证的增量实验。"
            )
        return (
            f"[R{round_index}] {role.title_en}: For '{query}', the evidence pool has {total_papers} papers "
            f"with {graph_stats['node_count']} graph nodes and {graph_stats['edge_count']} relations. "
            f"Prioritize '{role.focus}' with a verifiable incremental experiment path."
        )

    async def _compose_markdown(
        self,
        *,
        language: str,
        query: str,
        input_type: str,
        base_papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
        history_memory: list[str],
        session_memory: dict[str, list[str]],
        active_roles: list[_RoleSpec],
        rounds: int,
        extension_notes: list[str],
    ) -> str:
        now_text = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        top_papers = self._top_papers_for_prompt(base_papers + extension_papers, limit=8)
        role_labels = [
            role.title_zh if language == "zh" else role.title_en
            for role in active_roles
        ]
        hypotheses = (session_memory.get("hypotheses") or [])[:8]
        critic_notes = (session_memory.get("critic_notes") or [])[:8]
        decisions = (session_memory.get("decisions") or [])[:10]

        if language == "zh":
            sections = [
                "# 探索与洞察报告",
                "",
                f"- 查询主题：`{query}`",
                f"- 输入类型：`{input_type}`",
                f"- 生成时间：`{now_text}`",
                f"- 多智能体配置：`{len(active_roles)} Agents`，`{rounds} 轮协商/探索`",
                "",
                "## 1. 领域现状与论文关系",
                f"- 基础论文池：{len(base_papers)} 篇；扩展论文池：{len(extension_papers)} 篇（总计 {len(base_papers) + len(extension_papers)} 篇）",
                f"- 图谱规模：节点 {graph_stats['node_count']}，关系 {graph_stats['edge_count']}，论文节点 {graph_stats['paper_node_count']}",
                "- 当前发展判断：该领域在方法演进与应用落地之间呈现并行推进趋势，部分分支出现快速迭代与结构重组信号。",
                "",
                "## 2. 代表论文与关系脉络",
            ]
            for item in top_papers:
                sections.append(
                    f"- {item['title']} ({item['year'] or '-'}), 引用 {item['citation_count']}，"
                    f"venue: {item['venue'] or 'Unknown'}"
                )
            sections.extend(
                [
                    "",
                    "## 3. 发散性可行性探索（创新点/创新架构/创新应用）",
                ]
            )
            if hypotheses:
                for note in hypotheses:
                    sections.append(f"- {note}")
            else:
                sections.append("- 当前可行创新点集中在模块组合优化、任务迁移策略与低成本部署路径。")
            sections.extend(
                [
                    "",
                    "## 4. 多智能体协作摘要",
                    f"- 角色集合：{', '.join(role_labels)}",
                ]
            )
            if extension_notes:
                sections.extend([f"- {note}" for note in extension_notes[:6]])
            if decisions:
                sections.extend([f"- {line}" for line in decisions[:6]])
            sections.extend(
                [
                    "",
                    "## 5. 风险与约束",
                ]
            )
            if critic_notes:
                sections.extend([f"- {line}" for line in critic_notes[:6]])
            else:
                sections.append("- 主要风险包括评估指标偏差、外部数据分布漂移与工程资源预算约束。")
            sections.extend(
                [
                    "",
                    "## 6. 下一步建议",
                    "- 建议 1：基于图谱桥接节点构建最小可验证创新原型。",
                    "- 建议 2：针对高潜力应用场景设计双轨实验（离线评估 + 小规模在线验证）。",
                    "- 建议 3：将关键假设写入后续记忆库并持续迭代证据。",
                ]
            )
            if history_memory:
                sections.extend(
                    [
                        "",
                        "## 附录：历史记忆参考",
                        *[f"- {line}" for line in history_memory[:3]],
                    ]
                )
            return "\n".join(sections).strip() + "\n"

        sections = [
            "# Exploration & Insight Report",
            "",
            f"- Query: `{query}`",
            f"- Input Type: `{input_type}`",
            f"- Generated At: `{now_text}`",
            f"- Multi-agent Setup: `{len(active_roles)} agents`, `{rounds} exploration rounds`",
            "",
            "## 1. Domain Status and Paper Relationships",
            f"- Base paper pool: {len(base_papers)}; expansion pool: {len(extension_papers)} (total {len(base_papers) + len(extension_papers)})",
            (
                f"- Graph scale: {graph_stats['node_count']} nodes, "
                f"{graph_stats['edge_count']} edges, {graph_stats['paper_node_count']} paper nodes"
            ),
            "- Current status: the field is advancing in parallel tracks of method innovation and application implementation.",
            "",
            "## 2. Representative Papers and Relationship Clusters",
        ]
        for item in top_papers:
            sections.append(
                f"- {item['title']} ({item['year'] or '-'}), citations {item['citation_count']}, "
                f"venue: {item['venue'] or 'Unknown'}"
            )
        sections.extend(
            [
                "",
                "## 3. Divergent Feasibility Exploration",
            ]
        )
        if hypotheses:
            sections.extend([f"- {note}" for note in hypotheses[:8]])
        else:
            sections.append("- Practical opportunities are concentrated in modular redesign, transfer strategy, and low-cost deployment.")
        sections.extend(
            [
                "",
                "## 4. Multi-agent Deliberation Summary",
                f"- Active roles: {', '.join(role_labels)}",
            ]
        )
        if extension_notes:
            sections.extend([f"- {note}" for note in extension_notes[:6]])
        if decisions:
            sections.extend([f"- {line}" for line in decisions[:6]])
        sections.extend(
            [
                "",
                "## 5. Risks and Constraints",
            ]
        )
        if critic_notes:
            sections.extend([f"- {line}" for line in critic_notes[:6]])
        else:
            sections.append("- Key risks include evaluation mismatch, distribution shift, and engineering budget constraints.")
        sections.extend(
            [
                "",
                "## 6. Recommended Next Actions",
                "- Action 1: build a minimum verifiable prototype around graph bridge nodes.",
                "- Action 2: run dual-track validation (offline benchmark + limited online trial).",
                "- Action 3: persist critical hypotheses into memory and iterate with new evidence.",
            ]
        )
        if history_memory:
            sections.extend(
                [
                    "",
                    "## Appendix: Historical Memory Signals",
                    *[f"- {line}" for line in history_memory[:3]],
                ]
            )
        return "\n".join(sections).strip() + "\n"

    async def _stream_markdown(
        self,
        *,
        markdown: str,
        callback: StreamCallback,
        section: str,
        start_accumulated: int = 0,
    ) -> None:
        chunk_size = 180
        accumulated = max(0, int(start_accumulated or 0))
        for start in range(0, len(markdown), chunk_size):
            chunk = markdown[start:start + chunk_size]
            accumulated += len(chunk)
            await callback(
                {
                    "section": section,
                    "chunk": chunk,
                    "accumulated_chars": accumulated,
                    "done": False,
                }
            )
            await asyncio.sleep(0.02)
        await callback(
            {
                "section": section,
                "chunk": "",
                "accumulated_chars": accumulated,
                "done": True,
            }
        )

    def _persist_artifacts(self, *, session_id: str, markdown: str, language: str) -> dict[str, str]:
        output_dir = self.report_root / session_id
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "insight.md"
        md_path.write_text(markdown, encoding="utf-8")

        pdf_path = output_dir / "insight.pdf"
        if _REPORTLAB_AVAILABLE:
            try:
                self._write_pdf(
                    markdown=markdown,
                    pdf_path=pdf_path,
                    language=language,
                )
            except Exception:  # noqa: BLE001
                pdf_path = Path("")
        else:
            pdf_path = Path("")

        return {
            "markdown_path": str(md_path),
            "pdf_path": str(pdf_path) if str(pdf_path).strip() else "",
        }

    def _write_pdf(self, *, markdown: str, pdf_path: Path, language: str) -> None:
        assert _REPORTLAB_AVAILABLE and canvas is not None and A4 is not None
        font_name = "Helvetica"
        if language == "zh":
            try:
                assert pdfmetrics is not None and UnicodeCIDFont is not None
                pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
                font_name = "STSong-Light"
            except Exception:  # noqa: BLE001
                font_name = "Helvetica"

        doc = canvas.Canvas(str(pdf_path), pagesize=A4)
        width, height = A4
        x = 40
        y = height - 40
        line_height = 15
        doc.setFont(font_name, 11)

        for raw_line in markdown.splitlines():
            text = raw_line.rstrip()
            wrapped = self._wrap_text(text, max_chars=52 if language == "zh" else 96)
            if not wrapped:
                wrapped = [""]
            for segment in wrapped:
                if y <= 45:
                    doc.showPage()
                    doc.setFont(font_name, 11)
                    y = height - 40
                doc.drawString(x, y, segment)
                y -= line_height
        doc.save()

    @staticmethod
    def _wrap_text(text: str, *, max_chars: int) -> list[str]:
        safe = str(text or "")
        if not safe:
            return [""]
        segments: list[str] = []
        cursor = 0
        while cursor < len(safe):
            segments.append(safe[cursor:cursor + max_chars])
            cursor += max_chars
        return segments

    def _build_summary(
        self,
        *,
        language: str,
        extension_count: int,
        role_count: int,
        rounds: int,
        base_papers: int,
    ) -> str:
        if language == "zh":
            return (
                f"探索完成：{role_count} 个 Agents，{rounds} 轮协作，"
                f"基础论文 {base_papers} 篇，扩展新增 {extension_count} 篇。"
            )
        return (
            f"Exploration completed with {role_count} agents across {rounds} rounds, "
            f"{base_papers} base papers and {extension_count} expanded papers."
        )

    @staticmethod
    def _format_line(language: str, *, zh: str, en: str) -> str:
        return zh if language == "zh" else en

    @staticmethod
    def _top_papers_for_prompt(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        sorted_items = sorted(
            [dict(item) for item in items if isinstance(item, dict)],
            key=lambda item: (
                InsightExplorationService._safe_int(item.get("citation_count"), 0),
                InsightExplorationService._safe_int(item.get("year"), 0),
            ),
            reverse=True,
        )
        return sorted_items[: max(1, limit)]

    @staticmethod
    def _merge_papers(
        primary: list[dict[str, Any]],
        secondary: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source in (primary, secondary):
            for item in source:
                if not isinstance(item, dict):
                    continue
                paper_id = str(item.get("paper_id") or "").strip().lower()
                title = re.sub(r"\s+", " ", str(item.get("title") or "").strip().lower())
                key = paper_id or f"title:{title}"
                if not key:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= max(1, limit):
                    return merged
        return merged

    @staticmethod
    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return int(math.floor(float(value)))
        except (TypeError, ValueError):
            return default


@lru_cache
def get_insight_exploration_service() -> InsightExplorationService:
    return InsightExplorationService()
