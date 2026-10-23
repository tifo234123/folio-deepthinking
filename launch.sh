#!/usr/bin/env bash
set -euo pipefail
FOLIO_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ ! -x "$FOLIO_DIR/.venv/bin/python" ]; then
  printf '%s\n' 'Run ./install.sh once to install Folio dependencies.' >&2
  exit 1
fi
cd "$FOLIO_DIR"
export FOLIO_HOME="${FOLIO_HOME:-$FOLIO_DIR/data}"
exec "$FOLIO_DIR/.venv/bin/python" -m folio.desktop

