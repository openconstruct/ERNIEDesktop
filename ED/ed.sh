#!/usr/bin/env bash
# Simple ERNIE Desktop launcher with Tavily key export

set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
CHAT_DIR="$BASE_DIR/chat"
SEARCH_DIR="$BASE_DIR/search"
UI_FILE="$BASE_DIR/ernie.html"
USER_SEARCH_ENV=""

# --- load environment overrides ---
ENV_FILE="$BASE_DIR/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  echo "[!] .env file not found at $ENV_FILE – falling back to defaults." >&2
fi

if [ -n "${PYTHON_ENV_PATH:-}" ]; then
  ACTIVATE_SCRIPT="$PYTHON_ENV_PATH/bin/activate"
  if [ -f "$ACTIVATE_SCRIPT" ]; then
    echo "[*] Activating Python environment at $PYTHON_ENV_PATH"
    # shellcheck disable=SC1090
    source "$ACTIVATE_SCRIPT"
  else
    echo "[!] PYTHON_ENV_PATH is set to $PYTHON_ENV_PATH but activate script not found at $ACTIVATE_SCRIPT" >&2
  fi
fi

if [ -n "${SEARCH_VENV_PATH:-}" ]; then
  USER_SEARCH_ENV="$SEARCH_VENV_PATH"
elif [ -n "${PYTHON_ENV_PATH:-}" ]; then
  USER_SEARCH_ENV="$PYTHON_ENV_PATH"
else
  USER_SEARCH_ENV="/home/jerr/search"
fi

# --- defaults & normalization ---
LLM_HOST="${LLM_HOST:-127.0.0.1}"
LLM_MODEL_DIR="${LLM_MODEL_DIR:-./models}"
LLM_MODEL_PATH="${LLM_MODEL_PATH:-e4.gguf}"
LLM_PORT="${LLM_PORT:-8080}"
LLAMA_ARGS="${LLAMA_ARGS:---threads 7 --ctx-size 2048 --batch-size 4 --mlock}"
API_HOST="${API_HOST:-127.0.0.1}"
API_MODEL="${API_MODEL:-tavily-web}"
API_PORT="${API_PORT:-8000}"
TAVILY_API_KEY="${TAVILY_API_KEY:-}"
WEB_POLL_TIMER_MS="${WEB_POLL_TIMER_MS:-8000}"
WEB_TELEMETRY_MS="${WEB_TELEMETRY_MS:-10000}"

MODEL_SERVER_URL="http://${LLM_HOST}:${LLM_PORT}"
SEARCH_API_URL="http://${API_HOST}:${API_PORT}"

if ! [[ "$WEB_POLL_TIMER_MS" =~ ^[0-9]+$ ]]; then
  echo "[!] WEB_POLL_TIMER_MS is invalid ($WEB_POLL_TIMER_MS). Using 8000ms." >&2
  WEB_POLL_TIMER_MS=8000
fi
if ! [[ "$WEB_TELEMETRY_MS" =~ ^[0-9]+$ ]]; then
  echo "[!] WEB_TELEMETRY_MS is invalid ($WEB_TELEMETRY_MS). Using 10000ms." >&2
  WEB_TELEMETRY_MS=10000
fi

export TAVILY_API_KEY
export API_MODEL
export API_PORT
export API_HOST
export CHAT_DIR
export LLM_HOST
export LLM_PORT
export LLAMA_ARGS
export LLAMA_PID_FILE="$BASE_DIR/llama.pid"
export LLAMA_LOG_FILE="$BASE_DIR/llama.log"

