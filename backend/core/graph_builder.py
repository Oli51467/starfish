from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations
import re
from uuid import uuid4

from models.schemas import MapEdge, MapNode, MapResponse

from core.trend_analyzer import TrendAnalyzer


class GraphBuilder:
    """Build a feature-1 domain map from fetched paper metadata."""

    _THEME_RULES = [
        (
            "Theory & Foundations",
            {
                "theory",
                "proof",
                "formal",
                "analysis",
                "security",
                "secure",
                "verifiable",
                "cryptography",
                "homomorphic",
                "foundation",
            },
        ),
        (
            "Methods & Models",
            {
                "method",
                "model",
                "algorithm",
                "framework",
                "network",
                "architecture",
                "learning",
                "training",
                "optimization",
                "transformer",
            },
        ),
        (
            "Benchmarks & Evaluation",
            {
                "benchmark",
                "dataset",
                "evaluation",
                "survey",
                "comparison",
                "metrics",
                "review",
                "analysis",
            },
        ),
        (
            "Applications & Systems",
            {
                "application",
                "system",
                "deployment",
                "real-world",
                "practical",
                "implementation",
                "towards",
                "case",
            },
        ),
    ]
    _TOP_VENUE_TOKENS = {
        "NEURIPS",
        "NIPS",
        "ICML",
        "ICLR",
        "CVPR",
        "ECCV",
        "ICCV",
        "ACL",
        "EMNLP",
        "NAACL",
        "KDD",
        "AAAI",
        "IJCAI",
        "WWW",
        "SIGIR",
        "SIGMOD",
        "VLDB",
        "ICSE",
        "OSDI",
        "SOSP",
        "USENIX",
        "NATURE",
        "SCIENCE",
        "JMLR",
        "TPAMI",
    }

    def __init__(self) -> None:
        self.trend_analyzer = TrendAnalyzer()

    def build_domain_map(self, seed_document: dict, depth: int) -> MapResponse:
        seed_paper = seed_document.get("seed_paper") or {}
        papers = self._collect_candidate_papers(seed_paper)
        clusters = self._cluster_papers(seed_paper, papers, depth)

        nodes = self._build_nodes(seed_paper, papers, clusters)
        edges = self._build_edges(nodes)
        trend_summary = self._build_trend_summary(seed_paper, nodes)

        return MapResponse(
            map_id=f"map-{uuid4().hex[:12]}",
            nodes=nodes,
            edges=edges,
            trend_summary=trend_summary,
            generated_at=datetime.now(timezone.utc),
        )

    def _collect_candidate_papers(self, seed_paper: dict) -> list[dict]:
        candidates = [self._normalize_paper(seed_paper, relation="seed")]
        candidates.extend(self._normalize_paper(item, relation="reference") for item in seed_paper.get("references", []))
        candidates.extend(self._normalize_paper(item, relation="citation") for item in seed_paper.get("citations", []))

        unique: list[dict] = []
        seen: set[str] = set()
        for paper in candidates:
            if not paper.get("title"):
                continue
            dedupe_key = (paper.get("paper_id") or paper.get("title", "")).strip().lower()
            if not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            unique.append(paper)

        return unique or [
            {
                "paper_id": "seed-paper",
                "title": seed_paper.get("title") or "Seed Topic",
                "year": self._safe_int(seed_paper.get("year")),
                "citation_count": self._safe_int(seed_paper.get("citation_count")),
                "venue": seed_paper.get("venue") or "Unknown Venue",
                "relation": "seed",
            }
        ]

    @staticmethod
    def _normalize_paper(payload: dict, relation: str) -> dict:
        return {
            "paper_id": str(payload.get("paper_id") or ""),
            "title": str(payload.get("title") or "").strip(),
            "year": GraphBuilder._safe_int(payload.get("year")),
            "citation_count": GraphBuilder._safe_int(payload.get("citation_count")),
            "venue": str(payload.get("venue") or "Unknown Venue"),
            "relation": relation,
        }

    @staticmethod
    def _safe_int(value: object) -> int:
        try:
            return max(0, int(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    def _cluster_papers(self, seed_paper: dict, papers: list[dict], depth: int) -> list[tuple[str, list[dict]]]:
        buckets: dict[str, list[dict]] = {}
        for label, _ in self._THEME_RULES:
            buckets[label] = []

        for paper in papers:
            label = self._infer_theme(paper.get("title", ""))
            buckets[label].append(paper)

        clusters = [(label, items) for label, items in buckets.items() if items]
        clusters.sort(key=lambda item: len(item[1]), reverse=True)

        # If semantic buckets are sparse, inject relation-driven buckets to keep map structure readable.
        if len(clusters) < 3:
            relation_mapping = [
                ("Reference Backbone", "reference"),
                ("Frontier Citations", "citation"),
                ("Seed Core", "seed"),
            ]
            for label, relation in relation_mapping:
                relation_items = [paper for paper in papers if paper.get("relation") == relation]
                if relation_items and label not in {item[0] for item in clusters}:
                    clusters.append((label, relation_items))

        if len(clusters) < 3:
            fallback_labels = ["Emerging Threads", "Practical Pathways", "Open Questions"]
            for label in fallback_labels:
                if len(clusters) >= 3:
                    break
                if label in {item[0] for item in clusters}:
                    continue
                clusters.append((label, papers[: max(1, min(3, len(papers)))]))

        topic_prefix = self._topic_prefix(seed_paper.get("title") or "")
        target_cluster_count = max(3, min(5, depth + 2))
        selected = clusters[:target_cluster_count]

        if len(selected) < 2:
            selected = [("General Landscape", papers)]

        return [(f"{topic_prefix} · {label}", items) for label, items in selected]

    def _infer_theme(self, title: str) -> str:
        tokens = self._tokenize(title)
        if not tokens:
            return "Methods & Models"

        best_label = "Methods & Models"
        best_score = -1
        for label, keywords in self._THEME_RULES:
            score = sum(1 for token in tokens if token in keywords)
            if score > best_score:
                best_label = label
                best_score = score

        return best_label

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9\-\+]+", (text or "").lower())

    @staticmethod
    def _topic_prefix(seed_title: str) -> str:
        latin_tokens = re.findall(r"[A-Za-z0-9]+", seed_title)
        if latin_tokens:
            return " ".join(latin_tokens[:3]).strip()[:28]
        compact = "".join(seed_title.split())
        return compact[:12] if compact else "Seed Topic"

    def _build_nodes(
        self,
        seed_paper: dict,
        all_papers: list[dict],
        clusters: list[tuple[str, list[dict]]],
    ) -> list[MapNode]:
        now_year = datetime.now(timezone.utc).year
        estimated_volume = max(
            len(all_papers),
            self._safe_int(seed_paper.get("reference_count")) + self._safe_int(seed_paper.get("citation_count")) + 1,
        )
        total_raw = sum(len(items) for _, items in clusters) or 1

        nodes: list[MapNode] = []
        for index, (label, papers) in enumerate(clusters, start=1):
            raw_count = len(papers)
            estimated_count = max(raw_count, round(estimated_volume * raw_count / total_raw))

            paper_growth = self._growth_ratio(
                recent=self._window_metric(papers, now_year, metric="paper", window="recent"),
                previous=self._window_metric(papers, now_year, metric="paper", window="previous"),
            )
            citation_growth = self._growth_ratio(
                recent=self._window_metric(papers, now_year, metric="citation", window="recent"),
                previous=self._window_metric(papers, now_year, metric="citation", window="previous"),
            )

            top_venue_ratio = self._top_venue_ratio(papers)
            trend_score = self._compose_trend_score(
                paper_growth_ratio=paper_growth,
                citation_growth_ratio=citation_growth,
                top_venue_ratio=top_venue_ratio,
                github_growth_ratio=0.0,
            )
            trend = self.trend_analyzer.classify_by_growth(
                paper_growth_percent=paper_growth * 100,
                paper_count=estimated_count,
                score=trend_score,
            )

            top_papers = [
                paper.get("paper_id") or f"paper-{index}-{rank}"
                for rank, paper in enumerate(
                    sorted(
                        papers,
                        key=lambda item: (self._safe_int(item.get("citation_count")), self._safe_int(item.get("year"))),
                        reverse=True,
                    )[:3],
                    start=1,
                )
            ]

            nodes.append(
                MapNode(
                    id=f"node-{index}",
                    label=label,
                    paper_count=estimated_count,
                    trend=trend,
                    trend_score=round(trend_score, 2),
                    top_papers=top_papers,
                )
            )

        return nodes

    @staticmethod
    def _window_metric(papers: list[dict], current_year: int, metric: str, window: str) -> int:
        if window == "recent":
            lower, upper = current_year - 1, current_year
        else:
            lower, upper = current_year - 3, current_year - 2

        total = 0
        for paper in papers:
            year = GraphBuilder._safe_int(paper.get("year"))
            if lower <= year <= upper:
                if metric == "citation":
                    total += GraphBuilder._safe_int(paper.get("citation_count"))
                else:
                    total += 1
        return total

    @staticmethod
    def _growth_ratio(recent: int, previous: int) -> float:
        if previous <= 0:
            return 2.5 if recent > 0 else 0.0
        return (recent - previous) / previous

    def _top_venue_ratio(self, papers: list[dict]) -> float:
        if not papers:
            return 0.0
        top_count = 0
        for paper in papers:
            venue_upper = str(paper.get("venue") or "").upper()
            if any(token in venue_upper for token in self._TOP_VENUE_TOKENS):
                top_count += 1
        return top_count / len(papers)

    @staticmethod
    def _compose_trend_score(
        paper_growth_ratio: float,
        citation_growth_ratio: float,
        top_venue_ratio: float,
        github_growth_ratio: float,
    ) -> float:
        def normalize_growth(value: float) -> float:
            return GraphBuilder._clamp((value + 0.5) / 3.0, 0.0, 1.0)

        paper_component = normalize_growth(paper_growth_ratio)
        citation_component = normalize_growth(citation_growth_ratio)
        return GraphBuilder._clamp(
            paper_component * 0.4
            + citation_component * 0.3
            + GraphBuilder._clamp(top_venue_ratio, 0.0, 1.0) * 0.2
            + GraphBuilder._clamp(github_growth_ratio, 0.0, 1.0) * 0.1,
            0.0,
            1.0,
        )

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    def _build_edges(self, nodes: list[MapNode]) -> list[MapEdge]:
        if len(nodes) <= 1:
            return []

        pair_scores: list[tuple[float, int, int]] = []
        for left, right in combinations(range(len(nodes)), 2):
            weight = self._edge_weight(nodes[left], nodes[right])
            pair_scores.append((weight, left, right))

        pair_scores.sort(key=lambda item: item[0], reverse=True)

        parent = list(range(len(nodes)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> bool:
            root_a = find(a)
            root_b = find(b)
            if root_a == root_b:
                return False
            parent[root_b] = root_a
            return True

        chosen: list[tuple[int, int, float]] = []
        chosen_pairs: set[tuple[int, int]] = set()

        # Build a maximum spanning tree first so graph is connected.
        for weight, left, right in pair_scores:
            if union(left, right):
                pair = (min(left, right), max(left, right))
                chosen_pairs.add(pair)
                chosen.append((left, right, weight))
                if len(chosen) == len(nodes) - 1:
                    break

        target_edge_count = min(len(nodes) + 1, 6)
        for weight, left, right in pair_scores:
            if len(chosen) >= target_edge_count:
                break
            pair = (min(left, right), max(left, right))
            if pair in chosen_pairs:
                continue
            chosen_pairs.add(pair)
            chosen.append((left, right, weight))

        return [
            MapEdge(
                source=nodes[left].id,
                target=nodes[right].id,
                weight=round(weight, 2),
            )
            for left, right, weight in chosen
        ]

    @staticmethod
    def _edge_weight(left: MapNode, right: MapNode) -> float:
        size_balance = (2 * min(left.paper_count, right.paper_count)) / max(left.paper_count + right.paper_count, 1)
        trend_proximity = 1 - abs(left.trend_score - right.trend_score)
        return GraphBuilder._clamp(0.25 + size_balance * 0.55 + trend_proximity * 0.2, 0.12, 0.95)

    @staticmethod
    def _build_trend_summary(seed_paper: dict, nodes: list[MapNode]) -> str:
        if not nodes:
            return "暂未生成可用子方向，建议更换种子论文后重试。"

        hot_nodes = sorted(
            [node for node in nodes if node.trend in {"rising", "emerging"}],
            key=lambda item: item.trend_score,
            reverse=True,
        )
        stable_nodes = [node for node in nodes if node.trend == "stable"]
        saturated_nodes = [node for node in nodes if node.trend == "saturated"]

        hot_text = "、".join(node.label for node in hot_nodes[:2]) or "暂无显著爆发方向"
        stable_text = "、".join(node.label for node in stable_nodes[:2]) or "稳定方向较少"
        saturated_text = "、".join(node.label for node in saturated_nodes[:1]) or "未识别到明显饱和区"
        focus_node = hot_nodes[0].label if hot_nodes else nodes[0].label
        seed_title = seed_paper.get("title") or "当前输入论文"

        return (
            f"围绕《{seed_title[:48]}》识别出 {len(nodes)} 个子方向。"
            f"热点集中在 {hot_text}；稳定区主要为 {stable_text}；"
            f"饱和迹象：{saturated_text}。建议优先展开 {focus_node} 的代表论文。"
        )
