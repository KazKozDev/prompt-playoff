@echo off
rem  Double-click this file in Explorer to set up and launch Prompt Playoff.
rem  It installs what is missing - including the optional extras: the DSPy
rem  search backends, tracing, and the Hugging Face dataset importer - waits
rem  for Ollama, starts the web interface and opens it in the browser.
rem  Close this window or press Ctrl-C to stop.

setlocal enabledelayedexpansion

rem  Explorer runs a batch file from whatever the current directory happens to
rem  be, which is not the file's folder.
cd /d "%~dp0"

rem  The banner and the tick marks are UTF-8; the console starts on an OEM code
rem  page that cannot draw them. Every multi-byte sequence is above 0x7F, so
rem  nothing here can collide with a character cmd treats as special.
for /f "tokens=2 delims=:." %%c in ('chcp') do set "OLD_CODEPAGE=%%c"
chcp 65001 >nul

set "VENV_PY=.venv\Scripts\python.exe"
set "INSTALL_LOG=%TEMP%\prompt-playoff-install.log"
rem  Written when the extras failed to build, so the next double-click starts in
rem  seconds instead of retrying a multi-minute install that already lost once.
set "EXTRAS_STAMP=.venv\.extras-unavailable"
set "DEFAULT_MODEL=llama3.2:3b"
set "EXTRA_MODULES=dspy optuna langfuse opentelemetry.sdk datasets pyarrow"
set "OLLAMA_TAGS=http://127.0.0.1:11434/api/tags"

