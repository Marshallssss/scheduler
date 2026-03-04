@echo off
setlocal enabledelayedexpansion

cd /d %~dp0\..
set "PROJECT_DIR=%cd%"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PIP_COMMON=--default-timeout 60 --retries 2"
set "TEMP_EXTRACT_DIR="
set "SOURCE_DIR="
set "ZIP_PATH="
set "SOURCE_INPUT="

echo [INFO] Scheduler upgrade start
echo [INFO] Project Dir: %PROJECT_DIR%

if /I "%~1"=="--from-package" (
  set "SOURCE_INPUT=%~2"
  call :run_package_upgrade
  if errorlevel 1 goto :fail
  goto :post_upgrade
)

if not "%~1"=="" (
  set "SOURCE_INPUT=%~1"
  call :run_package_upgrade
  if errorlevel 1 goto :fail
  goto :post_upgrade
)

call :run_git_upgrade
if errorlevel 1 (
  echo [WARN] Git upgrade unavailable, fallback to package mode.
  set "SOURCE_INPUT="
  call :run_package_upgrade
  if errorlevel 1 goto :fail
)

goto :post_upgrade

:run_git_upgrade
where git >nul 2>nul
if errorlevel 1 (
  echo [WARN] git not found in PATH.
  exit /b 1
)

if not exist "%PROJECT_DIR%\.git" (
  echo [WARN] .git folder not found.
  exit /b 1
)

for /f %%i in ('git status --porcelain') do (
  echo [WARN] Working tree is not clean, skip git upgrade.
  exit /b 1
)

for /f %%b in ('git rev-parse --abbrev-ref HEAD') do set "CURRENT_BRANCH=%%b"
if "%CURRENT_BRANCH%"=="" set "CURRENT_BRANCH=main"
if "%CURRENT_BRANCH%"=="HEAD" set "CURRENT_BRANCH=main"

echo [INFO] Pull latest code from origin/%CURRENT_BRANCH%
git fetch origin
if errorlevel 1 exit /b 1
git pull --ff-only origin %CURRENT_BRANCH%
if errorlevel 1 exit /b 1

echo [INFO] Git code update completed.
exit /b 0

:run_package_upgrade
set "SOURCE_DIR="
set "ZIP_PATH="

if defined SOURCE_INPUT (
  call :resolve_source_input "%SOURCE_INPUT%"
  if errorlevel 1 exit /b 1
) else (
  call :find_latest_package_zip ZIP_PATH
  if defined ZIP_PATH (
    echo [INFO] Auto detected package zip: !ZIP_PATH!
  )
)

if not defined SOURCE_DIR if not defined ZIP_PATH (
  set /p "SOURCE_INPUT=[INPUT] Enter package zip path or extracted folder path: "
  if not defined SOURCE_INPUT (
    echo [ERROR] No package path provided.
    exit /b 1
  )
  echo [INFO] Package input: !SOURCE_INPUT!
  call :resolve_source_input "!SOURCE_INPUT!"
  if errorlevel 1 exit /b 1
)

if not defined SOURCE_DIR (
  call :extract_zip_to_temp "%ZIP_PATH%"
  if errorlevel 1 exit /b 1
  call :resolve_source_from_dir "%TEMP_EXTRACT_DIR%"
  if errorlevel 1 exit /b 1
)

if /I "%SOURCE_DIR%"=="%PROJECT_DIR%" (
  echo [INFO] Source directory equals project directory, skip file replace.
  exit /b 0
)

call :copy_package "%SOURCE_DIR%" "%PROJECT_DIR%"
if errorlevel 1 exit /b 1

if defined TEMP_EXTRACT_DIR (
  rmdir /s /q "%TEMP_EXTRACT_DIR%" >nul 2>nul
  set "TEMP_EXTRACT_DIR="
)

echo [INFO] Package file replacement completed.
exit /b 0

:resolve_source_input
set "CANDIDATE=%~1"
set "CANDIDATE=%CANDIDATE:"=%"
if exist "%CANDIDATE%\NUL" (
  call :resolve_source_from_dir "%CANDIDATE%"
  exit /b %errorlevel%
)
if exist "%CANDIDATE%" (
  set "ZIP_PATH=%CANDIDATE%"
  exit /b 0
)
echo [ERROR] Path not found: %CANDIDATE%
exit /b 1

:find_latest_package_zip
set "%~1="
for /f "delims=" %%f in ('dir /b /a:-d /o-d "%PROJECT_DIR%\_upgrade\*.zip" 2^>nul') do (
  set "%~1=%PROJECT_DIR%\_upgrade\%%f"
  goto :eof
)
for /f "delims=" %%f in ('dir /b /a:-d /o-d "%USERPROFILE%\Downloads\*scheduler*.zip" 2^>nul') do (
  set "%~1=%USERPROFILE%\Downloads\%%f"
  goto :eof
)
goto :eof

