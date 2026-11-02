"""Meta web_search tool configuration + request builders."""
from __future__ import annotations

from vii.config import Settings

SEARCH_SYSTEM = ("You are an evidence researcher. Use the web_search tool for every "
                 "factual claim. Return each answer with inline citations and never "
                 "invent URLs.")


def web_search_tool() -> dict:
    return {"type": "web_search"}


def build_search_payload(query: str, model: str,
                         context_size: str = "medium",
                         include_results: bool = True) -> dict:
    payload = {
        "model": model,
        "tools": [web_search_tool()],
        "tool_choice": "auto",
        "input": [{"role": "user", "content": (
            f"{SEARCH_SYSTEM}\n\nResearch this claim and report the strongest "
            f"supporting AND contradicting sources with exact URLs:\n{query}")}],
    }
    if context_size in ("low", "medium", "high"):
        payload["tool_choice"] = "auto"
        payload["metadata"] = {"web_search_context_size": context_size}
    if include_results:
        payload["include"] = ["web_search_call.results"]
    return payload


def search_configured(settings: Settings) -> bool:
    return settings.live_mode


def offline_note(settings: Settings) -> str:
    if settings.demo_enabled:
        return "synthetic demo mode: no live web search performed"
    if not settings.has_api_key:
        return "no API key configured: no live web search performed"
    return ""
