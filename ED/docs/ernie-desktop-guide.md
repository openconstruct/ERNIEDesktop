# ERNIE Desktop Documentation

## 1. Overview

ERNIE Desktop is a self-contained local LLM assistant that couples an offline inference stack (llama.cpp), a FastAPI service that augments responses with live web search and hardware telemetry, and a lightweight browser UI. Everything ships together so you can launch a full-featured chat experience from a single script with no external cloud dependencies.

### Key Capabilities

- Local inference using `llama.cpp` binaries and bundled `e4.gguf` model.
- FastAPI microservice that proxies Tavily search and streams host power/RAM/CPU/temperature metrics.
- Rich web UI with session management, attachment ingestion (text/PDF/DOCX/CSV/code), Markdown rendering, syntax highlighting, and search context injection.
- **Conversation branching** with message editing, response regeneration, and tree navigation for exploring alternative conversation paths.
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
├── models/               # GGUF model files (e4.gguf, g3.gguf, etc.)
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

- `LLM_HOST`, `LLM_PORT`: llama.cpp server binding.
- `LLM_MODEL_DIR`: Directory containing GGUF model files (default: `./models`, relative to project root).
- `LLM_MODEL_PATH`: Filename of the GGUF model to load (e.g., `e4.gguf`).
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
4. Starts `llama-server` **only if `LLM_MODEL_PATH` is specified** (7 threads, 2,048 ctx, ubatch=4, `--mlock`) and tails logs to `llama.log`. If no model is specified, users can select one from the UI.
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

### First Run Setup

On first launch, **no model is loaded by default**. This allows users to choose which model to use based on their hardware capabilities. Here's what to expect:

1. **Launch the application**: Run `./ed.sh` - the UI opens but shows "No model loaded"
2. **Open the sidebar**: Click the hamburger menu (☰) in the top-left corner
3. **Browse available models**: Navigate to the "Models" section to see all `.gguf` files in your `models/` directory
4. **Select a model**: Click on a model to load it - the model server will start automatically
5. **Wait for initialization**: The model server takes 10-30 seconds to load (check the green dot indicator)
6. **Start chatting**: Once the "Model Server" indicator is green, you're ready to go

**Model Selection Persistence**: Your selected model is automatically saved to `.env` as `LLM_MODEL_PATH`. On subsequent launches, this model loads automatically unless you change it.

### Switching Models

You can switch between models at any time without restarting the application:

1. Open the sidebar and go to "Models"
2. Click on any available model
3. The current model server stops gracefully
4. The new model loads (typically 10-30 seconds)
5. Your selection is saved for next time

**Note**: Switching models clears the current conversation context. Save your session first if you want to preserve it.

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

- **Session Management**: Start new chats, persist to `localStorage`, import/export sessions as JSON with full conversation tree structure.
- **Messaging Workflow**: Type, `Ctrl+Enter` to send, or use buttons. Attach multiple files; text/code/CSV/DOCX is inlined, PDFs parsed via pdf.js, binary files referenced.
- **Conversation Branching**: Edit user messages, regenerate assistant responses, and navigate between alternative conversation paths using branch controls.
- **Search Integration**: `Search` button runs Tavily query, stores context for the next user message, and clears the input automatically.
- **Markdown Rendering**: Powered by Marked + Highlight.js with light/dark themes. Each code block includes copy/download actions.
- **Performance Metrics**: TTFT, generation time, characters, tokens, and session tokens/sec displayed live.
- **Telemetry Header**: Power, RAM, CPU, and Temp pills update every `WEB_TELEMETRY_MS`. Color bands indicate severity (green/amber/red) with tooltips for timestamps.
- **Theme & Settings**: Temperature/top-k/p sampling options, stop sequences, manual token caps, and persistent theme toggle.
- **File Storage**: Local `lib/` libraries (Bootstrap, Marked, Highlight.js, pdf.js, PapaParse, mammoth.js) guarantee offline functionality and faster loads.

## 9. Telemetry Color Logic

- **Power utilization**: green `<60%` of idle–max span (or `<25 W` when span unknown); yellow `60–85%` (`25–40 W`); red `≥85%` (`≥40 W`).
- **RAM usage**: green `<70%`; yellow `70–85%`; red `≥85%`.
- **CPU usage**: green `<60%`; yellow `60–85%`; red `≥85%`.
- **CPU temperature**: green `<60 °C`; yellow `60–75 °C`; red `≥75 °C`.

