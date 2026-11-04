"""Slash-command terminal UI, a thin shell over the existing CLI tools.

No new analysis logic lives here: checks run through ``cli.run_check``,
credentials through ``vii.keystore``, follow-ups through
``VideoChecker.follow_up``. Session state (mode/output/AI) only selects
options on those existing entry points.

Commands:
    /key [status|set|remove|test]  provider credential management
    /mode [live|demo]              analysis mode for checks
    /output [text|json]            check output format
    /ai [on|off] [N]               AI-detection toggle + frame samples
    /check <path-or-url>           run a check (a bare path works too)
    /status                        credentials + readiness + session
    /help                          this list
    /quit                          exit
"""
from __future__ import annotations

import getpass
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vii.config import Settings

HELP = """Commands:
  /key [status|set|remove|test]  provider API key (MODEL_API_KEY) management
  /folder [path]                 show or change the media folder
  /mode [live|demo]              analysis mode for checks (default: live)
  /output [text|json]            check output format (default: text)
  /ai [on|off] [N]               AI-detection toggle + frame samples (default: off 5)
  /check <path-or-url>           run a check (a bare path or URL works too)
  /status                        credential source, readiness, session options
  /help                          show this help
  /quit                          exit"""


@dataclass
class Session:
    demo: bool = False
    as_json: bool = False
    ai_on: bool = False
    ai_samples: int = 5
    report: dict | None = None
    video_pick: list = None  # last listed videos, for "number N"
    media_dir: str | None = None  # user-chosen; default ~/Downloads

    def __post_init__(self):
        if self.video_pick is None:
            self.video_pick = []


def _settings(base: Settings | None, session: Session) -> Settings:
    from vii.config import get_settings

    s = base if base is not None else get_settings()
    return s.model_copy(update={"enable_ai_detection": session.ai_on,
                                "ai_detection_samples": session.ai_samples})


def _looks_like_key(text: str) -> bool:
    """True for a pasted secret like token. Never true for commands."""
    import re as _re

    t = text.strip()
    if text.startswith("/") or len(t) < 20 or len(t) > 256:
        return False
    if any(ch.isspace() for ch in t):
        return False
    if t.startswith(("http://", "https://")) or "/" in t:
        return False
    return bool(_re.fullmatch(r"[A-Za-z0-9_\-.:+/=]+", t))


def _offer_save_pasted_key(text: str, session: Session,
                           base: Settings | None) -> None:
    """Offer to store a pasted token. Never echoes the token."""
    from vii.keystore import store_api_key

    answer = input("That looks like an API key. Save it as your Meta "
                   "provider key? (yes/no): ").strip().lower()
    if answer not in ("y", "yes"):
        print("Not saved. Paste it again anytime, or run /key set.")
        return
    s = base if base is not None else _settings(None, session)
    print(f"stored via {store_api_key(text.strip(), s.storage_dir)}")


def cmd_key(args: list[str], session: Session,
            base: Settings | None) -> int:
    from vii import cli as cli_mod

    action = args[0] if args else "status"
    if action not in ("status", "set", "remove", "test"):
        print(f"unknown /key action {action!r}; use status|set|remove|test")
        return 2
    if not args and not _settings(base, session).has_api_key:
        print("No provider key yet. Let's add it now.")
        action = "set"
    if action == "set":
        key = getpass.getpass("Provider API key (input hidden): ").strip()
        if not key:
            print("empty key; nothing stored")
            return 2
        from vii.keystore import store_api_key

        s = base if base is not None else _settings(None, session)
        print(f"stored via {store_api_key(key, s.storage_dir)}")
        return 0
    if action == "remove":
        from vii.keystore import store_api_key

        s = base if base is not None else _settings(None, session)
        store_api_key("", s.storage_dir)
        print("stored provider key removed")
        return 0
    return cli_mod.run_credentials(
        action, settings=_settings(base, session))