call :banner
echo   %CD%
echo(
echo(

rem --------------------------------------------------------------------------- rem
rem  1. Python and the virtual environment
rem --------------------------------------------------------------------------- rem

rem  A venv is tied to the machine and to the path it was created in: its
rem  interpreter records one specific Python, its console scripts carry an
rem  absolute path, and an editable install points back at the source tree it
rem  was installed from. Copy the project to another PC, or just rename its
rem  folder, and every one of those breaks. So test the environment instead of
rem  testing for the presence of files, and rebuild it when the test fails.

call :environment_ready
if not errorlevel 1 goto :environment_done

if exist .venv (
    echo The environment does not match this machine, rebuilding it...
    rmdir /s /q .venv
    if exist .venv (
        call :fail "Could not remove the old .venv"
        goto :end
    )
) else (
    echo Creating the environment ^(once only^)...
)

call :find_python
if not defined PYTHON (
    call :fail "No Python 3.11+ found. Install one: https://www.python.org/downloads/"
    goto :end
)
for /f "tokens=*" %%v in ('%PYTHON% -V 2^>^&1') do echo   Using %PYTHON% ^(%%v^)

%PYTHON% -m venv .venv
if not exist "%VENV_PY%" (
    call :fail "Could not create .venv"
    goto :end
)

echo Installing dependencies ^(a couple of minutes^)...
"%VENV_PY%" -m pip install --quiet --upgrade pip >"%INSTALL_LOG%" 2>&1
"%VENV_PY%" -m pip install -e .[dev] >>"%INSTALL_LOG%" 2>&1
if errorlevel 1 (
    call :tail "%INSTALL_LOG%"
    call :fail "Installation failed. Full log: %INSTALL_LOG%"
    goto :end
)

call :environment_ready
if errorlevel 1 (
    call :tail "%INSTALL_LOG%"
    call :fail "The environment still does not work. Full log: %INSTALL_LOG%"
    goto :end
)

:environment_done
echo ✓ Environment ready

rem  The extras are a separate question from "does the app run". DSPy drags in
rem  litellm, tracing drags in opentelemetry, the importer drags in pyarrow -
rem  any of them can fail to build on a given PC, and none of them should stop
rem  the app from starting. So they are installed after the core, checked
rem  separately, and a failure is a warning rather than a dead end.
call :missing_extras
if not defined MISSING goto :extras_done

if exist "%EXTRAS_STAMP%" (
    echo ⚠ Optional extras are not installed:!MISSING!
    echo   They failed to build here before. Retry: del "%EXTRAS_STAMP%" and start again
    goto :extras_checked
)

echo Adding the optional extras ^(DSPy search, tracing, dataset import^)...
echo   First time only, a few minutes. Missing:!MISSING!
"%VENV_PY%" -m pip install -e .[dev,all] >>"%INSTALL_LOG%" 2>&1
call :missing_extras
if not defined MISSING goto :extras_done
rem  Named so the message says what the user loses, not just that pip failed.
echo ⚠ Could not install every extra:!MISSING!
echo ⚠ The app runs; the DSPy search backends, tracing or dataset import may not.
echo   Log: %INSTALL_LOG%
type nul >"%EXTRAS_STAMP%"
goto :extras_checked

:extras_done
echo ✓ Optional extras ready
:extras_checked

rem --------------------------------------------------------------------------- rem
rem  2. Ollama - the local model runtime
rem --------------------------------------------------------------------------- rem

call :ollama_up
if not errorlevel 1 goto :ollama_running

call :start_ollama
if not errorlevel 1 goto :ollama_running

rem  Nothing to start: Ollama is not on this PC at all.
where winget >nul 2>&1
if errorlevel 1 goto :ollama_missing
echo ⚠ Ollama is not installed. It runs the models that benchmarks measure.
call :ask "Install it with winget now (~1 GB)?"
if errorlevel 1 goto :ollama_missing
winget install --id Ollama.Ollama --exact --accept-package-agreements --accept-source-agreements
call :start_ollama
if not errorlevel 1 goto :ollama_running

:ollama_missing
rem  Selection and compilation work without a model; only measurement needs one.
echo ⚠ Ollama is not answering. Selection and compilation still work,
echo ⚠ benchmarking and optimization do not. Install: https://ollama.com/download
goto :ollama_done

:ollama_running
set "MODELS=0"
for /f "usebackq tokens=*" %%n in (`%VENV_PY% -c "import json, urllib.request; print(len(json.load(urllib.request.urlopen('%OLLAMA_TAGS%', timeout=5)).get('models', [])))" 2^>nul`) do set "MODELS=%%n"
if not "%MODELS%"=="0" (
    echo ✓ Ollama is up, models: %MODELS%
    goto :ollama_done
)
where ollama >nul 2>&1
if errorlevel 1 (
    echo ⚠ Ollama is up but has no models. Pull one from its app, or: ollama pull %DEFAULT_MODEL%
    goto :ollama_done
)
echo ⚠ Ollama is up but has no models, so nothing can be measured yet.
call :ask "Download %DEFAULT_MODEL% now (~2 GB)?"
if errorlevel 1 (
    echo   Later: ollama pull %DEFAULT_MODEL%
    goto :ollama_done
)
ollama pull %DEFAULT_MODEL%
if errorlevel 1 (
    echo ⚠ The download failed. Retry later: ollama pull %DEFAULT_MODEL%
) else (
    echo ✓ %DEFAULT_MODEL% ready
)
:ollama_done

rem --------------------------------------------------------------------------- rem
rem  3. Pick a free port instead of taking whatever holds 8000
rem --------------------------------------------------------------------------- rem

set /a PORT=8000
:port_loop
"%VENV_PY%" -c "import socket, sys; s = socket.socket(); code = s.connect_ex(('127.0.0.1', %PORT%)); s.close(); sys.exit(1 if code == 0 else 0)" >nul 2>&1
if not errorlevel 1 goto :port_free
set /a PORT+=1
if %PORT% GTR 8020 (
    call :fail "No free port in the range 8000-8020"
    goto :end
)
goto :port_loop

:port_free
if not %PORT%==8000 echo   Port 8000 is taken, using %PORT%

rem --------------------------------------------------------------------------- rem
rem  4. Serve, open the browser, wait
rem --------------------------------------------------------------------------- rem

set "URL=http://127.0.0.1:%PORT%"
echo Starting the interface...
echo(
echo Running. What to do next:
echo   1. Describe your task and press "Create my prompt"
echo   2. Pick a technique to see the prompt it compiles to
echo   3. "Benchmark this prompt" measures it on a live model
echo(
echo   Stop with Ctrl-C, or just close this window
echo(

rem  The server holds this window, so the browser is opened from a second
rem  process that waits for /health first - an empty tab on a port that is not
rem  listening yet looks like a failure.
start "" /b powershell -NoProfile -Command "for ($i = 0; $i -lt 60; $i++) { try { Invoke-WebRequest -UseBasicParsing '%URL%/health' -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Milliseconds 500 } }; Start-Process '%URL%'"

"%VENV_PY%" -m prompt_playoff serve --port %PORT%

:end
if defined OLD_CODEPAGE chcp %OLD_CODEPAGE% >nul
endlocal
exit /b 0

rem --------------------------------------------------------------------------- rem
rem  Subroutines
rem --------------------------------------------------------------------------- rem

:banner
rem  The wordmark is drawn in the same glyphs as the macOS launcher. Colour is
rem  left out: cmd.exe only honours ANSI when virtual-terminal processing is on,
rem  and that is a per-console setting this script has no business changing.
echo(
echo(
echo   ██████╗  ██████╗   ██████╗  ███╗   ███╗ ██████╗  ████████╗
echo   ██╔══██╗ ██╔══██╗ ██╔═══██╗ ████╗ ████║ ██╔══██╗ ╚══██╔══╝
echo   ██████╔╝ ██████╔╝ ██║   ██║ ██╔████╔██║ ██████╔╝    ██║
echo   ██╔═══╝  ██╔══██╗ ██║   ██║ ██║╚██╔╝██║ ██╔═══╝     ██║
echo   ██║      ██║  ██║ ╚██████╔╝ ██║ ╚═╝ ██║ ██║         ██║
echo   ╚═╝      ╚═╝  ╚═╝  ╚═════╝  ╚═╝     ╚═╝ ╚═╝         ╚═╝
echo(
echo   ██████╗  ██╗       █████╗  ██╗   ██╗  ██████╗  ███████╗ ███████╗
echo   ██╔══██╗ ██║      ██╔══██╗ ╚██╗ ██╔╝ ██╔═══██╗ ██╔════╝ ██╔════╝
echo   ██████╔╝ ██║      ███████║  ╚████╔╝  ██║   ██║ █████╗   █████╗
echo   ██╔═══╝  ██║      ██╔══██║   ╚██╔╝   ██║   ██║ ██╔══╝   ██╔══╝
echo   ██║      ███████╗ ██║  ██║    ██║    ╚██████╔╝ ██║      ██║
echo   ╚═╝      ╚══════╝ ╚═╝  ╚═╝    ╚═╝     ╚═════╝  ╚═╝      ╚═╝
echo(
echo(
exit /b 0

:find_python
rem  The py launcher first: it knows every install, including the ones that are
rem  not on PATH. A bare `python` on a clean Windows is the Store stub, which
rem  exits without running anything - so every candidate is tested by running it.
set "PYTHON="
for %%v in (3.14 3.13 3.12 3.11) do (
    if not defined PYTHON (
        py -%%v -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>&1 && set "PYTHON=py -%%v"
    )
)
if not defined PYTHON (
    py -3 -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>&1 && set "PYTHON=py -3"
)
if not defined PYTHON (
    python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>&1 && set "PYTHON=python"
)
exit /b 0

:environment_ready
if not exist "%VENV_PY%" exit /b 1
"%VENV_PY%" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>&1 || exit /b 1
rem  The web interface and the CLI that serves it.
"%VENV_PY%" -c "import fastapi, rich, typer, uvicorn" >nul 2>&1 || exit /b 1
rem  An editable install left over from a different checkout imports fine but
rem  runs that other copy of the code.
"%VENV_PY%" -c "import os, sys, prompt_playoff; package = os.path.realpath(os.path.dirname(prompt_playoff.__file__)); here = os.path.realpath(os.getcwd()); sys.exit(0 if package.startswith(here + os.sep) else 1)" >nul 2>&1 || exit /b 1
exit /b 0

:missing_extras
rem  A dotted name imports its parent package, which raises when the parent is
rem  the thing that is missing - so a non-zero exit covers both cases.
set "MISSING="
for %%m in (%EXTRA_MODULES%) do (
    "%VENV_PY%" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('%%m') else 1)" >nul 2>&1 || set "MISSING=!MISSING! %%m"
)
exit /b 0

:ollama_up
"%VENV_PY%" -c "import urllib.request; urllib.request.urlopen('%OLLAMA_TAGS%', timeout=2)" >nul 2>&1
exit /b %errorlevel%

:start_ollama
rem  The tray app is what the installer sets up; `ollama serve` is the fallback
rem  for an install that only put the CLI on PATH.
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" (
    start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
) else (
    where ollama >nul 2>&1 || exit /b 1
    start "" /b ollama serve >nul 2>&1
)
echo Starting Ollama...
for /l %%i in (1, 1, 30) do (
    call :ollama_up
    if not errorlevel 1 exit /b 0
    timeout /t 1 /nobreak >nul
)
exit /b 1

:ask
rem  A gigabyte-scale download is the user's call, so ask - but the script is
rem  started by a double-click and may be left alone, and an unanswered question
rem  must not hold the window open forever. No answer means no.
choice /c yn /n /t 30 /d n /m "%~1 [y/N] "
if errorlevel 2 exit /b 1
exit /b 0

:tail
rem  The last lines of the log, which is where pip says what actually failed.
powershell -NoProfile -Command "Get-Content -LiteralPath '%~1' -Tail 20" 2>nul
exit /b 0

:fail
echo(
echo ✗ %~1
echo(
pause
exit /b 1
