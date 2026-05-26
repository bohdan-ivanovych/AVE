# Autonomous Video Engine — Architecture

## 1. Project Overview

**Autonomous Video Engine (AVE)** is a proprietary Python desktop suite built for full-cycle automation of AI-driven creative and video production.

The system was purpose-built for a short-form AI video operation and eliminates the repetitive manual work that normally dominates a content pipeline — navigating browser UIs, uploading reference images, injecting prompts, waiting for generation, downloading results, and stitching final clips. AVE reduces that to a single button press and a progress bar.

Key design goals:
- **Throughput over interactivity** — maximize parallel generation across multiple Chrome profiles simultaneously.
- **Resilience over simplicity** — every critical step has multi-strategy fallbacks and structured error logging.
- **Zero-API mode** — the entire Sora integration operates via stealth browser automation because no public API exists.

---

## 2. Business Results

| Metric | Result |
|--------|--------|
| Total organic views | **37,000,000+** |
| Peak performance | **10,000,000 views in 48 hours** (single video) |
| Daily manual labour reduced | **6.5 hours → 30 minutes (−92%)** |
| Exit | Infrastructure became the core asset of a successful channel acquisition |

---

## 3. User Flow

The application covers the full production cycle from asset loading to final rendered montage.

### Stage 1 — Setup & Initialisation

1. **Launch & Auth** — The app auto-discovers local Chrome persistent contexts and populates available profiles. On first run the user completes a one-time manual login per profile via *Login Mode*; subsequent launches reuse the stored session (bypassing API rate limits).
2. **Reference Control** — In the **Pairing** tab the user drag-and-drops subject and reference images. Visual fidelity and character consistency across generations is maintained by anchoring each task to specific reference pairs.
3. **Mode Selection** — Manual pairing, Auto Pairing (Sequential / Random), or full Batch Mode for large queues.

### Stage 2 — Generation (Sora / Qwen / Outpaint)

1. **Parameter Setup** — Prompts are selected from the built-in Prompt Library or entered manually. Browser profiles are assigned to tasks.
2. **Queue Dispatch** — Clicking *Generate* pushes tasks into the async queue (`BatchService`).
3. **Stealth Execution**
   - Tasks are distributed across Chrome profiles (default: 6 parallel browsers, up to 12 concurrent task slots).
   - For each task: navigate to Sora, upload 1–4 reference images, inject the prompt directly into React state via a native setter, click *Create*.
   - A three-strategy completion detector polls for the generated result.
4. **Auto-Download** — Completed variants are saved to `outputs/` automatically.

### Stage 3 — Post-Production (Video Montage)

1. **Clip Assembly** — In the **Montage** tab the user selects generated clips and orders them on a timeline.
2. **Audio Mixing** — Background music is added with per-track volume control (0–200%), mute toggle, and fit/loop/trim modes.
3. **Render** — `MontageService` (MoviePy 2.x) concatenates and mixes everything in a background thread with live progress callbacks to the GUI.

### Stage 4 — Monitoring & Analytics

- Real-time statistics on the **Dashboard**.
- Windows toast notifications on task completion, batch completion, and errors.
- All operations logged to a rotating structured log (10 × 10 MB files via `structlog`).
- Full operation history stored in SQLite for success-rate tracking.

---

## 4. Technology Stack

| Layer | Technology |
|-------|-----------|
| Core & Concurrency | Python 3.10+, `asyncio`, `multiprocessing` |
| Browser Automation | Playwright (persistent contexts, stealth mode) |
| UI Framework | CustomTkinter (Apple dark-mode aesthetic) |
| Video Processing | MoviePy 2.x |
| Data Validation | Pydantic v2 |
| Database | SQLite / `aiosqlite` |
| Logging | `structlog` (JSON, rotating files) |
| Notifications | `win10toast` |

---

## 5. System Architecture

The project follows a strict layered architecture: GUI → Services → Adapters → Data.

```
AVE/
├── main.py                  # Entry point — config, logger, GUI bootstrap
├── core.py                  # Legacy sync automation (Playwright sync API)
├── config.yaml              # Centralised configuration
│
├── src/
│   ├── config.py            # Pydantic-based config loader with env-var substitution
│   ├── dto.py               # Pydantic v2 DTOs: GenerationTask, BatchJob, ImagePair …
│   ├── exceptions.py        # Typed exception hierarchy (AppError → ConfigError, BrowserError …)
│   │
│   ├── gui/                 # UI layer — one module per tab
│   │   ├── app.py           # Root CustomTkinter application shell
│   │   ├── dashboard.py     # Stats aggregation & quick actions
│   │   ├── pairing.py       # Drag-and-drop pairing UI (~200 KB, largest component)
│   │   ├── qwen_view.py     # Qwen Video generation interface
│   │   ├── outpaint_view.py # Outpaint generation interface
│   │   ├── montage_view.py  # Video timeline & audio mixing UI
│   │   ├── prompt_library_view.py  # Tag-based prompt management
│   │   ├── login.py         # Cookie / session management
│   │   ├── settings.py      # Live config.yaml editor
│   │   └── logs.py          # Structured log viewer (real-time)
│   │
│   ├── services/            # Business logic layer
│   │   ├── browser_service.py     # Core Sora automation (~1 400 lines)
│   │   ├── batch_service.py       # Async task orchestrator (Semaphore-based)
│   │   ├── browser_pool.py        # Reusable BrowserContext cache with idle-eviction
│   │   ├── qwen_service.py        # Qwen Video automation
│   │   ├── outpaint_service.py    # Outpaint automation
│   │   ├── montage_service.py     # Background video render (MoviePy)
│   │   ├── history_service.py     # SQLite operation history
│   │   ├── prompt_library.py      # SQLite prompt store
│   │   ├── auth_service.py        # Session & cookie management
│   │   ├── settings_service.py    # Runtime settings persistence
│   │   ├── notification_service.py# Windows toast dispatcher
│   │   └── logger.py              # structlog configuration
│   │
│   ├── adapters/
│   │   └── legacy_core.py   # Thin adapter bridging old sync core to new arch
│   │
│   └── utils/
│       ├── path_utils.py    # Path sanitisation & validation helpers
│       ├── name_utils.py    # Media file name parsing & description
│       └── retry.py         # Generic exponential-backoff decorator
```