def cmd_status(session: Session, base: Settings | None) -> int:
    from vii import cli as cli_mod

    code = cli_mod.run_credentials("status", settings=_settings(base, session))
    print(f"session: mode={'demo' if session.demo else 'live'} "
          f"output={'json' if session.as_json else 'text'} "
          f"ai={'on' if session.ai_on else 'off'} samples={session.ai_samples}")
    return code


_VERDICT_EMOJI = {
    "supported": "\u2705",
    "contradicted": "\u274c",
    "mixed_evidence": "\u26a0\ufe0f",
    "insufficient_evidence": "\u2753",
    "unverifiable": "\u25cb",
    "not_yet_analyzed": "\u23f3",
}

_WIDTH = 72


def panel(title: str, lines: list[str]) -> str:
    """Agent-style box panel (dependency-free, word-wrapped)."""
    import textwrap as _tw

    bar = "\u2500" * (_WIDTH - len(title) - 4)
    out = [f"\u256d\u2500 {title} {bar}"]
    for ln in lines:
        for chunk in (_tw.wrap(ln, width=_WIDTH - 4,
                               break_long_words=False,
                               break_on_hyphens=False) or [""]):
            out.append(f"\u2502 {chunk.ljust(_WIDTH - 4)} \u2502")
    out.append("\u2570" + "\u2500" * (_WIDTH - 2) + "\u256f")
    return "\n".join(out)


class spin:
    """TTY-only activity spinner; silent under pipes/tests."""

    _FRAMES = ("\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2837",
               "\u2827", "\u282f")

    def __init__(self, label: str):
        self.label = label
        self._stop = None
        self._thread = None

    def __enter__(self):
        import sys as _sys
        import threading as _threading
        import time as _time

        if not _sys.stdout.isatty():
            return self
        self._stop = _threading.Event()

        def _run():
            i = 0
            while not self._stop.is_set():
                frame = self._FRAMES[i % len(self._FRAMES)]
                _sys.stdout.write(f"\r{frame} {self.label}")
                _sys.stdout.flush()
                i += 1
                _time.sleep(0.09)

        self._thread = _threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=1.0)
            import sys as _sys

            _sys.stdout.write("\r" + " " * (_WIDTH) + "\r")
            _sys.stdout.flush()
        return False


def print_summary(report: dict) -> None:
    """Plain-language result: takeaway first, short lines, details on demand."""
    from collections import Counter

    claims = report.get("claims") or []
    counts = Counter(c.get("status", "?") for c in claims)
    bad = counts.get("contradicted", 0)
    mixed = counts.get("mixed_evidence", 0) + counts.get("insufficient_evidence", 0)
    if bad:
        takeaway = f"\u274c {bad} claim(s) look FALSE, see details below."
    elif mixed:
        takeaway = ("\u26a0\ufe0f No clear falsehoods, but some claims couldn't "
                    "be fully confirmed.")
    elif claims:
        takeaway = "\u2705 Everything checkable held up."
    else:
        takeaway = "No claims were extracted from this video."
    lines = [takeaway]
    spm = (report.get("metadata") or {}).get("spam_detection") or {}
    if spm.get("status") == "success" and spm.get("spam_probability") is not None:
        p = spm["spam_probability"]
        lines.append("🚨 This looks like a MASS-PRODUCED SPAM video "
                     f"(spam score {p})." if p >= 0.7 else
                     f"Not flagged as spam (spam score {p}).")
        if spm.get("signals"):
            lines.append("Spam signals: " + "; ".join(spm["signals"][:4]))
    lines.append("")
    for i, c in enumerate(claims, 1):
        emoji = _VERDICT_EMOJI.get(c.get("status", ""), "\u2022")
        lines.append(f"{i}. {emoji} {c.get('text', '')[:90]}")
    job = report.get("job_id", "")
    print(panel(f"Result · {len(claims)} claim(s) · {job[:16]}", lines))
    print("Say 'details' for the full why, 'details 2' for one claim, "
          "or ask anything about the report.")


