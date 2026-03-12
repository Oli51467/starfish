from __future__ import annotations

from functools import lru_cache

from models.schemas import LineageNode, LineageResponse, LineageStats, PaperRef


class LineageService:
    def get_lineage(
        self,
        paper_id: str,
        ancestor_depth: int,
        descendant_depth: int,
        citation_types: list[str] | None,
    ) -> LineageResponse:
        ancestor_depth = max(1, min(ancestor_depth, 4))
        descendant_depth = max(1, min(descendant_depth, 4))

        all_ancestors = [
            LineageNode(
                paper_id=f"ancestor-{idx}",
                title=f"Ancestor Paper {idx}",
                year=2012 + idx,
                relation_type="extending",
                relation_description="为当前论文提供了方法基础。",
                generation=min(idx, ancestor_depth),
            )
            for idx in range(1, ancestor_depth + 1)
        ]

        all_descendants = [
            LineageNode(
                paper_id=f"desc-{idx}",
                title=f"Descendant Paper {idx}",
                year=2018 + idx,
                relation_type="supporting" if idx % 3 else "contradicting",
                relation_description="在当前论文结论基础上进行扩展与验证。",
                generation=min(idx, descendant_depth),
                citation_type_source="scite-mock",
            )
            for idx in range(1, descendant_depth + 2)
        ]

        if citation_types:
            allowed = {item.strip().lower() for item in citation_types if item.strip()}
            all_descendants = [item for item in all_descendants if item.relation_type in allowed]

        return LineageResponse(
            root_paper=PaperRef(
                paper_id=paper_id,
                title=f"Root Paper {paper_id}",
                year=2017,
                citation_count=6842,
            ),
            ancestors=all_ancestors,
            descendants=all_descendants,
            controversy_summary="当前论文在评估设定上存在争议，建议重点审查反驳引用。",
            lineage_stats=LineageStats(
                total_descendants=847,
                supporting_ratio=0.72,
                contradicting_ratio=0.08,
                extending_ratio=0.51,
            ),
        )


@lru_cache
def get_lineage_service() -> LineageService:
    return LineageService()
