from __future__ import annotations

from models.schemas import GapEvidence, GapFeasibility, GapItem, GapsResponse


class GapDetector:
    """Skeleton structural-gap detector."""

    def detect(
        self,
        map_id: str,
        gap_types: list[str] | None,
        min_score: int,
    ) -> GapsResponse:
        candidates = [
            GapItem(
                gap_id="gap-1",
                type="method_scene",
                title="Transformer 方法在低资源工业数据场景未充分验证",
                opportunity_score=88,
                description="主流方法在公开数据集表现优异，但在小样本工业数据上缺少系统性研究。",
                evidence=GapEvidence(
                    covered_scenarios=["公开学术基准", "多语言文本"],
                    uncovered_scenario="低资源工业日志",
                    paper_counts={"covered": 67, "uncovered": 0},
                ),
                feasibility=GapFeasibility(
                    datasets_available=["OpenLogBench"],
                    baselines_available=["RNN baseline", "SVM baseline"],
                    challenges=["标注稀缺", "领域噪声高"],
                ),
                seed_papers=["method-5", "method-8"],
            ),
            GapItem(
                gap_id="gap-2",
                type="stagnant",
                title="子方向 Evaluation Robustness 在近 2 年停滞",
                opportunity_score=76,
                description="该分支在顶会论文产出显著下降，核心假设尚未被新数据重新验证。",
                evidence=GapEvidence(
                    covered_scenarios=["标准鲁棒性评估"],
                    uncovered_scenario="跨域鲁棒性评估",
                    paper_counts={"last_two_years": 1},
                ),
                feasibility=GapFeasibility(
                    datasets_available=["CrossDomain-Robust"],
                    baselines_available=["ERM", "DRO"],
                    challenges=["评估成本高"],
                ),
                seed_papers=["topic-13", "topic-14"],
            ),
        ]

        type_set = {item.strip() for item in gap_types or [] if item.strip()}
        gaps = [
            gap
            for gap in candidates
            if gap.opportunity_score >= min_score and (not type_set or gap.type in type_set)
        ]

        summary = (
            f"在该领域共发现 {len(gaps)} 个潜在研究空白，"
            "建议优先验证机会评分最高的方向。"
        )
        return GapsResponse(map_id=map_id, gaps=gaps, summary=summary)