def print_quick(quick: dict) -> None:
    """Fast pre-screen panel: instant local signals before the deep run."""
    dur = quick.get("duration_s")
    dur_s = f"{dur:.1f}s" if isinstance(dur, (int, float)) else "unknown"
    size_mb = (quick.get("size_bytes") or 0) / (1024 * 1024)
    forensic = (quick.get("forensics") or {}).get("status", "?")
    orig = quick.get("originality") or {}
    dup = orig.get("exact_duplicate_of")
    streams = quick.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    sigs = [(s.get("name"), s.get("status"))
            for s in (quick.get("forensics") or {}).get("signals", [])]
    evaluated = [n for n, st in sigs if st != "unavailable"]
    fired = [n for n, st in sigs if st == "signal"]
    lines = [
        f"File: {quick.get('file_name')} ({size_mb:.1f} MB, {dur_s}, "
        f"{quick.get('container')})",
        f"Streams: video={v.get('codec_name', '?')} "
        f"{v.get('width', '?')}x{v.get('height', '?')} "
        f"@{v.get('avg_frame_rate', '?')} · "
        f"audio={a.get('codec_name', 'none')}",
        f"Frames examined: {quick.get('frames_sampled', 0)} · "
        f"signals evaluated: {len(evaluated)}"
        + (f" · fired: {', '.join(fired)}" if fired
           else " · nothing fired"),
        f"Forensics: {forensic} · Originality: "
        f"{'duplicate of ' + dup if dup else 'no exact duplicate on record'}",
    ]
    if quick.get("filename_markers"):
        lines.append("Name hints: " + ", ".join(quick["filename_markers"]))
    lines.append(f"Ready in {quick.get('elapsed_s')}s, full analysis running…")
    print(panel("⚡ Fast screen (local only)", lines))


def cmd_check(source: str, session: Session,
              base: Settings | None) -> int:
    from vii import cli as cli_mod
    from vii.checker import VideoChecker

    if session.as_json:
        return cli_mod.run_check(source, settings=_settings(base, session),
                                 demo=session.demo, as_json=True)
    import sys as _sys
    from pathlib import Path as _Path

    print(f"\u23fa check({_Path(source).name}): "
          f"{'demo' if session.demo else 'live'}"
          f"{', ai on' if session.ai_on else ''}")
    if not session.demo and _sys.stdin.isatty():
        try:
            answer = input("Run live check (spends provider credits)? "
                           "[Y/n] ").strip().lower()
        except EOFError:
            answer = "y"
        if answer not in ("", "y", "yes"):
            print("Skipped. Switch to demo mode for a free trial run.")
            return 0
    checker = VideoChecker(settings=_settings(base, session))
    if not session.as_json:
        from pathlib import Path as _P2

        if _P2(source).is_file():
            try:
                print_quick(checker.quick_look(source))
            except Exception as e:
                print(f"(Fast screen unavailable: {type(e).__name__})")
    try:
        session.report = _check_with_progress(checker, source, session.demo,
                                              base)
    except Exception as e:
        print(f"That check failed ({type(e).__name__}: {e}). Nothing was "
              "kept, try another video or /help.")
        return 2
    finally:
        checker.close()
    print_summary(session.report)
    return 0