:extract_zip_to_temp
set "ZIP_TO_EXTRACT=%~1"
if not exist "%ZIP_TO_EXTRACT%" (
  echo [ERROR] Zip file not found: %ZIP_TO_EXTRACT%
  exit /b 1
)
set "TEMP_EXTRACT_DIR=%TEMP%\scheduler_upgrade_%RANDOM%%RANDOM%"
mkdir "%TEMP_EXTRACT_DIR%" >nul 2>nul
echo [INFO] Extracting package zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP_TO_EXTRACT%' -DestinationPath '%TEMP_EXTRACT_DIR%' -Force"
if errorlevel 1 (
  echo [ERROR] Failed to extract zip package.
  rmdir /s /q "%TEMP_EXTRACT_DIR%" >nul 2>nul
  set "TEMP_EXTRACT_DIR="
  exit /b 1
)
exit /b 0

:resolve_source_from_dir
set "CANDIDATE_DIR=%~1"
set "SOURCE_DIR="

if exist "%CANDIDATE_DIR%\pyproject.toml" (
  set "SOURCE_DIR=%CANDIDATE_DIR%"
)

if not defined SOURCE_DIR (
  for /f "delims=" %%d in ('dir /b /ad "%CANDIDATE_DIR%" 2^>nul') do (
    if exist "%CANDIDATE_DIR%\%%d\pyproject.toml" (
      set "SOURCE_DIR=%CANDIDATE_DIR%\%%d"
      goto :source_dir_found
    )
  )
)

if not defined SOURCE_DIR (
  for /f "delims=" %%p in ('dir /s /b /a:-d "%CANDIDATE_DIR%\pyproject.toml" 2^>nul') do (
    for %%q in ("%%p") do set "SOURCE_DIR=%%~dpq"
    goto :source_dir_found
  )
)

:source_dir_found
if not defined SOURCE_DIR (
  echo [ERROR] pyproject.toml not found in package path.
  exit /b 1
)
if not exist "%SOURCE_DIR%\scheduler\cli.py" (
  echo [ERROR] Invalid package: scheduler source not found.
  exit /b 1
)
exit /b 0

:copy_package
set "SRC=%~1"
set "DST=%~2"

echo [INFO] Replacing project files from:
echo        %SRC%
robocopy "%SRC%" "%DST%" /E /R:1 /W:1 /NFL /NDL /NP ^
  /XD ".git" ".venv" ".codex" ".pytest_cache" "__pycache__" "_upgrade" ^
  /XF ".scheduler.toml" ".DS_Store"
set "ROBOCODE=%errorlevel%"
if !ROBOCODE! GEQ 8 (
  echo [ERROR] File replacement failed with robocopy exit code !ROBOCODE!.
  exit /b 1
)
exit /b 0

:post_upgrade
if not exist "%PYTHON_EXE%" (
  echo [INFO] .venv not found, creating virtual environment...
  call :ensure_python_cmd
  if errorlevel 1 goto :fail
  %PY_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 goto :fail
)

echo [INFO] Install latest package...
echo [INFO] Upgrading pip/setuptools/wheel...
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel %PIP_COMMON%
if errorlevel 1 (
  echo [WARN] Packaging tools upgrade failed, continue with current versions.
)

echo [INFO] Install latest package (editable)...
"%PYTHON_EXE%" -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON%
if errorlevel 1 (
  echo [WARN] Editable install via mirror failed, retrying default index...
  "%PYTHON_EXE%" -m pip install -e . %PIP_COMMON%
)
if errorlevel 1 (
  echo [WARN] Editable install failed, fallback to non-editable install...
  "%PYTHON_EXE%" -m pip install . -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON%
)
if errorlevel 1 (
  echo [WARN] Non-editable install via mirror failed, retrying default index...
  "%PYTHON_EXE%" -m pip install . %PIP_COMMON%
)
if errorlevel 1 (
  goto :fail
)

echo [INFO] Apply DB migration via init...
"%PYTHON_EXE%" -m scheduler.cli init
if errorlevel 1 goto :fail

echo [DONE] Upgrade completed.
echo [INFO] Start web with:
echo        "%PYTHON_EXE%" -m scheduler.cli web --host=127.0.0.1 --port=8787
pause
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
if defined TEMP_EXTRACT_DIR (
  rmdir /s /q "%TEMP_EXTRACT_DIR%" >nul 2>nul
)
echo [ERROR] Upgrade failed. Please check logs above.
pause
exit /b 1
