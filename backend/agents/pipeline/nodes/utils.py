from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    block_match = re.search(r"\{[\s\S]*\}", raw)
    if not block_match:
        return {}

    try:
        parsed = json.loads(block_match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def parse_json_array(text: str) -> list[Any]:
    raw = str(text or "").strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        pass

    block_match = re.search(r"\[[\s\S]*\]", raw)
    if not block_match:
        return []

    try:
        parsed = json.loads(block_match.group(0))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def clamp_progress(value: int) -> int:
    return max(0, min(100, int(value)))


def deduplicate_keywords(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        safe = str(item or "").strip()
        if not safe:
            continue
        key = safe.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(safe)
    return result


def extract_keywords_from_text(text: str, *, limit: int = 6) -> list[str]:
    safe = str(text or "").strip()
    if not safe:
        return []
    chunks = re.split(r"[，,、;；\n\t ]+", safe)
    return deduplicate_keywords(chunks)[: max(1, int(limit))]


def summarize_exception(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__
