@echo off
setlocal enabledelayedexpansion

cd /d %~dp0\..
set "PROJECT_DIR=%cd%"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "LOG_DIR=%USERPROFILE%\.project_scheduler\logs"
set "UPGRADE_LOG=%LOG_DIR%\windows_upgrade.log"
set "PIP_COMMON=--default-timeout 60 --retries 2"
set "TEMP_EXTRACT_DIR="
set "SOURCE_DIR="
set "ZIP_FILE="
set "PACKAGE_INPUT="

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [INFO] Scheduler upgrade start
echo [INFO] Project Dir: %PROJECT_DIR%
echo [INFO] Log file: %UPGRADE_LOG%
echo [INFO] === upgrade start %date% %time% === > "%UPGRADE_LOG%"

if /I "%~1"=="--from-package" (
  set "PACKAGE_INPUT=%~2"
) else (
  set "PACKAGE_INPUT=%~1"
)

if not defined PACKAGE_INPUT (
  for /f "delims=" %%f in ('dir /b /a:-d /o-d "%PROJECT_DIR%\_upgrade\*.zip" 2^>nul') do (
    if not defined PACKAGE_INPUT set "PACKAGE_INPUT=%PROJECT_DIR%\_upgrade\%%f"
  )
)

if not defined PACKAGE_INPUT (
  for /f "delims=" %%f in ('dir /b /a:-d /o-d "%USERPROFILE%\Downloads\*scheduler*.zip" 2^>nul') do (
    if not defined PACKAGE_INPUT set "PACKAGE_INPUT=%USERPROFILE%\Downloads\%%f"
  )
)

if not defined PACKAGE_INPUT (
  echo [INPUT] Example 1: D:\Downloads\scheduler-v0.2.0.zip
  echo [INPUT] Example 2: D:\Downloads\scheduler-v0.2.0
  set /p "PACKAGE_INPUT=[INPUT] Enter package zip path or extracted folder path: "
)

if not defined PACKAGE_INPUT (
  echo [ERROR] No package path provided.
  goto :fail
)

set "PACKAGE_INPUT=%PACKAGE_INPUT:"=%"

echo [INFO] Package input: %PACKAGE_INPUT%
echo [INFO] Package input: %PACKAGE_INPUT% >> "%UPGRADE_LOG%"

if exist "%PACKAGE_INPUT%\NUL" (
  set "SOURCE_DIR=%PACKAGE_INPUT%"
  call :find_source "!SOURCE_DIR!"
  if errorlevel 1 goto :fail
) else if exist "%PACKAGE_INPUT%" (
  set "ZIP_FILE=%PACKAGE_INPUT%"
  set "TEMP_EXTRACT_DIR=%TEMP%\scheduler_upgrade_%RANDOM%%RANDOM%"
  mkdir "!TEMP_EXTRACT_DIR!" >nul 2>nul
  echo [INFO] Extracting package zip...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '!ZIP_FILE!' -DestinationPath '!TEMP_EXTRACT_DIR!' -Force" >> "%UPGRADE_LOG%" 2>&1
  if errorlevel 1 (
    echo [ERROR] Failed to extract zip package.
    goto :fail
  )
  call :find_source "!TEMP_EXTRACT_DIR!"
  if errorlevel 1 goto :fail
) else (
  echo [ERROR] Path not found: %PACKAGE_INPUT%
  goto :fail
)

if /I "%SOURCE_DIR%"=="%PROJECT_DIR%" (
  echo [INFO] Source directory equals project directory, skip file replace.
) else (
  echo [INFO] Replacing project files from:
  echo        %SOURCE_DIR%
  robocopy "%SOURCE_DIR%" "%PROJECT_DIR%" /E /R:1 /W:1 /NFL /NDL /NP ^
    /XD ".git" ".venv" ".codex" ".pytest_cache" "__pycache__" "_upgrade" ^
    /XF ".scheduler.toml" ".DS_Store" >> "%UPGRADE_LOG%" 2>&1
  set "ROBOCODE=%errorlevel%"
  if !ROBOCODE! GEQ 8 (
    echo [ERROR] File replacement failed with robocopy exit code !ROBOCODE!.
    goto :fail
  )
)

if not exist "%PYTHON_EXE%" (
  echo [INFO] .venv not found, creating virtual environment...
  call :ensure_python_cmd
  if errorlevel 1 goto :fail
  !PY_CMD! -m venv "%VENV_DIR%" >> "%UPGRADE_LOG%" 2>&1
  if errorlevel 1 goto :fail
)

echo [INFO] Upgrading pip/setuptools/wheel...
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
if errorlevel 1 echo [WARN] Packaging tools upgrade failed, continue with current versions.

echo [INFO] Installing scheduler package (editable)...
"%PYTHON_EXE%" -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
if errorlevel 1 (
  echo [WARN] Editable install via mirror failed, retrying default index...
  "%PYTHON_EXE%" -m pip install -e . %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
)
if errorlevel 1 (
  echo [WARN] Editable install failed, fallback to non-editable install...
  "%PYTHON_EXE%" -m pip install . -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
)
if errorlevel 1 (
  echo [WARN] Non-editable install via mirror failed, retrying default index...
  "%PYTHON_EXE%" -m pip install . %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
)
if errorlevel 1 goto :fail

echo [INFO] Apply DB migration via init...
"%PYTHON_EXE%" -m scheduler.cli init >> "%UPGRADE_LOG%" 2>&1
if errorlevel 1 goto :fail

if defined TEMP_EXTRACT_DIR rmdir /s /q "%TEMP_EXTRACT_DIR%" >nul 2>nul

echo [DONE] Upgrade completed.
echo [INFO] Log file: %UPGRADE_LOG%
echo [INFO] Start web with:
echo        "%PYTHON_EXE%" -m scheduler.cli web --host=127.0.0.1 --port=8787
pause
exit /b 0

:find_source
set "CANDIDATE_DIR=%~1"
set "SOURCE_DIR="

if exist "%CANDIDATE_DIR%\pyproject.toml" set "SOURCE_DIR=%CANDIDATE_DIR%"

if not defined SOURCE_DIR (
  for /f "delims=" %%d in ('dir /b /ad "%CANDIDATE_DIR%" 2^>nul') do (
    if not defined SOURCE_DIR if exist "%CANDIDATE_DIR%\%%d\pyproject.toml" set "SOURCE_DIR=%CANDIDATE_DIR%\%%d"
  )
)

if not defined SOURCE_DIR (
  for /f "delims=" %%p in ('dir /s /b /a:-d "%CANDIDATE_DIR%\pyproject.toml" 2^>nul') do (
    if not defined SOURCE_DIR for %%q in ("%%p") do set "SOURCE_DIR=%%~dpq"
  )
)

if not defined SOURCE_DIR (
  echo [ERROR] pyproject.toml not found in package path.
  exit /b 1
)

if not exist "%SOURCE_DIR%\scheduler\cli.py" (
  echo [ERROR] Invalid package: scheduler source not found.
  exit /b 1
)

exit /b 0

:ensure_python_cmd
where py >nul 2>nul
if %errorlevel%==0 (
  set "PY_CMD=py -3"
  exit /b 0
)

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Neither "py" nor "python" found in PATH.
  exit /b 1
)

set "PY_CMD=python"
exit /b 0

:fail
if defined TEMP_EXTRACT_DIR rmdir /s /q "%TEMP_EXTRACT_DIR%" >nul 2>nul
echo [ERROR] Upgrade failed. Log file: %UPGRADE_LOG%
pause
exit /b 1
