from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from models.schemas import MapEdge, MapNode, MapResponse

from core.trend_analyzer import TrendAnalyzer


class GraphBuilder:
    """Builds a mocked but contract-stable domain map payload."""

    def __init__(self) -> None:
        self.trend_analyzer = TrendAnalyzer()

    def build_domain_map(self, seed_document: dict, depth: int) -> MapResponse:
        seed_title = seed_document.get("seed_paper", {}).get("title", "Seed Topic")
        base = seed_title[:24] if seed_title else "Seed Topic"

        labels = [
            f"{base} · Fundamentals",
            f"{base} · Methods",
            f"{base} · Benchmarks",
            f"{base} · Applications",
        ]

        raw_scores = [0.86, 0.68, 0.44, 0.74]
        paper_counts = [220, 160, 540, 92]

        nodes: list[MapNode] = []
        for idx, label in enumerate(labels, start=1):
            trend_score = max(0.05, min(0.99, raw_scores[idx - 1] - (depth - 2) * 0.03))
            paper_count = max(20, paper_counts[idx - 1] + (depth - 2) * 15)
            trend = self.trend_analyzer.classify_by_score(trend_score, paper_count)
            nodes.append(
                MapNode(
                    id=f"node-{idx}",
                    label=label,
                    paper_count=paper_count,
                    trend=trend,
                    trend_score=round(trend_score, 2),
                    top_papers=[f"paper-{idx}a", f"paper-{idx}b"],
                )
            )

        edges = [
            MapEdge(source="node-1", target="node-2", weight=0.78),
            MapEdge(source="node-2", target="node-3", weight=0.67),
            MapEdge(source="node-2", target="node-4", weight=0.73),
            MapEdge(source="node-1", target="node-4", weight=0.52),
        ]

        hot_labels = [node.label for node in nodes if node.trend in {"rising", "emerging"}][:2]
        summary = (
            "当前领域图谱已生成："
            f"热点子方向集中在 {', '.join(hot_labels) if hot_labels else '暂无明显热点'}，"
            "建议优先阅读桥接节点对应论文。"
        )

        return MapResponse(
            map_id=f"map-{uuid4().hex[:12]}",
            nodes=nodes,
            edges=edges,
            trend_summary=summary,
            generated_at=datetime.now(timezone.utc),
        )
