#!/usr/bin/env bash
# Run the full test suite the same way CI does.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(cd .. && pwd)"

# On Linux CI there is no display server; the offscreen platform plus the
# local shim libraries in tools/headless_libs replace the missing system libs.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
# Qt needs GL/EGL/xkb/dbus symbols even offscreen; CI provides stub libraries.
for candidate in "$ROOT/tools/headless_libs" "$ROOT/myai_studio/tools/headless_libs"; do
  if [[ "$(uname -s)" == "Linux" && -d "$candidate" ]]; then
    export LD_LIBRARY_PATH="$candidate:${LD_LIBRARY_PATH:-}"
    break
  fi
done
export MYAI_STUDIO_HOME="${MYAI_STUDIO_HOME:-$(mktemp -d)}"

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON=python3
fi
exec "$PYTHON" -m pytest "$@"
