@echo off
setlocal enabledelayedexpansion

set "SCRIPT_PATH=%~f0"
call :normalize_path SCRIPT_DIR "%~dp0"

set "PROJECT_DIR="
set "UPGRADE_DIR="
set "CURRENT_PACKAGE_DIR="
set "LEGACY_UPGRADE_DIR="

set "VENV_DIR="
set "PYTHON_EXE="
set "WHEEL_DIR="
set "LOG_DIR="
set "UPGRADE_LOG="
set "PIP_COMMON=--default-timeout 60 --retries 2 --disable-pip-version-check --no-input"
set "PIP_INSTALL_FLAGS=--no-build-isolation"
set "TEMP_EXTRACT_DIR="
set "SOURCE_DIR="
set "ZIP_FILE="
set "PACKAGE_INPUT="
set "USE_LOCAL_WHEELS=0"
set "VENV_CREATED=0"
set "OFFLINE_ONLY=0"

call :resolve_project_dir
if errorlevel 1 goto :early_fail

call :resolve_upgrade_dir
if errorlevel 1 goto :early_fail

call :resolve_current_package_dir

cd /d "%PROJECT_DIR%"

set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "WHEEL_DIR=%PROJECT_DIR%\_wheels"
set "LOG_DIR=%USERPROFILE%\.project_scheduler\logs"
set "UPGRADE_LOG=%LOG_DIR%\windows_upgrade.log"

call :normalize_path LEGACY_UPGRADE_DIR "%PROJECT_DIR%\_upgrade"

if /I "%SCHEDULER_OFFLINE_ONLY%"=="1" set "OFFLINE_ONLY=1"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%UPGRADE_DIR%\NUL" mkdir "%UPGRADE_DIR%"

echo [INFO] Scheduler upgrade start
echo [INFO] Project Dir: %PROJECT_DIR%
echo [INFO] Upgrade Dir: %UPGRADE_DIR%
echo [INFO] Script Dir: %SCRIPT_DIR%
if defined CURRENT_PACKAGE_DIR echo [INFO] Detected extracted package: %CURRENT_PACKAGE_DIR%
echo [INFO] Log file: %UPGRADE_LOG%
echo [INFO] === upgrade start %date% %time% === > "%UPGRADE_LOG%"
echo [INFO] Project Dir: %PROJECT_DIR% >> "%UPGRADE_LOG%"
echo [INFO] Upgrade Dir: %UPGRADE_DIR% >> "%UPGRADE_LOG%"
echo [INFO] Script Dir: %SCRIPT_DIR% >> "%UPGRADE_LOG%"
if defined CURRENT_PACKAGE_DIR echo [INFO] Detected extracted package: %CURRENT_PACKAGE_DIR% >> "%UPGRADE_LOG%"

if not exist "%PROJECT_DIR%\.scheduler.toml" if not exist "%PROJECT_DIR%\.venv\NUL" (
  echo [ERROR] Current directory is not an existing installation path.
  echo [ERROR] Missing both .scheduler.toml and .venv under: %PROJECT_DIR%
  echo [ERROR] Put this script inside the old install directory or its upgrade folder, then run again.
  echo [ERROR] Current directory is not an existing installation path. >> "%UPGRADE_LOG%"
  echo [ERROR] Missing both .scheduler.toml and .venv under: %PROJECT_DIR% >> "%UPGRADE_LOG%"
  goto :fail
)

if exist "%WHEEL_DIR%\NUL" (
  dir /b "%WHEEL_DIR%\*.whl" >nul 2>nul
  if not errorlevel 1 (
    set "USE_LOCAL_WHEELS=1"
    echo [INFO] Local wheelhouse detected: %WHEEL_DIR%
    echo [INFO] Local wheelhouse detected: %WHEEL_DIR% >> "%UPGRADE_LOG%"
  )
)

if "%OFFLINE_ONLY%"=="1" if "%USE_LOCAL_WHEELS%"=="0" (
  echo [ERROR] SCHEDULER_OFFLINE_ONLY=1 but no wheel files found in %WHEEL_DIR%.
  echo [ERROR] Run scripts\build_windows_wheels.bat first.
  goto :fail
)

if /I "%~1"=="--from-package" (
  set "PACKAGE_INPUT=%~2"
) else (
  set "PACKAGE_INPUT=%~1"
)

if not defined PACKAGE_INPUT if defined CURRENT_PACKAGE_DIR (
  set "PACKAGE_INPUT=%CURRENT_PACKAGE_DIR%"
)