Idle/default state shows grey pills while the UI is initializing or after a session reset.

## 10. Conversation Branching

ERNIE Desktop features a conversation tree system that allows you to explore alternative responses and edit messages without losing your conversation history.

### How It Works

Instead of a simple linear chat history, conversations are stored as a tree where each message can have multiple child responses. This enables:

- **Editing user messages** and regenerating responses
- **Creating alternative assistant responses** at any point
- **Navigating between branches** to compare different conversation paths
- **Preserving all responses** so you never lose an interesting answer

### Tree Structure Example

```
User: "Explain quantum physics"
├─► Assistant: "Here's a technical explanation..." (Branch 1)
├─► Assistant: "In simple terms..." (Branch 2)
└─► Assistant: "Let me use an analogy..." (Branch 3)
```

Each branch represents a different response to the same question. You can switch between them without losing any content.

### Editing Messages

When you edit a user message, ERNIE will:

1. Prompt you to confirm (since this deletes all responses after that message)
2. Update the message content
3. Automatically generate a new response to the edited message
4. Preserve the conversation history up to that point

**Use Case**: Refine your question after seeing the initial response.

**Example**:
- Original: "Explain quantum physics" → Response is too technical
- Edit to: "Explain quantum physics simply" → Get a simplified response

### Regenerating Responses

Click the 🔄 **Regenerate** button on any assistant message to create an alternative response. Each regeneration:

- Creates a new "sibling" response to the same user message
- Keeps all previous responses accessible
- Doesn't affect the rest of the conversation

**Use Case**: Get multiple perspectives or writing styles for the same question.

**Example**:
- Ask: "Write a haiku about coding"
- Regenerate 3 times to get 4 different haikus
- Choose your favorite using the branch navigator

### Branch Navigation

When a message has multiple children (branches), you'll see navigation controls:

```
◀  2/4  ▶
```

- **◀ Button**: Switch to previous sibling response
- **Counter**: Shows current branch (2) of total branches (4)
- **▶ Button**: Switch to next sibling response
- Buttons are disabled at the boundaries

The entire conversation updates to follow the selected branch path.

### Practical Workflows

#### Workflow 1: Refining Questions
1. Ask a question
2. Review the response
3. Click ✏️ **Edit** to refine your question
4. Get a better-targeted response

#### Workflow 2: Exploring Options
1. Ask an open-ended question
2. Click 🔄 **Regenerate** multiple times
3. Use ◀▶ to browse all responses
4. Continue from your preferred response

#### Workflow 3: Conversation Branches
1. Have a conversation about Topic A
2. Get to an interesting point
3. Regenerate to explore Topic B instead
4. Now you have two conversation paths from the same starting point

### Session Management with Branches

- **Saving**: All branches are preserved when you save a session
- **Loading**: Sessions restore with the full tree structure intact
- **Exporting**: Export format (v2.0) includes complete tree data
- **Importing**: Supports both old linear (v1.0) and new tree (v2.0) formats
- **Legacy Support**: Old session files are automatically converted to tree format

## 11. File Attachments & Context Building

ERNIE Desktop supports multiple file formats for context injection:

### Supported File Formats

| Format | Library | Description | Max Size |
|--------|---------|-------------|----------|
| **Text/Code** | Native | Plain text, source code (`.txt`, `.py`, `.js`, `.java`, etc.) | 200 KB |
| **PDF** | pdf.js | Extracts text page-by-page from PDF documents | Unlimited* |
| **DOCX** | mammoth.js | Microsoft Word documents converted to plain text | Unlimited* |
| **CSV** | PapaParse | Spreadsheets formatted as markdown tables (1,000 row limit) | Unlimited* |
| **Markdown** | Native | Markdown files displayed as-is or rendered | 200 KB |
| **Binary/Images** | N/A | Acknowledged but not embedded in context | N/A |

*Practical limits apply based on available memory and model context window.

### Context Building Process

1. User text is combined with (optional) search context and attachment summaries.
2. Text/code files under ~200 KB are embedded directly; larger or binary files are acknowledged but not inlined.
3. **PDF ingestion** extracts text per page via pdf.js; embedded text is appended to the prompt builder.
4. **DOCX ingestion** uses mammoth.js to extract plain text from Word documents, stripping formatting.
5. **CSV ingestion** parses spreadsheets with PapaParse and formats them as markdown tables for the LLM. Shows first 1,000 rows with a note if more exist.
6. The session retains pending search contexts until the next send, allowing multiple search invocations before sending.

