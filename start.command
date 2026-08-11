#!/bin/bash
# Double-click this file in Finder to set up and launch Prompt Selector.
# It installs what is missing, waits for Ollama, starts the web interface and
# opens it in the browser. Close the Terminal window or press Ctrl-C to stop.

set -uo pipefail

# Finder starts scripts from the home directory, not from the file's folder.
cd "$(dirname "$0")" || exit 1

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; RESET=$'\033[0m'

say()  { printf '%s\n' "${BOLD}$1${RESET}"; }
note() { printf '%s\n' "${DIM}$1${RESET}"; }
ok()   { printf '%s\n' "${GREEN}✓${RESET} $1"; }
warn() { printf '%s\n' "${YELLOW}!${RESET} $1"; }

fail() {
    printf '%s\n' "${RED}✗ $1${RESET}"
    printf '\n%s' "Press Enter to close this window… "
    read -r _
    exit 1
}

printf '\n'
say "Prompt Selector"
note "$(pwd)"
printf '\n'

# --------------------------------------------------------------------------- #
# 1. Python and the virtual environment
# --------------------------------------------------------------------------- #

command -v python3 >/dev/null 2>&1 || fail "python3 not found. Install it: https://www.python.org/downloads/"

if [ ! -x .venv/bin/python ]; then
    say "Creating the environment (once only)…"
    python3 -m venv .venv || fail "Could not create .venv"
fi

if [ ! -x .venv/bin/prompt-selector ]; then
    say "Installing dependencies (a couple of minutes)…"
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -e '.[dev]' || fail "Installation failed"
fi
ok "Environment ready"

# --------------------------------------------------------------------------- #
# 2. Ollama — the local model runtime
# --------------------------------------------------------------------------- #

ollama_up() { curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; }

if ! ollama_up; then
    if [ -d /Applications/Ollama.app ]; then
        say "Starting Ollama…"
        open -a Ollama
        for _ in $(seq 1 30); do ollama_up && break; sleep 1; done
    fi
fi

if ollama_up; then
    MODELS=$(curl -s --max-time 5 http://127.0.0.1:11434/api/tags \
        | .venv/bin/python -c 'import json,sys; print(len(json.load(sys.stdin).get("models",[])))' 2>/dev/null || echo 0)
    if [ "${MODELS:-0}" -gt 0 ]; then
        ok "Ollama is up, models: $MODELS"
    else
        warn "Ollama is up but has no models. Pull one: ollama pull qwen2.5:7b"
    fi
else
    # Selection and compilation work without a model; only measurement needs one.
    warn "Ollama is not answering. Selection and compilation still work,"
    warn "benchmarking and optimization do not. Install: https://ollama.com/download"
fi

# --------------------------------------------------------------------------- #
# 3. Pick a free port instead of killing whatever holds 8000
# --------------------------------------------------------------------------- #

PORT=8000
while lsof -ti tcp:"$PORT" >/dev/null 2>&1; do
    PORT=$((PORT + 1))
    [ "$PORT" -gt 8020 ] && fail "No free port in the range 8000-8020"
done
[ "$PORT" -ne 8000 ] && note "Port 8000 is taken, using $PORT"

# --------------------------------------------------------------------------- #
# 4. Serve, open the browser, wait
# --------------------------------------------------------------------------- #

URL="http://127.0.0.1:$PORT"
say "Starting the interface…"

.venv/bin/prompt-selector serve --port "$PORT" >/tmp/prompt-selector-$PORT.log 2>&1 &
SERVER_PID=$!

cleanup() {
    printf '\n'
    note "Stopping…"
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
    exit 0
}
trap cleanup INT TERM

for _ in $(seq 1 40); do
    curl -s --max-time 2 "$URL/health" >/dev/null 2>&1 && break
    kill -0 "$SERVER_PID" 2>/dev/null || {
        printf '%s\n' "${RED}The server did not start. Log:${RESET}"
        tail -20 "/tmp/prompt-selector-$PORT.log"
        fail "Startup failed"
    }
    sleep 0.5
done

if ! curl -s --max-time 2 "$URL/health" >/dev/null 2>&1; then
    tail -20 "/tmp/prompt-selector-$PORT.log"
    fail "The server did not answer within 20 seconds"
fi

ok "Opening $URL"
open "$URL"

printf '\n'
say "Running. What to do next:"
printf '  %s\n' "1. Describe your task and press \"Create my prompt\""
printf '  %s\n' "2. Pick a technique to see the prompt it compiles to"
printf '  %s\n' "3. \"Benchmark this prompt\" measures it on a live model"
printf '\n'
note "Log: /tmp/prompt-selector-$PORT.log"
note "Stop with Ctrl-C, or just close this window"
printf '\n'

wait "$SERVER_PID"