### 5.1 GUI Layer (`src/gui/`)

Each of the 8 tabs is an independent module. The root `AVEApp` (CustomTkinter) wires them together, handles the asyncio ↔ Tkinter bridge, and manages the global settings and session state.

Notable components:
- **`pairing.py`** — The heaviest UI module (~200 KB). Implements full drag-and-drop image loading, auto/manual/batch pairing modes, and direct dispatch to `BatchService`.
- **`qwen_view.py` / `outpaint_view.py`** — Dedicated interfaces for alternative generation models with their own concurrency controls.
- **`settings.py`** — Live-edits `config.yaml` and propagates changes to the running service instances without a restart.

### 5.2 Services Layer (`src/services/`)

- **`BrowserService`** — The automation core (~1 400 lines). Manages Playwright persistent contexts, image upload sequences, prompt injection, completion detection, and variant download. All operations are `async`.
- **`BatchService`** — Async task orchestrator. Wraps tasks in `asyncio.Semaphore` to cap simultaneous browser instances. Cycles profiles round-robin across tasks.
- **`BrowserPool`** — `BrowserContext` cache keyed by Chrome profile name. Implements 5-minute idle-eviction TTL, cross-event-loop lock reconstruction, and exponential-backoff restart on Playwright failures.
- **`MontageService`** — Runs MoviePy rendering in a `ThreadPoolExecutor` to avoid blocking the Tkinter event loop. Progress callbacks are forwarded to the GUI via a thread-safe queue.
- **`HistoryService` / `PromptLibrary`** — `aiosqlite`-backed stores with async CRUD interfaces.

### 5.3 Data Layer

| Artefact | Purpose |
|----------|---------|
| `config.yaml` | Single source of truth for all tuneable parameters |
| `src/config.py` | Pydantic `AppConfig` with env-var substitution and full validation |
| `src/dto.py` | Typed data contracts between layers |
| `prompts.db` | SQLite — prompt templates, tags, favourites, generation history |
| `outputs/` | Generated media (`.webp`, `.mp4`) |
| `logs/` | Rotating structured JSON logs |

---

## 6. Key Engineering Decisions

### 6.1 Stealth Browser Orchestration

Sora has no public API. The system uses Playwright **persistent contexts** (real Chrome profiles, not ephemeral browsers) with `--disable-blink-features=AutomationControlled` and `ignore_default_args=["--enable-automation"]` to pass Cloudflare bot-detection. Each context maps to a separate Chrome profile directory so sessions are fully isolated.

### 6.2 React Prompt Injection

Standard `textarea.value = "..."` assignment is silently swallowed by React's fibre reconciler — the internal state never updates and the Create button stays disabled. AVE uses a **native property setter** to force React to acknowledge the change:

```javascript
const setter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype, 'value'
).set;
setter.call(textarea, prompt);
textarea.dispatchEvent(new Event('input', { bubbles: true }));
```

This triggers the synthetic event that React listens to and correctly updates internal state.

### 6.3 Three-Strategy Completion Detector

Sora's UI does not expose stable completion callbacks. `BrowserService` polls in parallel using three independent strategies — the first to fire wins:

| # | Strategy | Trigger |
|---|----------|---------|
| 1 | **DOM selector** | `img[alt="Sora generation"].object-cover` appears in the DOM |
| 2 | **Media-source diff** | Top-N tile `src`/`currentSrc` URLs differ from the baseline snapshot |
| 3 | **Tile-count delta** | Number of `div.group/tile` elements increases |

### 6.4 Cross-Event-Loop Lock Safety in BrowserPool

CustomTkinter runs its own event loop, separate from the `asyncio` loop used by the services. An `asyncio.Lock` created in one loop raises `RuntimeError` when awaited from another. `BrowserPool` detects loop changes at acquire time and transparently reconstructs its lock, so the pool is safe regardless of which loop calls into it.

### 6.5 Lazy MoviePy Import

`from moviepy.editor import ...` at module level adds ~2 seconds to startup time even when no montage is requested. `MontageService` defers the import to an internal `_import_moviepy()` helper that runs only at the moment rendering begins, keeping startup instant.

### 6.6 Duplicate-Generation Guard

Before launching a browser for a task, the system globs `outputs/` for files matching the task's naming pattern. If `max_variants` files already exist, the task is skipped — preserving account quotas and avoiding redundant generation.
