"""VII as agentic tools (MCP server for Claude Code / OpenClaw).

Exposes the existing library surface as MCP tools, no new analysis
logic. The caller supplies its own API key per tool call (or leaves it
blank for local-only tools), so agent code never depends on VII's .env.

Tools:
    vii_quick_look   fast local pre-screen (no key needed)
    vii_check        full pipeline analysis (needs api_key unless demo)
    vii_follow_up    ask about a kept report (needs the report JSON)
    vii_key_status   credential + readiness state (never shows secrets)

Run over stdio: ``.venv/bin/vii-mcp`` or ``python -m vii.mcp_server``.
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("vii")


def _client(api_key: str | None, demo: bool):
    """Library client with a caller-supplied key (never VII's env)."""
    from vii.checker import VideoChecker
    from vii.config import Settings

    settings = Settings(_env_file=None, VII_DEMO_MODE=demo)
    return VideoChecker(api_key=api_key or None, settings=settings)


@mcp.tool()
def vii_quick_look(path: str) -> dict[str, Any]:
    """Fast local pre-screen of a video file (seconds, no key needed).

    Returns file facts, forensics signals, originality, and spam
    markers. Local only, no provider, no credits, no job created.
    """
    from vii import VII
    from vii.config import Settings

    client = VII(settings=Settings(_env_file=None))
    try:
        return client.quick_look(path)
    finally:
        client.close()


@mcp.tool()
def vii_check(source: str, api_key: str = "", demo: bool = False,
              enable_ai_detection: bool = False) -> dict[str, Any]:
    """Full VII pipeline analysis of a video file or URL.

    Provide the caller's own Meta API key via api_key (never read
    from VII's environment), or set demo=true for a free synthetic
    run. Returns the complete report dict (claims, verdicts, evidence,
    transcript, capabilities). Long videos take minutes.
    """
    if not demo and not api_key:
        return {"ok": False,
                "error": "api_key is required unless demo=true"}
    checker = _client(api_key or None, demo)
    if enable_ai_detection:
        checker.settings = checker.settings.model_copy(
            update={"enable_ai_detection": True})
        checker._client.settings = checker.settings
    try:
        report = checker.check(source, demo=demo)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        checker.close()
    report["ok"] = True
    return report


@mcp.tool()
def vii_follow_up(report_json: str, question: str) -> dict[str, Any]:
    """Ask a follow-up about a kept VII report (no provider call).

    Pass the report dict from vii_check as a JSON string. Answers
    from stored claims/sources only, 'claims', 'sources', a verdict
    name, or keywords.
    """
    from vii.checker import VideoChecker
    from vii.config import Settings

    try:
        report = json.loads(report_json)
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": f"invalid report_json: {e}"}
    checker = VideoChecker(settings=Settings(_env_file=None))
    try:
        answer = checker.follow_up(report, question)
    finally:
        checker.close()
    return {"ok": True, "answer": answer}


@mcp.tool()
def vii_key_status() -> dict[str, Any]:
    """Credential + readiness state (never shows secret values)."""
    from vii.config import get_settings
    from vii.providers.capabilities import readiness_report

    s = get_settings()
    return {"provider_key_configured": s.has_api_key,
            "key_source": s.key_source,
            "model": s.meta_model,
            "base_url": s.meta_base_url,
            "readiness": readiness_report(s)}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