### File Icon Reference

When files are loaded, they appear in the document tray with visual icons:

- 📕 PDF documents
- 📘 DOCX (Word) documents
- 📊 CSV spreadsheets
- 📝 Plain text files
- 💻 Source code files
- 📋 Markdown files
- 🖼️ Image files
- 📄 Other file types
## 12. Troubleshooting

- **"No model loaded" message on startup**: This is expected behavior. Open the sidebar and select a model from the Models section to get started.
- **Model Server indicator stays red**: No model is loaded or model failed to start. Check `llama.log` for errors. Verify the model file exists in your `models/` directory.
- **Can't send messages**: Model server must be online (green indicator). Select a model from the sidebar if none is loaded.
- **UI pills show `n/a`**: FastAPI unreachable or psutil lacks sensors. Check `search.log`, hit `/telemetry/power`, fix permissions.
- **Search calls fail with 503**: `TAVILY_API_KEY` missing or invalid. Update `.env`, rerun launcher.
- **llama-server exits immediately**: Model path wrong or insufficient RAM. Verify model file exists, free memory, adjust `--threads`.
- **Chromium fails to launch**: Binary absent or custom command misconfigured. Install Chromium or fix `UI_BROWSER_CMD`.
- **PDF attachments not parsed**: pdf.js assets missing. Confirm `lib/pdf.min.js` and `lib/pdf.worker.min.js`.
- **DOCX files show error**: mammoth.js library missing. Verify `lib/mammoth.min.js` exists and is loaded.
- **CSV files not formatted**: PapaParse library missing. Verify `lib/papaparse.min.js` exists and is loaded.
- **Branch navigation buttons missing**: Old session format loaded. Save and reload the session to convert to tree structure.
- **Can't see regenerated responses**: Use branch navigation arrows (◀▶) to switch between alternative responses.

## 13. Performance Tips

- Match `--threads` to physical cores; adjust `--batch-size`/`--ubatch-size` for your CPU.
- Enable `--flash-attn` or quantized models if your llama.cpp build supports them for ARM.
- Reduce `WEB_TELEMETRY_MS` only if needed; lower intervals increase psutil sampling overhead.
- Use smaller context windows when latency is more important than maximum history.

## 14. Security Considerations

- The UI loads from `file://` and fetches only localhost endpoints by default.
- Tavily calls are proxied server-side to avoid exposing API keys to the browser.
- Uploaded files never leave the browser; only extracted text is sent to the model.
- Logs may contain prompts; rotate or redact as needed during demos.

## 15. Third-Party Licenses

- **Bootstrap 5.3.3** — MIT License.
- **Marked 11.x** — MIT License.
- **Highlight.js 11.9.0** — BSD-3-Clause License.
- **pdf.js 3.11.174** — Apache-2.0 License.
- **PapaParse 5.4.1** — MIT License.
- **mammoth.js 1.6.0** — BSD-2-Clause License.
- **Tavily Python SDK** — MIT License.

Include license notices if redistributing binaries or UI assets.

## 16. Generating This Document

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

## 17. Change Log (excerpt)

- **v2.0 (Latest)**:
  - **Conversation branching**: Edit user messages, regenerate assistant responses, navigate between alternative conversation paths
  - **Extended file support**: Added DOCX (mammoth.js) and CSV (PapaParse) format support
  - **Tree-based sessions**: Conversations stored as tree structure preserving all branches
  - **Model directory support**: Separate `models/` directory for GGUF files, configurable via `LLM_MODEL_DIR`
  - **No default model**: Users select models on first run; selection persists to `.env` automatically
  - **First-run experience**: Helpful UI guidance when no model is loaded
  - **Model persistence**: Selected model saved to `.env` and loads automatically on subsequent runs
  - **Backward compatibility**: Automatic migration of v1.0 sessions to tree format
  - **Export format v2.0**: Includes full tree structure with legacy array format
- **v1.0**: Offline JS libs, environment-driven Python activation, telemetry badges with CPU/temp, PDF export instructions.
- See git history for earlier iterations.

---

Happy hacking with ERNIE Desktop!
