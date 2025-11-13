# ERNIE Desktop Documentation

## 1. Overview

ERNIE Desktop is a self-contained local LLM assistant that couples an offline inference stack (llama.cpp), a FastAPI service that augments responses with live web search and hardware telemetry, and a lightweight browser UI. Everything ships together so you can launch a full-featured chat experience from a single script with no external cloud dependencies.

### Key Capabilities

- Local inference using `llama.cpp` binaries and bundled `e4.gguf` model.
- FastAPI microservice that proxies Tavily search and streams host power/RAM/CPU/temperature metrics.
- Rich web UI with session management, attachment ingestion (text/PDF/code), Markdown rendering, syntax highlighting, and search context injection.
- Single launcher (`ed.sh`) that writes runtime config, boots both backends, and opens the UI in a fullscreen Chromium window.

## 2. Architecture

```
┌──────────────┐     JSON completions     ┌────────────┐
│  Web UI      │ ───────────────────────► │ llama.cpp  │
│ (ernie.html) │ ◄─────────────────────── │  server    │
└─────┬────────┘                         └────────────┘
      │  REST (fetch)                               ▲
      │                                             │
      ▼                                             │
┌──────────────┐ Tavily + telemetry  ┌──────────────┘
│ FastAPI      │ ◄────────────────► │ Tavily API /
│ search.py    │                    │ Host sensors
└──────────────┘
```

### Components

- `chat/`: llama.cpp binaries + GGUF model, launched in server mode.
- `search/search.py`: FastAPI app providing `/search/web`, `/telemetry/power`, and `/health`.
- `ernie.html` + `runtime-config.js`: Single-page UI served from local filesystem.
- `lib/`: Pinned copies of Bootstrap, Marked, Highlight.js, and pdf.js for offline use.
- `ed.sh`: Launcher orchestrating env loading, runtime config generation, process startup, and UI opening.

## 3. Repository Layout

```
ED/
├── chat/                 # llama.cpp executables and shared libs
├── search/               # FastAPI app + virtualenv (if desired)
├── lib/                  # Front-end third-party JS/CSS
├── ernie.html            # UI
├── runtime-config.js     # Generated at launch
├── ed.sh                 # Launcher
├── .env                  # Primary configuration file
├── docs/                 # Documentation assets
└── *.log                 # Runtime logs (llama.log, search.log)
```

## 4. Requirements

- 64-bit Linux host (tested on Radxa Orion O6 ARM SBC).
- `chromium` in `$PATH` (for fullscreen UI).
- Python 3.11+ with `psutil`, `fastapi`, `uvicorn`, `tavily`, and dependencies installed (use the provided virtualenv or system packages).
- Tavily API key for web search (`TAVILY_API_KEY` in `.env`).
- Adequate RAM/VRAM for the bundled model (≈6 GB recommended).

## 5. Configuration

All runtime knobs live in `.env`. Notable fields:

- `LLM_HOST`, `LLM_PORT`, `LLM_MODEL_PATH`: llama.cpp server binding + GGUF path (absolute or relative to `chat/`).
- `API_HOST`, `API_PORT`, `API_MODEL`: FastAPI binding and Tavily model label.
- `TAVILY_API_KEY`: Required for `/search/web`.
- `WEB_POLL_TIMER_MS`, `WEB_TELEMETRY_MS`: UI polling cadence for server health and telemetry.
- `PYTHON_ENV_PATH`: Optional venv to auto-activate before launching services.
- `SEARCH_VENV_PATH`: Preferred interpreter for `search.py` (falls back to `PYTHON_ENV_PATH` or `python3`).
- `POWER_IDLE_WATTS`, `POWER_MAX_WATTS`: Used to normalize power utilization/indicator colors.
- `UI_BROWSER_CMD`: Override command used to open the UI (defaults to Chromium fullscreen fallback logic).

## 6. Launcher Workflow (`ed.sh`)

1. Loads `.env`, exporting values for downstream processes.
2. Activates `$PYTHON_ENV_PATH` when provided.
3. Writes `runtime-config.js` with resolved endpoint URLs and poll intervals.
4. Starts `llama-server` (7 threads, 2,048 ctx, ubatch=4, `--mlock`) and tails logs to `llama.log`.
5. Locates a Python interpreter (prefers `$SEARCH_VENV_PATH` / `$PYTHON_ENV_PATH`) and runs `search.py`, logging to `search.log`.
6. Opens `ernie.html` in Chromium (fullscreen `--app` window). Falls back to Firefox kiosk or `xdg-open`.
7. Traps `Ctrl+C` to cleanly terminate both processes.

### Useful Commands

```bash
# Run everything
./ed.sh

# Inspect logs
tail -f llama.log
tail -f search.log
```

## 7. FastAPI Search & Telemetry Service

- `GET /`: Service metadata and endpoint list.
- `GET /health`: Returns `{"status": "healthy"}` when alive.
- `POST /search/web`: Body `{"query": "...", "count": 5}`. Uses Tavily, formats results for UI consumption, returns a `SearchResponse`.
- `GET /telemetry/power`: Returns `PowerTelemetry` with watts, battery status, RAM usage, CPU usage, CPU temp, and derived color thresholds.

