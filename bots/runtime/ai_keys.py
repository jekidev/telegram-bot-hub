"""Shared AI API key resolution (no secrets in code — use env only)."""

import os


def venice_api_key_candidates() -> list[str]:
    """Primary Venice key (OLLAMA_API_KEY) then optional VALKYRIE_AI_FALLBACK_KEY."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in (
        os.environ.get("OLLAMA_API_KEY", "").strip(),
        os.environ.get("VALKYRIE_AI_FALLBACK_KEY", "").strip(),
    ):
        if raw and raw not in seen:
            seen.add(raw)
            out.append(raw)
    return out
