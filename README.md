# Autonomous Video Engine — AVE

<div align="center">

**Production-grade Python desktop suite for AI video generation at scale.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)](https://microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-22c55e)](LICENSE)
[![Playwright](https://img.shields.io/badge/Playwright-stealth-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev)
[![asyncio](https://img.shields.io/badge/asyncio-concurrent-6366f1)](https://docs.python.org/3/library/asyncio.html)

</div>

---

Built and shipped a full-cycle automation platform that **eliminated 6.5 hours of daily manual labour** from an AI short-form video operation — slashing active work time by **92%** (to ≈ 30 minutes of monitoring) and driving the channel to **37M+ organic views**, with a single video reaching **10M views in 48 hours**.

The system became the core proprietary asset behind a successful channel exit.

---

## Business Impact

| Metric | Result |
|--------|--------|
| Total organic views | **37,000,000+** |
| Peak single video | **10,000,000 views / 48 h** |
| Daily labour reduced | **6.5 h → 30 min (−92%)** |
| Outcome | Core asset of a successful channel acquisition |

---

## Engineering Highlights

- **Stealth Browser Orchestration** — Playwright persistent contexts with `--disable-blink-features=AutomationControlled` and custom user agents bypass Cloudflare / bot-detection where zero public APIs exist.

- **React Prompt Injection** — Standard `textarea.value =` assignments are swallowed by React's fibre reconciler. AVE calls the native `HTMLTextAreaElement` property setter via `Object.getOwnPropertyDescriptor` and dispatches synthetic input events to correctly trigger React state updates.

- **Three-Strategy Completion Detector** — Replaced brittle notification listeners with a three-pronged parallel detector: DOM selector polling → media-source URL diffing against a baseline snapshot → tile-count delta.

- **Concurrent Batch Engine** — `asyncio` task queue with a configurable `Semaphore` (up to 12 parallel task slots / 6 simultaneous browser contexts) cycling round-robin across isolated Chrome profiles.

- **Browser Pool** — Reusable `BrowserContext` cache per Chrome profile with 5-minute idle-eviction TTL, exponential-backoff restart on Playwright failures, and cross-event-loop lock reconstruction for safe use from both the asyncio loop and the CustomTkinter event loop.

- **Zero-Touch Post-Production** — `MontageService` (MoviePy 2.x) handles multi-clip concatenation, audio mixing (0–200% volume, mute, trim/loop/fit modes), and renders in a background thread with live progress callbacks to the GUI.

- **Rich Desktop UI** — Modular CustomTkinter app: Apple-inspired dark mode, 8 tabbed views (Dashboard, Pairing, Qwen, Outpaint, Montage, Login, Prompt Library, Settings), real-time progress bars, structured JSON log viewer, and Windows toast notifications.

---

## Tech Stack

| Area | Technology |
|------|-----------|
| Core & Concurrency | Python 3.10+, `asyncio`, `multiprocessing` |
| Browser Automation | Playwright (persistent contexts, stealth flags) |
| UI Framework | CustomTkinter |
| Video Processing | MoviePy 2.x |
| Data Validation | Pydantic v2 |
| Database | SQLite, `aiosqlite` |
| Logging | `structlog` (JSON, rotating files) |
| Notifications | `win10toast` |

---

## Architecture Overview

```
AVE/
├── main.py                  # Entry point
├── core.py                  # Sync automation core (Playwright sync API)
├── config.yaml              # Centralised configuration
│
├── src/
│   ├── config.py            # Pydantic AppConfig with env-var substitution
│   ├── dto.py               # Typed DTOs: GenerationTask, BatchJob, ImagePair …
│   ├── exceptions.py        # Typed exception hierarchy
│   │
│   ├── gui/                 # One module per UI tab
│   │   ├── app.py           # Root CustomTkinter shell & asyncio bridge
│   │   ├── dashboard.py     # Real-time stats & quick actions
│   │   ├── pairing.py       # Drag-and-drop pairing (~200 KB, largest component)
│   │   ├── montage_view.py  # Video timeline & audio mixing UI
│   │   └── …               # qwen_view, outpaint_view, prompt_library_view …
│   │
│   ├── services/            # Business logic
│   │   ├── browser_service.py     # Core Sora automation (~1 400 lines, async)
│   │   ├── batch_service.py       # Semaphore-based task orchestrator
│   │   ├── browser_pool.py        # BrowserContext cache with idle-eviction
│   │   ├── montage_service.py     # Background MoviePy renderer
│   │   └── …               # qwen, outpaint, history, prompt_library, auth …
│   │
│   ├── adapters/
│   │   └── legacy_core.py   # Adapter: sync core → new async architecture
│   │
│   └── utils/
│       ├── path_utils.py    # Path sanitisation helpers
│       ├── name_utils.py    # Media filename parsing
│       └── retry.py         # Exponential-backoff decorator
```

For a deep dive into every architectural decision see **[architecture.md](architecture.md)**.

---

## Prerequisites

- **Windows 10 / 11** (win10toast and Chrome profile paths are Windows-specific)
- **Python 3.10+**
- **Google Chrome** installed with at least one profile that is already logged in to [Sora](https://sora.chatgpt.com)
- **Playwright browsers** — installed automatically on first run

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-username/autonomous-video-engine.git
cd autonomous-video-engine/AVE

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install runtime dependencies
pip install -r requirements.txt

# 4. Install Playwright browser binaries
playwright install chromium

# 5. (Optional) Install dev dependencies
pip install -r requirements-dev.txt
```

---

## Configuration

Copy `.env.example` to `.env` and set your Chrome profile path:

```bash
copy .env.example .env
```

```dotenv
# .env
CHROME_BASE_PATH=C:\Users\YourUser\AppData\Local\Google\Chrome\User Data
```

Alternatively, edit `config.yaml` directly — all tuneable parameters live there:

```yaml
sora:
  url: "https://sora.chatgpt.com/library"
  notification_timeout_seconds: 240   # max wait per generation

batch:
  max_concurrent_tasks: 12            # total task slots
  max_parallel_browsers: 6           # simultaneous Chrome windows

browser:
  enable_stealth: true                # disable automation fingerprints
```

> **First-time login:** On the first run, open the *Login* tab and use *Login Mode* to complete a manual sign-in for each Chrome profile. AVE will reuse the stored session on every subsequent run.

---

## Quickstart

```bash
# Windows — double-click or run from terminal:
run.bat

# Or directly:
python main.py
```

The GUI will launch. Typical workflow:

1. **Pairing tab** — drag in your subject and reference images, configure pairs.
2. **Prompt Library tab** — select or create a generation prompt.
3. **Settings tab** — choose active Chrome profiles and concurrency limits.
4. **Pairing tab → Generate** — watch the batch run and progress bars fill.
5. **Montage tab** — select generated clips, add audio, click *Render*.

---

## Running Tests

```bash
pytest
```

Coverage report is generated in `htmlcov/` and `coverage.xml`.

---

## Project Structure (detail)

```
AVE/
├── .env.example             # Environment variable documentation
├── .gitignore
├── .pre-commit-config.yaml  # black + ruff + isort + mypy hooks
├── LICENSE
├── README.md
├── architecture.md          # In-depth architecture doc
├── config.yaml              # Runtime configuration
├── main.py                  # Entry point
├── core.py                  # Sync Playwright automation core
├── profiles.py              # Chrome profile discovery & validation
├── utils.py                 # Shared logging helpers
├── requirements.txt
├── requirements-dev.txt
├── mypy.ini
├── pytest.ini
├── run.bat                  # One-click Windows launcher
│
├── src/
│   ├── config.py
│   ├── dto.py
│   ├── exceptions.py
│   ├── adapters/legacy_core.py
│   ├── gui/           (app, dashboard, pairing, montage_view, …)
│   ├── services/      (browser_service, batch_service, browser_pool, …)
│   └── utils/         (path_utils, name_utils, retry)
│
├── assets/
│   ├── subjects/      # Subject reference images (not committed)
│   └── references/    # Style/scene reference images (not committed)
│
├── outputs/           # Generated media — gitignored
├── logs/              # Rotating structlog output — gitignored
└── tests/
    └── unit/
        └── test_image_service.py
```

---

## Contributing

Pull requests are welcome. Please:

1. Run `pre-commit install` after cloning.
2. Ensure `ruff`, `black`, and `mypy` pass before opening a PR.
3. Add tests for new service-layer logic under `tests/unit/`.

---

## License

[MIT](LICENSE) © 2025 Bohdan
