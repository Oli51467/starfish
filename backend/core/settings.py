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

        # External APIs
        self.semantic_scholar_api_key = (os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip()
        self.scite_api_key = (os.getenv("SCITE_API_KEY") or "").strip()
        self.github_token = (os.getenv("GITHUB_TOKEN") or "").strip()

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

        self.http_timeout_seconds = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
        self.task_progress_step_seconds = float(os.getenv("TASK_PROGRESS_STEP_SECONDS", "0.2"))

    @staticmethod
    def _parse_csv(raw_value: str) -> list[str]:
        return [item.strip() for item in raw_value.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
