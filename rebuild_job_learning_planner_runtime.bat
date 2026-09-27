@echo off
setlocal
cd /d "%~dp0"

echo.
echo Runtime Environment Rebuild
echo This replaces only the local .venv and reinstalls project dependencies.
echo It does not modify Job Learning Planner roles, jobs, knowledge, learning data, roadmaps, or audit history.
echo.
set /p JLP_CONFIRM=Type REBUILD to continue: 
if /I not "%JLP_CONFIRM%"=="REBUILD" (
    echo Runtime rebuild cancelled.
    goto finished
)

where python >nul 2>&1
if not errorlevel 1 (
    python runtime_bootstrap.py --rebuild
    goto finished
)

where py >nul 2>&1
if not errorlevel 1 (
    py -3 runtime_bootstrap.py --rebuild
    goto finished
)

echo.
echo Runtime rebuild could not start.
echo No Python command was available to check for Python 3.11 or newer.
echo Install a compatible Python, then run this file again.

:finished
if errorlevel 1 pause
endlocal
