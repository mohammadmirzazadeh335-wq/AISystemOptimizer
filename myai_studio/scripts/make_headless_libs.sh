#!/usr/bin/env bash
# Build minimal stand-in libraries so Qt can run headless in CI containers.
#
# Qt links against libGL, libEGL, libxkbcommon and libdbus even when the
# "offscreen" platform is used. Those libraries are not installed here, so this
# script generates stubs that satisfy the dynamic linker:
#
#   1. collect every undefined symbol from the bundled Qt libraries/plugins,
#   2. bucket them by name prefix into the library that should provide them,
#   3. emit a tiny C file per bucket, compile it with a matching SONAME.
#
# Symbols are emitted unversioned (via a linker version script) because Qt
# references versioned symbols; an unversioned definition still resolves.
#
# Usage: scripts/make_headless_libs.sh [output-dir]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Keep the shims where run_tests.sh and capture_ui.sh look for them.
OUT="${1:-$ROOT/../tools/headless_libs}"
# The venv lives either inside the app folder or one level up at repo root.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in "$ROOT/.venv/bin/python" "$ROOT/../.venv/bin/python" "$(command -v python3)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
  done
fi

SITE="$("$PYTHON" -c 'import PySide6, pathlib; print(pathlib.Path(PySide6.__file__).parent)')"
QT_DIR="$SITE/Qt"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "[headless] collecting undefined symbols from $QT_DIR"
find "$QT_DIR/lib" "$QT_DIR/plugins" "$SITE" -maxdepth 3 -name '*.so*' -type f 2>/dev/null \
  | while read -r lib; do objdump -T "$lib" 2>/dev/null || true; done \
  | awk '$0 ~ /\*UND\*/ {print $NF}' | sed 's/@.*//' | sort -u > "$WORK/undefined.txt"

count=$(wc -l < "$WORK/undefined.txt")
echo "[headless] $count undefined symbols"

# Generate a C stub file for every undefined symbol matching a pattern.
gen_stub() {
  local name="$1" pattern="$2"
  local symbols="$WORK/$name.txt"
  grep -E "$pattern" "$WORK/undefined.txt" > "$symbols" || true
  local n
  n=$(wc -l < "$symbols")
  if [ "$n" -eq 0 ]; then
    echo "[headless] $name: no symbols"
    return 1
  fi
  {
    echo "/* generated: $n symbols */"
    while read -r sym; do
      case "$sym" in
        glX*|glGet*) printf 'void *%s(void) { return 0; }\n' "$sym" ;;
        *)           printf 'long %s(void) { return 0; }\n' "$sym" ;;
      esac
    done < "$symbols"
  } > "$WORK/$name.c"
  # Versioned consumers (Qt requests xkb@V_0.5.0 and dbus@LIBDBUS_1_3) fail a
  # glibc consistency assertion if the stub exports unversioned symbols only,
  # so the matching version node is declared where the caller expects one.
  case "$name" in
    xkb)  printf 'V_0.5.0 { global: *; };\n' > "$WORK/$name.map" ;;
    dbus) printf 'LIBDBUS_1_3 { global: *; };\n' > "$WORK/$name.map" ;;
    *)    printf '{ global: *; };\n' > "$WORK/$name.map" ;;
  esac
}

# Link one stub object under a specific SONAME. Each library is compiled
# separately: re-using a file with a different SONAME makes glibc's dynamic
# loader abort with a version-consistency assertion.
link_stub() {
  local name="$1" soname="$2"
  gcc -shared -fPIC -O1 -w \
      -Wl,-soname,"$soname" \
      -Wl,--version-script,"$WORK/$name.map" \
      -o "$OUT/$soname" "$WORK/$name.c"
  echo "[headless] $soname <- $(wc -l < "$WORK/$name.txt") symbols"
}

mkdir -p "$OUT"
rm -f "$OUT"/libGL.so.1 "$OUT"/libGLX.so.0 "$OUT"/libEGL.so.1 \
      "$OUT"/libxkbcommon.so.0 "$OUT"/libdbus-1.so.3

if gen_stub gl '^glX|^gl[A-Z]'; then
  link_stub gl libGL.so.1
  link_stub gl libGLX.so.0
fi
if gen_stub egl '^egl'; then link_stub egl libEGL.so.1; fi
if gen_stub xkb '^xkb_'; then link_stub xkb libxkbcommon.so.0; fi
if gen_stub dbus '^dbus_'; then link_stub dbus libdbus-1.so.3; fi

echo "[headless] done -> $OUT"
ls -1 "$OUT"
