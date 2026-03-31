from __future__ import annotations

from functools import lru_cache
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "Starfish Backend")
        self.app_version = os.getenv("APP_VERSION", "0.1.0")
        self.app_description = os.getenv(
            "APP_DESCRIPTION",
            "Starfish backend skeleton for domain map, reading list, gap finder and lineage APIs.",
        )

        self.cors_origins = self._parse_csv(
            os.getenv(
                "CORS_ORIGINS",
                "http://localhost:17327,http://127.0.0.1:17327,http://localhost:5173,http://127.0.0.1:5173",
            )
        )

        # LLM (OpenAI-compatible)
        self.api_key = (os.getenv("API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip()
        self.openai_base_url = (os.getenv("OPENAI_BASE_URL") or "").strip()
        self.openai_model = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
        self.embedding_model = (os.getenv("EMBEDDING_MODEL") or "text-embedding-v3").strip()

        # External APIs
        self.semantic_scholar_api_key = (os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip()
        self.openalex_mailto = (os.getenv("OPENALEX_MAILTO") or "").strip()
        self.crossref_mailto = (os.getenv("CROSSREF_MAILTO") or self.openalex_mailto or "").strip()
        self.opencitations_access_token = (os.getenv("OPENCITATIONS_ACCESS_TOKEN") or "").strip()
        self.scite_api_key = (os.getenv("SCITE_API_KEY") or "").strip()
        self.github_token = (os.getenv("GITHUB_TOKEN") or "").strip()
        self.retrieval_max_workers = max(2, int(os.getenv("RETRIEVAL_MAX_WORKERS", "4")))
        self.retrieval_provider_timeout_seconds = max(
            2.0,
            float(os.getenv("RETRIEVAL_PROVIDER_TIMEOUT_SECONDS", "12")),
        )
        self.retrieval_enable_semantic_scholar = self._parse_bool(
            os.getenv("RETRIEVAL_ENABLE_SEMANTIC_SCHOLAR"),
            default=True,
        )
        self.retrieval_enable_openalex = self._parse_bool(
            os.getenv("RETRIEVAL_ENABLE_OPENALEX"),
            default=True,
        )
        self.retrieval_enable_arxiv = self._parse_bool(
            os.getenv("RETRIEVAL_ENABLE_ARXIV"),
            default=True,
        )
        self.retrieval_enable_crossref = self._parse_bool(
            os.getenv("RETRIEVAL_ENABLE_CROSSREF"),
            default=True,
        )
        self.retrieval_enable_opencitations = self._parse_bool(
            os.getenv("RETRIEVAL_ENABLE_OPENCITATIONS"),
            default=True,
        )

        # Data layer placeholders
        self.postgres_dsn = os.getenv(
            "POSTGRES_DSN",
            "postgresql://starfish:starfish@localhost:5432/starfish",
        )
        self.neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_username = os.getenv("NEO4J_USERNAME", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", "starfish")
        self.neo4j_connect_retries = max(1, int(os.getenv("NEO4J_CONNECT_RETRIES", "3")))
        self.neo4j_connect_retry_interval_seconds = max(
            0.1, float(os.getenv("NEO4J_CONNECT_RETRY_INTERVAL_SECONDS", "0.8"))
        )
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.enable_landscape_cache = self._parse_bool(
            os.getenv("ENABLE_LANDSCAPE_CACHE"),
            default=True,
        )
        self.landscape_cache_ttl_seconds = max(
            60,
            int(os.getenv("LANDSCAPE_CACHE_TTL_SECONDS", "604800")),
        )
        self.enable_landscape_inflight_dedup = self._parse_bool(
            os.getenv("ENABLE_LANDSCAPE_INFLIGHT_DEDUP"),
            default=True,
        )
        self.landscape_inflight_ttl_seconds = max(
            60,
            int(os.getenv("LANDSCAPE_INFLIGHT_TTL_SECONDS", "1800")),
        )

        self.http_timeout_seconds = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
        self.task_progress_step_seconds = float(os.getenv("TASK_PROGRESS_STEP_SECONDS", "0.2"))
        self.graphrag_force_mock = (os.getenv("GRAPHRAG_FORCE_MOCK") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.enable_landscape_summary = self._parse_bool(os.getenv("ENABLE_LANDSCAPE_SUMMARY"), default=False)

        # Insight orchestration
        self.insight_agent_mode = self._parse_choice(
            os.getenv("INSIGHT_AGENT_MODE"),
            default="orchestrated",
            choices={"legacy", "orchestrated"},
        )
        self.insight_worker_count = max(1, min(16, int(os.getenv("INSIGHT_WORKER_COUNT", "4"))))
        self.insight_worker_execution_backend = self._parse_choice(
            os.getenv("INSIGHT_WORKER_EXECUTION_BACKEND"),
            default="subprocess",
            choices={"inprocess", "subprocess"},
        )
        self.insight_worker_subprocess_timeout_seconds = max(
            5.0,
            min(180.0, float(os.getenv("INSIGHT_WORKER_SUBPROCESS_TIMEOUT_SECONDS", "40"))),
        )
        self.insight_worker_task_timeout_seconds = max(
            10.0,
            min(300.0, float(os.getenv("INSIGHT_WORKER_TASK_TIMEOUT_SECONDS", "75"))),
        )
        self.insight_pdf_render_timeout_seconds = max(
            8.0,
            min(90.0, float(os.getenv("INSIGHT_PDF_RENDER_TIMEOUT_SECONDS", "15"))),
        )
        self.insight_max_subagent_depth = max(0, min(8, int(os.getenv("INSIGHT_MAX_SUBAGENT_DEPTH", "2"))))
        self.insight_max_subtasks_per_round = max(
            1,
            min(128, int(os.getenv("INSIGHT_MAX_SUBTASKS_PER_ROUND", "24"))),
        )
        self.insight_max_subtasks_per_parent = max(
            1,
            min(8, int(os.getenv("INSIGHT_MAX_SUBTASKS_PER_PARENT", "2"))),
        )
        self.insight_memory_db_path = (os.getenv("INSIGHT_MEMORY_DB_PATH") or "").strip()
        self.runtime_eval_db_path = (os.getenv("RUNTIME_EVAL_DB_PATH") or "").strip()
        self.unified_memory_db_path = (os.getenv("UNIFIED_MEMORY_DB_PATH") or "").strip()

        # Auth
        self.google_client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
        self.github_oauth_client_id = (os.getenv("GITHUB_OAUTH_CLIENT_ID") or "").strip()
        self.github_oauth_client_secret = (os.getenv("GITHUB_OAUTH_CLIENT_SECRET") or "").strip()
        self.github_oauth_redirect_uri = (os.getenv("GITHUB_OAUTH_REDIRECT_URI") or "").strip()
        self.session_secret = (os.getenv("SESSION_SECRET") or "change-this-session-secret").strip()
        self.session_expire_hours = max(1, int(os.getenv("SESSION_EXPIRE_HOURS", "168")))

    @staticmethod
    def _parse_csv(raw_value: str) -> list[str]:
        return [item.strip() for item in raw_value.split(",") if item.strip()]

    @staticmethod
    def _parse_bool(raw_value: str | None, *, default: bool = False) -> bool:
        if raw_value is None:
            return default
        return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _parse_choice(
        raw_value: str | None,
        *,
        default: str,
        choices: set[str],
    ) -> str:
        if raw_value is None:
            return default
        safe = str(raw_value).strip().lower()
        if safe in choices:
            return safe
        return default


@lru_cache
def get_settings() -> Settings:
    return Settings()
