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
    printf '\n%s' "Нажмите Enter, чтобы закрыть окно… "
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

command -v python3 >/dev/null 2>&1 || fail "Не найден python3. Установите его: https://www.python.org/downloads/"

if [ ! -x .venv/bin/python ]; then
    say "Создаю окружение (это делается один раз)…"
    python3 -m venv .venv || fail "Не удалось создать .venv"
fi

if [ ! -x .venv/bin/prompt-selector ]; then
    say "Устанавливаю зависимости (пара минут)…"
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -e '.[dev]' || fail "Установка не удалась"
fi
ok "Окружение готово"

# --------------------------------------------------------------------------- #
# 2. Ollama — the local model runtime
# --------------------------------------------------------------------------- #

ollama_up() { curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; }

if ! ollama_up; then
    if [ -d /Applications/Ollama.app ]; then
        say "Запускаю Ollama…"
        open -a Ollama
        for _ in $(seq 1 30); do ollama_up && break; sleep 1; done
    fi
fi

if ollama_up; then
    MODELS=$(curl -s --max-time 5 http://127.0.0.1:11434/api/tags \
        | .venv/bin/python -c 'import json,sys; print(len(json.load(sys.stdin).get("models",[])))' 2>/dev/null || echo 0)
    if [ "${MODELS:-0}" -gt 0 ]; then
        ok "Ollama работает, моделей: $MODELS"
    else
        warn "Ollama работает, но моделей нет. Скачайте одну: ollama pull qwen2.5:7b"
    fi
else
    # Selection and compilation work without a model; only measurement needs one.
    warn "Ollama не отвечает — подбор техник и сборка промпта будут работать,"
    warn "а бенчмарк и оптимизация нет. Установка: https://ollama.com/download"
fi

# --------------------------------------------------------------------------- #
# 3. Pick a free port instead of killing whatever holds 8000
# --------------------------------------------------------------------------- #

PORT=8000
while lsof -ti tcp:"$PORT" >/dev/null 2>&1; do
    PORT=$((PORT + 1))
    [ "$PORT" -gt 8020 ] && fail "Не нашёл свободный порт в диапазоне 8000-8020"
done
[ "$PORT" -ne 8000 ] && note "Порт 8000 занят, использую $PORT"

# --------------------------------------------------------------------------- #
# 4. Serve, open the browser, wait
# --------------------------------------------------------------------------- #

URL="http://127.0.0.1:$PORT"
say "Запускаю интерфейс…"

.venv/bin/prompt-selector serve --port "$PORT" >/tmp/prompt-selector-$PORT.log 2>&1 &
SERVER_PID=$!

cleanup() {
    printf '\n'
    note "Останавливаю…"
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
    exit 0
}
trap cleanup INT TERM

for _ in $(seq 1 40); do
    curl -s --max-time 2 "$URL/health" >/dev/null 2>&1 && break
    kill -0 "$SERVER_PID" 2>/dev/null || {
        printf '%s\n' "${RED}Сервер не стартовал. Лог:${RESET}"
        tail -20 "/tmp/prompt-selector-$PORT.log"
        fail "Запуск не удался"
    }
    sleep 0.5
done

if ! curl -s --max-time 2 "$URL/health" >/dev/null 2>&1; then
    tail -20 "/tmp/prompt-selector-$PORT.log"
    fail "Сервер не ответил за 20 секунд"
fi

ok "Открываю $URL"
open "$URL"

printf '\n'
say "Работает. Что делать дальше:"
printf '  %s\n' "1. Опишите задачу и нажмите «Select techniques»"
printf '  %s\n' "2. Выберите технику — увидите готовый промпт"
printf '  %s\n' "3. «Benchmark this prompt» — измерит его на живой модели"
printf '\n'
note "Лог: /tmp/prompt-selector-$PORT.log"
note "Остановить: Ctrl-C или закройте это окно"
printf '\n'

wait "$SERVER_PID"
