#!/usr/bin/env bash
# One-command setup + start.
#   ./run.sh
# Creates a virtualenv, installs Python deps, downloads the Chromium that
# Playwright drives (first run only), then serves http://localhost:5000
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
command -v "$PY" >/dev/null || { echo "Python 3.10+ required"; exit 1; }

if [ ! -d .venv ]; then
  echo "→ creating virtualenv (.venv)"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ installing Python packages"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

if [ ! -f .venv/.browser-installed ]; then
  echo "→ downloading Chromium for Playwright (one-time, ~150MB)"
  python -m playwright install chromium
  touch .venv/.browser-installed
fi

[ -f .env ] || { cp .env.example .env; echo "→ created .env from .env.example"; }

echo
echo "  Lead Finder is starting → http://localhost:${PORT:-5000}"
echo "  (Ctrl-C to stop)"
echo
exec python app.py
