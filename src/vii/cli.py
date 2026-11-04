"""Terminal client: ``vii check`` (scriptable) and interactive ``vii``.

No UI imports: this module never touches vii.ui/PySide6 and runs with
PySide6 absent. With ``--json``, stdout carries exactly one JSON object;
all diagnostics go to stderr. Exit codes: 0 success, 2 invalid input,
3 provider not configured, 4 provider/execution failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vii.config import Settings

EXIT_OK, EXIT_INPUT, EXIT_CONFIG, EXIT_PROVIDER = 0, 2, 3, 4


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vii",
        description="Video Integrity Intelligence terminal client.")
    sub = p.add_subparsers(dest="command")
    check = sub.add_parser("check", help="Check one video file or URL.")
    check.add_argument("source", help="Local media path or public http(s) URL.")
    check.add_argument("--json", action="store_true",
                       help="Print exactly one JSON object on stdout.")
    check.add_argument("--demo", action="store_true",
                       help="Explicit synthetic-demo opt-in (labeled, no provider).")
    check.add_argument("--quick", action="store_true",
                       help="Fast local pre-screen only (seconds, no provider).")
    check.add_argument("--title", default=None)
    sub.add_parser("interactive", help="Interactive terminal session (default).")
    sub.add_parser("tui", help="Slash-command terminal UI (/help inside).")
    cred = sub.add_parser(
        "credentials",
        help="Provider API key setup (MODEL_API_KEY; never displayed).")
    cred_sub = cred.add_subparsers(dest="cred_command")
    cred_sub.add_parser("status", help="Show credential source and readiness.")
    cred_sub.add_parser("set", help="Save/update the provider key (hidden prompt).")
    cred_sub.add_parser("remove", help="Remove the stored provider key.")
    cred_sub.add_parser("test", help="One authorized provider connection test.")
    return p


def test_connection(base_url: str, api_key: str, *, get=None) -> dict:
    """One provider connection test. Never returns or logs the key.

    ``ok`` means the /models endpoint accepted the key; it does not prove
    video, search, or transcription compatibility.
    """
    if get is None:
        import httpx

        get = httpx.get
    try:
        resp = get(f"{base_url.rstrip('/')}/models",
                   headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
    except Exception as e:
        return {"ok": False, "message": f"connection failed: {type(e).__name__}"}
    code = int(getattr(resp, "status_code", 0) or 0)
    if code < 400:
        return {"ok": True, "status_code": code,
                "message": ("key accepted by the provider /models endpoint; "
                            "this does not prove video/search compatibility")}
    if code in (401, 403):
        return {"ok": False, "status_code": code,
                "message": "key rejected by the provider (HTTP "
                           f"{code}); check MODEL_API_KEY"}
    return {"ok": False, "status_code": code,
            "message": f"provider returned HTTP {code}; result inconclusive"}


def _effective_settings(settings: Settings | None) -> Settings:
    if settings is not None:
        return settings
    from vii.config import get_settings

    return get_settings()


def run_credentials(action: str | None, *,
                    settings: Settings | None = None) -> int:
    """Terminal credential setup. The secret is never printed or logged."""
    import getpass

    from vii.keystore import store_api_key
    from vii.providers.capabilities import readiness_report

    s = _effective_settings(settings)
    action = action or "status"
    if action == "status":
        report = readiness_report(s)
        print(f"Provider key (MODEL_API_KEY): "
              f"{'configured' if s.has_api_key else 'not configured'} "
              f"(source: {s.key_source})")
        print(f"Provider endpoint: {s.meta_base_url} model: {s.meta_model}")
        print(f"Readiness: local_ingestion={report['local_ingestion']['status']} "
              f"demo={report['demo']['status']} "
              f"provider_configuration="
              f"{report['provider_configuration']['status']} "
              f"live_verification={report['live_verification']['status']}")
        print("Note: MODEL_API_KEY is the provider credential. VII consumer "
              "keys (VII_API_KEYS / VII_CONSUMER_KEYS) authenticate callers "
              "of the VII API server instead; they are different secrets.")
        print("A configured key proves configuration only, not provider "
              "compatibility. Verify live with: vii credentials test")
        return EXIT_OK
    if action == "set":
        key = getpass.getpass("Provider API key (input hidden): ").strip()
        if not key:
            print("error: empty key; nothing stored", file=sys.stderr)
            return EXIT_INPUT
        backend = store_api_key(key, s.storage_dir)
        print(f"Provider key stored via {backend}. "
              "It was not written to .env or any tracked file.")
        return EXIT_OK
    if action == "remove":
        store_api_key("", s.storage_dir)
        print("Stored provider key removed (keyring entry and fallback "
              "file cleared). An env MODEL_API_KEY, if set, is unchanged.")
        return EXIT_OK
    if action == "test":
        key = s.effective_api_key
        if not key:
            print("error: no provider key configured; run "
                  "vii credentials set first", file=sys.stderr)
            return EXIT_CONFIG
        out = test_connection(s.meta_base_url, key)
        print(out["message"])
        return EXIT_OK if out["ok"] else EXIT_PROVIDER
    print(f"error: unknown credentials action {action!r}", file=sys.stderr)
    return EXIT_INPUT


def run_check(source: str, *, settings: Settings | None = None,
              demo: bool = False, title: str | None = None,
              as_json: bool = False) -> int:
    from vii.checker import VideoChecker
    from vii.errors import ProviderConfigurationError, ProviderError

    checker = VideoChecker(settings=settings)
    try:
        report = checker.check(source, title=title, demo=demo)
    except ProviderConfigurationError as e:
        return _fail(as_json, EXIT_CONFIG, type(e).__name__, str(e))
    except ProviderError as e:
        return _fail(as_json, EXIT_PROVIDER, type(e).__name__, str(e))
    except ValueError as e:
        return _fail(as_json, EXIT_INPUT, type(e).__name__, str(e))
    except Exception as e:  # execution failure, reported honestly
        return _fail(as_json, EXIT_PROVIDER, type(e).__name__, str(e))
    finally:
        checker.close()
    if as_json:
        print(json.dumps(report, default=str))
    else:
        from vii.reports.exporter import verdict_story
        print(f"job={report.get('job_id', '')} claims={len(report.get('claims') or [])}")
        for c in report.get("claims") or []:
            print(f"\n[{c.get('status', '?')}] {c.get('text', '')}")
            print(verdict_story(c))
    return EXIT_OK


def _fail(as_json: bool, code: int, error: str, message: str) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": error, "message": message}))
    else:
        print(f"error: {message}", file=sys.stderr)
    return code


def interactive(*, settings: Settings | None = None) -> int:
    """Prompt loop: first line is a source, then follow-ups from the report."""
    from vii.checker import VideoChecker
    from vii.errors import ProviderConfigurationError

    checker = VideoChecker(settings=settings)
    report: dict | None = None
    print("VII terminal client. Enter a video path or URL, then ask "
          "follow-ups ('claims', 'sources', a status, or keywords). "
          "'quit' exits.")
    try:
        while True:
            try:
                line = input("vii> " if report else "vii source> ").strip()
            except EOFError:
                print()
                return EXIT_OK
            if not line:
                continue
            if line.lower() in ("quit", "exit", "q"):
                return EXIT_OK
            if report is None:
                demo = checker.settings.demo_enabled
                try:
                    report = checker.check(line, demo=demo)
                except ProviderConfigurationError as e:
                    print(f"error: {e}", file=sys.stderr)
                    continue
                except Exception as e:
                    print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
                    continue
                print(f"Checked (job {report.get('job_id', '')}). "
                      "Ask a follow-up or 'quit'.")
            elif line.lower() == "new":
                report = None
            else:
                print(checker.follow_up(report, line))
    except KeyboardInterrupt:
        print()
        return EXIT_OK
    finally:
        checker.close()


def main(argv: list[str] | None = None, *,
         settings: Settings | None = None) -> int:
    from vii.logging_setup import setup_logging

    setup_logging()
    argv = list(sys.argv[1:] if argv is None else argv)
    # Legacy operator flags delegate to vii.main without importing the UI.
    if argv and argv[0].startswith("--") and argv[0] not in ("--help", "-h"):
        from vii import main as _main

        return _main.main(argv)
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        if args.quick:
            from vii.checker import VideoChecker

            checker = VideoChecker(settings=settings)
            try:
                quick = checker.quick_look(args.source)
            except ValueError as e:
                return _fail(args.json, 2, type(e).__name__, str(e))
            finally:
                checker.close()
            if args.json:
                print(json.dumps(quick, default=str))
            else:
                from vii.tui import print_quick

                print_quick(quick)
            return 0
        return run_check(args.source, settings=settings, demo=args.demo,
                         title=args.title, as_json=args.json)
    if args.command == "credentials":
        return run_credentials(args.cred_command, settings=settings)
    if args.command == "tui":
        from vii.tui import run_tui

        return run_tui(settings=settings)
    return interactive(settings=settings)


if __name__ == "__main__":
    raise SystemExit(main())
