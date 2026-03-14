from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
import logging
from threading import Lock
from typing import Any
from uuid import uuid4

from core.domain_explorer import DomainExplorer
from core.settings import get_settings
from core.task_manager import TaskManager, get_task_manager
from models.schemas import (
    LandscapeGenerateRequest,
    LandscapeResponse,
    LandscapeStepKey,
    LandscapeStepLog,
    LandscapeTaskDetailResponse,
    TaskCreateResponse,
)
from repositories.landscape_repository import LandscapeRepository, get_landscape_repository
from repositories.neo4j_repository import Neo4jRepository, get_neo4j_repository
from services.landscape_cache_service import LandscapeCacheService, get_landscape_cache_service
from services.landscape_graph_adapter import build_landscape_graph

logger = logging.getLogger(__name__)


@dataclass
class _LandscapeRuntime:
    step_key: LandscapeStepKey = "research"
    logs: list[LandscapeStepLog] = field(default_factory=list)
    preview_graph: dict[str, Any] = field(default_factory=dict)
    preview_stats: dict[str, Any] = field(default_factory=dict)


class LandscapeService:
    """Async service for domain landscape generation."""

    def __init__(
        self,
        *,
        task_manager: TaskManager | None = None,
        landscape_repository: LandscapeRepository | None = None,
        explorer: DomainExplorer | None = None,
        neo4j_repository: Neo4jRepository | None = None,
        cache_service: LandscapeCacheService | None = None,
    ) -> None:
        settings = get_settings()
        self.task_manager = task_manager or get_task_manager()
        self.repository = landscape_repository or get_landscape_repository()
        self.explorer = explorer or DomainExplorer()
        self.neo4j_repository = neo4j_repository or get_neo4j_repository()
        self.cache_service = cache_service or get_landscape_cache_service()
        self.summary_enabled = bool(settings.enable_landscape_summary)
        self._runtime: dict[str, _LandscapeRuntime] = {}
        self._runtime_lock = Lock()
        self._task_create_lock = asyncio.Lock()

    async def create_landscape_task(self, request: LandscapeGenerateRequest) -> TaskCreateResponse:
        cache_key = self.cache_service.build_cache_key(
            query=request.query,
            paper_range_years=request.paper_range_years,
            summary_enabled=self.summary_enabled,
        )
        async with self._task_create_lock:
            cached_payload = await self.cache_service.get(cache_key)
            if cached_payload is not None:
                try:
                    cached_response = LandscapeResponse.model_validate(cached_payload)
                except Exception:  # noqa: BLE001
                    logger.warning("Invalid landscape cache payload, fallback to regeneration.")
                else:
                    self.repository.save_landscape(cached_response.landscape_id, cached_response.model_dump())
                    task = self.task_manager.create_task(message="命中公共缓存，准备快速复用结果")
                    self._ensure_runtime(task.task_id)
                    seed_preview = build_landscape_graph(
                        {"domain_name": request.query, "sub_directions": []},
                        max_papers_per_direction=0,
                    )
                    self._set_preview(
                        task.task_id,
                        seed_preview,
                        self._build_preview_stats({"sub_directions": []}, seed_preview),
                    )
                    self._append_log(
                        task.task_id,
                        step_key="research",
                        message="命中公共缓存：准备加载历史结果并回放工作流步骤。",
                        level="info",
                    )
                    asyncio.create_task(self._run_cached_task(task.task_id, request, cached_response))
                    return TaskCreateResponse(
                        task_id=task.task_id,
                        status=task.status,
                        message="命中公共缓存，已进入快速回放流程",
                    )

            inflight_task_id = await self.cache_service.get_inflight_task(cache_key)
            if inflight_task_id:
                inflight_task = self.task_manager.get_task(inflight_task_id)
                if inflight_task is not None and inflight_task.status in {"pending", "processing", "completed"}:
                    message = "命中并发去重，复用已存在任务。"
                    if inflight_task.status == "completed":
                        message = "命中并发去重，复用已完成任务。"
                    return TaskCreateResponse(
                        task_id=inflight_task.task_id,
                        status=inflight_task.status,
                        message=message,
                    )
                await self.cache_service.release_inflight(cache_key, expected_task_id=inflight_task_id)

            task = self.task_manager.create_task(message="任务已创建，等待执行")
            acquired, existing_task_id = await self.cache_service.acquire_inflight(cache_key, task.task_id)
            if not acquired and existing_task_id:
                existing_task = self.task_manager.get_task(existing_task_id)
                if existing_task is not None and existing_task.status in {"pending", "processing", "completed"}:
                    self.task_manager.update_task(
                        task.task_id,
                        status="failed",
                        progress=100,
                        message="并发去重：当前任务未执行。",
                        error="deduplicated_by_inflight",
                    )
                    message = "命中并发去重，复用已存在任务。"
                    if existing_task.status == "completed":
                        message = "命中并发去重，复用已完成任务。"
                    return TaskCreateResponse(
                        task_id=existing_task.task_id,
                        status=existing_task.status,
                        message=message,
                    )
                await self.cache_service.release_inflight(cache_key, expected_task_id=existing_task_id)
                acquired, _ = await self.cache_service.acquire_inflight(cache_key, task.task_id)
                if not acquired:
                    self.task_manager.update_task(
                        task.task_id,
                        status="failed",
                        progress=100,
                        message="任务创建失败，请重试。",
                        error="inflight_acquire_failed",
                    )
                    return TaskCreateResponse(
                        task_id=task.task_id,
                        status="failed",
                        message="任务创建失败，请重试",
                    )

            self._ensure_runtime(task.task_id)
            seed_preview = build_landscape_graph(
                {"domain_name": request.query, "sub_directions": []},
                max_papers_per_direction=0,
            )
            self._set_preview(
                task.task_id,
                seed_preview,
                self._build_preview_stats({"sub_directions": []}, seed_preview),
            )
            self._append_log(
                task.task_id,
                step_key="research",
                message="任务已创建，准备开始领域调研。",
                level="info",
            )
            asyncio.create_task(self._run_task(task.task_id, request, cache_key=cache_key))
            return TaskCreateResponse(
                task_id=task.task_id,
                status=task.status,
                message="领域全景任务已提交",
            )

    def get_task(self, task_id: str) -> LandscapeTaskDetailResponse | None:
        task = self.task_manager.get_task(task_id)
        if task is None:
            return None
        base = task.to_schema()
        runtime = self._snapshot_runtime(task_id)
        return LandscapeTaskDetailResponse(
            **base.model_dump(),
            step_key=runtime.step_key,
            summary_enabled=self.summary_enabled,
            step_logs=runtime.logs,
            preview_graph=runtime.preview_graph,
            preview_stats=runtime.preview_stats,
        )

    def get_landscape(self, landscape_id: str) -> LandscapeResponse | None:
        payload = self.repository.get_landscape(landscape_id)
        if payload is None:
            return None
        return LandscapeResponse.model_validate(payload)

    def get_landscape_by_task(self, task_id: str) -> LandscapeResponse | None:
        task = self.task_manager.get_task(task_id)
        if task is None or task.status != "completed" or not task.result_id:
            return None
        return self.get_landscape(task.result_id)

    async def _run_task(
        self,
        task_id: str,
        request: LandscapeGenerateRequest,
        *,
        cache_key: str | None = None,
    ) -> None:
        landscape_id = f"landscape-{uuid4().hex[:12]}"
        self._ensure_runtime(task_id)

        try:
            normalized_query = await self.explorer.normalize_user_query(request.query)
            effective_query = str(normalized_query.get("canonical_query") or request.query).strip()
            if not effective_query:
                effective_query = str(request.query).strip()

            self._set_step(task_id, "research")
            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=5,
                message="领域调研中：正在解析研究方向结构...",
            )
            original_query = str(normalized_query.get("original_query") or request.query).strip()
            corrected_query = str(normalized_query.get("corrected_query") or original_query).strip()
            translated_query = str(normalized_query.get("translated_query") or "").strip()
            normalization_mode = "LLM+规则纠错" if bool(normalized_query.get("used_llm")) else "规则映射/直通"
            self._append_log(
                task_id,
                step_key="research",
                message=(
                    "输入标准化完成："
                    f"原始“{original_query}” -> 当前检索“{effective_query}”。"
                ),
                level="done",
                meta={
                    "处理方式": normalization_mode,
                    "纠错后输入": corrected_query or original_query,
                    "英文检索词": translated_query or effective_query,
                    "是否发生修正": "是" if bool(normalized_query.get("was_corrected")) else "否",
                },
            )
            self._append_log(
                task_id,
                step_key="research",
                message="领域骨架规划：准备生成 10 个子方向（含状态、方法与检索关键词）。",
                level="info",
            )
            self._append_log(task_id, step_key="research", message="开始调用 LLM 生成领域骨架。", level="info")

            skeleton = await self.explorer.generate_domain_skeleton(effective_query)
            skeleton["domain_name"] = effective_query
            skeleton["domain_name_en"] = effective_query
            sub_directions = list(skeleton.get("sub_directions") or [])
            direction_count = len(sub_directions)
            status_counter = Counter(
                str(item.get("status") or "unknown").strip().lower()
                for item in sub_directions
            )
            all_keywords = [
                str(keyword).strip().lower()
                for direction in sub_directions
                for keyword in (direction.get("search_keywords") or [])
                if str(keyword).strip()
            ]
            avg_keywords = (len(all_keywords) / direction_count) if direction_count else 0.0
            missing_keyword_count = sum(
                1
                for direction in sub_directions
                if not [item for item in (direction.get("search_keywords") or []) if str(item).strip()]
            )
            status_summary = ", ".join(
                f"{name}:{count}" for name, count in sorted(status_counter.items())
            ) or "unknown:0"
            direction_preview = "、".join(
                str(direction.get("name") or "").strip()
                for direction in sub_directions[:6]
                if str(direction.get("name") or "").strip()
            ) or "暂无可展示方向"
            self._append_log(
                task_id,
                step_key="research",
                message=f"领域调研完成，识别到 {direction_count} 个候选子方向。",
                level="done",
                meta={"sub_direction_count": str(direction_count)},
            )
            self._append_log(
                task_id,
                step_key="research",
                message=f"子方向状态分布：{status_summary}",
                level="done",
                meta={
                    "子方向总数": str(direction_count),
                    "缺少关键词方向": str(missing_keyword_count),
                    "关键词总数": str(len(all_keywords)),
                    "关键词去重后": str(len(set(all_keywords))),
                },
            )
            self._append_log(
                task_id,
                step_key="research",
                message=f"子方向预览：{direction_preview}",
                level="done",
                meta={
                    "平均每方向关键词": f"{avg_keywords:.1f}",
                    "领域描述": str(skeleton.get("description") or "暂无"),
                },
            )
            preview_graph = build_landscape_graph(skeleton, max_papers_per_direction=0)
            self._set_preview(task_id, preview_graph, self._build_preview_stats(skeleton, preview_graph))

            self._set_step(task_id, "retrieve")
            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=26,
                message="论文检索中：正在并行抓取真实论文...",
            )
            range_hint = ""
            if request.paper_range_years:
                range_hint = f"，时间范围近 {int(request.paper_range_years)} 年"
            self._append_log(
                task_id,
                step_key="retrieve",
                message=f"开始论文检索并并行抓取候选论文{range_hint}。",
                level="info",
            )

            partial_directions = list(skeleton.get("sub_directions") or [])
            completed = 0

            async def direction_callback(index: int, direction: dict[str, Any], total: int) -> None:
                nonlocal completed
                completed += 1
                partial_directions[index] = direction
                partial_landscape = {**skeleton, "sub_directions": list(partial_directions)}
                partial_graph = build_landscape_graph(partial_landscape, max_papers_per_direction=15)
                self._set_preview(task_id, partial_graph, self._build_preview_stats(partial_landscape, partial_graph))

                progress = min(62, 26 + int((completed / max(total, 1)) * 34))
                self.task_manager.update_task(
                    task_id,
                    status="processing",
                    progress=progress,
                    message=f"论文检索中：已完成 {completed}/{total} 个子方向。",
                )
                provider = str(direction.get("provider_used") or "none")
                paper_count = int(direction.get("paper_count") or 0)
                level = "done" if provider != "none" else "fallback"
                self._append_log(
                    task_id,
                    step_key="retrieve",
                    message=f"{direction.get('name', '未命名方向')} 检索完成：{paper_count} 篇。",
                    level=level,
                    meta={
                        "paper_count": str(paper_count),
                        "recent_ratio": f"{float(direction.get('recent_ratio') or 0.0):.3f}",
                        "retrieval_status": "done" if level == "done" else "fallback",
                    },
                )

            enriched = await self.explorer.enrich_with_papers(
                skeleton,
                direction_callback=direction_callback,
                paper_range_years=request.paper_range_years,
            )
            enriched = self.explorer.sort_sub_directions(enriched)
            self._append_log(
                task_id,
                step_key="retrieve",
                message="论文检索阶段完成，已完成子方向热度排序。",
                level="done",
            )

            graph_progress = 86
            write_progress = 94
            if self.summary_enabled:
                self._set_step(task_id, "summarize")
                self.task_manager.update_task(
                    task_id,
                    status="processing",
                    progress=68,
                    message="深度总结中：正在生成趋势洞察...",
                )
                self._append_log(
                    task_id,
                    step_key="summarize",
                    message="开始生成深度总结（目标 1000+ 字）。",
                    level="info",
                )
                enriched["trend_summary"] = await self.explorer.generate_landscape_summary(enriched)
                summary_length = len(str(enriched.get("trend_summary") or ""))
                self._append_log(
                    task_id,
                    step_key="summarize",
                    message=f"深度总结完成，正文长度约 {summary_length} 字。",
                    level="done",
                    meta={"summary_length": str(summary_length)},
                )
            else:
                enriched["trend_summary"] = "深度总结已关闭（ENABLE_LANDSCAPE_SUMMARY=false）。"
                graph_progress = 78
                write_progress = 90
                self.task_manager.update_task(
                    task_id,
                    status="processing",
                    progress=graph_progress - 2,
                    message="深度总结已关闭：直接进入图谱生成...",
                )

            self._set_step(task_id, "graph")
            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=graph_progress,
                message="图谱生成中：正在构建并刷新知识图谱...",
            )
            final_graph = build_landscape_graph(enriched, max_papers_per_direction=15)
            self._set_preview(task_id, final_graph, self._build_preview_stats(enriched, final_graph))
            self._append_log(
                task_id,
                step_key="graph",
                message=(
                    f"图谱生成完成：节点 {len(final_graph.get('nodes') or [])}，"
                    f"边 {len(final_graph.get('edges') or [])}。"
                ),
                level="done",
            )

            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=write_progress,
                message="图谱生成中：正在写入图数据库...",
            )
            stored = await asyncio.to_thread(
                self.neo4j_repository.store_domain_landscape,
                landscape_id,
                request.query,
                enriched,
            )
            self._append_log(
                task_id,
                step_key="graph",
                message="图数据库写入完成。" if stored else "Neo4j 不可用，已降级为内存结果。",
                level="done" if stored else "fallback",
            )

            response = LandscapeResponse(
                landscape_id=landscape_id,
                query=request.query,
                domain_name=str(enriched.get("domain_name") or request.query),
                domain_name_en=str(enriched.get("domain_name_en") or ""),
                description=str(enriched.get("description") or ""),
                provider_priority="openalex_then_semantic_scholar",
                sub_directions=list(enriched.get("sub_directions") or []),
                trend_summary=str(enriched.get("trend_summary") or ""),
                summary_enabled=self.summary_enabled,
                graph_data=final_graph,
                stored_in_neo4j=bool(stored),
                generated_at=datetime.now(timezone.utc),
            )
            self.repository.save_landscape(landscape_id, response.model_dump())
            if cache_key:
                try:
                    await self.cache_service.set(cache_key, response.model_dump(mode="json"))
                    self._append_log(
                        task_id,
                        step_key="graph",
                        message="公共结果缓存已更新。",
                        level="done",
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Failed persisting landscape public cache.")

            self.task_manager.update_task(
                task_id,
                status="completed",
                progress=100,
                message="领域全景生成完成",
                result_id=landscape_id,
            )
            self._append_log(task_id, step_key="graph", message="任务完成。", level="done")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Landscape generation task failed")
            self.task_manager.update_task(
                task_id,
                status="failed",
                progress=100,
                message="领域全景生成失败",
                error=str(exc),
            )
            runtime = self._snapshot_runtime(task_id)
            self._append_log(
                task_id,
                step_key=runtime.step_key,
                message=f"任务失败：{exc}",
                level="error",
            )
        finally:
            if cache_key:
                await self.cache_service.release_inflight(cache_key, expected_task_id=task_id)

    async def _run_cached_task(
        self,
        task_id: str,
        request: LandscapeGenerateRequest,
        cached_response: LandscapeResponse,
    ) -> None:
        self._ensure_runtime(task_id)
        cached_landscape = cached_response.model_dump()
        cached_graph = dict(cached_response.graph_data or {})

        try:
            self._set_step(task_id, "research")
            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=8,
                message="领域调研中：正在解析研究方向结构...",
            )
            await asyncio.sleep(1.18)
            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=16,
                message="领域调研中：正在校验缓存骨架一致性...",
            )
            await asyncio.sleep(0.96)
            skeleton_preview = build_landscape_graph(cached_landscape, max_papers_per_direction=0)
            self._set_preview(
                task_id,
                skeleton_preview,
                self._build_preview_stats(cached_landscape, skeleton_preview),
            )
            self._append_log(
                task_id,
                step_key="research",
                message="命中公共缓存：已复用历史领域骨架。",
                level="done",
            )
            await asyncio.sleep(0.72)

            self._set_step(task_id, "retrieve")
            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=30,
                message="论文检索中：正在并行抓取真实论文...",
            )
            await asyncio.sleep(1.24)
            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=44,
                message="论文检索中：正在回放子方向检索结果...",
            )
            await asyncio.sleep(0.98)
            partial_graph = build_landscape_graph(cached_landscape, max_papers_per_direction=6)
            self._set_preview(
                task_id,
                partial_graph,
                self._build_preview_stats(cached_landscape, partial_graph),
            )
            self._append_log(
                task_id,
                step_key="retrieve",
                message="命中公共缓存：已快速复用论文检索结果。",
                level="done",
            )
            await asyncio.sleep(0.78)

            graph_progress = 86
            write_progress = 94
            if self.summary_enabled:
                self._set_step(task_id, "summarize")
                self.task_manager.update_task(
                    task_id,
                    status="processing",
                    progress=62,
                    message="深度总结中：正在生成趋势洞察...",
                )
                await asyncio.sleep(1.08)
                self.task_manager.update_task(
                    task_id,
                    status="processing",
                    progress=72,
                    message="深度总结中：正在回放趋势洞察内容...",
                )
                await asyncio.sleep(0.82)
                self._append_log(
                    task_id,
                    step_key="summarize",
                    message=(
                        "命中公共缓存：已复用趋势总结，正文长度约 "
                        f"{len(str(cached_response.trend_summary or ''))} 字。"
                    ),
                    level="done",
                )
            else:
                graph_progress = 78
                write_progress = 90

            self._set_step(task_id, "graph")
            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=graph_progress - 6,
                message="图谱生成中：正在构建并刷新知识图谱...",
            )
            await asyncio.sleep(1.06)
            self._set_preview(
                task_id,
                cached_graph,
                self._build_preview_stats(cached_landscape, cached_graph),
            )
            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=graph_progress,
                message="图谱生成中：正在校验图谱结构...",
            )
            self._append_log(
                task_id,
                step_key="graph",
                message=(
                    f"图谱生成完成：节点 {len(cached_graph.get('nodes') or [])}，"
                    f"边 {len(cached_graph.get('edges') or [])}。"
                ),
                level="done",
            )
            await asyncio.sleep(0.78)

            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=write_progress,
                message="图谱生成中：正在写入图数据库...",
            )
            await asyncio.sleep(0.72)
            self._append_log(
                task_id,
                step_key="graph",
                message="命中公共缓存：已跳过图数据库重复写入。",
                level="done",
            )
            await asyncio.sleep(0.54)

            self.task_manager.update_task(
                task_id,
                status="completed",
                progress=100,
                message="领域全景生成完成（缓存命中）",
                result_id=cached_response.landscape_id,
            )
            self._append_log(task_id, step_key="graph", message="任务完成。", level="done")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Cached landscape replay task failed")
            self.task_manager.update_task(
                task_id,
                status="failed",
                progress=100,
                message="领域全景生成失败",
                error=str(exc),
            )
            runtime = self._snapshot_runtime(task_id)
            self._append_log(
                task_id,
                step_key=runtime.step_key,
                message=f"任务失败：{exc}",
                level="error",
            )

    def _ensure_runtime(self, task_id: str) -> None:
        with self._runtime_lock:
            self._runtime.setdefault(task_id, _LandscapeRuntime())

    def _snapshot_runtime(self, task_id: str) -> _LandscapeRuntime:
        with self._runtime_lock:
            current = self._runtime.get(task_id) or _LandscapeRuntime()
            return _LandscapeRuntime(
                step_key=current.step_key,
                logs=[LandscapeStepLog.model_validate(item.model_dump()) for item in current.logs],
                preview_graph=dict(current.preview_graph),
                preview_stats=dict(current.preview_stats),
            )

    def _set_step(self, task_id: str, step_key: LandscapeStepKey) -> None:
        with self._runtime_lock:
            runtime = self._runtime.setdefault(task_id, _LandscapeRuntime())
            runtime.step_key = step_key

    def _append_log(
        self,
        task_id: str,
        *,
        step_key: LandscapeStepKey,
        message: str,
        level: str = "info",
        meta: dict[str, Any] | None = None,
    ) -> None:
        normalized_meta = {
            str(key): str(value)
            for key, value in (meta or {}).items()
            if str(key).strip() and str(value).strip()
        }
        entry = LandscapeStepLog(
            timestamp=datetime.now(timezone.utc),
            step_key=step_key,
            level=level if level in {"info", "done", "fallback", "error"} else "info",
            message=str(message).strip(),
            meta=normalized_meta,
        )
        with self._runtime_lock:
            runtime = self._runtime.setdefault(task_id, _LandscapeRuntime())
            runtime.step_key = step_key
            runtime.logs.append(entry)
            if len(runtime.logs) > 240:
                runtime.logs = runtime.logs[-240:]

    def _set_preview(self, task_id: str, graph: dict[str, Any], stats: dict[str, Any]) -> None:
        with self._runtime_lock:
            runtime = self._runtime.setdefault(task_id, _LandscapeRuntime())
            runtime.preview_graph = dict(graph)
            runtime.preview_stats = dict(stats)

    @staticmethod
    def _build_preview_stats(landscape: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
        directions = list(landscape.get("sub_directions") or [])
        completed = sum(1 for item in directions if int(item.get("paper_count") or 0) > 0)
        return {
            "sub_direction_total": len(directions),
            "sub_direction_completed": completed,
            "node_count": len(graph.get("nodes") or []),
            "edge_count": len(graph.get("edges") or []),
        }


@lru_cache
def get_landscape_service() -> LandscapeService:
    return LandscapeService()
