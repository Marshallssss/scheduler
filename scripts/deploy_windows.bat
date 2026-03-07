@echo off
setlocal enabledelayedexpansion

cd /d %~dp0\..
set "PROJECT_DIR=%cd%"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "WHEEL_DIR=%PROJECT_DIR%\_wheels"
set "LOG_DIR=%USERPROFILE%\.project_scheduler\logs"
set "BOOT_LOG=%LOG_DIR%\windows_deploy.log"
set "PIP_COMMON=--default-timeout 60 --retries 2 --disable-pip-version-check --no-input"
set "PIP_INSTALL_FLAGS=--no-build-isolation"
set "USE_LOCAL_WHEELS=0"
set "VENV_CREATED=0"
set "OFFLINE_ONLY=0"

if /I "%SCHEDULER_OFFLINE_ONLY%"=="1" set "OFFLINE_ONLY=1"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [INFO] Project Dir: %PROJECT_DIR%
echo [INFO] Log file: %BOOT_LOG%
echo [INFO] === deploy start %date% %time% === > "%BOOT_LOG%"

if exist "%WHEEL_DIR%\NUL" (
  dir /b "%WHEEL_DIR%\*.whl" >nul 2>nul
  if not errorlevel 1 (
    set "USE_LOCAL_WHEELS=1"
    echo [INFO] Local wheelhouse detected: %WHEEL_DIR%
    echo [INFO] Local wheelhouse detected: %WHEEL_DIR% >> "%BOOT_LOG%"
  )
)

if "%OFFLINE_ONLY%"=="1" if "%USE_LOCAL_WHEELS%"=="0" (
  echo [ERROR] SCHEDULER_OFFLINE_ONLY=1 but no wheel files found in %WHEEL_DIR%.
  echo [ERROR] Run scripts\build_windows_wheels.bat first.
  goto :fail
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

if not exist "%PYTHON_EXE%" (
  echo [INFO] Creating virtual environment...
  %PY_CMD% -m venv "%VENV_DIR%" >> "%BOOT_LOG%" 2>&1
  if errorlevel 1 goto :fail
  set "VENV_CREATED=1"
)

if "%VENV_CREATED%"=="1" goto :upgrade_pip_tools
if /I "%SCHEDULER_FORCE_PIP_TOOLS_UPGRADE%"=="1" goto :upgrade_pip_tools
echo [INFO] Skipping pip/setuptools/wheel upgrade (set SCHEDULER_FORCE_PIP_TOOLS_UPGRADE=1 to force).
goto :after_pip_tools

:upgrade_pip_tools
echo [INFO] Upgrading pip/setuptools/wheel...
if "%USE_LOCAL_WHEELS%"=="1" (
  "%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel --no-index --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  if errorlevel 1 (
    if "%OFFLINE_ONLY%"=="1" (
      echo [ERROR] Offline pip tools upgrade failed. Refresh _wheels via scripts\build_windows_wheels.bat.
      goto :fail
    )
    echo [WARN] Local wheelhouse install for packaging tools failed, fallback online...
    "%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  )
) else (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline mode requires local wheelhouse.
    goto :fail
  )
  "%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
)
if errorlevel 1 (
  echo [WARN] Packaging tools upgrade failed, continue with current versions.
)
:after_pip_tools