def _check_with_progress(checker, source: str, demo: bool,
                         base: Settings | None) -> dict:
    """Run the check while streaming real stage progress from the job log.

    The check runs in a worker thread; this thread polls the newest job's
    processing log and prints each stage line once, so long evidence
    searches show life instead of a frozen spinner.
    """
    import datetime as _dt
    import sys as _sys
    import threading as _threading

    from vii.application.services import AnalysisService

    if not _sys.stdout.isatty():
        return checker.check(source, demo=demo)
    outcome: dict = {}
    started = _dt.datetime.now(_dt.UTC).replace(tzinfo=None)

    def _run():
        try:
            outcome["report"] = checker.check(source, demo=demo)
        except Exception as e:  # re-raised on the main thread
            outcome["error"] = e

    worker = _threading.Thread(target=_run, daemon=True)
    worker.start()
    seen = 0
    svc = AnalysisService(checker.settings if base is None else base)
    with spin("Analyzing video"):
        while worker.is_alive():
            worker.join(timeout=2.5)
            try:
                with svc.Session() as db:
                    from vii.persistence.models import AnalysisJob

                    job = (db.query(AnalysisJob)
                           .order_by(AnalysisJob.created_at.desc())
                           .first())
                    if job is None or job.created_at < started:
                        continue
                    from vii.persistence.repositories import JobRepo

                    logs = JobRepo(db).logs(job.id)
                    for entry in logs[seen:]:
                        mark = ("⚠" if entry.level in ("warning", "error")
                                else "✓")
                        print(f"\n  {mark} {entry.stage}: "
                              f"{entry.message[:100]}")
                    seen = len(logs)
            except Exception:
                pass  # progress is best-effort; the check is the truth
    if "error" in outcome:
        raise outcome["error"]
    return outcome["report"]


def print_details(text: str, session: Session) -> bool:
    """Print verdict narratives. Returns True when handled."""
    import re as _re

    from vii.reports.exporter import verdict_story

    low = text.strip().lower()
    m = _re.fullmatch(r"(?:details|why|explain)(?:\s+(\d{1,3}))?", low)
    if not m or session.report is None:
        return False
    claims = session.report.get("claims") or []
    if m.group(1):
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(claims):
            c = claims[idx]
            emoji = _VERDICT_EMOJI.get(c.get("status", ""), "\u2022")
            print(panel(f"{emoji} [{c.get('status', '?')}] claim {idx + 1}",
                        [c.get("text", ""), "", *verdict_story(c).split("\n")]))
        else:
            print(f"There's no claim number {m.group(1)} "
                  f"(I have {len(claims)}).")
        return True
    for i, c in enumerate(claims, 1):
        emoji = _VERDICT_EMOJI.get(c.get("status", ""), "\u2022")
        print(panel(f"{emoji} [{c.get('status', '?')}] claim {i}",
                    [c.get("text", ""), "", *verdict_story(c).split("\n")]))
    return True


def media_folder(session: Session, base: Settings | None) -> str:
    """Media folder: session choice, then VII_MEDIA_DIR, then ~/Downloads."""
    from pathlib import Path as _Path

    if session.media_dir:
        return session.media_dir
    if base is not None and getattr(base, "vii_media_dir", ""):
        return base.vii_media_dir  # type: ignore[return-value]
    return str(_Path.home() / "Downloads")


def find_videos(directory: str | None = None) -> list:
    """Local MP4s the chatbot can offer (never modified, only listed)."""
    from pathlib import Path as _Path

    folder = _Path(directory) if directory else _Path.home() / "Downloads"
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.mp4"), key=lambda p: p.name.lower())


