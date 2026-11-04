"""Spam-format screening: local signals, hosted judgment, wiring."""
from __future__ import annotations

import json


def test_local_signals_catch_formula_markers():
    from vii.integrity.spam import local_signals

    out = local_signals("A reddit story reading.", "", ["Part 1 of the story"])
    assert any("part 1" in s for s in out)
    assert any("reddit story" in s for s in out)
    assert local_signals("A news report.", "", ["The council voted."]) == []


def test_hosted_judgment_parses_probability():
    from vii.integrity.spam import assess_spam

    class _Fake:
        live = True

        def responses_create(self, payload):
            return {"id": "r", "output": [
                {"type": "message", "content": [{
                    "type": "output_text",
                    "text": json.dumps({"spam_probability": 0.9,
                                        "signals": ["TTS narration"],
                                        "format": "storytime spam"})}]}]}

    out = assess_spam("summary", "transcript", ["claim"], _Fake(), "m")
    assert out["status"] == "success"
    assert out["spam_probability"] == 0.9
    assert "TTS narration" in out["signals"]


def test_no_client_returns_local_signals_only():
    from vii.integrity.spam import assess_spam

    out = assess_spam("storytime part 1", "", [], None, "m")
    assert out["status"] == "unavailable"
    assert out["spam_probability"] is None
    assert out["signals"]


def test_tui_summary_flags_spam(tmp_path, capsys):
    from vii.tui import print_summary

    print_summary({"job_id": "job_x", "claims": [],
                   "metadata": {"spam_detection": {
                       "status": "success", "spam_probability": 0.92,
                       "signals": ["formulaic marker: 'part 1'"]}}})
    out = capsys.readouterr().out
    assert "MASS-PRODUCED SPAM" in out
    assert "part 1" in out
