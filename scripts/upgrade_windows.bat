@echo off
setlocal enabledelayedexpansion

cd /d %~dp0\..
set "PROJECT_DIR=%cd%"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

echo [INFO] Scheduler upgrade start
echo [INFO] Project Dir: %PROJECT_DIR%

where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] git not found in PATH.
  pause
  exit /b 1
)

for /f %%i in ('git status --porcelain') do (
  echo [ERROR] Working tree is not clean. Please commit/stash changes before upgrade.
  pause
  exit /b 1
)

for /f %%b in ('git rev-parse --abbrev-ref HEAD') do set "CURRENT_BRANCH=%%b"
if "%CURRENT_BRANCH%"=="" set "CURRENT_BRANCH=main"
if "%CURRENT_BRANCH%"=="HEAD" set "CURRENT_BRANCH=main"

echo [INFO] Pull latest code from origin/%CURRENT_BRANCH%
git fetch origin
if errorlevel 1 goto :fail
git pull --ff-only origin %CURRENT_BRANCH%
if errorlevel 1 goto :fail

if not exist "%PYTHON_EXE%" (
  echo [INFO] .venv not found, creating virtual environment...
  where py >nul 2>nul
  if %errorlevel%==0 (
    set "PY_CMD=py -3"
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo [ERROR] Neither "py" nor "python" found in PATH.
      pause
      exit /b 1
    )
    set "PY_CMD=python"
  )

  %PY_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 goto :fail
)

echo [INFO] Install latest package...
"%PYTHON_EXE%" -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout 30 --retries 1
if errorlevel 1 (
  echo [WARN] Mirror install failed, retrying with default index...
  "%PYTHON_EXE%" -m pip install -e .
  if errorlevel 1 goto :fail
)

if exist "%PROJECT_DIR%\.scheduler.toml" (
  echo [INFO] Apply DB migration via init...
  "%PYTHON_EXE%" -m scheduler.cli init >nul
) else (
  echo [INFO] Init scheduler...
  "%PYTHON_EXE%" -m scheduler.cli init
  if errorlevel 1 goto :fail
)

echo [DONE] Upgrade completed.
echo [INFO] Start web with:
echo        "%PYTHON_EXE%" -m scheduler.cli web --host=127.0.0.1 --port=8787
pause
exit /b 0

:fail
echo [ERROR] Upgrade failed. Please check logs above.
pause
exit /b 1