def chat(text: str, session: Session, base: Settings | None) -> None:
    """Plain-words assistant: guide, list videos, run checks on request."""
    import difflib
    import re as _re

    low = text.strip().lower()
    folder = media_folder(session, base)
    videos = find_videos(folder)

    def show_videos() -> None:
        if not videos:
            print(f"I couldn't find any .mp4 files in {folder}. "
                  "Use '/folder <path>' to point me at your videos, or "
                  "paste a full video path or URL.")
            return
        session.video_pick = [str(v) for v in videos]
        print(f"Your videos in {folder}:")
        for i, v in enumerate(videos, 1):
            print(f"  {i}. {v.name}")
        print("Say 'check number N' or 'check <name>' and I'll run it.")

    def run_video(path: str) -> None:
        print(f"Checking {path} ...")
        cmd_check(path, session, base)  # stay in session either way

    # pick by number ("number 3", "3", "check 3", "try 3")
    m = _re.fullmatch(r"(?:check\s+|try\s+)?(?:number\s+)?(\d{1,3})", low)
    if m and session.video_pick:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(session.video_pick):
            run_video(session.video_pick[idx])
            return
        print(f"There's no number {m.group(1)}, I listed "
              f"{len(session.video_pick)} video(s).")
        return

    # run verbs with a fuzzy name ("check the hoax video")
    m = _re.match(r"(?:check|analyse|analyze|verify|test|run|try)\s+(.+)",
                  low)
    if m and videos:
        names = [v.name for v in videos]
        hits = difflib.get_close_matches(m.group(1), names, n=1, cutoff=0.4)
        if not hits:  # fall back to word overlap ("hoax video")
            words = set(m.group(1).split())
            hits = sorted(names,
                          key=lambda n: len(words & set(n.lower().split())),
                          reverse=True)[:1]
            if not (words & set(hits[0].lower().split())):
                hits = []
        if hits:
            run_video(str(next(v for v in videos if v.name == hits[0])))
        else:
            print(f"I couldn't match '{m.group(1)}' to a video.")
            show_videos()
        return

    if any(w in low for w in ("list", "videos", "show", "what have",
                              "browse", "find")):
        show_videos()
        return
    m = _re.match(r"(?:use|change|set)\s+(?:media\s+)?folder\s+(.+)", low)
    if m:
        from pathlib import Path as _Path

        candidate = _Path(m.group(1).strip()).expanduser()
        if not candidate.is_dir():
            print(f"Not a folder: {candidate}")
            return
        session.media_dir = str(candidate)
        session.video_pick = []
        show_videos()
        return
    if low in ("hi", "hello", "hey", "yo", "test", "testing", "hello!",
               "hi!") or low.startswith(("hello ", "hi ")):
        print("Hey! I can check a video for you. No manual paths needed.")
        show_videos()
        return
    if "demo" in low and any(w in low for w in ("mode", "on", "use", "switch")):
        session.demo = True
        print("Demo mode on. Checks use synthetic fixtures, no credits.")
        return
    if "live" in low and any(w in low for w in ("mode", "on", "use", "switch")):
        session.demo = False
        print("Live mode on. Checks use the real provider and spend credits.")
        return
    if "json" in low and "output" in low:
        session.as_json = True
        print("Output set to json.")
        return
    if "text" in low and "output" in low:
        session.as_json = False
        print("Output set to text.")
        return
    if low.startswith("ai ") or " ai " in f" {low} ":
        if "on" in low:
            session.ai_on = True
            print(f"AI detection on ({session.ai_samples} frames per video).")
            return
        if "off" in low:
            session.ai_on = False
            print("AI detection off.")
            return
    if "key" in low or "api" in low:
        print("Manage the provider key with: /key status, /key set "
              "(hidden prompt), /key remove, /key test. The key is never "
              "displayed.")
        return
    if any(w in low for w in ("help", "what can", "how", "commands")):
        print(HELP)
        print("Or just talk to me: 'list videos', 'check the hoax video', "
              "'check number 2'.")
        return
    if chat_llm(text, session, base):
        return
    if _looks_like_key(text):
        print("I never repeat things that look like API keys. Paste it "
              "again to save it, or run /key set.")
        return
    print(f"I'm not sure what '{text.strip()}' means. Try 'list videos', "
          "'check <name>', or /help for every command.")