if not defined PACKAGE_INPUT (
  for /f "delims=" %%f in ('dir /b /a:-d /o-d "%UPGRADE_DIR%\*.zip" 2^>nul') do (
    if not defined PACKAGE_INPUT set "PACKAGE_INPUT=%UPGRADE_DIR%\%%f"
  )
)

if not defined PACKAGE_INPUT if exist "%LEGACY_UPGRADE_DIR%\NUL" (
  for /f "delims=" %%f in ('dir /b /a:-d /o-d "%LEGACY_UPGRADE_DIR%\*.zip" 2^>nul') do (
    if not defined PACKAGE_INPUT set "PACKAGE_INPUT=%LEGACY_UPGRADE_DIR%\%%f"
  )
)

if not defined PACKAGE_INPUT (
  for /f "delims=" %%f in ('dir /b /a:-d /o-d "%USERPROFILE%\Downloads\*scheduler*.zip" 2^>nul') do (
    if not defined PACKAGE_INPUT set "PACKAGE_INPUT=%USERPROFILE%\Downloads\%%f"
  )
)

if not defined PACKAGE_INPUT (
  echo [INPUT] Recommended directory: %UPGRADE_DIR%
  echo [INPUT] Example 1: %UPGRADE_DIR%\scheduler-main.zip
  echo [INPUT] Example 2: D:\Downloads\scheduler-main.zip
  echo [INPUT] Example 3: D:\Downloads\scheduler-main
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
  call :find_source "%PACKAGE_INPUT%"
  if errorlevel 1 (
    echo [ERROR] Valid scheduler source not found in folder: %PACKAGE_INPUT%
    echo [ERROR] Valid scheduler source not found in folder: %PACKAGE_INPUT% >> "%UPGRADE_LOG%"
    goto :fail
  )
) else if exist "%PACKAGE_INPUT%" (
  set "ZIP_FILE=%PACKAGE_INPUT%"
  set "TEMP_EXTRACT_DIR=%TEMP%\scheduler_upgrade_%RANDOM%%RANDOM%"
  mkdir "!TEMP_EXTRACT_DIR!" >nul 2>nul
  echo [INFO] Extracting package zip...
  echo [INFO] Extracting package zip... >> "%UPGRADE_LOG%"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '!ZIP_FILE!' -DestinationPath '!TEMP_EXTRACT_DIR!' -Force" >> "%UPGRADE_LOG%" 2>&1
  if errorlevel 1 (
    echo [ERROR] Failed to extract zip package.
    goto :fail
  )
  call :find_source "!TEMP_EXTRACT_DIR!"
  if errorlevel 1 (
    echo [ERROR] Valid scheduler source not found in zip: %ZIP_FILE%
    echo [ERROR] Valid scheduler source not found in zip: %ZIP_FILE% >> "%UPGRADE_LOG%"
    goto :fail
  )
) else (
  echo [ERROR] Path not found: %PACKAGE_INPUT%
  goto :fail
)

echo [INFO] Source Dir: %SOURCE_DIR%
echo [INFO] Source Dir: %SOURCE_DIR% >> "%UPGRADE_LOG%"

if /I "%SOURCE_DIR%"=="%PROJECT_DIR%" (
  echo [ERROR] Source directory equals project directory, no files to replace.
  echo [ERROR] Source directory equals project directory, no files to replace. >> "%UPGRADE_LOG%"
  echo [ERROR] Please place a newer zip under %UPGRADE_DIR% or run the script from an extracted new package.
  goto :fail
) else (
  echo [INFO] Replacing project files from:
  echo        %SOURCE_DIR%
  echo [INFO] Replacing project files from: %SOURCE_DIR% >> "%UPGRADE_LOG%"
  robocopy "%SOURCE_DIR%" "%PROJECT_DIR%" /E /R:1 /W:1 /NFL /NDL /NP ^
    /XD ".git" ".venv" ".codex" ".pytest_cache" "__pycache__" "_upgrade" "upgrade" ^
    /XF ".scheduler.toml" ".DS_Store" >> "%UPGRADE_LOG%" 2>&1
  set "ROBOCODE=%errorlevel%"
  if !ROBOCODE! GEQ 8 (
    echo [ERROR] File replacement failed with robocopy exit code !ROBOCODE!.
    goto :fail
  )
  call :verify_scripts_sync
  if errorlevel 1 goto :fail
)

if not exist "%PYTHON_EXE%" (
  echo [INFO] .venv not found, creating virtual environment...
  call :ensure_python_cmd
  if errorlevel 1 goto :fail
  !PY_CMD! -m venv "%VENV_DIR%" >> "%UPGRADE_LOG%" 2>&1
  if errorlevel 1 goto :fail
  set "VENV_CREATED=1"
)

