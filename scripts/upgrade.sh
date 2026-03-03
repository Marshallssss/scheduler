#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$ROOT_DIR/.venv/bin/python"
CONFIG_FILE="$ROOT_DIR/.scheduler.toml"

echo "[INFO] Scheduler upgrade start"
echo "[INFO] Project: $ROOT_DIR"

cd "$ROOT_DIR"

if ! command -v git >/dev/null 2>&1; then
  echo "[ERROR] git not found in PATH"
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "[ERROR] Working tree is not clean. Please commit/stash changes before upgrade."
  exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ -z "$CURRENT_BRANCH" || "$CURRENT_BRANCH" == "HEAD" ]]; then
  CURRENT_BRANCH="main"
fi

echo "[INFO] Fetch latest code from origin/$CURRENT_BRANCH"
git fetch origin
git pull --ff-only origin "$CURRENT_BRANCH"

if [[ ! -x "$VENV_PY" ]]; then
  echo "[INFO] .venv not found, creating virtual environment"
  if command -v python3 >/dev/null 2>&1; then
    python3 -m venv "$ROOT_DIR/.venv"
  elif command -v python >/dev/null 2>&1; then
    python -m venv "$ROOT_DIR/.venv"
  else
    echo "[ERROR] python3/python not found in PATH"
    exit 1
  fi
fi

echo "[INFO] Install latest package"
"$VENV_PY" -m pip install -e .

echo "[INFO] Apply DB/config initialization step"
if [[ -f "$CONFIG_FILE" ]]; then
  "$VENV_PY" -m scheduler.cli init >/dev/null
else
  "$VENV_PY" -m scheduler.cli init
fi

echo "[DONE] Upgrade completed"
echo "[INFO] Start web with:"
echo "       $VENV_PY -m scheduler.cli web --host=127.0.0.1 --port=8787"
