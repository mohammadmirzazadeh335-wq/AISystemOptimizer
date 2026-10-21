@echo off
REM ---------------------------------------------------------------------------
REM  MyAI Studio Ultimate - one-click launcher for Windows 11
REM  Creates the virtual environment on first use, installs requirements, runs.
REM ---------------------------------------------------------------------------
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PYTHON="
for %%P in (py.exe python.exe) do (
    if not defined PYTHON (
        where %%P >nul 2>nul && set "PYTHON=%%P"
    )
)
if not defined PYTHON (
    echo [ERROR] Python was not found on PATH.
    echo Install Python 3.10-3.13 from https://www.python.org/downloads/windows/
    echo and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
    echo [2/3] Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. Check your internet connection.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment found.
)

echo [3/3] Starting MyAI Studio Ultimate...
".venv\Scripts\python.exe" -m myai %*
if errorlevel 1 (
    echo.
    echo [ERROR] The application exited with an error.
    echo See: %APPDATA%\MyAIStudio\logs\myai_studio.jsonl
    pause
)
endlocal
