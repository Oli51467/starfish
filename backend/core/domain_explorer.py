from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import json
import logging
import re
from typing import Any

from core.llm_client import chat, is_configured
from external.openalex import OpenAlexClient, OpenAlexClientError
from external.semantic_scholar import SemanticScholarClient, SemanticScholarClientError

logger = logging.getLogger(__name__)


ProgressCallback = Callable[[int, str], Any]
DirectionProgressCallback = Callable[[int, dict[str, Any], int], Any]


class DomainExplorer:
    """Generate domain landscape with LLM skeleton + real paper evidence."""

    _STATUS_VALUES = {"emerging", "growing", "stable", "saturated"}
    _TARGET_DIRECTIONS = 10
    _MIN_DIRECTIONS = 10
    _MAX_DIRECTIONS = 10
    _ZH_TO_EN = {
        "深度强化学习": "deep reinforcement learning",
        "强化学习": "reinforcement learning",
        "多模态大模型": "multimodal large language model",
        "多模态": "multimodal learning",
        "大模型": "large language model",
        "transformer": "transformer",
        "扩散模型": "diffusion model",
        "图神经网络": "graph neural network",
        "推荐系统": "recommender system",
        "计算机视觉": "computer vision",
        "自然语言处理": "natural language processing",
    }

    def __init__(
        self,
        *,
        semantic_client: SemanticScholarClient | None = None,
        openalex_client: OpenAlexClient | None = None,
    ) -> None:
        self.semantic = semantic_client or SemanticScholarClient()
        self.openalex = openalex_client or OpenAlexClient()

    async def generate_landscape(
        self,
        query: str,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        safe_query = str(query or "").strip()
        if not safe_query:
            raise ValueError("query must not be empty")

        await self._emit_progress(progress_callback, 10, "LLM 正在分析领域结构...")
        skeleton = await self.generate_domain_skeleton(safe_query)

        await self._emit_progress(progress_callback, 45, "正在抓取真实论文数据...")
        enriched = await self.enrich_with_papers(skeleton)

        await self._emit_progress(progress_callback, 70, "正在计算热度趋势...")
        enriched = self.sort_sub_directions(enriched)

        await self._emit_progress(progress_callback, 88, "正在生成趋势洞察...")
        enriched["trend_summary"] = await self.generate_landscape_summary(enriched)
        return enriched

    async def generate_domain_skeleton(self, query: str) -> dict[str, Any]:
        if not is_configured():
            return self._fallback_skeleton(query)

        prompt = f"""你是一位资深学术研究员，请分析以下研究领域的全景结构。

研究领域：{query}

请返回严格 JSON，格式如下：
{{
  "domain_name": "领域标准名称",
  "domain_name_en": "English name",
  "description": "简短描述（50字以内）",
  "sub_directions": [
    {{
      "name": "子方向名称",
      "name_en": "English name",
      "description": "子方向简短描述",
      "status": "emerging|growing|stable|saturated",
      "methods": ["代表方法1", "代表方法2"],
      "search_keywords": ["英文检索关键词1", "关键词2"],
      "estimated_active_years": "2020-2025"
    }}
  ]
}}

要求：
1. 子方向数量必须是 10 个，覆盖主流分支并避免语义重叠
2. search_keywords 必须是英文学术搜索词
3. status 仅允许 emerging/growing/stable/saturated
4. 只输出 JSON，不输出解释文本"""

        try:
            response = await asyncio.to_thread(
                chat,
                [{"role": "user", "content": prompt}],
                max_tokens=1800,
                timeout=35,
            )
            raw_content = str(response.choices[0].message.content or "").strip()
            parsed = self._extract_json_payload(raw_content)
            return self._normalize_skeleton(parsed, query)
        except Exception:  # noqa: BLE001
            logger.exception("Failed generating skeleton with LLM, falling back to template.")
            return self._fallback_skeleton(query)

    async def enrich_with_papers(
        self,
        skeleton: dict[str, Any],
        *,
        direction_callback: DirectionProgressCallback | None = None,
    ) -> dict[str, Any]:
        semaphore = asyncio.Semaphore(3)
        directions = list(skeleton.get("sub_directions") or [])

        async def fetch_direction(index: int, direction: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                keywords = [
                    str(item).strip()
                    for item in (direction.get("search_keywords") or [])
                    if str(item).strip()
                ]
                if direction.get("name_en"):
                    keywords.append(str(direction["name_en"]).strip())
                keywords.append(self._normalize_query_for_search(str(direction.get("name") or "")))
                if not keywords:
                    keywords = [self._normalize_query_for_search(str(skeleton.get("domain_name") or ""))]

                dedup_keywords: list[str] = []
                seen: set[str] = set()
                for item in keywords:
                    lowered = item.lower()
                    if not item or lowered in seen:
                        continue
                    seen.add(lowered)
                    dedup_keywords.append(item)

                merged_papers: list[dict[str, Any]] = []
                used_providers: list[str] = []
                used_keyword = dedup_keywords[0] if dedup_keywords else ""
                searched_keywords: set[str] = set()
                for keyword in dedup_keywords[:3]:
                    lowered = keyword.lower()
                    if lowered in searched_keywords:
                        continue
                    searched_keywords.add(lowered)
                    papers, provider = await self.search_papers_by_keyword(keyword, limit=50)
                    if papers:
                        merged_papers = self._merge_papers_by_identity(merged_papers, papers, max_size=120)
                        used_keyword = keyword
                        if provider and provider not in used_providers:
                            used_providers.append(provider)
                    if len(merged_papers) >= 90:
                        break

                # Top-up retrieval to improve the chance of getting >=15 core papers per direction.
                if len(merged_papers) < 15:
                    direction_query = self._normalize_query_for_search(
                        str(direction.get("name_en") or direction.get("name") or "")
                    )
                    domain_query = self._normalize_query_for_search(
                        str(skeleton.get("domain_name_en") or skeleton.get("domain_name") or "")
                    )
                    fallback_keywords = []
                    if direction_query:
                        fallback_keywords.extend(
                            [
                                f"{direction_query} survey".strip(),
                                f"{direction_query} review".strip(),
                            ]
                        )
                    if domain_query and direction_query:
                        fallback_keywords.append(f"{domain_query} {direction_query}".strip())
                    if domain_query:
                        fallback_keywords.append(domain_query)
                    for keyword in fallback_keywords:
                        normalized = str(keyword).strip()
                        lowered = normalized.lower()
                        if not normalized or lowered in searched_keywords:
                            continue
                        searched_keywords.add(lowered)
                        papers, provider = await self.search_papers_by_keyword(normalized, limit=40)
                        if papers:
                            merged_papers = self._merge_papers_by_identity(merged_papers, papers, max_size=140)
                            used_keyword = normalized
                            if provider and provider not in used_providers:
                                used_providers.append(provider)
                        if len(merged_papers) >= 15:
                            break

                papers = self._rank_direction_papers(merged_papers)[:70]
                provider = "+".join(used_providers) if used_providers else "none"

                enriched_direction = self._build_direction_metrics(
                    direction=direction,
                    papers=papers,
                    provider=provider,
                    used_keyword=used_keyword,
                )
                if direction_callback is not None:
                    maybe_awaitable = direction_callback(index, enriched_direction, len(directions))
                    if asyncio.iscoroutine(maybe_awaitable):
                        await maybe_awaitable
                return enriched_direction

        enriched_directions = await asyncio.gather(
            *(fetch_direction(index, item) for index, item in enumerate(directions))
        )
        return {
            **skeleton,
            "sub_directions": list(enriched_directions),
        }

    async def search_papers_by_keyword(
        self,
        keyword: str,
        *,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], str]:
        safe_keyword = str(keyword or "").strip()
        if not safe_keyword:
            return [], ""

        safe_limit = max(1, min(int(limit), 50))
        openalex_error: Exception | None = None
        try:
            openalex_payload = await asyncio.to_thread(self.openalex.search_papers, safe_keyword, safe_limit, 0)
            openalex_papers = list(openalex_payload.get("papers") or [])
            if openalex_papers:
                return openalex_papers, "openalex"
        except OpenAlexClientError as exc:
            openalex_error = exc

        try:
            semantic_payload = await asyncio.to_thread(self.semantic.search_papers, safe_keyword, safe_limit, 0)
            semantic_papers = list(semantic_payload.get("papers") or [])
            if semantic_papers:
                return semantic_papers, "semantic_scholar"
        except SemanticScholarClientError as exc:
            if openalex_error is not None:
                logger.warning(
                    "OpenAlex and Semantic Scholar both unavailable for keyword '%s': openalex=%s, semantic=%s",
                    safe_keyword,
                    openalex_error,
                    exc,
                )
            else:
                logger.warning("Semantic Scholar unavailable for keyword '%s': %s", safe_keyword, exc)

        return [], ""

    async def generate_landscape_summary(self, landscape: dict[str, Any]) -> str:
        directions = list(landscape.get("sub_directions") or [])
        if not directions:
            return "暂未检索到足够论文数据，建议细化领域关键词后重试。"

        if not is_configured():
            return self._fallback_summary(landscape)

        direction_lines = []
        for direction in directions[:8]:
            direction_lines.append(
                "- "
                f"{direction.get('name', 'Unknown')}："
                f"{int(direction.get('paper_count') or 0)}篇，"
                f"近2年占比{float(direction.get('recent_ratio') or 0):.0%}，"
                f"均引用{int(direction.get('avg_citations') or 0)}，"
                f"状态={direction.get('status', 'stable')}"
            )

        prompt = (
            f"你是一名资深科研情报分析师。请基于以下 {landscape.get('domain_name', '')} 领域数据，"
            "撰写一份深度趋势洞察报告。\n\n"
            f"{chr(10).join(direction_lines)}\n\n"
            "要求：\n"
            "1. 正文必须不少于1000字。\n"
            "2. 使用连续自然段输出，不要 markdown 标题、不要序号。\n"
            "3. 必须覆盖：领域现状、核心赛道对比、近三年机会、经典方向价值、潜在瓶颈、"
            "未来1-3年可执行建议。\n"
            "4. 结论必须结合给定数据，不要空泛表述。"
        )

        try:
            response = await asyncio.to_thread(
                chat,
                [{"role": "user", "content": prompt}],
                max_tokens=2200,
                timeout=45,
            )
            text = str(response.choices[0].message.content or "").strip()
            if text and len(text) >= 1000:
                return text
        except Exception:  # noqa: BLE001
            logger.exception("Failed generating landscape summary with LLM, fallback to template summary.")

        return self._fallback_summary(landscape)

    async def _emit_progress(
        self,
        callback: ProgressCallback | None,
        progress: int,
        message: str,
    ) -> None:
        if callback is None:
            return
        maybe_awaitable = callback(progress, message)
        if asyncio.iscoroutine(maybe_awaitable):
            await maybe_awaitable

    def _build_direction_metrics(
        self,
        *,
        direction: dict[str, Any],
        papers: list[dict[str, Any]],
        provider: str,
        used_keyword: str,
    ) -> dict[str, Any]:
        current_year = datetime.now(timezone.utc).year
        total = len(papers)
        recent_papers = [
            paper
            for paper in papers
            if self._safe_int(paper.get("year")) >= current_year - 2
        ]
        recent_ratio = (len(recent_papers) / total) if total else 0.0
        avg_citations = (
            sum(self._safe_int(paper.get("citation_count")) for paper in papers) / total if total else 0.0
        )
        target_paper_count = max(15, min(total, 20)) if total else 0
        top_papers = self._select_core_papers(papers, current_year=current_year, limit=target_paper_count)

        normalized_status = self._calibrate_status(
            default_status=str(direction.get("status") or "stable"),
            total=total,
            recent_ratio=recent_ratio,
            avg_citations=avg_citations,
        )
        correlation_score = self._compute_correlation_score(
            total=total,
            recent_ratio=recent_ratio,
            avg_citations=avg_citations,
        )
        core_papers = [self._normalize_core_paper(item, provider=provider) for item in top_papers]
        core_papers = [item for item in core_papers if item.get("id") and item.get("title")]

        next_keywords = [str(item).strip() for item in (direction.get("search_keywords") or []) if str(item).strip()]
        if used_keyword and used_keyword not in next_keywords:
            next_keywords = [used_keyword, *next_keywords]

        return {
            **direction,
            "status": normalized_status,
            "provider_used": provider or "none",
            "paper_count": total,
            "recent_ratio": round(recent_ratio, 3),
            "recent_paper_count": len(recent_papers),
            "avg_citations": int(round(avg_citations)),
            "correlation_score": round(correlation_score, 3),
            "search_keywords": next_keywords[:6],
            "core_papers": core_papers,
        }

    def _normalize_core_paper(self, paper: dict[str, Any], *, provider: str) -> dict[str, Any]:
        title = str(paper.get("title") or "").strip()
        paper_id = str(paper.get("paper_id") or paper.get("id") or "").strip()
        if not paper_id and title:
            paper_id = f"{provider}:{self._slug(title)}"
        authors = [str(item).strip() for item in (paper.get("authors") or []) if str(item).strip()]
        return {
            "id": paper_id,
            "title": title,
            "year": self._safe_int_or_none(paper.get("year")),
            "citation_count": self._safe_int(paper.get("citation_count")),
            "authors": authors[:3],
        }

    def _calibrate_status(
        self,
        *,
        default_status: str,
        total: int,
        recent_ratio: float,
        avg_citations: float,
    ) -> str:
        status = str(default_status or "stable").strip().lower()
        if status not in self._STATUS_VALUES:
            status = "stable"

        if total <= 0:
            return status
        if total < 8 and recent_ratio >= 0.25:
            return "emerging"
        if recent_ratio >= 0.55:
            return "growing"
        if avg_citations >= 450 and recent_ratio < 0.2:
            return "saturated"
        if recent_ratio >= 0.35:
            return "stable"
        return status

    def _heat_score(self, direction: dict[str, Any]) -> float:
        if direction.get("correlation_score") is not None:
            return float(direction.get("correlation_score") or 0.0)
        return self._compute_correlation_score(
            total=int(direction.get("paper_count") or 0),
            recent_ratio=float(direction.get("recent_ratio") or 0.0),
            avg_citations=float(direction.get("avg_citations") or 0.0),
        )

    def sort_sub_directions(self, landscape: dict[str, Any]) -> dict[str, Any]:
        sub_directions = list(landscape.get("sub_directions") or [])
        sub_directions.sort(key=self._heat_score, reverse=True)
        return {**landscape, "sub_directions": sub_directions}

    def _fallback_summary(self, landscape: dict[str, Any]) -> str:
        directions = list(landscape.get("sub_directions") or [])
        if not directions:
            return "当前数据不足，建议扩大关键词范围后重试。"

        domain = str(landscape.get("domain_name") or "该领域")
        top = directions[0]
        emerging = [str(item.get("name") or "") for item in directions if item.get("status") == "emerging"]
        saturated = [str(item.get("name") or "") for item in directions if item.get("status") == "saturated"]

        paragraphs = [
            (
                f"{domain} 的研究生态呈现出“主干稳定、局部爆发、应用回流基础理论”的结构。"
                f"从当前样本看，最活跃方向是 {str(top.get('name') or '未知方向')}，近两年论文占比约 "
                f"{float(top.get('recent_ratio') or 0):.0%}，样本量 {int(top.get('paper_count') or 0)} 篇。"
                "这意味着学界和工业界对该方向的增量投入仍在持续，短期内仍会有高质量工作出现。"
            ),
            (
                "从赛道分化看，增速较高方向通常具备三个共同特征：一是任务定义清晰并具备可扩展 benchmark；"
                "二是训练和部署成本可被工程优化吸收；三是能够被上游基础模型能力红利直接放大。"
                "因此在选题上，不建议只追逐热点名词，而应优先关注“可度量改进”和“跨场景可复现”两个维度。"
            ),
            (
                "近三年的机会主要集中在效率、可解释性、数据质量与多任务迁移的交叉区域。"
                "这些方向往往不是单点算法创新，而是体系化优化：包括数据构造、评测协议、训练策略、"
                "推理链路和错误分析闭环。对于希望快速形成成果的团队，建议先在公开数据集形成可复现实验基线，"
                "再叠加任务约束或行业先验，通常比完全从零提出新范式更稳健。"
            ),
            (
                "经典论文虽然发布时间较早，但在今天仍然具有不可替代的结构性价值。"
                "奠基工作定义了问题边界、提出核心归纳偏置并提供了被反复验证的实验框架，"
                "这些内容决定了后续创新是否真正有效。实际调研中应同时维护“经典论文清单”和"
                "“近三年增量论文清单”，并通过复现实验明确哪些改进来自架构、哪些来自训练技巧。"
            ),
            (
                f"可能趋于饱和的方向包括：{ '、'.join(item for item in saturated if item) or '暂未出现明显饱和方向' }。"
                "此类方向常见风险是边际提升下降、实验成本上升、结论泛化能力不足。"
                "在该阶段继续投入时，应把重点转向评测严谨性和场景迁移，而不是仅追求单榜单提升。"
                f"新兴方向包括：{ '、'.join(item for item in emerging if item) or '暂无显著新兴分支' }，"
                "需要通过小规模验证快速判断是否具备长期研究价值。"
            ),
            (
                "未来1-3年建议采用“主线+前沿+保底”的组合策略：主线方向确保持续产出，"
                "前沿方向争取突破性结果，保底方向则用于沉淀可复用基础设施。"
                "每季度应复盘一次论文增速、引用增速和复现难度，形成动态路线图。"
                "如果目标是产学协同，建议优先布局可部署、可评估、可解释的议题，"
                "这样更容易转化为长期可持续的技术资产。"
            ),
        ]
        text = "\n\n".join(paragraphs)
        extra = (
            "\n\n进一步建议：建立统一的数据版本与实验追踪体系，保证不同子方向的结果可横向比较。"
            "对于关键结论必须进行跨数据集、跨随机种子复现，避免偶然性改进误导研究路线。"
            "在团队协作上可以按“基础模型、训练系统、评测分析、应用验证”分工推进，"
            "通过接口契约降低协作耦合度，并保持研究迭代节奏。"
        )
        while len(text) < 1000:
            text = f"{text}{extra}"
        return text

    def _select_core_papers(
        self,
        papers: list[dict[str, Any]],
        *,
        current_year: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        sorted_papers = self._rank_direction_papers(papers)
        recent = [item for item in sorted_papers if self._safe_int(item.get("year")) >= current_year - 2]
        classic = [
            item
            for item in sorted_papers
            if self._safe_int(item.get("year")) > 0 and self._safe_int(item.get("year")) < current_year - 2
        ]

        selected: list[dict[str, Any]] = []
        for item in recent[: max(1, int(limit * 0.7))]:
            selected.append(item)
        for item in classic[:2]:
            if item not in selected:
                selected.append(item)

        for item in sorted_papers:
            if len(selected) >= limit:
                break
            if item in selected:
                continue
            selected.append(item)
        return selected[:limit]

    def _rank_direction_papers(self, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        current_year = datetime.now(timezone.utc).year

        def score(item: dict[str, Any]) -> tuple[float, int, int]:
            citation = self._safe_int(item.get("citation_count"))
            year = self._safe_int(item.get("year"))
            recent = 1 if year >= current_year - 2 else 0
            citation_component = min(citation / 2500.0, 1.0)
            recency_component = 0.32 if recent else 0.0
            score_value = citation_component * 0.62 + recency_component + min(max(year - 2010, 0) / 30.0, 0.06)
            return (score_value, citation, year)

        ranked = sorted(papers, key=score, reverse=True)
        return ranked

    def _compute_correlation_score(self, *, total: int, recent_ratio: float, avg_citations: float) -> float:
        return (
            max(0.0, min(recent_ratio, 1.0)) * 0.52
            + min(max(avg_citations, 0.0) / 700.0, 1.0) * 0.3
            + min(max(total, 0) / 80.0, 1.0) * 0.18
        )

    def _merge_papers_by_identity(
        self,
        base: list[dict[str, Any]],
        incoming: list[dict[str, Any]],
        *,
        max_size: int = 120,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()

        def make_key(item: dict[str, Any]) -> str:
            paper_id = str(item.get("paper_id") or item.get("id") or "").strip().lower()
            if paper_id:
                return f"id:{paper_id}"
            title = str(item.get("title") or "").strip().lower()
            year = str(self._safe_int(item.get("year")))
            return f"title:{title}:{year}"

        for item in [*base, *incoming]:
            if not isinstance(item, dict):
                continue
            key = make_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= max(10, max_size):
                break
        return merged

    def _normalize_skeleton(self, payload: dict[str, Any], query: str) -> dict[str, Any]:
        domain_name = str(payload.get("domain_name") or query).strip() or query
        domain_name_en = str(payload.get("domain_name_en") or self._normalize_query_for_search(query)).strip()
        description = str(payload.get("description") or "").strip()
        raw_directions = payload.get("sub_directions")
        directions: list[dict[str, Any]] = []

        if isinstance(raw_directions, list):
            for raw in raw_directions:
                if not isinstance(raw, dict):
                    continue
                name = str(raw.get("name") or "").strip()
                if not name:
                    continue
                status = str(raw.get("status") or "stable").strip().lower()
                if status not in self._STATUS_VALUES:
                    status = "stable"
                methods = self._normalize_text_list(raw.get("methods"), limit=4)
                keywords = self._normalize_text_list(raw.get("search_keywords"), limit=6)
                if not keywords:
                    keyword_seed = str(raw.get("name_en") or name or query)
                    keywords = [self._normalize_query_for_search(keyword_seed)]
                directions.append(
                    {
                        "name": name,
                        "name_en": str(raw.get("name_en") or "").strip(),
                        "description": str(raw.get("description") or "").strip(),
                        "status": status,
                        "methods": methods,
                        "search_keywords": keywords,
                        "estimated_active_years": str(raw.get("estimated_active_years") or "").strip(),
                    }
                )
                if len(directions) >= self._MAX_DIRECTIONS:
                    break

        if len(directions) < self._MIN_DIRECTIONS:
            fallback = self._fallback_skeleton(query).get("sub_directions") or []
            known = {str(item.get("name") or "").strip().lower() for item in directions}
            for item in fallback:
                item_name = str(item.get("name") or "").strip()
                if not item_name or item_name.lower() in known:
                    continue
                directions.append(item)
                if len(directions) >= self._MIN_DIRECTIONS:
                    break

        return {
            "domain_name": domain_name,
            "domain_name_en": domain_name_en,
            "description": description or f"{domain_name} 领域的关键方向与研究热度概览。",
            "sub_directions": directions[: self._MAX_DIRECTIONS],
        }

    def _fallback_skeleton(self, query: str) -> dict[str, Any]:
        normalized_query = self._normalize_query_for_search(query)
        return {
            "domain_name": query,
            "domain_name_en": normalized_query.title(),
            "description": f"{query} 领域的主要研究分支、方法路线与发展阶段概览。",
            "sub_directions": [
                {
                    "name": "基础建模与理论",
                    "name_en": "Core Modeling and Theory",
                    "description": "关注问题定义、理论分析与标准化建模。",
                    "status": "stable",
                    "methods": ["theoretical analysis", "benchmarking"],
                    "search_keywords": [f"{normalized_query} survey", f"{normalized_query} benchmark"],
                    "estimated_active_years": "2018-2026",
                },
                {
                    "name": "训练与优化策略",
                    "name_en": "Training and Optimization",
                    "description": "围绕训练稳定性、效率和泛化能力优化。",
                    "status": "growing",
                    "methods": ["curriculum learning", "regularization"],
                    "search_keywords": [f"{normalized_query} training", f"{normalized_query} optimization"],
                    "estimated_active_years": "2020-2026",
                },
                {
                    "name": "高效化与部署",
                    "name_en": "Efficiency and Deployment",
                    "description": "探索轻量化、压缩和工程部署能力。",
                    "status": "growing",
                    "methods": ["distillation", "quantization"],
                    "search_keywords": [f"efficient {normalized_query}", f"{normalized_query} deployment"],
                    "estimated_active_years": "2021-2026",
                },
                {
                    "name": "应用拓展",
                    "name_en": "Applications",
                    "description": "聚焦跨场景迁移与行业落地。",
                    "status": "stable",
                    "methods": ["transfer learning", "domain adaptation"],
                    "search_keywords": [f"{normalized_query} application", f"{normalized_query} real-world"],
                    "estimated_active_years": "2019-2026",
                },
                {
                    "name": "评测与可信性",
                    "name_en": "Evaluation and Reliability",
                    "description": "关注评测体系、鲁棒性与可解释性。",
                    "status": "emerging",
                    "methods": ["robustness evaluation", "interpretability"],
                    "search_keywords": [f"{normalized_query} robustness", f"{normalized_query} evaluation"],
                    "estimated_active_years": "2022-2026",
                },
                {
                    "name": "多模态融合",
                    "name_en": "Multimodal Fusion",
                    "description": "结合文本、视觉、语音等多模态信息进行联合建模。",
                    "status": "growing",
                    "methods": ["cross-modal alignment", "contrastive learning"],
                    "search_keywords": [f"{normalized_query} multimodal", f"{normalized_query} cross-modal"],
                    "estimated_active_years": "2021-2026",
                },
                {
                    "name": "可解释性与安全性",
                    "name_en": "Interpretability and Safety",
                    "description": "提升模型可解释、可控和安全对齐能力。",
                    "status": "emerging",
                    "methods": ["mechanistic interpretability", "safety alignment"],
                    "search_keywords": [f"{normalized_query} interpretability", f"{normalized_query} safety"],
                    "estimated_active_years": "2022-2026",
                },
                {
                    "name": "数据工程与合成数据",
                    "name_en": "Data Engineering and Synthetic Data",
                    "description": "优化数据质量、构建高价值训练语料与合成数据管线。",
                    "status": "growing",
                    "methods": ["data curation", "synthetic data generation"],
                    "search_keywords": [f"{normalized_query} data curation", f"{normalized_query} synthetic data"],
                    "estimated_active_years": "2021-2026",
                },
                {
                    "name": "推理增强与工具调用",
                    "name_en": "Reasoning and Tool Use",
                    "description": "强化复杂推理、规划与外部工具调用能力。",
                    "status": "growing",
                    "methods": ["chain-of-thought", "tool augmentation"],
                    "search_keywords": [f"{normalized_query} reasoning", f"{normalized_query} tool use"],
                    "estimated_active_years": "2022-2026",
                },
                {
                    "name": "领域迁移与垂直应用",
                    "name_en": "Domain Adaptation and Vertical Applications",
                    "description": "面向医疗、金融、工业等垂直场景进行迁移优化。",
                    "status": "stable",
                    "methods": ["domain adaptation", "instruction tuning"],
                    "search_keywords": [f"{normalized_query} domain adaptation", f"{normalized_query} vertical application"],
                    "estimated_active_years": "2020-2026",
                },
            ],
        }

    def _extract_json_payload(self, text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]

        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("skeleton payload must be JSON object")
        return data

    def _normalize_query_for_search(self, query: str) -> str:
        text = str(query or "").strip()
        if not text:
            return "machine learning"
        lowered = text.lower()
        for zh_term, en_term in self._ZH_TO_EN.items():
            if zh_term.lower() in lowered:
                return en_term
        if re.search(r"[a-zA-Z]", text):
            return text
        return text

    @staticmethod
    def _normalize_text_list(payload: Any, *, limit: int) -> list[str]:
        if not isinstance(payload, list):
            return []
        values: list[str] = []
        seen: set[str] = set()
        for item in payload:
            text = str(item or "").strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            values.append(text)
            if len(values) >= max(1, limit):
                break
        return values

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe_int_or_none(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _slug(text: str) -> str:
        lowered = text.strip().lower()
        return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-") or "paper"
