# Video Integrity Intelligence (VII)

VII checks whether videos say things that are true. Give it a video file
or a public video URL. It watches the video, pulls out factual claims,
searches the live web for evidence with cited sources, and gives every
claim a verdict: supported, contradicted, mixed, insufficient, or
unverifiable. It also transcribes speech, screens for AI generated
frames, and flags mass produced spam formats.

VII never outputs a single real/fake score. Every finding shows its
evidence.

## Install (clean machine)

Prerequisites: Python 3.12 or newer, plus system ffmpeg and ffprobe.

```text
git clone https://github.com/Rahmat-Altamis/VII.git
cd VII
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[app,mcp]"
```

Then start the app and add your key inside it. No hidden files needed:

```text
.venv/bin/vii tui
```

```text
/key set
```

Paste your Meta API key when asked. VII stores it in your OS keyring
(or a permission 0600 fallback file when no keyring exists) and never
shows it again. Verify with `/status` inside the TUI.

Developers can still use a `.env` file (`cp .env.example .env`, then
set `MODEL_API_KEY`) or run `.venv/bin/vii credentials set`. The test
suite (`.venv/bin/python -m pytest tests/ -q`, 255 tests, mocked
providers) spends no credits. Desktop UI users add the desktop extra
at install time.

Everything provider backed runs on one provider: the Meta Model API
(video understanding on Muse Spark, visual perception on SAM, speech
to text on Muse Voice, plus evidence search through the Meta built in
web search tool). No Exa, no Tavily, no extra search key. One Meta key
unlocks every online feature.

## Use it: terminal UI (recommended)

```text
.venv/bin/vii tui
```

The TUI asks for your media folder, then you talk to it:

```text
list videos
check the hoax video
details 2
```

A fast local screen appears in under a second (file facts, forensics,
originality). The deep analysis streams live stage progress after that.
Slash commands: /key /folder /mode /output /ai /check /status /help.

## Use it: one shot CLI

```text
.venv/bin/vii check <video> --quick
.venv/bin/vii check <video>
.venv/bin/vii check <video> --json > result.json
```

Exit codes: 0 success, 2 bad input, 3 key missing, 4 provider failure.

## Credentials

Two secret kinds exist. Keep them apart:

1. `MODEL_API_KEY` is the provider credential (Meta Model API). Used
   only for provider backed analysis.
2. `VII_API_KEYS` and `VII_CONSUMER_KEYS` authenticate callers of the
   VII API server. They never call the provider.

Lookup order, first match wins: environment or `.env` value, then OS
keyring, then its permission 0600 fallback file. Manage it safely:

```text
.venv/bin/vii credentials set
.venv/bin/vii credentials status
.venv/bin/vii credentials remove
.venv/bin/vii credentials test
```

Status and diagnostics never display secret values.

## Use it: Python library

```python
from vii import VII, VideoChecker

client = VII(api_key="YOUR_KEY_HERE")
fast = client.quick_look("video.mp4")
report = client.analyze("video.mp4")

checker = VideoChecker(api_key="YOUR_KEY_HERE")
cached = checker.check("video.mp4")
print(checker.follow_up(cached, "contradicted"))
```

Caller supplied keys never touch VII environment files. Repeated
checks of the same file reuse a SHA 256 hash cache instead of rebilling.

## Use it: agent tools (MCP server)

For Claude Code, OpenClaw, and other agents:

```text
.venv/bin/vii-mcp
```

Register once in Claude Code (absolute path to your install):

```text
claude mcp add vii /home/YOU/VII/.venv/bin/vii-mcp
```

Or add this JSON to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "vii": {
      "command": "/home/YOU/VII/.venv/bin/vii-mcp"
    }
  }
}
```

Available tools: `vii_quick_look`, `vii_check`, `vii_follow_up`,
`vii_key_status`. Agents pass their own Meta key per call through the
`api_key` argument, so agent setups never need VII environment files.

## Use it: API server

```text
./scripts/run_api.sh
```

Serves FastAPI on 127.0.0.1:8765 with interactive docs at /docs.
Contract details live in docs/API.md.

## What a check produces

1. Claims with verdicts plus cited evidence URLs
2. Claim vs reality narrative per claim
3. Transcript with speaker turns
4. AI generation probability over sampled frames
5. Spam format score with named signals
6. Originality and forensics findings
7. Per capability ledger (success, partial, unavailable, failed)

## Datasets

1. Real world pilot: 14 videos, 20972 frames indexed, under
   data/evaluation/real_world_pilot, with reproducible builders
2. AI detection: 975 labeled images plus a measured 40 sample eval
   under data/evaluation/ai_detection
3. Operator CSV inbox: drop a file at data/dataset.csv, then validate
   and ingest through the documented workflow in docs/DATASET.md

## Documentation

1. docs/ARCHITECTURE.md: boundaries, data flow, decisions
2. docs/TECH_STACK.md: chosen technologies and rejected options
3. docs/API.md: /v1 contract, auth, errors
4. docs/DATASET.md: CSV schema and evaluation workflow
5. docs/DEVELOPMENT.md: setup, testing, linting, migrations
6. docs/SECURITY.md: auth, isolation, SSRF and upload boundaries

## Layout

Source lives under src/vii. Major areas: config, domain (typed
contracts), persistence (SQLAlchemy plus Alembic migrations), meta
(provider adapter), media (ingestion, guards, ffmpeg, hashing),
evidence, verification, integrity (forensics, AI, spam), dataset,
reports, api (FastAPI /v1), application (pipeline, worker), checker
and client (library), tui and cli (terminal), mcp_server (agent
tools), ui (optional desktop).
