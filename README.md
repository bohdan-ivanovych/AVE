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

- **Rich Desktop UI** — Modular CustomTkinter app: Apple-inspired pure-black dark mode with iOS blue accents, smooth hover animations, 9 tabbed views, real-time progress bars, structured JSON log viewer, and Windows toast notifications.

---

## Tech Stack

| Area | Technology |
|------|-----------|
| Core & Concurrency | Python 3.10+, `asyncio`, `multiprocessing` |
| Browser Automation | Playwright (persistent contexts, stealth flags) |
| UI Framework | CustomTkinter (Apple dark-mode aesthetic) |
| Video Processing | MoviePy 2.x |
| Data Validation | Pydantic v2 |
| Database | SQLite, `aiosqlite` |
| Logging | `structlog` (JSON, rotating files) |
| Notifications | `win10toast` |

---

## Prerequisites

- **Windows 10 / 11** (win10toast and Chrome profile paths are Windows-specific)
- **Python 3.10+**
- **Google Chrome** installed (accounts will be set up via Login Mode on first run)

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/bohdan-ivanovych/AVE.git
cd AVE

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install runtime dependencies
pip install -r requirements.txt

# 4. Install Playwright browser binaries
playwright install chromium
```

---

## Configuration

Copy `.env.example` to `.env` and set your Chrome User Data path:

```bash
copy .env.example .env
```

```dotenv
# .env
CHROME_BASE_PATH=C:\Users\YourUser\AppData\Local\Google\Chrome\User Data
```

Or edit `config.yaml` directly — all parameters live there:

```yaml
batch:
  max_concurrent_tasks: 12   # total async task slots
  max_parallel_browsers: 6   # simultaneous Chrome windows

browser:
  enable_stealth: true        # strip automation fingerprints
```

---

## Workflow

AVE covers the full production cycle across 9 views.
**Always start with Login Mode** — it is the prerequisite for all generation features.

---

### Step 0 — Login Mode *(required once per profile)*

> **Tab: 🔐 Login Mode**

Click **Start Login**. For each Chrome profile AVE opens a single browser window with **3 tabs in parallel**:

| Tab | Service | Purpose |
|-----|---------|---------|
| 1 | **Sora** (`sora.chatgpt.com`) | AI video generation |
| 2 | **Outpaint / Pixelcut** (`pixelcut.ai`) | Image outpainting |
| 3 | **Qwen** (`chat.qwen.ai`) | Alternative video model |

Log into all three manually, then click **Next Profile** to advance. Repeat until all profiles are authenticated. AVE reuses the saved Chrome sessions on every subsequent run — this step is only needed once per profile.

---

### Step 1 — Set Up & Configure

> **Tab: ⚙️ Settings**

Configure active Chrome profiles, concurrency limits (`max_parallel_browsers`, `max_concurrent_tasks`), timeouts, and output directories. Changes propagate to running services without a restart.

---

### Step 2 — Sora Generation (image-pair → video)

> **Tab: 🤝 Pairing**

The core Sora generation pipeline:

1. **Drag-and-drop** subject images (Subjects) and reference images (References) into the pairing UI.
2. Configure pairs: **Manual**, **Sequential Auto**, or **Random Auto** pairing modes.
3. Select a prompt from the **🧾 Prompt Library** or type one directly.
4. Choose the profiles to use and click **Generate**.

`BatchService` distributes tasks across Chrome profiles concurrently. For each task:
- Navigates to Sora, uploads 1–4 reference images.
- Injects the prompt via native React setter.
- Polls for completion with the three-strategy detector.
- Auto-downloads generated `.webp` variants to `outputs/`.

---

### Step 3 — Qwen Video Generation

> **Tab: 🎬 Qwen Video**

Alternative generation pipeline targeting [Qwen](https://chat.qwen.ai/). Upload assets, configure parameters, and dispatch a batch. Operates through the same `BatchService` / `BrowserPool` infrastructure as Sora but with Qwen-specific DOM interaction logic (`QwenService`).

---

### Step 4 — Outpaint

> **Tab: 🖌️ Outpaint**

Batch outpainting via [Pixelcut AI](https://www.pixelcut.ai/uncrop/ai-outpainting). Select images, configure aspect ratio targets, and run. `OutpaintService` handles browser automation end-to-end.

---

### Step 5 — Video Montage (post-production)

> **Tab: 🎞️ Video Montage**

Combine generated clips into a final video:

1. Load clips — drag-and-drop or file picker.
2. Order them on the timeline.
3. Add background audio with per-track controls:
   - Volume: 0–200%
   - Mute original audio toggle
   - Trim / Loop / Fit modes
4. Click **Render** — `MontageService` runs MoviePy in a background thread with a live progress bar.

---

### Utilities

| Tab | Purpose |
|-----|---------|
| **🏠 Dashboard** | Real-time stats (profiles, subjects, references, outputs), quick-action buttons, recent history with success-rate badges |
| **🧾 Prompt Library** | SQLite-backed prompt store with tag search and favourites — prompts are shared across all generation tabs |
| **📜 Logs** | Live structured log viewer (JSON, rotated 10 × 10 MB files) |

---

## Running

```bash
# One-click launcher (installs deps automatically if missing)
run.bat

