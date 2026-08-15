#!/bin/bash
# Double-click this file in Finder to set up and launch Prompt Playoff.
# It installs what is missing — including the optional extras: the DSPy search
# backends, tracing, and the Hugging Face dataset importer — waits for Ollama,
# starts the web interface and opens it in the browser. Close the Terminal
# window or press Ctrl-C to stop.

set -uo pipefail

# Finder starts scripts from the home directory, not from the file's folder.
cd "$(dirname "$0")" || exit 1

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; RESET=$'\033[0m'

# The logo is drawn in 256 colours; every other message stays in the eight the
# oldest terminal has. Unset TERM, or a terminal that cannot say, means eight.
COLORS=$(tput colors 2>/dev/null) || COLORS=8
case $COLORS in ''|*[!0-9]*) COLORS=8 ;; esac

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

banner() {
    local i art hue base

    # Two words, two colours: PROMPT in dark blue, PLAYOFF in dark gold, each
    # stepping down from light to deep so the word reads as one mark. The steps
    # stay mid-range: a Terminal window is white by default and black by
    # preference, and only the middle is legible on both. The glyphs are heavy
    # already, so no bold on top.
    art=(
        '██████╗  ██████╗   ██████╗  ███╗   ███╗ ██████╗  ████████╗'
        '██╔══██╗ ██╔══██╗ ██╔═══██╗ ████╗ ████║ ██╔══██╗ ╚══██╔══╝'
        '██████╔╝ ██████╔╝ ██║   ██║ ██╔████╔██║ ██████╔╝    ██║'
        '██╔═══╝  ██╔══██╗ ██║   ██║ ██║╚██╔╝██║ ██╔═══╝     ██║'
        '██║      ██║  ██║ ╚██████╔╝ ██║ ╚═╝ ██║ ██║         ██║'
        '╚═╝      ╚═╝  ╚═╝  ╚═════╝  ╚═╝     ╚═╝ ╚═╝         ╚═╝'
        ''
        '██████╗  ██╗       █████╗  ██╗   ██╗  ██████╗  ███████╗ ███████╗'
        '██╔══██╗ ██║      ██╔══██╗ ╚██╗ ██╔╝ ██╔═══██╗ ██╔════╝ ██╔════╝'
        '██████╔╝ ██║      ███████║  ╚████╔╝  ██║   ██║ █████╗   █████╗'
        '██╔═══╝  ██║      ██╔══██║   ╚██╔╝   ██║   ██║ ██╔══╝   ██╔══╝'
        '██║      ███████╗ ██║  ██║    ██║    ╚██████╔╝ ██║      ██║'
        '╚═╝      ╚══════╝ ╚═╝  ╚═╝    ╚═╝     ╚═════╝  ╚═╝      ╚═╝'
    )
    hue=(27 27 26 26 25 25 0 178 178 172 172 136 136)
    # The same two colours in the eight every terminal has, for the ones that
    # cannot do 256.
    base=(34 34 34 34 34 34 0 33 33 33 33 33 33)

    printf '\n\n\n'
    for i in $(seq 0 $(( ${#art[@]} - 1 ))); do
        if [ "$COLORS" -ge 256 ]; then
            printf '\033[38;5;%sm  %s%s\n' "${hue[$i]}" "${art[$i]}" "$RESET"
        else
            printf '\033[%sm  %s%s\n' "${base[$i]}" "${art[$i]}" "$RESET"
        fi
    done
    printf '\n\n'
}

banner
note "  $(pwd)"
printf '\n\n\n'

# --------------------------------------------------------------------------- #
# 1. Python and the virtual environment
# --------------------------------------------------------------------------- #

# A venv is tied to the machine and to the path it was created in: its
# interpreter is a symlink to one specific Python, its console scripts carry an
# absolute shebang, and an editable install points back at the source tree it
# was installed from. Copy the project to another Mac, or just rename its
# folder, and every one of those breaks. So test the environment instead of
# testing for the presence of files, and rebuild it when the test fails.

usable_python() {  # $1 = interpreter; runs, and is new enough for this project
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)' \
        >/dev/null 2>&1
}

find_python() {
    local version candidate resolved
    for version in 3.14 3.13 3.12 3.11; do
        for candidate in \
            "python$version" \
            "/opt/homebrew/bin/python$version" \
            "/usr/local/bin/python$version" \
            "/Library/Frameworks/Python.framework/Versions/$version/bin/python3"
        do
            resolved=$(command -v "$candidate" 2>/dev/null) || continue
            usable_python "$resolved" && { printf '%s\n' "$resolved"; return 0; }
        done
    done
    # Whatever `python3` is on this Mac — Apple ships 3.9, which is too old.
    resolved=$(command -v python3 2>/dev/null) || return 1
    usable_python "$resolved" && { printf '%s\n' "$resolved"; return 0; }
    return 1
}

environment_ready() {
    [ -x .venv/bin/python ] || return 1
    .venv/bin/python - <<'PY' >/dev/null 2>&1
import os
import sys

if sys.version_info[:2] < (3, 11):
    raise SystemExit(1)

import fastapi  # noqa: F401  — the web interface
import rich  # noqa: F401
import typer  # noqa: F401  — the CLI that serves it
import uvicorn  # noqa: F401

import prompt_playoff

# An editable install left over from a different checkout imports fine but
# runs that other copy of the code.
package = os.path.realpath(os.path.dirname(prompt_playoff.__file__))
here = os.path.realpath(os.getcwd())
raise SystemExit(0 if package.startswith(here + os.sep) else 1)
PY
}

# The extras are a separate question from "does the app run". DSPy drags in
# litellm, tracing drags in opentelemetry, the importer drags in pyarrow — any
# of them can fail to build on a given Mac, and none of them should stop the
# app from starting. So they are installed after the core, checked separately,
# and a failure is a warning rather than a dead end.
EXTRA_MODULES="dspy optuna langfuse opentelemetry.sdk datasets pyarrow"

missing_extras() {  # prints the ones that are not importable
    .venv/bin/python - "$EXTRA_MODULES" <<'PY' 2>/dev/null
import importlib.util
import sys

missing = []
for module in sys.argv[1].split():
    try:
        # A dotted name imports its parent package, which raises when the
        # parent is the thing that is missing.
        found = importlib.util.find_spec(module) is not None
    except Exception:
        found = False
    if not found:
        missing.append(module)
print(" ".join(missing))
PY
}

INSTALL_LOG="/tmp/prompt-playoff-install.log"
# Written when the extras failed to build, so the next double-click starts in
# seconds instead of retrying a multi-minute install that already lost once.
EXTRAS_STAMP=".venv/.extras-unavailable"

if ! environment_ready; then
    if [ -e .venv ]; then
        say "The environment does not match this machine, rebuilding it…"
        rm -rf .venv || fail "Could not remove the old .venv"
    else
        say "Creating the environment (once only)…"
    fi

    PYTHON=$(find_python) || fail "No Python 3.11+ found. Install one: https://www.python.org/downloads/"
    note "Using $PYTHON ($("$PYTHON" -V 2>&1))"

    "$PYTHON" -m venv .venv || fail "Could not create .venv"

    say "Installing dependencies (a couple of minutes)…"
    .venv/bin/python -m pip install --quiet --upgrade pip >"$INSTALL_LOG" 2>&1
    if ! .venv/bin/python -m pip install -e '.[dev]' >>"$INSTALL_LOG" 2>&1; then
        tail -20 "$INSTALL_LOG"
        fail "Installation failed. Full log: $INSTALL_LOG"
    fi

    environment_ready || {
        tail -20 "$INSTALL_LOG"
        fail "The environment still does not work. Full log: $INSTALL_LOG"
    }
fi
ok "Environment ready"

MISSING=$(missing_extras)
if [ -n "$MISSING" ] && [ -f "$EXTRAS_STAMP" ]; then
    warn "Optional extras are not installed: $MISSING"
    note "They failed to build here before. Retry: rm $EXTRAS_STAMP and start again"
elif [ -n "$MISSING" ]; then
    say "Adding the optional extras (DSPy search, tracing, dataset import)…"
    note "First time only, a few minutes. Missing: $MISSING"
    if .venv/bin/python -m pip install -e '.[dev,all]' >>"$INSTALL_LOG" 2>&1 \
        && [ -z "$(missing_extras)" ]; then
        ok "Optional extras installed"
    else
        # Named so the message says what the user loses, not just that pip failed.
        warn "Could not install every extra: $(missing_extras)"
        warn "The app runs; the DSPy search backends, tracing or dataset import may not."
        note "Log: $INSTALL_LOG"
        : >"$EXTRAS_STAMP"
    fi
else
    ok "Optional extras ready"
fi

# --------------------------------------------------------------------------- #
# 2. Ollama — the local model runtime
# --------------------------------------------------------------------------- #

ollama_up() { curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; }

# The model the interface asks for out of the box. Downloading anything else
# would leave the settings pointing at a model that is not there.
DEFAULT_MODEL="llama3.2:3b"

# A gigabyte-scale download is the user's call, so ask — but the script is
# started by a double-click and may be left alone, and an unanswered question
# must not hold the window open forever. No answer means no download.
ask() {  # $1 = question
    printf '%s' "${BOLD}$1${RESET} [y/N] "
    read -r -t 30 reply || { printf '\n'; note "No answer, skipping."; return 1; }
    case "$reply" in [yY]*) return 0 ;; *) return 1 ;; esac
}

start_ollama() {
    # `open -a` finds the app wherever it is installed, not just in /Applications.
    if open -a Ollama >/dev/null 2>&1; then :
    elif command -v ollama >/dev/null 2>&1; then
        ollama serve >/tmp/prompt-playoff-ollama.log 2>&1 &
    else
        return 1
    fi
    say "Starting Ollama…"
    for _ in $(seq 1 30); do ollama_up && return 0; sleep 1; done
    return 1
}

if ! ollama_up && ! start_ollama; then
    # Nothing to start: Ollama is not on this Mac at all.
    if command -v brew >/dev/null 2>&1; then
        warn "Ollama is not installed. It runs the models that benchmarks measure."
        if ask "Install it with Homebrew now (~1 GB)?"; then
            brew install --cask ollama || warn "Homebrew could not install Ollama"
            start_ollama || true
        fi
    fi
fi

if ollama_up; then
    MODELS=$(curl -s --max-time 5 http://127.0.0.1:11434/api/tags \
        | .venv/bin/python -c 'import json,sys; print(len(json.load(sys.stdin).get("models",[])))' 2>/dev/null || echo 0)
    if [ "${MODELS:-0}" -gt 0 ]; then
        ok "Ollama is up, models: $MODELS"
    elif command -v ollama >/dev/null 2>&1; then
        warn "Ollama is up but has no models, so nothing can be measured yet."
        if ask "Download $DEFAULT_MODEL now (~2 GB)?"; then
            if ollama pull "$DEFAULT_MODEL"; then
                ok "$DEFAULT_MODEL ready"
            else
                warn "The download failed. Retry later: ollama pull $DEFAULT_MODEL"
            fi
        else
            note "Later: ollama pull $DEFAULT_MODEL"
        fi
    else
        warn "Ollama is up but has no models. Pull one from its app, or: ollama pull $DEFAULT_MODEL"
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

.venv/bin/python -m prompt_playoff serve --port "$PORT" >/tmp/prompt-playoff-$PORT.log 2>&1 &
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
        tail -20 "/tmp/prompt-playoff-$PORT.log"
        fail "Startup failed"
    }
    sleep 0.5
done

if ! curl -s --max-time 2 "$URL/health" >/dev/null 2>&1; then
    tail -20 "/tmp/prompt-playoff-$PORT.log"
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
note "Log: /tmp/prompt-playoff-$PORT.log"
note "Stop with Ctrl-C, or just close this window"
printf '\n'

wait "$SERVER_PID"
