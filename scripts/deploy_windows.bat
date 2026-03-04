@echo off
setlocal enabledelayedexpansion

cd /d %~dp0\..
set "PROJECT_DIR=%cd%"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "LOG_DIR=%USERPROFILE%\.project_scheduler\logs"
set "BOOT_LOG=%LOG_DIR%\windows_deploy.log"
set "PIP_COMMON=--default-timeout 60 --retries 2"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [INFO] Project Dir: %PROJECT_DIR%
echo [INFO] Log file: %BOOT_LOG%
echo [INFO] === deploy start %date% %time% === > "%BOOT_LOG%"

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
  %PY_CMD% -m venv "%VENV_DIR%" >> "%BOOT_LOG%" 2>&1
  if errorlevel 1 goto :fail
)

echo [INFO] Upgrading pip/setuptools/wheel...
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
if errorlevel 1 (
  echo [WARN] Packaging tools upgrade failed, continue with current versions.
)

echo [INFO] Installing scheduler package (editable)...
"%PYTHON_EXE%" -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
if errorlevel 1 (
  echo [WARN] Editable install via mirror failed, retrying default index...
  "%PYTHON_EXE%" -m pip install -e . %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
)
if errorlevel 1 (
  echo [WARN] Editable install failed, fallback to non-editable install...
  "%PYTHON_EXE%" -m pip install . -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
)
if errorlevel 1 (
  echo [WARN] Non-editable install via mirror failed, retrying default index...
  "%PYTHON_EXE%" -m pip install . %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
)
if errorlevel 1 (
  goto :fail
)

if not exist "%PROJECT_DIR%\.scheduler.toml" (
  echo [INFO] Initializing scheduler config and database...
  "%PYTHON_EXE%" -m scheduler.cli init >> "%BOOT_LOG%" 2>&1
  if errorlevel 1 goto :fail
) else (
  echo [INFO] Existing .scheduler.toml found, skipping init.
)

echo [INFO] Checking scheduler cli...
"%PYTHON_EXE%" -m scheduler.cli --help >nul 2>> "%BOOT_LOG%"
if errorlevel 1 goto :fail

echo [INFO] Launching web server on http://127.0.0.1:8787 ...
start "Scheduler Web" cmd /k "\"%PYTHON_EXE%\" -m scheduler.cli web --host=127.0.0.1 --port=8787"

echo [DONE] Deployment finished. Browser URL: http://127.0.0.1:8787
pause
exit /b 0

:fail
echo [ERROR] Deployment failed. Please check the error logs above.
echo [ERROR] Log file: %BOOT_LOG%
pause
exit /b 1
