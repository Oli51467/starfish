from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import logging
import re
from typing import Any

from core.signal_scoring import (
    compute_controversy_score,
    compute_heat_score,
    resolve_trend_label,
)
from models.schemas import (
    LineageResponse,
    PaperSignal,
    PaperSignalEvent,
    PaperSignalEventListResponse,
    PaperSignalRefreshItem,
    PaperSignalRefreshResponse,
    UserProfile,
)
from repositories.collection_repository import CollectionRepository, get_collection_repository
from repositories.paper_signal_repository import PaperSignalRepository, get_paper_signal_repository
from services.lineage_service import LineageService, get_lineage_service

logger = logging.getLogger(__name__)

_VALID_EVENT_TYPES = {
    "lineage_expanded",
    "controversy_rise",
    "citation_delta",
    "metadata_enriched",
}
_YEAR_PATTERN = re.compile(r"(19|20)\d{2}")
_DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
_SIGNAL_REFRESH_INTERVAL_SECONDS = 24 * 60 * 60


class PaperSignalService:
    def __init__(
        self,
        *,
        lineage_service: LineageService | None = None,
        collection_repository: CollectionRepository | None = None,
        signal_repository: PaperSignalRepository | None = None,
    ) -> None:
        self.lineage_service = lineage_service or get_lineage_service()
        self.collection_repository = collection_repository or get_collection_repository()
        self.signal_repository = signal_repository or get_paper_signal_repository()

    async def get_paper_signal(self, *, paper_id: str, force_refresh: bool = False) -> PaperSignal:
        safe_paper_id = str(paper_id or "").strip()
        if not safe_paper_id:
            raise ValueError("paper_id_required")

        lineage = await self.lineage_service.get_lineage(
            safe_paper_id,
            ancestor_depth=2,
            descendant_depth=2,
            citation_types=None,
            force_refresh=bool(force_refresh),
        )
        return self._build_signal(safe_paper_id, lineage)

    async def refresh_saved_paper_signals(
        self,
        *,
        user: UserProfile,
        collection_id: str = "",
        limit: int = 20,
        force_refresh: bool = False,
    ) -> PaperSignalRefreshResponse:
        safe_limit = max(1, min(50, int(limit)))
        safe_collection_id = str(collection_id or "").strip() or None
        rows, _ = self.collection_repository.list_saved_papers(
            user_id=user.id,
            page=1,
            page_size=safe_limit,
            collection_id=safe_collection_id,
            sort_by="saved_at",
            sort_order="desc",
        )

        items: list[PaperSignalRefreshItem] = []
        event_count = 0
        now_utc = datetime.now(timezone.utc)

        for row in rows:
            saved_paper_id = str(row.get("id") or "").strip()
            paper_id = str(row.get("paper_id") or "").strip()
            if not saved_paper_id or not paper_id:
                continue

            raw_payload = row.get("paper_payload") if isinstance(row.get("paper_payload"), dict) else {}
            current_payload = raw_payload if isinstance(raw_payload, dict) else {}
            previous_snapshot = self._extract_signal_snapshot(current_payload)
            metadata_completeness, metadata_covered_count, metadata_total_count = self._compute_metadata_completeness(
                current_payload
            )
            snapshot_computed_at = self._parse_snapshot_time(previous_snapshot.get("computed_at"))
            if (not force_refresh) and self._is_snapshot_recent(snapshot_computed_at, now_utc):
                continue

            try:
                signal = await self.get_paper_signal(paper_id=paper_id, force_refresh=force_refresh)
            except Exception:  # noqa: BLE001
                logger.exception("Failed refreshing paper signal for %s", paper_id)
                continue

            event_payload = self._build_event_payload(
                paper_title=signal.paper_title,
                previous_snapshot=previous_snapshot,
                signal=signal,
                metadata_completeness=metadata_completeness,
                metadata_covered_count=metadata_covered_count,
                metadata_total_count=metadata_total_count,
            )
            created_event = False
            if event_payload is not None:
                event_row = self.signal_repository.create_event(
                    user_id=user.id,
                    saved_paper_id=saved_paper_id,
                    paper_id=paper_id,
                    event_type=event_payload["event_type"],
                    title=event_payload["title"],
                    content=event_payload["content"],
                    payload=event_payload["payload"],
                )
                created_event = bool(event_row)
                if created_event:
                    event_count += 1

            next_payload = dict(current_payload)
            next_payload["signal_snapshot"] = self._to_signal_snapshot(
                signal,
                metadata_completeness=metadata_completeness,
                metadata_covered_count=metadata_covered_count,
                metadata_total_count=metadata_total_count,
            )
            try:
                self.collection_repository.update_saved_paper_payload(
                    user_id=user.id,
                    saved_paper_id=saved_paper_id,
                    paper_payload=next_payload,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed storing signal snapshot for %s", paper_id)

            items.append(
                PaperSignalRefreshItem(
                    saved_paper_id=saved_paper_id,
                    paper_id=paper_id,
                    signal=signal,
                    event_created=created_event,
                )
            )

        return PaperSignalRefreshResponse(
            refreshed_count=len(items),
            event_count=event_count,
            items=items,
        )

    def list_signal_events(
        self,
        *,
        user: UserProfile,
        page: int,
        page_size: int,
        unread_only: bool,
        paper_id: str = "",
        saved_paper_id: str = "",
    ) -> PaperSignalEventListResponse:
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(50, int(page_size)))
        rows, total, unread_count = self.signal_repository.list_events(
            user_id=user.id,
            page=safe_page,
            page_size=safe_page_size,
            unread_only=bool(unread_only),
            paper_id=str(paper_id or "").strip(),
            saved_paper_id=str(saved_paper_id or "").strip(),
        )
        total_pages = (total + safe_page_size - 1) // safe_page_size if total > 0 else 0
        items = [self._to_signal_event(row) for row in rows]
        return PaperSignalEventListResponse(
            page=safe_page,
            page_size=safe_page_size,
            total=total,
            total_pages=total_pages,
            unread_count=max(0, unread_count),
            items=items,
        )

    def mark_event_read(self, *, user: UserProfile, event_id: str) -> bool:
        return self.signal_repository.mark_event_read(
            user_id=user.id,
            event_id=str(event_id or "").strip(),
        )

    @staticmethod
    def _extract_year_from_text(raw_value: Any) -> int | None:
        text = str(raw_value or "").strip()
        if not text:
            return None
        matched = _YEAR_PATTERN.search(text)
        if not matched:
            return None
        try:
            return int(matched.group(0))
        except (TypeError, ValueError):
            return None

    def _build_signal(self, paper_id: str, lineage: LineageResponse) -> PaperSignal:
        root = lineage.root
        paper_title = str(root.title or "").strip() or paper_id
        citation_count = max(0, int(root.citation_count or 0))
        ancestor_count = len(lineage.ancestors)
        descendant_count = len(lineage.descendants)

        published_year: int | None = None
        if root.year is not None:
            try:
                published_year = int(root.year)
            except (TypeError, ValueError):
                published_year = None
        if published_year is None:
            published_year = self._extract_year_from_text(root.publication_date)

        relation_distribution = self._build_relation_distribution(lineage)
        total_relations = sum(relation_distribution.values())
        contradicting_count = relation_distribution.get("contradicting", 0)

        heat_score = compute_heat_score(
            citation_count=citation_count,
            published_year=published_year,
            descendant_count=descendant_count,
        )
        controversy_score = compute_controversy_score(
            contradicting_count=contradicting_count,
            total_relations=total_relations,
        )
        trend_label = resolve_trend_label(
            heat_score=heat_score,
            controversy_score=controversy_score,
            published_year=published_year,
        )

        return PaperSignal(
            paper_id=paper_id,
            paper_title=paper_title,
            citation_count=citation_count,
            published_year=published_year,
            ancestor_count=ancestor_count,
            descendant_count=descendant_count,
            relation_distribution=relation_distribution,
            heat_score=round(heat_score, 4),
            controversy_score=round(controversy_score, 4),
            trend_label=trend_label,
            computed_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _build_relation_distribution(lineage: LineageResponse) -> dict[str, int]:
        result = {
            "supporting": 0,
            "contradicting": 0,
            "extending": 0,
            "migrating": 0,
            "mentioning": 0,
        }

        for item in lineage.ancestors + lineage.descendants:
            key = str(item.ctype or item.relation_type or "mentioning").strip().lower()
            if key not in result:
                key = "mentioning"
            result[key] += 1

        if isinstance(lineage.stats.type_distribution, dict):
            for key in list(result.keys()):
                stat_value = lineage.stats.type_distribution.get(key)
                if isinstance(stat_value, int) and stat_value >= 0:
                    result[key] = max(result[key], stat_value)

        return result

    @staticmethod
    def _extract_signal_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        snapshot = payload.get("signal_snapshot")
        return snapshot if isinstance(snapshot, dict) else {}

    @classmethod
    def _to_signal_snapshot(
        cls,
        signal: PaperSignal,
        *,
        metadata_completeness: float = 0.0,
        metadata_covered_count: int = 0,
        metadata_total_count: int = 0,
    ) -> dict[str, Any]:
        safe_metadata_total = max(0, int(metadata_total_count))
        safe_metadata_covered = min(max(0, int(metadata_covered_count)), safe_metadata_total)
        return {
            "paper_id": signal.paper_id,
            "paper_title": signal.paper_title,
            "citation_count": signal.citation_count,
            "published_year": signal.published_year,
            "ancestor_count": signal.ancestor_count,
            "descendant_count": signal.descendant_count,
            "relation_distribution": signal.relation_distribution,
            "heat_score": signal.heat_score,
            "controversy_score": signal.controversy_score,
            "trend_label": signal.trend_label,
            "metadata_completeness": round(
                max(0.0, min(1.0, cls._safe_float(metadata_completeness, fallback=0.0))),
                4,
            ),
            "metadata_covered_count": safe_metadata_covered,
            "metadata_total_count": safe_metadata_total,
            "computed_at": signal.computed_at.isoformat(),
        }

    def _build_event_payload(
        self,
        *,
        paper_title: str,
        previous_snapshot: dict[str, Any],
        signal: PaperSignal,
        metadata_completeness: float,
        metadata_covered_count: int,
        metadata_total_count: int,
    ) -> dict[str, Any] | None:
        title = str(paper_title or signal.paper_id).strip() or signal.paper_id
        if not previous_snapshot:
            return {
                "event_type": "metadata_enriched",
                "title": "研究动态已同步",
                "content": f"《{title}》已完成首次动态同步，可查看外部来源链接。",
                "payload": {
                    "bootstrap": True,
                    "links": self._build_fallback_external_links(signal.paper_id),
                    "metadata_completeness": round(
                        max(0.0, min(1.0, self._safe_float(metadata_completeness, fallback=0.0))),
                        4,
                    ),
                    "metadata_covered_count": max(0, int(metadata_covered_count)),
                    "metadata_total_count": max(0, int(metadata_total_count)),
                },
            }

        prev_ancestor = max(0, self._safe_int(previous_snapshot.get("ancestor_count"), fallback=0))
        prev_descendant = max(0, self._safe_int(previous_snapshot.get("descendant_count"), fallback=0))
        prev_citation_count = max(0, self._safe_int(previous_snapshot.get("citation_count"), fallback=0))
        prev_controversy = self._safe_float(previous_snapshot.get("controversy_score"), fallback=0.0)
        prev_metadata_completeness = self._safe_float_or_none(previous_snapshot.get("metadata_completeness"))

        lineage_growth = (signal.ancestor_count - prev_ancestor) + (signal.descendant_count - prev_descendant)
        controversy_delta = signal.controversy_score - prev_controversy
        citation_delta = signal.citation_count - prev_citation_count
        metadata_delta = (
            metadata_completeness - prev_metadata_completeness
            if prev_metadata_completeness is not None
            else 0.0
        )

        if lineage_growth >= 2:
            return {
                "event_type": "lineage_expanded",
                "title": "血缘脉络扩展",
                "content": f"《{title}》新增 {lineage_growth} 个关联节点，研究脉络出现扩展。",
                "payload": {
                    "lineage_growth": lineage_growth,
                    "ancestor_count": signal.ancestor_count,
                    "descendant_count": signal.descendant_count,
                },
            }

        if signal.controversy_score >= 0.24 and controversy_delta >= 0.12:
            return {
                "event_type": "controversy_rise",
                "title": "争议信号上升",
                "content": f"《{title}》近期争议信号上升，建议关注相关反驳与讨论。",
                "payload": {
                    "controversy_score": signal.controversy_score,
                    "previous_controversy_score": prev_controversy,
                    "delta": round(controversy_delta, 4),
                },
            }

        citation_threshold = max(5, int(prev_citation_count * 0.1))
        if citation_delta >= citation_threshold:
            return {
                "event_type": "citation_delta",
                "title": "引用增长",
                "content": f"《{title}》引用较上次增加 {citation_delta}，关注度出现变化。",
                "payload": {
                    "citation_count": signal.citation_count,
                    "previous_citation_count": prev_citation_count,
                    "delta": citation_delta,
                },
            }

        if prev_metadata_completeness is not None and metadata_delta >= 0.2:
            return {
                "event_type": "metadata_enriched",
                "title": "论文信息补全",
                "content": (
                    f"《{title}》新增关键信息字段，已补全至 "
                    f"{metadata_covered_count}/{max(1, metadata_total_count)}。"
                ),
                "payload": {
                    "metadata_completeness": round(metadata_completeness, 4),
                    "previous_metadata_completeness": round(prev_metadata_completeness, 4),
                    "delta": round(metadata_delta, 4),
                    "metadata_covered_count": max(0, int(metadata_covered_count)),
                    "metadata_total_count": max(0, int(metadata_total_count)),
                },
            }

        return None

    @classmethod
    def _build_fallback_external_links(cls, paper_id: str) -> list[str]:
        safe_paper_id = str(paper_id or "").strip()
        if not safe_paper_id:
            return []
        links: list[str] = []
        normalized = safe_paper_id.lower()
        if "doi.org/" in normalized:
            doi_value = safe_paper_id.split("doi.org/", 1)[1].strip()
            if doi_value:
                links.append(f"https://doi.org/{doi_value}")
        else:
            doi_matched = _DOI_PATTERN.search(safe_paper_id)
            if doi_matched:
                links.append(f"https://doi.org/{doi_matched.group(0)}")

        arxiv_matched = re.search(r"arxiv\.org/abs/([^?#\s]+)", safe_paper_id, re.IGNORECASE)
        if arxiv_matched and arxiv_matched.group(1):
            links.append(f"https://arxiv.org/abs/{arxiv_matched.group(1)}")
        else:
            normalized_text = re.sub(r"^arxiv:\s*", "", safe_paper_id, flags=re.IGNORECASE).strip()
            if re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", normalized_text, flags=re.IGNORECASE):
                links.append(f"https://arxiv.org/abs/{normalized_text}")
            elif re.fullmatch(r"[a-z\-]+(?:\.[a-z\-]+)?/\d{7}(v\d+)?", normalized_text, flags=re.IGNORECASE):
                links.append(f"https://arxiv.org/abs/{normalized_text}")

        deduped: list[str] = []
        seen = set()
        for item in links:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    @classmethod
    def _compute_metadata_completeness(cls, payload: dict[str, Any]) -> tuple[float, int, int]:
        if not isinstance(payload, dict):
            return 0.0, 0, 8

        authors = payload.get("authors")
        fields_of_study = payload.get("fields_of_study")
        if not isinstance(fields_of_study, list):
            fields_of_study = payload.get("fieldsOfStudy")

        year_value = cls._safe_int_or_none(payload.get("year"))
        has_year = (
            (year_value is not None and year_value > 0)
            or cls._extract_year_from_text(payload.get("publication_date")) is not None
            or cls._extract_year_from_text(payload.get("publicationDate")) is not None
        )
        impact_value = cls._safe_float_or_none(payload.get("impact_factor"))
        has_impact = impact_value is not None and impact_value > 0

        checks = (
            cls._has_text(payload.get("title")),
            cls._has_text(payload.get("abstract")),
            cls._has_text(payload.get("venue")),
            cls._has_non_empty_list(authors),
            cls._has_non_empty_list(fields_of_study),
            has_year,
            cls._has_text(payload.get("url")),
            has_impact,
        )
        total = len(checks)
        covered = sum(1 for item in checks if item)
        completeness = covered / total if total > 0 else 0.0
        return round(completeness, 4), covered, total

    def _to_signal_event(self, row: dict[str, Any]) -> PaperSignalEvent:
        event_type = self._normalize_event_type(row.get("event_type"))
        return PaperSignalEvent(
            event_id=str(row.get("id") or ""),
            saved_paper_id=str(row.get("saved_paper_id") or ""),
            paper_id=str(row.get("paper_id") or ""),
            event_type=event_type,
            title=str(row.get("title") or ""),
            content=str(row.get("content") or ""),
            payload=row.get("payload") if isinstance(row.get("payload"), dict) else {},
            is_read=bool(row.get("is_read")),
            created_at=row.get("created_at"),
        )

    @staticmethod
    def _normalize_event_type(raw_value: Any) -> str:
        value = str(raw_value or "").strip().lower()
        if value in _VALID_EVENT_TYPES:
            return value
        return "citation_delta"

    @staticmethod
    def _safe_int(value: Any, *, fallback: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _safe_float(value: Any, *, fallback: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _parse_snapshot_time(raw_value: Any) -> datetime | None:
        text = str(raw_value or "").strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _is_snapshot_recent(snapshot_time: datetime | None, now_utc: datetime) -> bool:
        if snapshot_time is None:
            return False
        age_seconds = (now_utc - snapshot_time).total_seconds()
        return age_seconds >= 0 and age_seconds < _SIGNAL_REFRESH_INTERVAL_SECONDS

    @staticmethod
    def _safe_int_or_none(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed

    @staticmethod
    def _safe_float_or_none(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed != parsed:  # NaN check
            return None
        return parsed

    @staticmethod
    def _has_text(value: Any) -> bool:
        return bool(str(value or "").strip())

    @staticmethod
    def _has_non_empty_list(value: Any) -> bool:
        if not isinstance(value, list):
            return False
        return any(bool(str(item or "").strip()) for item in value)


@lru_cache
def get_paper_signal_service() -> PaperSignalService:
    return PaperSignalService()
