@echo off
setlocal enabledelayedexpansion

cd /d %~dp0\..
set "PROJECT_DIR=%cd%"
set "WHEEL_DIR=%PROJECT_DIR%\_wheels"
set "REQ_FILE=%PROJECT_DIR%\scripts\windows_runtime_requirements.txt"
set "PIP_COMMON=--default-timeout 60 --retries 2 --disable-pip-version-check --no-input"
set "FORCE_PIP_UPGRADE=0"
set "OFFLINE_ONLY=0"

if /I "%SCHEDULER_FORCE_PIP_TOOLS_UPGRADE%"=="1" set "FORCE_PIP_UPGRADE=1"
if /I "%SCHEDULER_OFFLINE_ONLY%"=="1" set "OFFLINE_ONLY=1"

echo [INFO] Project Dir: %PROJECT_DIR%
echo [INFO] Wheel Dir: %WHEEL_DIR%
if "%OFFLINE_ONLY%"=="1" echo [INFO] Offline-only mode enabled via SCHEDULER_OFFLINE_ONLY=1

if not exist "%REQ_FILE%" (
  echo [ERROR] Requirements file not found: %REQ_FILE%
  pause
  exit /b 1
)

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

if not exist "%WHEEL_DIR%" mkdir "%WHEEL_DIR%"

if "%FORCE_PIP_UPGRADE%"=="1" (
  echo [INFO] Upgrading pip because SCHEDULER_FORCE_PIP_TOOLS_UPGRADE=1...
  %PY_CMD% -m pip install --upgrade pip %PIP_COMMON%
  if errorlevel 1 (
    echo [WARN] pip upgrade failed or was cancelled, continue with current pip.
  )
) else (
  echo [INFO] Skipping pip upgrade (set SCHEDULER_FORCE_PIP_TOOLS_UPGRADE=1 to force).
)

echo [INFO] Checking build tools wheels from local wheelhouse first...
%PY_CMD% -m pip download --dest "%WHEEL_DIR%" --only-binary=:all: pip setuptools wheel --no-index --find-links="%WHEEL_DIR%" %PIP_COMMON%
if errorlevel 1 (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline-only mode: local wheelhouse does not satisfy build tools ^(pip/setuptools/wheel^).
    goto :fail
  )
  echo [WARN] Local wheelhouse missing some build tools, retrying mirror...
  %PY_CMD% -m pip download --dest "%WHEEL_DIR%" --only-binary=:all: pip setuptools wheel -i https://pypi.tuna.tsinghua.edu.cn/simple --find-links="%WHEEL_DIR%" %PIP_COMMON%
  if errorlevel 1 (
    echo [WARN] Mirror download failed, retrying default index...
    %PY_CMD% -m pip download --dest "%WHEEL_DIR%" --only-binary=:all: pip setuptools wheel --find-links="%WHEEL_DIR%" %PIP_COMMON%
    if errorlevel 1 goto :fail
  )
)

echo [INFO] Checking runtime dependency wheels from local wheelhouse first...
%PY_CMD% -m pip download --dest "%WHEEL_DIR%" --only-binary=:all: -r "%REQ_FILE%" --no-index --find-links="%WHEEL_DIR%" %PIP_COMMON%
if errorlevel 1 (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline-only mode: local wheelhouse does not satisfy runtime requirements.
    goto :fail
  )
  echo [WARN] Local wheelhouse missing some runtime wheels, retrying mirror...
  %PY_CMD% -m pip download --dest "%WHEEL_DIR%" --only-binary=:all: -r "%REQ_FILE%" -i https://pypi.tuna.tsinghua.edu.cn/simple --find-links="%WHEEL_DIR%" %PIP_COMMON%
  if errorlevel 1 (
    echo [WARN] Mirror download failed, retrying default index...
    %PY_CMD% -m pip download --dest "%WHEEL_DIR%" --only-binary=:all: -r "%REQ_FILE%" --find-links="%WHEEL_DIR%" %PIP_COMMON%
    if errorlevel 1 goto :fail
  )
)

echo [DONE] Wheelhouse prepared: %WHEEL_DIR%
echo [INFO] You can now run scripts\deploy_windows.bat or scripts\upgrade_windows.bat with fewer network failures.
pause
exit /b 0

:fail
echo [ERROR] Failed to prepare wheelhouse.
pause
exit /b 1
