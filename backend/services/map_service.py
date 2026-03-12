from __future__ import annotations

import asyncio
from functools import lru_cache
import logging

from core.graph_builder import GraphBuilder
from core.paper_fetcher import PaperFetcher
from core.settings import get_settings
from core.task_manager import TaskManager, get_task_manager
from models.schemas import MapGenerateRequest, MapResponse, TaskCreateResponse, TaskDetailResponse

logger = logging.getLogger(__name__)


class MapService:
    def __init__(self, task_manager: TaskManager | None = None) -> None:
        self.task_manager = task_manager or get_task_manager()
        self.paper_fetcher = PaperFetcher()
        self.graph_builder = GraphBuilder()
        self.settings = get_settings()

    async def create_map_task(self, request: MapGenerateRequest) -> TaskCreateResponse:
        task = self.task_manager.create_task(message="任务已创建，等待执行")
        asyncio.create_task(self._run_task(task.task_id, request))
        return TaskCreateResponse(
            task_id=task.task_id,
            status=task.status,
            message="地图生成任务已提交",
        )

    async def _run_task(self, task_id: str, request: MapGenerateRequest) -> None:
        try:
            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=8,
                message="正在解析输入类型",
            )
            await asyncio.sleep(self.settings.task_progress_step_seconds)

            breadth = min(200, 30 + request.depth * 35)
            seed_document = self.paper_fetcher.fetch_seed_document(
                input_type=request.input_type,
                input_value=request.input_value,
                reference_limit=breadth,
                citation_limit=breadth,
            )

            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=42,
                message="正在抓取论文元数据和引用信息",
            )
            await asyncio.sleep(self.settings.task_progress_step_seconds)

            map_payload = self.graph_builder.build_domain_map(
                seed_document=seed_document,
                depth=request.depth,
            )

            self.task_manager.store_map(map_payload.map_id, map_payload.model_dump())
            self.task_manager.update_task(
                task_id,
                status="processing",
                progress=85,
                message="正在生成趋势解读",
            )
            await asyncio.sleep(self.settings.task_progress_step_seconds)

            self.task_manager.update_task(
                task_id,
                status="completed",
                progress=100,
                message="任务完成",
                result_id=map_payload.map_id,
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception("Map generation task failed")
            self.task_manager.update_task(
                task_id,
                status="failed",
                progress=100,
                message="任务失败",
                error=str(exc),
            )

    def get_task(self, task_id: str) -> TaskDetailResponse | None:
        task = self.task_manager.get_task(task_id)
        return task.to_schema() if task else None

    def get_map(self, map_id: str) -> MapResponse | None:
        payload = self.task_manager.get_map(map_id)
        return MapResponse(**payload) if payload else None


@lru_cache
def get_map_service() -> MapService:
    return MapService()
