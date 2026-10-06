@echo off
title TestHub Automation Studio (dev, unprotected)
cd /d "%~dp0"

:: This is the FAST, UNPROTECTED path: it runs app.py straight from source in a
:: local venv. No Nuitka, no C compiler, no Node — just Python 3 on PATH. Use it
:: for your own review while the protected build's Windows toolchain gets set
:: up (see scripts\build-client-version.bat at the repo root for that path).
:: Never send this folder as-is to an external client: the source is fully
:: readable. The protected zip from build-client-version.bat is what ships.

if not exist ".venv-dev\Scripts\python.exe" (
    echo First-time setup - preparing TestHub Automation Studio, this takes about a minute...
    py -3 -m venv .venv-dev 2>nul || python -m venv .venv-dev
    ".venv-dev\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv-dev\Scripts\python.exe" -m pip install --quiet flask openpyxl pyyaml
)

".venv-dev\Scripts\python.exe" app.py
if errorlevel 1 pause
