#!/usr/bin/env bash
# Start the Feral Media Library (macOS/Linux) — double-click friendly like
# ComfyUI portable: creates the Python environment on first start, keeps it
# current when the pinned dependencies change, and opens the browser.
#
#   ./start.sh                        → config.toml, server on port 8765
#                                       (or [web] port from the config)
#   ./start.sh --config archive.toml  → second instance: own config with
#                                       its own DB + its own port
#                                       (see docs/instanzen.md)
#   ./start.sh --port 9000            → all arguments go to "python -m feral.web"
#
# The server opens the browser itself (--browser) once the port is actually
# accepted — it knows the effective port from the full precedence chain
# (--port > $PORT > config > 8765), this script does not need to compute it.
# The DB path comes from the config ([database] path, default ./feral.sqlite)
# — hence NO forced --db here.
set -euo pipefail
cd "$(dirname "$0")"

# -- Find Python (3.12+) --------------------------------------------------------
PY=""
for cand in python3.13 python3.12 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
      PY="$cand"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "ERROR: Python 3.12+ not found. Please install it from https://www.python.org." >&2
  exit 1
fi

# -- Create / update the environment --------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
  echo "First start: creating the Python environment (.venv) ..."
  "$PY" -m venv .venv
fi

# Only reinstall when the pinned dependencies have changed.
STAMP=".venv/.deps-stamp"
if [ ! -f "$STAMP" ] || ! cmp -s requirements.txt "$STAMP"; then
  echo "Installing/updating dependencies ..."
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
  .venv/bin/pip install --quiet -e .
  cp requirements.txt "$STAMP"
fi

# -- Start the server (opens the browser itself, see header comment) -------------
exec .venv/bin/python -m feral.web --browser "$@"
