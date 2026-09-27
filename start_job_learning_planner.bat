@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo Runtime Environment invalid: .venv\Scripts\python.exe could not be executed.
        echo Next step: run rebuild_job_learning_planner_runtime.bat.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" runtime_bootstrap.py
    goto finished
)

where python >nul 2>&1
if not errorlevel 1 (
    python runtime_bootstrap.py
    goto finished
)

where py >nul 2>&1
if not errorlevel 1 (
    py -3 runtime_bootstrap.py
    goto finished
)

echo.
echo Job Learning Planner could not start.
echo No Python command was available to check for Python 3.11 or newer.
echo Install a compatible Python, then double-click this file again.

:finished
if errorlevel 1 pause
endlocal
