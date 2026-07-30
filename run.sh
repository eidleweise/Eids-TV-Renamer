#!/usr/bin/env bash
set -euo pipefail

VENV_DIR=".venv"
PYTHON=${PYTHON:-python3}

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python not found. Please install Python 3.8+ or set PYTHON env var." >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment in $VENV_DIR..."
  "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# Install requirements if present (suppress output unless error)
if [ -f "requirements.txt" ]; then
  pip install --upgrade pip -q >/dev/null
  if ! pip install -r requirements.txt -q 2>&1 | grep -i "error"; then
    true  # requirements satisfied silently
  fi
fi

# Ensure package is installed (editable during development)
python -c "import importlib, sys
try:
    importlib.import_module('tvrenamer')
except Exception:
    sys.exit(2)
" || (
  echo "Installing package in editable mode..."
  pip install -e .
)

# Detect stale console entrypoint (generated before package rename) and reinstall if needed
if [ -f "$VENV_DIR/bin/tvrenamer" ]; then
  if grep -q "src.cli" "$VENV_DIR/bin/tvrenamer" 2>/dev/null; then
    echo "Detected stale entrypoint referencing 'src.cli' — force-reinstalling package"
    pip install --upgrade --force-reinstall -e .
  fi
fi

# Forward arguments to the CLI via the venv-installed script. If none provided, run in interactive mode.
TVRENAME_SCRIPT="$VENV_DIR/bin/tvrenamer"
if [ "$#" -eq 0 ]; then
  echo "Running tvrenamer in interactive mode. The wizard will ask for your media directory."
  if [ -x "$TVRENAME_SCRIPT" ]; then
    "$TVRENAME_SCRIPT" --interactive
  else
    tvrenamer --interactive
  fi
else
  if [ -x "$TVRENAME_SCRIPT" ]; then
    "$TVRENAME_SCRIPT" "$@"
  else
    tvrenamer "$@"
  fi
fi