# Or directly
python main.py
```

---

## Architecture Overview

```
AVE/
├── main.py                  # Entry point — config, logger, GUI bootstrap
├── core.py                  # Sync automation core (Playwright sync API)
├── config.yaml              # Centralised configuration
│
├── src/
│   ├── config.py            # Pydantic AppConfig + env-var substitution
│   ├── dto.py               # Typed DTOs: GenerationTask, BatchJob, ImagePair …
│   ├── exceptions.py        # Typed exception hierarchy
│   │
│   ├── gui/                 # One module per view
│   │   ├── app.py           # Root CTk shell, sidebar, asyncio↔Tkinter bridge
│   │   ├── dashboard.py     # Stats + quick actions + history
│   │   ├── login.py         # Sequential multi-profile login (Sora+Outpaint+Qwen)
│   │   ├── pairing.py       # Drag-and-drop pairing + Sora batch dispatch (~200 KB)
│   │   ├── qwen_view.py     # Qwen Video generation UI
│   │   ├── outpaint_view.py # Outpaint / Pixelcut UI
│   │   ├── montage_view.py  # Video timeline + audio mixing UI
│   │   ├── prompt_library_view.py  # Tag-based prompt management
│   │   ├── settings.py      # Live config editor
│   │   └── logs.py          # Structured log viewer
│   │
│   ├── services/            # Business logic
│   │   ├── browser_service.py      # Core Sora automation (~1 400 lines, async)
│   │   ├── batch_service.py        # Semaphore-based task orchestrator
│   │   ├── browser_pool.py         # BrowserContext cache, idle-eviction, lock safety
│   │   ├── qwen_service.py         # Qwen Video full automation
│   │   ├── outpaint_service.py     # Pixelcut outpaint automation
│   │   ├── montage_service.py      # Background MoviePy renderer
│   │   ├── history_service.py      # SQLite operation history
│   │   ├── prompt_library.py       # SQLite prompt store
│   │   ├── auth_service.py         # Cookie / session management
│   │   ├── notification_service.py # Windows toast dispatcher
│   │   └── logger.py               # structlog JSON configuration
│   │
│   ├── adapters/
│   │   └── legacy_core.py   # Thin adapter: sync core → async architecture
│   │
│   └── utils/
│       ├── path_utils.py    # Path sanitisation helpers
│       ├── name_utils.py    # Media filename parsing
│       └── retry.py         # Exponential-backoff decorator
│
└── tests/
    └── unit/
        └── test_image_service.py
```

For a deep-dive into every architectural decision see **[architecture.md](architecture.md)**.

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Coverage report is generated in `htmlcov/` and `coverage.xml`.

---

## Contributing

1. Run `pre-commit install` after cloning.
2. Ensure `ruff`, `black`, and `mypy` pass before opening a PR.
3. Add tests for new service-layer logic under `tests/unit/`.

---

## License

[MIT](LICENSE) © 2025 Bohdan Ivanovych