echo [INFO] Verifying wheel package availability...
"%PYTHON_EXE%" -m pip show wheel >nul 2>> "%BOOT_LOG%"
if errorlevel 1 (
  echo [WARN] wheel not found in virtual environment, installing wheel...
  if "%USE_LOCAL_WHEELS%"=="1" (
    "%PYTHON_EXE%" -m pip install wheel --no-index --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  ) else (
    if "%OFFLINE_ONLY%"=="1" (
      echo [ERROR] Offline mode requires local wheelhouse to install wheel.
      goto :fail
    )
    "%PYTHON_EXE%" -m pip install wheel -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  )
  if errorlevel 1 (
    if "%OFFLINE_ONLY%"=="1" (
      echo [ERROR] Offline wheel installation failed. Refresh _wheels via scripts\build_windows_wheels.bat.
      goto :fail
    )
    echo [WARN] wheel install via mirror failed, retrying default index...
    if "%USE_LOCAL_WHEELS%"=="1" (
      "%PYTHON_EXE%" -m pip install wheel --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
    ) else (
      "%PYTHON_EXE%" -m pip install wheel %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
    )
  )
)
if errorlevel 1 echo [WARN] wheel installation check failed, installation may fail.

echo [INFO] Installing scheduler package (editable)...
if "%USE_LOCAL_WHEELS%"=="1" (
  "%PYTHON_EXE%" -m pip install -e . %PIP_INSTALL_FLAGS% --no-index --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
) else (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline mode requires local wheelhouse.
    goto :fail
  )
  "%PYTHON_EXE%" -m pip install -e . %PIP_INSTALL_FLAGS% -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
)
if errorlevel 1 (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline editable install failed. Refresh _wheels via scripts\build_windows_wheels.bat.
    goto :fail
  )
  if "%USE_LOCAL_WHEELS%"=="1" (
    echo [WARN] Offline editable install failed, retrying mirror...
    "%PYTHON_EXE%" -m pip install -e . %PIP_INSTALL_FLAGS% --find-links="%WHEEL_DIR%" -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  )
)
if errorlevel 1 (
  echo [WARN] Editable install failed, retrying default index...
  if "%USE_LOCAL_WHEELS%"=="1" (
    "%PYTHON_EXE%" -m pip install -e . %PIP_INSTALL_FLAGS% --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  ) else (
    "%PYTHON_EXE%" -m pip install -e . %PIP_INSTALL_FLAGS% %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  )
)
if errorlevel 1 (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline editable install failed. Refresh _wheels via scripts\build_windows_wheels.bat.
    goto :fail
  )
  echo [WARN] Editable install failed, fallback to non-editable install...
  if "%USE_LOCAL_WHEELS%"=="1" (
    "%PYTHON_EXE%" -m pip install . %PIP_INSTALL_FLAGS% --no-index --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  ) else (
    "%PYTHON_EXE%" -m pip install . %PIP_INSTALL_FLAGS% -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  )
)
if errorlevel 1 (
  if "%OFFLINE_ONLY%"=="1" (
    echo [ERROR] Offline non-editable install failed. Refresh _wheels via scripts\build_windows_wheels.bat.
    goto :fail
  )
  if "%USE_LOCAL_WHEELS%"=="1" (
    echo [WARN] Offline non-editable install failed, retrying mirror...
    "%PYTHON_EXE%" -m pip install . %PIP_INSTALL_FLAGS% --find-links="%WHEEL_DIR%" -i https://pypi.tuna.tsinghua.edu.cn/simple %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  )
)
if errorlevel 1 (
  echo [WARN] Non-editable install failed, retrying default index...
  if "%USE_LOCAL_WHEELS%"=="1" (
    "%PYTHON_EXE%" -m pip install . %PIP_INSTALL_FLAGS% --find-links="%WHEEL_DIR%" %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  ) else (
    "%PYTHON_EXE%" -m pip install . %PIP_INSTALL_FLAGS% %PIP_COMMON% >> "%BOOT_LOG%" 2>&1
  )
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

echo [INFO] Launching web server on http://0.0.0.0:8787 ...
start "Scheduler Web" "%PYTHON_EXE%" -m scheduler.cli web --host=0.0.0.0 --port=8787

echo [DONE] Deployment finished. Browser URL: http://0.0.0.0:8787
pause
exit /b 0

:fail
echo [ERROR] Deployment failed. Please check the error logs above.
echo [ERROR] Log file: %BOOT_LOG%
pause
exit /b 1
