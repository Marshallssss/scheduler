@echo off
setlocal enabledelayedexpansion

cd /d %~dp0\..
set "PROJECT_DIR=%cd%"
set "WHEEL_DIR=%PROJECT_DIR%\_wheels"
set "REQ_FILE=%PROJECT_DIR%\scripts\windows_runtime_requirements.txt"
set "PIP_COMMON=--default-timeout 60 --retries 2"

echo [INFO] Project Dir: %PROJECT_DIR%
echo [INFO] Wheel Dir: %WHEEL_DIR%

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

echo [INFO] Upgrading pip...
%PY_CMD% -m pip install --upgrade pip %PIP_COMMON%
if errorlevel 1 (
  echo [WARN] pip upgrade failed, continue.
)

echo [INFO] Downloading build tools wheels...
%PY_CMD% -m pip download --dest "%WHEEL_DIR%" --only-binary=:all: pip setuptools wheel -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON%
if errorlevel 1 (
  echo [WARN] Mirror download failed, retrying default index...
  %PY_CMD% -m pip download --dest "%WHEEL_DIR%" --only-binary=:all: pip setuptools wheel %PIP_COMMON%
  if errorlevel 1 goto :fail
)

echo [INFO] Downloading runtime dependency wheels...
%PY_CMD% -m pip download --dest "%WHEEL_DIR%" --only-binary=:all: -r "%REQ_FILE%" -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON%
if errorlevel 1 (
  echo [WARN] Mirror download failed, retrying default index...
  %PY_CMD% -m pip download --dest "%WHEEL_DIR%" --only-binary=:all: -r "%REQ_FILE%" %PIP_COMMON%
  if errorlevel 1 goto :fail
)

echo [DONE] Wheelhouse prepared: %WHEEL_DIR%
echo [INFO] You can now run scripts\deploy_windows.bat or scripts\upgrade_windows.bat with fewer network failures.
pause
exit /b 0

:fail
echo [ERROR] Failed to prepare wheelhouse.
pause
exit /b 1