# Resolve model directory for search.py
MODEL_DIR_FOR_EXPORT="$LLM_MODEL_DIR"
if [[ "$MODEL_DIR_FOR_EXPORT" != /* ]]; then
  MODEL_DIR_FOR_EXPORT="$BASE_DIR/$MODEL_DIR_FOR_EXPORT"
fi
export LLM_MODEL_DIR="$MODEL_DIR_FOR_EXPORT"

# runtime config for UI (poll timer etc.)
cat > "$BASE_DIR/runtime-config.js" <<EOF
window.ERNIE_RUNTIME_CONFIG = {
  webPollTimerMs: ${WEB_POLL_TIMER_MS},
  powerPollMs: ${WEB_TELEMETRY_MS},
  modelServerUrl: "${MODEL_SERVER_URL}",
  searchApiUrl: "${SEARCH_API_URL}"
};
EOF

# --- start llama server (if model is specified) ---
if [ -z "$LLM_MODEL_PATH" ]; then
  echo "[*] No model specified in LLM_MODEL_PATH. Skipping llama-server startup."
  echo "[*] You can select and load a model from the UI once it opens."
  LLAMA_PID=""
else
  echo "[*] Starting llama-server with model: $LLM_MODEL_PATH"
  cd "$CHAT_DIR"

  # Resolve model directory path
  MODEL_DIR="$LLM_MODEL_DIR"
  if [[ "$MODEL_DIR" != /* ]]; then
    MODEL_DIR="$BASE_DIR/$MODEL_DIR"
  fi

  # Combine directory and model filename
  MODEL_ARG="$MODEL_DIR/$LLM_MODEL_PATH"

  if [ ! -f "$MODEL_ARG" ]; then
    echo "[!] Warning: Model file not found at $MODEL_ARG"
    echo "[*] Skipping llama-server startup. You can select a model from the UI."
    LLAMA_PID=""
    cd "$BASE_DIR"
  else
    nohup ./llama-server -m "$MODEL_ARG" \
      --host "$LLM_HOST" \
      --port "$LLM_PORT" \
      $LLAMA_ARGS > "$BASE_DIR/llama.log" 2>&1 &
    LLAMA_PID=$!

    # Write PID and model to file for FastAPI management
    echo "$LLAMA_PID" > "$LLAMA_PID_FILE"
    echo "$MODEL_ARG" >> "$LLAMA_PID_FILE"
    cd "$BASE_DIR"
  fi
fi

select_search_python() {
  if [ -n "${VIRTUAL_ENV:-}" ]; then
    if [ -x "$VIRTUAL_ENV/bin/python" ]; then
      SEARCH_PYTHON="$VIRTUAL_ENV/bin/python"
      echo "[*] Using already-active Python environment at $VIRTUAL_ENV"
      return
    fi
    echo "[!] VIRTUAL_ENV is set to $VIRTUAL_ENV but no python interpreter was found; falling back to discovery." >&2
  fi

  local candidates=()
  if [ -n "$USER_SEARCH_ENV" ]; then
    candidates+=("$USER_SEARCH_ENV")
  fi
  candidates+=("$SEARCH_DIR/venv" "$SEARCH_DIR/.venv")

  for env_path in "${candidates[@]}"; do
    if [ -z "$env_path" ]; then
      continue
    fi
    if [ -x "$env_path/bin/python" ]; then
      SEARCH_PYTHON="$env_path/bin/python"
      echo "[*] Using search interpreter at $SEARCH_PYTHON"
      return
    fi
  done

  SEARCH_PYTHON="python3"
  echo "[!] No dedicated Python virtual environment found for search server. Using system interpreter." >&2
}

open_ui() {
  local url="file://$UI_FILE"

  if [ -n "${UI_BROWSER_CMD:-}" ]; then
    echo "[*] Opening ERNIE Desktop UI with custom browser command"
    nohup bash -c "${UI_BROWSER_CMD} \"$url\"" >/dev/null 2>&1 &
    return
  fi

  local chrome_variants=("chromium-browser" "chromium" "google-chrome" "google-chrome-stable" "brave-browser" "brave" "microsoft-edge" "microsoft-edge-stable")
  for browser in "${chrome_variants[@]}"; do
    if command -v "$browser" >/dev/null 2>&1; then
      echo "[*] Opening ERNIE Desktop UI in $browser fullscreen..."
      nohup "$browser" --app="$url" --start-fullscreen >/dev/null 2>&1 &
      return
    fi
  done

  if command -v firefox >/dev/null 2>&1; then
    echo "[*] Opening ERNIE Desktop UI in Firefox kiosk mode..."
    nohup firefox --kiosk "$url" >/dev/null 2>&1 &
    return
  fi

  echo "[*] Opening ERNIE Desktop UI with xdg-open (fullscreen may depend on system defaults)..."
  nohup xdg-open "$url" >/dev/null 2>&1 &
}

# --- start FastAPI search server ---
echo "[*] Starting search server..."
cd "$SEARCH_DIR"
select_search_python
nohup "$SEARCH_PYTHON" search.py > "$BASE_DIR/search.log" 2>&1 &
SEARCH_PID=$!
cd "$BASE_DIR"

# --- open UI ---
open_ui

if [ -n "$LLAMA_PID" ]; then
  echo "llama-server PID: $LLAMA_PID"
else
  echo "llama-server: Not started (no model loaded)"
fi
echo "search server PID: $SEARCH_PID"
echo "Logs: $BASE_DIR/llama.log, $BASE_DIR/search.log"
echo "Press Ctrl+C to stop everything."

# Trap to stop processes on exit
stop_services() {
  echo
  echo 'Stopping services...'
  if [ -n "$LLAMA_PID" ]; then
    kill "$LLAMA_PID" 2>/dev/null || true
  fi
  kill "$SEARCH_PID" 2>/dev/null || true
  rm -f "$LLAMA_PID_FILE"
  exit 0
}

trap stop_services INT

while true; do sleep 1; done
