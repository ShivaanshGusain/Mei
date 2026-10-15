@echo off
REM Double-click friendly wrapper for run_and_watch.ps1 — bypasses PowerShell's
REM default execution-policy restriction just for this one script, no
REM permanent system change.
REM
REM Usage: run_and_watch.bat [headless|tui] [StallSeconds]
REM   run_and_watch.bat            -> headless, 60s stall threshold
REM   run_and_watch.bat tui        -> TUI mode
REM   run_and_watch.bat tui 90     -> TUI mode, 90s stall threshold

set MODE=%1
set STALL=%2
if "%MODE%"=="" set MODE=headless
if "%STALL%"=="" set STALL=60

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_and_watch.ps1" -Mode %MODE% -StallSeconds %STALL%