call :repair_pip_if_missing_launcher
if errorlevel 1 goto :fail

if "%VENV_CREATED%"=="1" goto :upgrade_pip_tools
if /I "%SCHEDULER_FORCE_PIP_TOOLS_UPGRADE%"=="1" goto :upgrade_pip_tools
echo [INFO] Skipping pip/setuptools/wheel upgrade (set SCHEDULER_FORCE_PIP_TOOLS_UPGRADE=1 to force).
goto :after_pip_tools

:upgrade_pip_tools
echo [INFO] Upgrading pip/setuptools/wheel...
if "%USE_LOCAL_WHEELS%"=="1" (
  "%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel --no-index --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  if errorlevel 1 (
    if "%OFFLINE_ONLY%"=="1" (
      echo [ERROR] Offline pip tools upgrade failed. Refresh _wheels via scripts\build_windows_wheels.bat.
      goto :fail
    )
    echo [WARN] Local wheelhouse install for packaging tools failed, fallback online...
    "%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  )
) else (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline mode requires local wheelhouse.
    goto :fail
  )
  "%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
)
if errorlevel 1 echo [WARN] Packaging tools upgrade failed, continue with current versions.
:after_pip_tools

echo [INFO] Verifying wheel package availability...
"%PYTHON_EXE%" -m pip show wheel >nul 2>> "%UPGRADE_LOG%"
if errorlevel 1 (
  echo [WARN] wheel not found in virtual environment, installing wheel...
  if "%USE_LOCAL_WHEELS%"=="1" (
    "%PYTHON_EXE%" -m pip install wheel --no-index --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  ) else (
    if "%OFFLINE_ONLY%"=="1" (
      echo [ERROR] Offline mode requires local wheelhouse to install wheel.
      goto :fail
    )
    "%PYTHON_EXE%" -m pip install wheel -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  )
  if errorlevel 1 (
    if "%OFFLINE_ONLY%"=="1" (
      echo [ERROR] Offline wheel installation failed. Refresh _wheels via scripts\build_windows_wheels.bat.
      goto :fail
    )
    echo [WARN] wheel install via mirror failed, retrying default index...
    if "%USE_LOCAL_WHEELS%"=="1" (
      "%PYTHON_EXE%" -m pip install wheel --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
    ) else (
      "%PYTHON_EXE%" -m pip install wheel %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
    )
  )
)
if errorlevel 1 echo [WARN] wheel installation check failed, installation may fail.

echo [INFO] Installing scheduler package (editable)...
if "%USE_LOCAL_WHEELS%"=="1" (
  "%PYTHON_EXE%" -m pip install -e . %PIP_INSTALL_FLAGS% --no-index --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
) else (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline mode requires local wheelhouse.
    goto :fail
  )
  "%PYTHON_EXE%" -m pip install -e . %PIP_INSTALL_FLAGS% -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
)
if errorlevel 1 (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline editable install failed. Refresh _wheels via scripts\build_windows_wheels.bat.
    goto :fail
  )
  if "%USE_LOCAL_WHEELS%"=="1" (
    echo [WARN] Offline editable install failed, retrying mirror...
    "%PYTHON_EXE%" -m pip install -e . %PIP_INSTALL_FLAGS% --find-links="%WHEEL_DIR%" -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  )
)
if errorlevel 1 (
  echo [WARN] Editable install failed, retrying default index...
  if "%USE_LOCAL_WHEELS%"=="1" (
    "%PYTHON_EXE%" -m pip install -e . %PIP_INSTALL_FLAGS% --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  ) else (
    "%PYTHON_EXE%" -m pip install -e . %PIP_INSTALL_FLAGS% %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  )
)
if errorlevel 1 (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline editable install failed. Refresh _wheels via scripts\build_windows_wheels.bat.
    goto :fail
  )
  echo [WARN] Editable install failed, fallback to non-editable install...
  if "%USE_LOCAL_WHEELS%"=="1" (
    "%PYTHON_EXE%" -m pip install . %PIP_INSTALL_FLAGS% --no-index --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  ) else (
    "%PYTHON_EXE%" -m pip install . %PIP_INSTALL_FLAGS% -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  )
)
if errorlevel 1 (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline non-editable install failed. Refresh _wheels via scripts\build_windows_wheels.bat.
    goto :fail
  )
  if "%USE_LOCAL_WHEELS%"=="1" (
    echo [WARN] Offline non-editable install failed, retrying mirror...
    "%PYTHON_EXE%" -m pip install . %PIP_INSTALL_FLAGS% --find-links="%WHEEL_DIR%" -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  )
)
if errorlevel 1 (
  echo [WARN] Non-editable install failed, retrying default index...
  if "%USE_LOCAL_WHEELS%"=="1" (
    "%PYTHON_EXE%" -m pip install . %PIP_INSTALL_FLAGS% --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  ) else (
    "%PYTHON_EXE%" -m pip install . %PIP_INSTALL_FLAGS% %PIP_COMMON% >> "%UPGRADE_LOG%" 2>&1
  )
)
if errorlevel 1 goto :fail

