#!/usr/bin/env bash
# Wrapper around Ghidra's analyzeHeadless for this project. Requires GHIDRA_HOME (default ~/.local/opt/ghidra_12.1.3_PUBLIC)
# and the AEON R2 extension installed in $GHIDRA_HOME/Ghidra/Extensions/AeonR2. Ghidra projects live in data/ (ignored).
#
#   tools/ghidra/run-headless.sh import-ram  <ram-image.bin>               # prefix+AP at 0x200000 -> data/ghidra-ram/ram
#   tools/ghidra/run-headless.sh import-ap   <ap-body.bin>                 # AP body at 0x203800 + seeding + full decompile
#   tools/ghidra/run-headless.sh assemble    <patch.s> <out.lst>           # AsmPatch2 against the RAM project
#   tools/ghidra/run-headless.sh script      <project-dir> <name> <program> <Script.java> [args...]
set -euo pipefail
GHIDRA_HOME="${GHIDRA_HOME:-$HOME/.local/opt/ghidra_12.1.3_PUBLIC}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
AH="$GHIDRA_HOME/support/analyzeHeadless"
LANG_ID="AEON:BE:32:R2"
[ -x "$AH" ] || { echo "analyzeHeadless not found under GHIDRA_HOME=$GHIDRA_HOME" >&2; exit 2; }
[ -d "$GHIDRA_HOME/Ghidra/Extensions/AeonR2" ] || { echo "AEON R2 extension not installed (see tools/ghidra/README.md)" >&2; exit 2; }
cmd="${1:-}"; shift || true
case "$cmd" in
  import-ram)
    img="$(realpath "$1")"; mkdir -p "$ROOT/data/ghidra-ram"
    "$AH" "$ROOT/data/ghidra-ram" ram -import "$img" -loader BinaryLoader -loader-baseAddr 0x200000 \
      -processor "$LANG_ID" -noanalysis -scriptPath "$HERE" -postScript SeedRange.java 0x200100-0x203800 ;;
  import-ap)
    ap="$(realpath "$1")"; mkdir -p "$ROOT/data/ghidra2"
    "$AH" "$ROOT/data/ghidra2" inst -import "$ap" -loader BinaryLoader -loader-baseAddr 0x203800 -processor "$LANG_ID" \
      -analysisTimeoutPerFile 3600 -max-cpu 6 -scriptPath "$HERE" -postScript SeedDisasm.java
    "$AH" "$ROOT/data/ghidra2" inst -process "$(basename "$ap")" -scriptPath "$HERE" -postScript SeedPointers.java -analysisTimeoutPerFile 3600
    "$AH" "$ROOT/data/ghidra2" inst -process "$(basename "$ap")" -noanalysis -scriptPath "$HERE" -postScript DecompAll.java "$ROOT/data/ghidra2/inst.c" ;;
  assemble)
    src="$(realpath "$1")"; out="$(realpath -m "$2")"; ram="${RAM_IMAGE:-$ROOT/data/vendor/ram-installed.bin}"
    [ -f "$ram" ] || { echo "RAM image $ram missing: build it from your own dump (docs/guides/assemble.md)" >&2; exit 2; }
    "$AH" "$ROOT/data/ghidra-ram" ram -process "$(basename "$ram")" -noanalysis -readOnly -scriptPath "$HERE" \
      -postScript AsmPatch2.java "$src" "$out" "$ram" > "$ROOT/out/assemble.log" 2>&1 || { tail -20 "$ROOT/out/assemble.log"; exit 1; }
    grep -q "AsmPatch2.java> wrote" "$ROOT/out/assemble.log" || { grep -A4 "Exception\|error:" "$ROOT/out/assemble.log" | head -30; exit 1; }
    echo "wrote $out" ;;
  script)
    proj="$1"; name="$2"; prog="$3"; script="$4"; shift 4
    "$AH" "$proj" "$name" -process "$prog" -noanalysis -readOnly -scriptPath "$HERE" -postScript "$script" "$@" ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