### Telemetry Sources

- **Power**: `/sys/class/power_supply/*` first, then `/sys/class/hwmon`, finally CPU-utilization-based estimate.
- **RAM**: `psutil.virtual_memory()`.
- **CPU usage**: `psutil.cpu_percent(interval=0.05)`.
- **Temperature**: `psutil.sensors_temperatures()` with preference order `coretemp`, `k10temp`, `cpu-thermal`, etc.
- **Battery Plug State**: `psutil.sensors_battery()` when available.

## 8. Web UI Highlights

- **Session Management**: Start new chats, persist to `localStorage`, import/export sessions as JSON.
- **Messaging Workflow**: Type, `Ctrl+Enter` to send, or use buttons. Attach multiple files; text/code is inlined, PDFs parsed via pdf.js, binary files referenced.
- **Search Integration**: `Search` button runs Tavily query, stores context for the next user message, and clears the input automatically.
- **Markdown Rendering**: Powered by Marked + Highlight.js with light/dark themes. Each code block includes copy/download actions.
- **Performance Metrics**: TTFT, generation time, characters, tokens, and session tokens/sec displayed live.
- **Telemetry Header**: Power, RAM, CPU, and Temp pills update every `WEB_TELEMETRY_MS`. Color bands indicate severity (green/amber/red) with tooltips for timestamps.
- **Theme & Settings**: Temperature/top-k/p sampling options, stop sequences, manual token caps, and persistent theme toggle.
- **File Storage**: Local `lib/` libraries guarantee offline functionality and faster loads.

## 9. Telemetry Color Logic

- **Power utilization**: green `<60%` of idle–max span (or `<25 W` when span unknown); yellow `60–85%` (`25–40 W`); red `≥85%` (`≥40 W`).
- **RAM usage**: green `<70%`; yellow `70–85%`; red `≥85%`.
- **CPU usage**: green `<60%`; yellow `60–85%`; red `≥85%`.
- **CPU temperature**: green `<60 °C`; yellow `60–75 °C`; red `≥75 °C`.

Idle/default state shows grey pills while the UI is initializing or after a session reset.

## 10. File Attachments & Context Building

1. User text is combined with (optional) search context and attachment summaries.
2. Text/code files under ~200 KB are embedded directly; larger or binary files are acknowledged but not inlined.
3. PDF ingestion extracts text per page via pdf.js; embedded text is appended to the prompt builder.
4. The session retains pending search contexts until the next send, allowing multiple search invocations before sending.

## 11. Troubleshooting

- **UI pills show `n/a`**: FastAPI unreachable or psutil lacks sensors. Check `search.log`, hit `/telemetry/power`, fix permissions.
- **Search calls fail with 503**: `TAVILY_API_KEY` missing or invalid. Update `.env`, rerun launcher.
- **llama-server exits immediately**: Model path wrong or insufficient RAM. Verify `LLM_MODEL_PATH`, free memory, adjust `--threads`.
- **Chromium fails to launch**: Binary absent or custom command misconfigured. Install Chromium or fix `UI_BROWSER_CMD`.
- **PDF attachments not parsed**: pdf.js assets missing. Confirm `lib/pdf.min.js` and `lib/pdf.worker.min.js`.

## 12. Performance Tips

- Match `--threads` to physical cores; adjust `--batch-size`/`--ubatch-size` for your CPU.
- Enable `--flash-attn` or quantized models if your llama.cpp build supports them for ARM.
- Reduce `WEB_TELEMETRY_MS` only if needed; lower intervals increase psutil sampling overhead.
- Use smaller context windows when latency is more important than maximum history.

## 13. Security Considerations

- The UI loads from `file://` and fetches only localhost endpoints by default.
- Tavily calls are proxied server-side to avoid exposing API keys to the browser.
- Uploaded files never leave the browser; only extracted text is sent to the model.
- Logs may contain prompts; rotate or redact as needed during demos.

## 14. Third-Party Licenses

- **Bootstrap 5.3.3** — MIT License.
- **Marked 11.x** — MIT License.
- **Highlight.js 11.9.0** — BSD-3-Clause License.
- **pdf.js 3.11.174** — Apache-2.0 License.
- **Tavily Python SDK** — MIT License.

Include license notices if redistributing binaries or UI assets.

## 15. Generating This Document

The Markdown source (`docs/ernie-desktop-guide.md`) can be converted to HTML/PDF locally:

```bash
# HTML (uses helper script)
python3 tools/md_to_html.py docs/ernie-desktop-guide.md docs/ernie-desktop-guide.html

# PDF (requires chromium)
chromium --headless --disable-gpu \
  --print-to-pdf=docs/ernie-desktop-guide.pdf \
  docs/ernie-desktop-guide.html
```

The repository already includes a pre-generated PDF; regenerate after major changes for accuracy.

## 16. Change Log (excerpt)

- **Latest**: Offline JS libs, environment-driven Python activation, telemetry badges with CPU/temp, PDF export instructions.
- See git history for earlier iterations.

---

Happy hacking with ERNIE Desktop!
