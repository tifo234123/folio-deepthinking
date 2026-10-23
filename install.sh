#!/usr/bin/env bash
set -euo pipefail
FOLIO_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$FOLIO_DIR"
if command -v uv >/dev/null 2>&1; then
  uv venv --allow-existing "$FOLIO_DIR/.venv"
  uv pip install --python "$FOLIO_DIR/.venv/bin/python" -r "$FOLIO_DIR/requirements.lock" -e "$FOLIO_DIR"
else
  python3 -m venv "$FOLIO_DIR/.venv"
  "$FOLIO_DIR/.venv/bin/python" -m pip install -r "$FOLIO_DIR/requirements.lock" -e "$FOLIO_DIR"
fi
printf '%s\n' 'Folio is installed. Start it with ./launch.sh'
