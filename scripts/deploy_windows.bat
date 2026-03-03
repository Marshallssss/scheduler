@echo off
setlocal enabledelayedexpansion

cd /d %~dp0\..
set "PROJECT_DIR=%cd%"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

echo [INFO] Project Dir: %PROJECT_DIR%

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY_CMD=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Neither "py" nor "python" was found in PATH.
    echo [HINT] Please install Python 3.9+ first.
    pause
    exit /b 1
  )
  set "PY_CMD=python"
)

if not exist "%PYTHON_EXE%" (
  echo [INFO] Creating virtual environment...
  %PY_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 goto :fail
)

echo [INFO] Installing scheduler package...
"%PYTHON_EXE%" -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout 30 --retries 1
if errorlevel 1 (
  echo [WARN] Mirror install failed, retrying with default index...
  "%PYTHON_EXE%" -m pip install -e .
  if errorlevel 1 goto :fail
)

if not exist "%PROJECT_DIR%\.scheduler.toml" (
  echo [INFO] Initializing scheduler config and database...
  "%PYTHON_EXE%" -m scheduler.cli init
  if errorlevel 1 goto :fail
) else (
  echo [INFO] Existing .scheduler.toml found, skipping init.
)

echo [INFO] Launching web server on http://127.0.0.1:8787 ...
start "Scheduler Web" "%PYTHON_EXE%" -m scheduler.cli web --host=127.0.0.1 --port=8787

echo [DONE] Deployment finished. Browser URL: http://127.0.0.1:8787
pause
exit /b 0

:fail
echo [ERROR] Deployment failed. Please check the error logs above.
pause
exit /b 1