echo [INFO] Apply DB migration via init...
"%PYTHON_EXE%" -m scheduler.cli init >> "%UPGRADE_LOG%" 2>&1
if errorlevel 1 goto :fail

if defined TEMP_EXTRACT_DIR rmdir /s /q "%TEMP_EXTRACT_DIR%" >nul 2>nul

echo [DONE] Upgrade completed.
echo [INFO] Log file: %UPGRADE_LOG%
echo [INFO] Continue using the old install directory.
echo [INFO] Daily start script:
echo        %PROJECT_DIR%\scripts\start_windows.bat
pause
exit /b 0

:normalize_path
set "%~1="
for %%i in ("%~2\.") do set "%~1=%%~fi"
exit /b 0

:resolve_project_dir
set "SEARCH_DIR=%SCRIPT_DIR%"
for %%L in (1 2 3 4 5 6 7 8) do (
  if exist "!SEARCH_DIR!\.scheduler.toml" (
    set "PROJECT_DIR=!SEARCH_DIR!"
    exit /b 0
  )
  if exist "!SEARCH_DIR!\.venv\NUL" (
    set "PROJECT_DIR=!SEARCH_DIR!"
    exit /b 0
  )
  call :parent_dir "!SEARCH_DIR!" PARENT_DIR
  if /I "!PARENT_DIR!"=="!SEARCH_DIR!" goto :resolve_project_dir_fail
  set "SEARCH_DIR=!PARENT_DIR!"
)

:resolve_project_dir_fail
echo [ERROR] Could not locate the old installation directory from:
echo         %SCRIPT_DIR%
echo [ERROR] Expected to find .scheduler.toml or .venv in an ancestor directory.
exit /b 1

:resolve_upgrade_dir
set "SEARCH_DIR=%SCRIPT_DIR%"
for %%L in (1 2 3 4 5 6 7 8) do (
  for %%n in ("!SEARCH_DIR!") do set "DIR_NAME=%%~nxn"
  if /I "!DIR_NAME!"=="upgrade" (
    set "UPGRADE_DIR=!SEARCH_DIR!"
    exit /b 0
  )
  if /I "!DIR_NAME!"=="_upgrade" (
    set "UPGRADE_DIR=!SEARCH_DIR!"
    exit /b 0
  )
  if /I "!SEARCH_DIR!"=="%PROJECT_DIR%" goto :resolve_upgrade_dir_default
  call :parent_dir "!SEARCH_DIR!" PARENT_DIR
  if /I "!PARENT_DIR!"=="!SEARCH_DIR!" goto :resolve_upgrade_dir_default
  set "SEARCH_DIR=!PARENT_DIR!"
)

:resolve_upgrade_dir_default
call :normalize_path UPGRADE_DIR "%PROJECT_DIR%\upgrade"
exit /b 0

:resolve_current_package_dir
set "CURRENT_PACKAGE_DIR="
set "SEARCH_DIR=%SCRIPT_DIR%"
for %%L in (1 2 3 4 5 6 7 8) do (
  if exist "!SEARCH_DIR!\pyproject.toml" if exist "!SEARCH_DIR!\scheduler\cli.py" if exist "!SEARCH_DIR!\scripts\upgrade_windows.bat" (
    if /I not "!SEARCH_DIR!"=="%PROJECT_DIR%" (
      set "CURRENT_PACKAGE_DIR=!SEARCH_DIR!"
      exit /b 0
    )
  )
  if /I "!SEARCH_DIR!"=="%PROJECT_DIR%" exit /b 0
  call :parent_dir "!SEARCH_DIR!" PARENT_DIR
  if /I "!PARENT_DIR!"=="!SEARCH_DIR!" exit /b 0
  set "SEARCH_DIR=!PARENT_DIR!"
)
exit /b 0

:parent_dir
for %%p in ("%~1\..") do set "%~2=%%~fp"
call :normalize_path %~2 "%%%~2%%"
exit /b 0

