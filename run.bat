@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
set "VENV_DIR=.venv"

where python >nul 2>&1 || (
  echo Python not found. Please install Python 3.8+ and ensure it's on PATH.
  exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Creating virtual environment in %VENV_DIR%...
  python -m venv "%VENV_DIR%"
)

call "%VENV_DIR%\Scripts\activate.bat"

if exist requirements.txt (
  echo Installing requirements from requirements.txt...
  pip install --upgrade pip >nul
  pip install -r requirements.txt
)

python -c "import importlib,sys
try:
    importlib.import_module('tvrenamer')
except Exception:
    sys.exit(2)
" 2>nul || (
  echo Installing package in editable mode...
  pip install -e .
)

:: Detect stale entrypoint referencing src.cli and reinstall if necessary
if exist "%VENV_DIR%\Scripts\tvrenamer-script.py" (
  findstr /C:"src.cli" "%VENV_DIR%\Scripts\tvrenamer-script.py" >nul 2>nul && (
    echo Detected stale entrypoint referencing 'src.cli' — force-reinstalling package
    pip install --upgrade --force-reinstall -e .
  )
)

if "%*"=="" (
  echo Running tvrenamer in interactive mode. The wizard will ask for your media directory.
  if exist "%VENV_DIR%\Scripts\tvrenamer.exe" (
    "%VENV_DIR%\Scripts\tvrenamer.exe" --interactive
  ) else (
    tvrenamer --interactive
  )
) else (
  if exist "%VENV_DIR%\Scripts\tvrenamer.exe" (
    "%VENV_DIR%\Scripts\tvrenamer.exe" %*
  ) else (
    tvrenamer %*
  )
)
