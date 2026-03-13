from __future__ import annotations

from contextlib import suppress
from functools import lru_cache
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import Neo4jError

    _NEO4J_AVAILABLE = True
except ImportError:  # pragma: no cover - handled for local/dev fallback
    GraphDatabase = None  # type: ignore[assignment]
    Neo4jError = Exception  # type: ignore[assignment]
    _NEO4J_AVAILABLE = False

from core.settings import get_settings

logger = logging.getLogger(__name__)


class Neo4jRepository:
    """Persistence adapter for Starfish knowledge graphs."""

    def __init__(self) -> None:
        settings = get_settings()
        self.uri = settings.neo4j_uri
        self.username = settings.neo4j_username
        self.password = settings.neo4j_password
        self.connect_retries = settings.neo4j_connect_retries
        self.connect_retry_interval_seconds = settings.neo4j_connect_retry_interval_seconds
        self._driver = None
        if not _NEO4J_AVAILABLE:
            logger.warning("Neo4j driver package is not installed; graph persistence disabled.")

    def _driver_or_none(self):
        if not _NEO4J_AVAILABLE:
            return None

        if self._driver is not None:
            return self._driver

        candidates = self._candidate_uris()
        attempts = max(1, self.connect_retries)
        for attempt in range(1, attempts + 1):
            for candidate_uri in candidates:
                driver = None
                try:
                    driver = GraphDatabase.driver(
                        candidate_uri,
                        auth=(self.username, self.password),
                    )
                    # Force connectivity check to avoid caching an unreachable driver.
                    driver.verify_connectivity()
                    self._driver = driver
                    if candidate_uri != self.uri:
                        logger.warning(
                            "Neo4j URI fallback in use: configured '%s', active '%s'",
                            self.uri,
                            candidate_uri,
                        )
                    return self._driver
                except Exception as exc:  # noqa: BLE001
                    with suppress(Exception):
                        if driver is not None:
                            driver.close()
                    logger.warning(
                        "Neo4j connection attempt %d/%d failed for '%s': %s",
                        attempt,
                        attempts,
                        candidate_uri,
                        exc,
                    )

            if attempt < attempts:
                time.sleep(self.connect_retry_interval_seconds)

        return None

    def is_available(self) -> bool:
        driver = self._driver_or_none()
        if driver is None:
            return False

        try:
            with driver.session() as session:
                session.run("RETURN 1 AS ok").single()
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Neo4j connectivity check failed")
            return False

    def _candidate_uris(self) -> list[str]:
        base_uri = (self.uri or "").strip()
        candidates: list[str] = []
        if base_uri:
            self._append_candidate(candidates, base_uri)
            parsed = urlparse(base_uri)
            host = parsed.hostname or ""

            if host == "neo4j":
                self._append_candidate(candidates, self._replace_hostname(base_uri, "localhost"))
                self._append_candidate(candidates, self._replace_hostname(base_uri, "127.0.0.1"))
            elif host in {"localhost", "127.0.0.1"}:
                self._append_candidate(candidates, self._replace_hostname(base_uri, "neo4j"))

        # Keep common local defaults to make startup resilient when env injection is missing.
        self._append_candidate(candidates, "bolt://neo4j:7687")
        self._append_candidate(candidates, "bolt://localhost:7687")
        self._append_candidate(candidates, "bolt://127.0.0.1:7687")
        return candidates

    @staticmethod
    def _append_candidate(candidates: list[str], uri: str) -> None:
        value = (uri or "").strip()
        if not value:
            return
        if value in candidates:
            return
        candidates.append(value)

    @staticmethod
    def _replace_hostname(uri: str, new_host: str) -> str:
        parsed = urlparse(uri)
        if not parsed.hostname:
            return uri

        userinfo = ""
        if parsed.username:
            userinfo = parsed.username
            if parsed.password:
                userinfo += f":{parsed.password}"
            userinfo += "@"

        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"{userinfo}{new_host}{port}"
        return urlunparse(parsed._replace(netloc=netloc))

    def store_graph(
        self,
        graph_id: str,
        query: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> bool:
        driver = self._driver_or_none()
        if driver is None:
            return False

        try:
            with driver.session() as session:
                session.execute_write(
                    self._write_graph,
                    graph_id,
                    query,
                    nodes,
                    edges,
                )
            return True
        except Neo4jError:
            logger.exception("Failed writing graph to Neo4j")
            return False
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected Neo4j write error")
            return False

    def store_domain_landscape(
        self,
        landscape_id: str,
        query: str,
        payload: dict[str, Any],
    ) -> bool:
        driver = self._driver_or_none()
        if driver is None:
            return False

        try:
            with driver.session() as session:
                session.execute_write(
                    self._write_domain_landscape,
                    landscape_id,
                    query,
                    payload,
                )
            return True
        except Neo4jError:
            logger.exception("Failed writing domain landscape to Neo4j")
            return False
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected domain landscape write error")
            return False

    def fetch_graph(self, graph_id: str) -> dict[str, Any] | None:
        driver = self._driver_or_none()
        if driver is None:
            return None

        try:
            with driver.session() as session:
                return session.execute_read(self._read_graph, graph_id)
        except Neo4jError:
            logger.exception("Failed reading graph from Neo4j")
            return None
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected Neo4j read error")
            return None

    @staticmethod
    def _write_graph(tx, graph_id: str, query: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        tx.run(
            """
            MERGE (g:GraphRun {graph_id: $graph_id})
            SET g.query = $source_query, g.updated_at = datetime(), g.source = 'graphrag'
            """,
            graph_id=graph_id,
            source_query=query,
        )
        tx.run(
            """
            MATCH (g:GraphRun {graph_id: $graph_id})-[r:CONTAINS]->()
            DELETE r
            """,
            graph_id=graph_id,
        )
        tx.run(
            """
            MATCH ()-[r:MENTIONS|BELONGS_TO|RELATED_TO|COVERS {graph_id: $graph_id}]-()
            DELETE r
            """,
            graph_id=graph_id,
        )

        for node in nodes:
            node_type = node.get("type")
            if node_type == "paper":
                tx.run(
                    """
                    MERGE (p:Paper {paper_id: $paper_id})
                    SET p.title = $label,
                        p.size = $size,
                        p.score = $score,
                        p.year = $year,
                        p.venue = $venue,
                        p.url = $url,
                        p.authors = $authors,
                        p.abstract = $abstract,
                        p.keywords = $keywords,
                        p.published_month = $published_month,
                        p.impact_factor = $impact_factor,
                        p.quartile = $quartile,
                        p.citation_count = $citation_count,
                        p.relevance = $relevance,
                        p.influence = $influence
                    WITH p
                    MATCH (g:GraphRun {graph_id: $graph_id})
                    MERGE (g)-[:CONTAINS]->(p)
                    """,
                    graph_id=graph_id,
                    paper_id=node.get("paper_id") or node.get("id"),
                    label=node.get("label", ""),
                    size=float(node.get("size") or 1.0),
                    score=float(node.get("score") or 0.0),
                    year=node.get("meta", {}).get("year"),
                    venue=node.get("meta", {}).get("venue"),
                    url=node.get("meta", {}).get("url"),
                    authors=node.get("meta", {}).get("authors", ""),
                    abstract=node.get("meta", {}).get("abstract", ""),
                    keywords=node.get("meta", {}).get("keywords", ""),
                    published_month=int(node.get("meta", {}).get("published_month") or 0),
                    impact_factor=float(node.get("meta", {}).get("impact_factor") or 0.0),
                    quartile=node.get("meta", {}).get("quartile", ""),
                    citation_count=int(node.get("meta", {}).get("citation_count") or 0),
                    relevance=float(node.get("meta", {}).get("relevance") or 0.0),
                    influence=float(node.get("meta", {}).get("influence") or 0.0),
                )
            elif node_type == "entity":
                tx.run(
                    """
                    MERGE (e:Entity {name: $name})
                    SET e.size = $size, e.score = $score, e.entity_type = $entity_type
                    WITH e
                    MATCH (g:GraphRun {graph_id: $graph_id})
                    MERGE (g)-[:CONTAINS]->(e)
                    """,
                    graph_id=graph_id,
                    name=node.get("label", ""),
                    size=float(node.get("size") or 1.0),
                    score=float(node.get("score") or 0.0),
                    entity_type=node.get("meta", {}).get("entity_type", "concept"),
                )
            elif node_type == "domain":
                tx.run(
                    """
                    MERGE (d:Domain {name: $name})
                    SET d.size = $size,
                        d.score = $score
                    WITH d
                    MATCH (g:GraphRun {graph_id: $graph_id})
                    MERGE (g)-[:CONTAINS]->(d)
                    """,
                    graph_id=graph_id,
                    name=node.get("label", ""),
                    size=float(node.get("size") or 1.0),
                    score=float(node.get("score") or 0.0),
                )

        for edge in edges:
            relation = edge.get("relation")
            if relation == "mentions":
                tx.run(
                    """
                    MATCH (p:Paper {paper_id: $source_paper_id})
                    MATCH (e:Entity {name: $target_entity})
                    MERGE (p)-[r:MENTIONS {graph_id: $graph_id}]->(e)
                    SET r.weight = $weight
                    """,
                    graph_id=graph_id,
                    source_paper_id=edge.get("meta", {}).get("source_paper_id"),
                    target_entity=edge.get("meta", {}).get("target_entity"),
                    weight=float(edge.get("weight") or 0.0),
                )
            elif relation == "belongs_to":
                tx.run(
                    """
                    MATCH (p:Paper {paper_id: $source_paper_id})
                    MATCH (d:Domain {name: $target_domain})
                    MERGE (p)-[r:BELONGS_TO {graph_id: $graph_id}]->(d)
                    SET r.weight = $weight
                    """,
                    graph_id=graph_id,
                    source_paper_id=edge.get("meta", {}).get("source_paper_id"),
                    target_domain=edge.get("meta", {}).get("target_domain"),
                    weight=float(edge.get("weight") or 0.0),
                )
            elif relation == "related":
                tx.run(
                    """
                    MATCH (p1:Paper {paper_id: $left_paper_id})
                    MATCH (p2:Paper {paper_id: $right_paper_id})
                    MERGE (p1)-[r:RELATED_TO {graph_id: $graph_id}]->(p2)
                    SET r.weight = $weight,
                        r.basis = 'shared_entity',
                        r.shared_entities = $shared_entities
                    """,
                    graph_id=graph_id,
                    left_paper_id=edge.get("meta", {}).get("left_paper_id"),
                    right_paper_id=edge.get("meta", {}).get("right_paper_id"),
                    weight=float(edge.get("weight") or 0.0),
                    shared_entities=edge.get("meta", {}).get("shared_entities", ""),
                )
            elif relation == "covers":
                tx.run(
                    """
                    MATCH (d:Domain {name: $domain})
                    MATCH (e:Entity {name: $entity})
                    MERGE (d)-[r:COVERS {graph_id: $graph_id}]->(e)
                    SET r.weight = $weight
                    """,
                    graph_id=graph_id,
                    domain=edge.get("meta", {}).get("domain"),
                    entity=edge.get("meta", {}).get("entity"),
                    weight=float(edge.get("weight") or 0.0),
                )

    @staticmethod
    def _write_domain_landscape(
        tx,
        landscape_id: str,
        query: str,
        payload: dict[str, Any],
    ) -> None:
        domain_name = str(payload.get("domain_name") or query or "").strip()
        domain_name_en = str(payload.get("domain_name_en") or "").strip()
        description = str(payload.get("description") or "").strip()
        sub_directions = list(payload.get("sub_directions") or [])

        tx.run(
            """
            MERGE (run:LandscapeRun {landscape_id: $landscape_id})
            SET run.query = $source_query,
                run.domain_name = $domain_name,
                run.updated_at = datetime(),
                run.source = 'domain_landscape'
            """,
            landscape_id=landscape_id,
            source_query=query,
            domain_name=domain_name,
        )
        tx.run(
            """
            MATCH (s:SubDomain {landscape_id: $landscape_id})
            DETACH DELETE s
            """,
            landscape_id=landscape_id,
        )
        tx.run(
            """
            MATCH (run:LandscapeRun {landscape_id: $landscape_id})-[r]->()
            DELETE r
            """,
            landscape_id=landscape_id,
        )
        tx.run(
            """
            MERGE (d:Domain {name: $domain_name})
            SET d.description = $description,
                d.domain_name_en = $domain_name_en
            WITH d
            MATCH (run:LandscapeRun {landscape_id: $landscape_id})
            MERGE (run)-[:ROOT_DOMAIN]->(d)
            """,
            landscape_id=landscape_id,
            domain_name=domain_name,
            description=description,
            domain_name_en=domain_name_en,
        )

        for index, sub in enumerate(sub_directions):
            sub_key = f"{landscape_id}:{index}"
            sub_name = str(sub.get("name") or "").strip()
            if not sub_name:
                continue

            tx.run(
                """
                MERGE (s:SubDomain {landscape_key: $sub_key})
                SET s.landscape_id = $landscape_id,
                    s.name = $name,
                    s.name_en = $name_en,
                    s.description = $description,
                    s.status = $status,
                    s.paper_count = $paper_count,
                    s.recent_ratio = $recent_ratio,
                    s.recent_paper_count = $recent_paper_count,
                    s.avg_citations = $avg_citations,
                    s.provider_used = $provider_used,
                    s.updated_at = datetime()
                WITH s
                MATCH (run:LandscapeRun {landscape_id: $landscape_id})
                MERGE (run)-[:HAS_SUBDOMAIN]->(s)
                WITH s
                MATCH (d:Domain {name: $domain_name})
                MERGE (d)-[r:HAS_SUBDOMAIN {landscape_id: $landscape_id}]->(s)
                SET r.weight = $recent_ratio
                """,
                sub_key=sub_key,
                landscape_id=landscape_id,
                domain_name=domain_name,
                name=sub_name,
                name_en=str(sub.get("name_en") or "").strip(),
                description=str(sub.get("description") or "").strip(),
                status=str(sub.get("status") or "stable").strip(),
                paper_count=int(sub.get("paper_count") or 0),
                recent_ratio=float(sub.get("recent_ratio") or 0.0),
                recent_paper_count=int(sub.get("recent_paper_count") or 0),
                avg_citations=int(sub.get("avg_citations") or 0),
                provider_used=str(sub.get("provider_used") or "").strip(),
            )

            methods = sub.get("methods") or []
            for method_name in methods:
                method = str(method_name or "").strip()
                if not method:
                    continue
                tx.run(
                    """
                    MATCH (s:SubDomain {landscape_key: $sub_key})
                    MERGE (m:Method {name: $method})
                    MERGE (s)-[r:HAS_METHOD {landscape_id: $landscape_id}]->(m)
                    SET r.weight = 1.0
                    """,
                    sub_key=sub_key,
                    method=method,
                    landscape_id=landscape_id,
                )

            papers = sub.get("core_papers") or []
            for paper in papers:
                if not isinstance(paper, dict):
                    continue
                paper_id = str(paper.get("id") or "").strip()
                title = str(paper.get("title") or "").strip()
                if not paper_id and not title:
                    continue
                if not paper_id:
                    paper_id = f"{landscape_id}:{sub_key}:{Neo4jRepository._slug(title)}"
                tx.run(
                    """
                    MATCH (s:SubDomain {landscape_key: $sub_key})
                    MERGE (p:Paper {paper_id: $paper_id})
                    SET p.title = $title,
                        p.year = $year,
                        p.citation_count = $citation_count,
                        p.authors = $authors
                    MERGE (s)-[r:CORE_PAPER {landscape_id: $landscape_id}]->(p)
                    SET r.weight = $weight
                    """,
                    sub_key=sub_key,
                    landscape_id=landscape_id,
                    paper_id=paper_id,
                    title=title,
                    year=paper.get("year"),
                    citation_count=int(paper.get("citation_count") or 0),
                    authors=", ".join(str(item).strip() for item in (paper.get("authors") or []) if str(item).strip()),
                    weight=float(sub.get("recent_ratio") or 0.0),
                )

    @staticmethod
    def _read_graph(tx, graph_id: str) -> dict[str, Any] | None:
        graph_row = tx.run(
            """
            MATCH (g:GraphRun {graph_id: $graph_id})
            RETURN g.query AS query, toString(g.updated_at) AS updated_at
            """,
            graph_id=graph_id,
        ).single()
        if graph_row is None:
            return None

        node_rows = tx.run(
            """
            MATCH (:GraphRun {graph_id: $graph_id})-[:CONTAINS]->(n)
            RETURN labels(n) AS labels, properties(n) AS props
            """,
            graph_id=graph_id,
        )
        nodes: list[dict[str, Any]] = []
        for row in node_rows:
            label_list = row.get("labels") or []
            props = row.get("props") or {}
            mapped = Neo4jRepository._map_node_to_payload(label_list, props)
            if mapped:
                nodes.append(mapped)

        edge_rows = tx.run(
            """
            MATCH (g:GraphRun {graph_id: $graph_id})-[:CONTAINS]->(source)
            MATCH (g)-[:CONTAINS]->(target)
            MATCH (source)-[r]->(target)
            WHERE type(r) IN ['MENTIONS', 'BELONGS_TO', 'RELATED_TO', 'COVERS']
              AND coalesce(r.graph_id, '') = $graph_id
            RETURN labels(source) AS source_labels,
                   properties(source) AS source_props,
                   labels(target) AS target_labels,
                   properties(target) AS target_props,
                   type(r) AS relation_type,
                   properties(r) AS relation_props
            """,
            graph_id=graph_id,
        )
        edges: list[dict[str, Any]] = []
        for row in edge_rows:
            mapped = Neo4jRepository._map_edge_to_payload(
                row.get("source_labels") or [],
                row.get("source_props") or {},
                row.get("target_labels") or [],
                row.get("target_props") or {},
                str(row.get("relation_type") or ""),
                row.get("relation_props") or {},
            )
            if mapped:
                edges.append(mapped)

        return {
            "graph_id": graph_id,
            "query": str(graph_row.get("query") or ""),
            "updated_at": str(graph_row.get("updated_at") or ""),
            "nodes": nodes,
            "edges": edges,
        }

    @staticmethod
    def _map_node_to_payload(labels: list[str], props: dict[str, Any]) -> dict[str, Any] | None:
        if "Paper" in labels:
            paper_id = str(props.get("paper_id") or "")
            if not paper_id:
                return None
            return {
                "id": f"paper:{paper_id}",
                "paper_id": paper_id,
                "label": str(props.get("title") or "Unknown Paper"),
                "type": "paper",
                "size": Neo4jRepository._safe_float(props.get("size"), 6.0),
                "score": Neo4jRepository._safe_float(props.get("score"), 0.0),
                "meta": {
                    "title": str(props.get("title") or "Unknown Paper"),
                    "year": str(props.get("year") or ""),
                    "venue": str(props.get("venue") or "Unknown Venue"),
                    "url": str(props.get("url") or ""),
                    "authors": str(props.get("authors") or ""),
                    "abstract": str(props.get("abstract") or ""),
                    "keywords": str(props.get("keywords") or ""),
                    "published_month": str(props.get("published_month") or ""),
                    "impact_factor": str(props.get("impact_factor") or ""),
                    "quartile": str(props.get("quartile") or ""),
                    "citation_count": str(props.get("citation_count") or 0),
                    "relevance": str(props.get("relevance") or 0),
                    "influence": str(props.get("influence") or 0),
                },
            }

        if "Entity" in labels:
            name = str(props.get("name") or "")
            if not name:
                return None
            return {
                "id": f"entity:{Neo4jRepository._slug(name)}",
                "label": name,
                "type": "entity",
                "size": Neo4jRepository._safe_float(props.get("size"), 4.0),
                "score": Neo4jRepository._safe_float(props.get("score"), 0.0),
                "meta": {"entity_type": str(props.get("entity_type") or "concept")},
            }

        if "Domain" in labels:
            name = str(props.get("name") or "")
            if not name:
                return None
            return {
                "id": f"domain:{Neo4jRepository._slug(name)}",
                "label": name,
                "type": "domain",
                "size": Neo4jRepository._safe_float(props.get("size"), 6.0),
                "score": Neo4jRepository._safe_float(props.get("score"), 0.0),
                "meta": {},
            }

        return None

    @staticmethod
    def _map_edge_to_payload(
        source_labels: list[str],
        source_props: dict[str, Any],
        target_labels: list[str],
        target_props: dict[str, Any],
        relation_type: str,
        relation_props: dict[str, Any],
    ) -> dict[str, Any] | None:
        source_id = Neo4jRepository._node_id(source_labels, source_props)
        target_id = Neo4jRepository._node_id(target_labels, target_props)
        if not source_id or not target_id:
            return None

        mapping = {
            "MENTIONS": "mentions",
            "BELONGS_TO": "belongs_to",
            "RELATED_TO": "related",
            "COVERS": "covers",
        }
        relation = mapping.get(relation_type)
        if relation is None:
            return None

        meta: dict[str, str] = {}
        if relation == "mentions":
            meta = {
                "source_paper_id": str(source_props.get("paper_id") or ""),
                "target_entity": str(target_props.get("name") or ""),
            }
        elif relation == "belongs_to":
            meta = {
                "source_paper_id": str(source_props.get("paper_id") or ""),
                "target_domain": str(target_props.get("name") or ""),
            }
        elif relation == "related":
            meta = {
                "left_paper_id": str(source_props.get("paper_id") or ""),
                "right_paper_id": str(target_props.get("paper_id") or ""),
                "shared_entities": str(relation_props.get("shared_entities") or ""),
            }
        elif relation == "covers":
            meta = {
                "domain": str(source_props.get("name") or ""),
                "entity": str(target_props.get("name") or ""),
            }

        return {
            "source": source_id,
            "target": target_id,
            "relation": relation,
            "weight": Neo4jRepository._safe_float(relation_props.get("weight"), 0.0),
            "meta": meta,
        }

    @staticmethod
    def _node_id(labels: list[str], props: dict[str, Any]) -> str:
        if "Paper" in labels:
            paper_id = str(props.get("paper_id") or "")
            return f"paper:{paper_id}" if paper_id else ""
        if "Entity" in labels:
            name = str(props.get("name") or "")
            return f"entity:{Neo4jRepository._slug(name)}" if name else ""
        if "Domain" in labels:
            name = str(props.get("name") or "")
            return f"domain:{Neo4jRepository._slug(name)}" if name else ""
        return ""

    @staticmethod
    def _slug(text: str) -> str:
        lowered = text.strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
        return slug or "node"

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def close(self) -> None:
        if self._driver is None:
            return
        with suppress(Exception):
            self._driver.close()
        self._driver = None


@lru_cache
def get_neo4j_repository() -> Neo4jRepository:
    return Neo4jRepository()