:find_source
set "CANDIDATE_DIR=%~1"
set "SOURCE_DIR="
call :normalize_path CANDIDATE_DIR "%CANDIDATE_DIR%"

if exist "%CANDIDATE_DIR%\pyproject.toml" set "SOURCE_DIR=%CANDIDATE_DIR%"

if not defined SOURCE_DIR (
  for /f "delims=" %%d in ('dir /b /ad "%CANDIDATE_DIR%" 2^>nul') do (
    if not defined SOURCE_DIR if exist "%CANDIDATE_DIR%\%%d\pyproject.toml" call :normalize_path SOURCE_DIR "%CANDIDATE_DIR%\%%d"
  )
)

if not defined SOURCE_DIR (
  for /f "delims=" %%p in ('dir /s /b /a:-d "%CANDIDATE_DIR%\pyproject.toml" 2^>nul') do (
    if not defined SOURCE_DIR for %%q in ("%%p") do call :normalize_path SOURCE_DIR "%%~dpq"
  )
)

if not defined SOURCE_DIR exit /b 1

if not exist "%SOURCE_DIR%\scheduler\cli.py" (
  set "SOURCE_DIR="
  exit /b 1
)

if not exist "%SOURCE_DIR%\scripts\NUL" (
  set "SOURCE_DIR="
  exit /b 1
)

if not exist "%SOURCE_DIR%\scripts\upgrade_windows.bat" (
  set "SOURCE_DIR="
  exit /b 1
)

exit /b 0

:verify_scripts_sync
if not exist "%SOURCE_DIR%\scripts\NUL" exit /b 0

if not exist "%PROJECT_DIR%\scripts\NUL" (
  echo [ERROR] scripts directory missing after file replacement.
  echo [ERROR] scripts directory missing after file replacement. >> "%UPGRADE_LOG%"
  exit /b 1
)

set "VERIFY_MISSING=0"
for /f "delims=" %%f in ('dir /b /s /a:-d "%SOURCE_DIR%\scripts" 2^>nul') do (
  set "SRC_FILE=%%f"
  set "REL_PATH=!SRC_FILE:%SOURCE_DIR%\scripts\=!"
  if not exist "%PROJECT_DIR%\scripts\!REL_PATH!" (
    echo [ERROR] Missing upgraded script file: scripts\!REL_PATH!
    echo [ERROR] Missing upgraded script file: scripts\!REL_PATH! >> "%UPGRADE_LOG%"
    set "VERIFY_MISSING=1"
  )
)

if "!VERIFY_MISSING!"=="1" (
  echo [ERROR] scripts directory sync verification failed.
  echo [ERROR] scripts directory sync verification failed. >> "%UPGRADE_LOG%"
  exit /b 1
)

echo [INFO] scripts directory sync verified.
echo [INFO] scripts directory sync verified. >> "%UPGRADE_LOG%"
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

:repair_pip_if_missing_launcher
"%PYTHON_EXE%" -c "import pathlib,pip; p=pathlib.Path(pip.__file__).resolve().parent/'_vendor'/'distlib'/'t64.exe'; raise SystemExit(0 if p.exists() else 1)" >nul 2>> "%UPGRADE_LOG%"
if not errorlevel 1 exit /b 0

echo [WARN] pip launcher resource missing (t64.exe), trying ensurepip repair...
echo [WARN] pip launcher resource missing (t64.exe), trying ensurepip repair... >> "%UPGRADE_LOG%"
"%PYTHON_EXE%" -m ensurepip --upgrade >> "%UPGRADE_LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] ensurepip repair failed.
  exit /b 1
)

"%PYTHON_EXE%" -c "import pathlib,pip; p=pathlib.Path(pip.__file__).resolve().parent/'_vendor'/'distlib'/'t64.exe'; raise SystemExit(0 if p.exists() else 1)" >nul 2>> "%UPGRADE_LOG%"
if errorlevel 1 (
  echo [ERROR] pip repair failed: still missing pip._vendor.distlib\t64.exe.
  exit /b 1
)

echo [INFO] pip launcher resource repaired.
echo [INFO] pip launcher resource repaired. >> "%UPGRADE_LOG%"
exit /b 0

:early_fail
echo [ERROR] Upgrade bootstrap failed.
pause
exit /b 1

:fail
if defined TEMP_EXTRACT_DIR rmdir /s /q "%TEMP_EXTRACT_DIR%" >nul 2>nul
echo [ERROR] Upgrade failed. Log file: %UPGRADE_LOG%
pause
exit /b 1