def chat_llm(text: str, session: Session, base: Settings | None) -> bool:
    """Discuss with the user through Muse Spark. Returns True if answered.

    Deterministic intents (video picks, toggles) run before this; the
    model handles open conversation only. Silent fallback to False when
    no live key is configured or the call fails, so the TUI never
    depends on the provider for chatting.
    """
    from vii.config import get_settings

    s = base if base is not None else get_settings()
    if session.demo or not s.has_api_key:
        return False
    from vii.meta.client import MetaClient
    from vii.meta.response_parser import output_text

    claims = ""
    if session.report:
        lines = [f"- [{c.get('status')}] {c.get('text')}"
                 for c in (session.report.get("claims") or [])[:12]]
        claims = "Latest report claims:\n" + "\n".join(lines)
    videos = [v.name for v in find_videos(media_folder(session, s))][:20]
    prompt = (
        "You are the VII video-integrity assistant, chatting inside the "
        "VII terminal UI. Be brief, warm, and concrete (2-4 sentences "
        "unless asked for more). You can discuss the report below and "
        "suggest commands like 'check number 2', 'details 1', /mode, "
        "/output, /ai, /key, /folder. Never invent verdicts, sources, or "
        "API keys; say what you don't know.\n"
        f"Session: mode={'demo' if session.demo else 'live'}, "
        f"ai={'on' if session.ai_on else 'off'}.\n"
        f"Videos: {', '.join(videos) if videos else 'none found'}.\n"
        f"{claims}\nUser says: {text.strip()}")
    try:
        client = MetaClient(s.effective_api_key, s.meta_base_url,
                            s.meta_model, s.request_timeout_s, 0,
                            s.meta_transcription_model)
        with spin("Thinking…"):
            resp = client.responses_create(
                {"model": s.meta_model,
                 "input": [{"role": "user", "content": [
                     {"type": "input_text", "text": prompt}]}]})
        answer = output_text(resp if isinstance(resp, dict) else {}).strip()
    except Exception:
        return False
    if not answer:
        return False
    print(f"\u273b {answer[:1500]}")
    return True


def status_line(session: Session, base: Settings | None) -> str:
    """Claude-Code-style status line: model · folder · mode · branch."""
    import subprocess as _sp

    from vii.config import get_settings

    s = base if base is not None else get_settings()
    from pathlib import Path as _Path

    try:
        folder = media_folder(session, s).replace(str(_Path.home()), "~")
    except Exception:
        folder = "?"
    try:
        branch = _sp.run(["git", "branch", "--show-current"],
                         capture_output=True, text=True,
                         timeout=3).stdout.strip() or "no-git"
    except Exception:
        branch = "?"
    return (f"{s.meta_model} · {folder} · "
            f"{'demo' if session.demo else 'live'}"
            f"{' · ai' if session.ai_on else ''} · {branch}")


