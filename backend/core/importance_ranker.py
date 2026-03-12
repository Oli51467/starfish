from __future__ import annotations

from models.schemas import ReadingLayer, ReadingListResponse, ReadingPaper


class ImportanceRanker:
    """Returns layered reading list skeleton from map payload."""

    def build_reading_list(
        self,
        map_id: str,
        focus_area: str | None,
        max_papers: int,
    ) -> ReadingListResponse:
        focus = focus_area or "General"
        layers = [
            ReadingLayer(
                layer=1,
                label="奠基论文",
                description="必须读，不读后续看不懂",
                papers=self._papers(prefix="foundation", start=1, count=min(4, max_papers), focus=focus),
            ),
            ReadingLayer(
                layer=2,
                label="方法论文",
                description="应该读，建立方法对比视角",
                papers=self._papers(prefix="method", start=5, count=min(8, max(max_papers - 4, 0)), focus=focus),
            ),
            ReadingLayer(
                layer=3,
                label="专题论文",
                description="按兴趣方向定制",
                papers=self._papers(prefix="topic", start=13, count=min(6, max(max_papers - 12, 0)), focus=focus),
            ),
        ]
        return ReadingListResponse(map_id=map_id, layers=layers)

    @staticmethod
    def _papers(prefix: str, start: int, count: int, focus: str) -> list[ReadingPaper]:
        papers: list[ReadingPaper] = []
        for idx in range(count):
            rank = start + idx
            papers.append(
                ReadingPaper(
                    paper_id=f"{prefix}-{rank}",
                    title=f"{focus} {prefix.title()} Paper {rank}",
                    authors=["Author A", "Author B"],
                    year=2016 + (rank % 9),
                    importance_score=max(0.35, 0.96 - idx * 0.05),
                    importance_reason="图谱关键桥接节点，能解释多个子方向之间的方法迁移。",
                    graph_role="bridge" if idx % 2 else "hub",
                    estimated_read_time_min=90 if prefix == "foundation" else 60,
                    citation_count=2000 - idx * 80,
                    venue="NeurIPS",
                )
            )
        return papers
