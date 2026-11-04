"""MCP server: tools registered, callable, caller-owned keys."""
from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio()
async def test_tools_registered():
    from vii.mcp_server import mcp

    names = [t.name for t in await mcp.list_tools()]
    assert names == ["vii_quick_look", "vii_check",
                     "vii_follow_up", "vii_key_status"]


@pytest.mark.asyncio()
async def test_quick_look_tool_no_key_needed(tmp_path):
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    from vii.mcp_server import mcp

    src = tmp_path / "tiny.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=black:size=64x64:duration=1",
                    str(src)], check=True, timeout=60)
    out = await mcp.call_tool("vii_quick_look", {"path": str(src)})
    text = out.content[0].text
    assert '"file_name": "tiny.mp4"' in text


@pytest.mark.asyncio()
async def test_check_requires_caller_key_unless_demo():
    from vii.mcp_server import mcp

    out = await mcp.call_tool("vii_check", {"source": "x.mp4"})
    assert "api_key is required" in out.content[0].text


@pytest.mark.asyncio()
async def test_follow_up_uses_supplied_report():
    from vii.mcp_server import mcp

    report = {"claims": [{"text": "The Eiffel Tower is tall.",
                          "status": "supported", "explanation": "yes"}],
              "sources": []}
    out = await mcp.call_tool("vii_follow_up",
                              {"report_json": json.dumps(report),
                               "question": "claims"})
    assert "Eiffel Tower" in out.content[0].text


@pytest.mark.asyncio()
async def test_key_status_never_shows_secret():
    from vii.mcp_server import mcp

    out = await mcp.call_tool("vii_key_status", {})
    payload = json.loads(out.content[0].text)
    assert "key_source" in payload
    assert "MODEL_API_KEY" not in out.content[0].text or \
        "provider_key_configured" in payload


def test_library_accepts_caller_key(tmp_path):
    from vii import VII, VideoChecker

    client = VII(api_key="caller-key-not-real",
                 database_url=f"sqlite:///{tmp_path}/vii.db",
                 storage_dir=tmp_path)
    assert client.settings.effective_api_key == "caller-key-not-real"
    checker = VideoChecker(settings=client.settings)
    assert checker.settings.effective_api_key == "caller-key-not-real"
    checker2 = VideoChecker(api_key="caller-key-not-real")
    assert checker2.settings.effective_api_key == "caller-key-not-real"
