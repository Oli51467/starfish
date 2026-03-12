from __future__ import annotations

from typing import Any

from openai import OpenAI

from core.settings import get_settings


def get_client() -> OpenAI:
    settings = get_settings()
    if not settings.api_key:
        raise RuntimeError("API_KEY is not configured.")

    if settings.openai_base_url:
        return OpenAI(api_key=settings.api_key, base_url=settings.openai_base_url)
    return OpenAI(api_key=settings.api_key)


def is_configured() -> bool:
    return bool(get_settings().api_key)


def chat(messages: list[dict[str, Any]], **kwargs: Any) -> Any:
    settings = get_settings()
    client = get_client()
    return client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        temperature=0.2,
        **kwargs,
    )