def handle(line: str, session: Session, base: Settings | None) -> int | None:
    """Run one TUI line. Returns exit code to quit, else None to continue."""
    from vii.checker import VideoChecker

    text = line.strip()
    if not text:
        return None
    if _looks_like_key(text):
        _offer_save_pasted_key(text, session, base)
        return None
    if not text.startswith("/"):
        from pathlib import Path as _Path

        looks_like_source = (
            text.startswith(("http://", "https://"))
            or _Path(text).exists()
            or _Path(text).suffix.lower() in
            (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"))
        if looks_like_source:
            cmd_check(text, session, base)  # stay in session either way
            return None
        if session.report is not None and print_details(text, session):
            return None
        if session.report is not None:
            checker = VideoChecker(settings=_settings(base, session))
            try:
                answer = checker.follow_up(session.report, text)
            finally:
                checker.close()
            if not answer.startswith("No matching information"):
                print(answer)
                return None
        chat(text, session, base)
        return None
    parts = text[1:].split()
    cmd, args = parts[0].lower(), parts[1:]
    if cmd in ("quit", "exit", "q"):
        return 0
    if cmd == "help":
        print(HELP)
        return None
    if cmd == "key":
        cmd_key(args, session, base)  # stay in session either way
        return None
    if cmd == "folder":
        from pathlib import Path as _Path

        if args:
            candidate = _Path(" ".join(args)).expanduser()
            if not candidate.is_dir():
                print(f"Not a folder: {candidate}")
                return None
            session.media_dir = str(candidate)
        else:
            current = media_folder(session, base)
            try:
                answer = input(f"Media folder [{current}]: ").strip()
            except EOFError:
                print()
                return None
            if answer:
                candidate = _Path(answer).expanduser()
                if not candidate.is_dir():
                    print(f"Not a folder: {candidate}")
                    return None
                session.media_dir = str(candidate)
        session.video_pick = []
        print(f"Media folder: {media_folder(session, base)} "
              f"({len(find_videos(media_folder(session, base)))} videos)")
        return None
    if cmd == "mode":
        if args and args[0] not in ("live", "demo"):
            print("usage: /mode [live|demo]")
        elif args:
            session.demo = args[0] == "demo"
        print(f"mode: {'demo' if session.demo else 'live'}")
        return None
    if cmd == "output":
        if args and args[0] not in ("text", "json"):
            print("usage: /output [text|json]")
        elif args:
            session.as_json = args[0] == "json"
        print(f"output: {'json' if session.as_json else 'text'}")
        return None
    if cmd == "ai":
        if args and args[0] not in ("on", "off"):
            print("usage: /ai [on|off] [N]")
        elif args:
            session.ai_on = args[0] == "on"
            if len(args) > 1:
                try:
                    session.ai_samples = max(1, min(20, int(args[1])))
                except ValueError:
                    print(f"ignoring bad sample count {args[1]!r}")
        print(f"ai: {'on' if session.ai_on else 'off'} "
              f"samples={session.ai_samples}")
        return None
    if cmd == "check":
        if not args:
            print("usage: /check <path-or-url> or just say "
                  "'check the hoax video'")
            return None
        cmd_check(" ".join(args), session, base)  # stay in session either way
        return None
    if cmd == "status":
        cmd_status(session, base)
        return None
    print(f"unknown command {text!r}; try /help")
    return None


def run_tui(*, settings: Settings | None = None,
            commands: list[str] | None = None) -> int:
    """Slash-command loop. ``commands`` feeds scripted lines (tests)."""
    import logging as _logging

    # Clean UX: progress chatter stays out of the user's face; warnings
    # and errors still show. Restored on exit.
    _vii_log = _logging.getLogger("vii")
    _prior_level = _vii_log.level
    _vii_log.setLevel(_logging.WARNING)
    session = Session()
    print(panel("VII · video integrity agent",
                ["Talk to me: 'list videos', 'check the hoax video'.",
                 "Commands: /help · /key · /folder · /mode · /output · "
                 "/ai · /check · /status · /quit"]))
    source = iter(commands) if commands is not None else None
    import sys as _sys

    pending: list[str] = []
    if source is None and _sys.stdin.isatty():
        from pathlib import Path as _Path

        default = media_folder(session, settings)
        try:
            answer = input(f"Media folder [{default}]: ").strip()
        except EOFError:
            answer = ""
        if answer.startswith("/"):
            pending.append(answer)  # a command, not a folder, run it first
        elif answer:
            candidate = _Path(answer).expanduser()
            if candidate.is_dir():
                session.media_dir = str(candidate)
            else:
                print(f"Not a folder. Sticking with {default}.")
    try:
        while True:
            try:
                if pending:
                    line = pending.pop(0)
                    print(f"> {line}")
                elif source is not None:
                    line = next(source)
                else:
                    print(status_line(session, settings))
                    line = input("> ")
            except (EOFError, StopIteration):
                print()
                return 0
            try:
                code = handle(line, session, settings)
            except KeyboardInterrupt:
                print()
                return 0
            if code is not None and source is None:
                return code
    finally:
        _vii_log.setLevel(_prior_level)


def main(argv: list[str] | None = None, *,
         settings: Settings | None = None) -> int:
    _ = argv
    from vii.logging_setup import setup_logging

    setup_logging()
    return run_tui(settings=settings)


if __name__ == "__main__":
    raise SystemExit(main())
