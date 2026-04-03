from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import re
from typing import Any, Callable


@dataclass(frozen=True)
class GraphDomainSpec:
    name: str
    keywords: tuple[str, ...]


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(text or "")))


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _tokenize_ascii(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,}", str(text or "").lower())


def _dedupe_names(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_space(value)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


_GENERIC_DOMAIN_KEYS = {
    "computer science",
    "engineering",
    "science",
    "artificial intelligence",
    "ai",
}


def build_graph_domain_specs(
    query: str,
    *,
    target_domains: int = 5,
    seed_domains: list[str] | None = None,
) -> list[GraphDomainSpec]:
    safe_query = _normalize_space(query) or "研究主题"
    target_count = max(1, min(8, int(target_domains or 5)))
    zh_query = _contains_cjk(safe_query)

    specs: list[GraphDomainSpec] = []
    used_names: set[str] = set()

    def add_spec(name: str, keywords: list[str]) -> None:
        normalized_name = _normalize_space(name)
        if not normalized_name:
            return
        key = normalized_name.lower()
        if key in used_names:
            return
        used_names.add(key)
        token_keywords = [kw for kw in _dedupe_names(keywords) if kw]
        if not token_keywords:
            token_keywords = _tokenize_ascii(normalized_name)[:6]
        specs.append(GraphDomainSpec(name=normalized_name, keywords=tuple(token_keywords[:10])))

    if seed_domains:
        for raw in seed_domains:
            name = _normalize_space(raw)
            if not name:
                continue
            if name.lower() in _GENERIC_DOMAIN_KEYS:
                continue
            add_spec(name, _tokenize_ascii(name))
            if len(specs) >= target_count:
                break

    if zh_query:
        facet_templates = [
            (f"{safe_query} · 基础理论", ["理论", "机制", "原理", "分析", "foundation", "theory"]),
            (f"{safe_query} · 核心方法", ["方法", "模型", "算法", "架构", "method", "model", "algorithm"]),
            (f"{safe_query} · 系统优化", ["系统", "优化", "效率", "部署", "system", "optimization", "efficiency"]),
            (f"{safe_query} · 评测基准", ["评测", "基准", "数据集", "benchmark", "evaluation", "dataset"]),
            (f"{safe_query} · 行业应用", ["应用", "场景", "行业", "application", "real-world", "industry"]),
        ]
    else:
        facet_templates = [
            (f"{safe_query} · Foundations", ["foundation", "theory", "analysis", "mechanism", "principle"]),
            (f"{safe_query} · Methods", ["method", "model", "architecture", "algorithm", "framework"]),
            (f"{safe_query} · Systems", ["system", "optimization", "efficiency", "deployment", "platform"]),
            (f"{safe_query} · Evaluation", ["benchmark", "evaluation", "dataset", "metric", "ablation"]),
            (f"{safe_query} · Applications", ["application", "industry", "real-world", "case", "practice"]),
        ]

    for name, keywords in facet_templates:
        if len(specs) >= target_count:
            break
        add_spec(name, list(keywords))

    fallback_index = 1
    while len(specs) < target_count:
        if zh_query:
            add_spec(
                f"{safe_query} · 子方向{fallback_index}",
                [safe_query, "方法", "应用", "研究"],
            )
        else:
            add_spec(
                f"{safe_query} · Subdomain {fallback_index}",
                [safe_query.lower(), "method", "application", "research"],
            )
        fallback_index += 1

    return specs[:target_count]


def assign_papers_to_graph_domains(
    papers: list[dict[str, Any]],
    domain_specs: list[GraphDomainSpec],
    *,
    score_relevance: Callable[[str, str, str], float],
    score_title_overlap: Callable[[str, str], float],
    min_papers_per_domain: int = 6,
    max_domains_per_paper: int = 2,
) -> tuple[dict[str, set[str]], dict[str, str], Counter[str]]:
    if not papers:
        return {}, {}, Counter()

    safe_specs = list(domain_specs or [])
    if not safe_specs:
        safe_specs = build_graph_domain_specs("Research Topic", target_domains=1)

    safe_min_per_domain = max(1, int(min_papers_per_domain or 1))
    safe_max_domains_per_paper = max(1, min(3, int(max_domains_per_paper or 1)))

    score_table: dict[str, list[tuple[str, float]]] = {}
    paper_domains: dict[str, set[str]] = {}
    paper_primary_domain: dict[str, str] = {}
    domain_to_papers: dict[str, set[str]] = defaultdict(set)

    for paper in papers:
        paper_id = _normalize_space(paper.get("paper_id") or "")
        if not paper_id:
            continue
        title = _normalize_space(paper.get("title") or "")
        abstract = _normalize_space(paper.get("abstract") or "")
        text = f"{title} {abstract}".lower()
        field_values = [
            _normalize_space(item).lower()
            for item in (paper.get("fields_of_study") or [])
            if _normalize_space(item)
        ]

        scored_domains: list[tuple[str, float]] = []
        for spec in safe_specs:
            base_relevance = max(0.0, min(1.0, float(score_relevance(spec.name, title, abstract))))
            title_overlap = max(0.0, min(1.0, float(score_title_overlap(spec.name, title))))
            keyword_hits = 0
            for keyword in spec.keywords:
                key = _normalize_space(keyword).lower()
                if not key:
                    continue
                if key in text:
                    keyword_hits += 1
            keyword_denom = max(1, min(4, len(spec.keywords)))
            keyword_signal = min(1.0, keyword_hits / keyword_denom)
            field_bonus = 0.0
            for field_value in field_values:
                if not field_value:
                    continue
                if field_value in spec.name.lower() or any(field_value in token for token in spec.keywords):
                    field_bonus = 0.08
                    break
            domain_score = min(1.0, max(base_relevance, title_overlap) * 0.74 + keyword_signal * 0.22 + field_bonus)
            scored_domains.append((spec.name, domain_score))

        scored_domains.sort(key=lambda item: item[1], reverse=True)
        score_table[paper_id] = scored_domains
        if not scored_domains:
            continue

        primary_domain, primary_score = scored_domains[0]
        assigned_domains: set[str] = {primary_domain}
        paper_primary_domain[paper_id] = primary_domain
        if safe_max_domains_per_paper > 1 and len(scored_domains) > 1:
            second_domain, second_score = scored_domains[1]
            if second_score >= max(0.18, primary_score * 0.72):
                assigned_domains.add(second_domain)

        paper_domains[paper_id] = assigned_domains
        for domain_name in assigned_domains:
            domain_to_papers[domain_name].add(paper_id)

    for spec in safe_specs:
        domain_name = spec.name
        current_count = len(domain_to_papers.get(domain_name, set()))
        if current_count >= safe_min_per_domain:
            continue
        ranked = sorted(
            (
                (paper_id, score)
                for paper_id, domain_scores in score_table.items()
                for candidate_name, score in domain_scores
                if candidate_name == domain_name
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        for paper_id, _score in ranked:
            assigned = paper_domains.setdefault(paper_id, set())
            if domain_name in assigned:
                continue
            assigned.add(domain_name)
            domain_to_papers[domain_name].add(paper_id)
            if current_count < 1:
                paper_primary_domain[paper_id] = domain_name
            current_count += 1
            if current_count >= safe_min_per_domain:
                break

    domain_counter: Counter[str] = Counter()
    for domain_names in paper_domains.values():
        for domain_name in domain_names:
            domain_counter[domain_name] += 1

    for spec in safe_specs:
        if domain_counter.get(spec.name, 0) <= 0:
            domain_counter[spec.name] = 0

    return paper_domains, paper_primary_domain, domain_counter
