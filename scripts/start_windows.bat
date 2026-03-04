@echo off
setlocal enabledelayedexpansion

cd /d %~dp0\..
set "PROJECT_DIR=%cd%"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "LOG_DIR=%USERPROFILE%\.project_scheduler\logs"
set "START_LOG=%LOG_DIR%\windows_start.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [INFO] Project Dir: %PROJECT_DIR%
echo [INFO] Log file: %START_LOG%
echo [INFO] === start at %date% %time% === > "%START_LOG%"

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Python virtual environment not found: %PYTHON_EXE%
  echo [HINT] Please run scripts\deploy_windows.bat first.
  pause
  exit /b 1
)

if not exist "%PROJECT_DIR%\.scheduler.toml" (
  echo [WARN] .scheduler.toml not found, running init...
  "%PYTHON_EXE%" -m scheduler.cli init >> "%START_LOG%" 2>&1
  if errorlevel 1 goto :fail
)

echo [INFO] Checking scheduler cli...
"%PYTHON_EXE%" -m scheduler.cli --help >nul 2>> "%START_LOG%"
if errorlevel 1 goto :fail

echo [INFO] Launching web server on http://127.0.0.1:8787 ...
start "Scheduler Web" cmd /k "\"%PYTHON_EXE%\" -m scheduler.cli web --host=127.0.0.1 --port=8787"
if errorlevel 1 goto :fail

echo [DONE] Start command submitted.
pause
exit /b 0

:fail
echo [ERROR] Start failed.
echo [ERROR] Please check: %START_LOG%
pause
exit /b 1
