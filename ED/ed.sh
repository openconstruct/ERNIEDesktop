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
LLM_MODEL_PATH="${LLM_MODEL_PATH:-e4.gguf}"
LLM_PORT="${LLM_PORT:-8080}"
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

# runtime config for UI (poll timer etc.)
cat > "$BASE_DIR/runtime-config.js" <<EOF
window.ERNIE_RUNTIME_CONFIG = {
  webPollTimerMs: ${WEB_POLL_TIMER_MS},
  powerPollMs: ${WEB_TELEMETRY_MS},
  modelServerUrl: "${MODEL_SERVER_URL}",
  searchApiUrl: "${SEARCH_API_URL}"
};
EOF

# --- start llama server ---
echo "[*] Starting llama-server..."
cd "$CHAT_DIR"
MODEL_ARG="$LLM_MODEL_PATH"
if [[ "$MODEL_ARG" != /* ]]; then
  MODEL_ARG="$CHAT_DIR/$MODEL_ARG"
fi
nohup ./llama-server -m "$MODEL_ARG" \
  --host "$LLM_HOST" \
  --port "$LLM_PORT" \
  --threads 7 \
  --ctx-size 2048 \
  --batch-size 4 \
  --mlock > "$BASE_DIR/llama.log" 2>&1 &
LLAMA_PID=$!
cd "$BASE_DIR"

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

echo "llama-server PID: $LLAMA_PID"
echo "search server PID: $SEARCH_PID"
echo "Logs: $BASE_DIR/llama.log, $BASE_DIR/search.log"
echo "Press Ctrl+C to stop everything."

trap "echo; echo 'Stopping...'; kill $LLAMA_PID $SEARCH_PID 2>/dev/null || true; exit 0" INT

while true; do sleep 1; done
