from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from core.settings import get_settings


class OpenCitationsClientError(RuntimeError):
    """Raised when OpenCitations API is unavailable or returns invalid payload."""


class OpenCitationsClient:
    """OpenCitations Index API wrapper for citation-count enrichment."""

    BASE_URL = "https://api.opencitations.net/index/v2"

    def __init__(self) -> None:
        settings = get_settings()
        self.timeout = settings.http_timeout_seconds
        self.access_token = settings.opencitations_access_token

    def fetch_citation_count_by_doi(self, doi: str) -> int:
        normalized_doi = self._normalize_doi(doi)
        if not normalized_doi:
            return 0

        path = f"/citation-count/doi:{quote(normalized_doi, safe='')}"
        payload = self._get(path)
        if isinstance(payload, list):
            if not payload:
                return 0
            head = payload[0] if isinstance(payload[0], dict) else {}
            return self._safe_int(head.get("count"))
        if isinstance(payload, dict):
            return self._safe_int(payload.get("count"))
        return 0

    def _get(self, path: str) -> Any:
        headers: dict[str, str] = {}
        if self.access_token:
            headers["authorization"] = self.access_token

        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
                response = client.get(f"{self.BASE_URL}{path}")
        except httpx.RequestError as exc:
            raise OpenCitationsClientError(str(exc)) from exc

        if response.status_code == 404:
            return []
        if response.status_code >= 400:
            raise OpenCitationsClientError(self._extract_error_message(response))

        try:
            return response.json()
        except ValueError as exc:
            raise OpenCitationsClientError("invalid_opencitations_json_response") from exc

    @classmethod
    def _normalize_doi(cls, raw_value: Any) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return ""
        value = re.sub(r"^doi:\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
        return value.lower()

    @staticmethod
    def _safe_int(raw_value: Any) -> int:
        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            return (response.text or "").strip() or f"opencitations_api_error_{response.status_code}"

        if isinstance(payload, list) and payload:
            head = payload[0]
            if isinstance(head, dict):
                for key in ("error", "message", "detail"):
                    value = head.get(key)
                    if value:
                        return str(value)
        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                value = payload.get(key)
                if value:
                    return str(value)
        return str(payload)
