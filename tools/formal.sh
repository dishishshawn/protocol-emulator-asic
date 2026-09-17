#!/usr/bin/env bash
# Run the SymbiYosys tasks in formal/engine.sby with the pinned Yosys/sby/Yices
# from the local nix-portable store (the store tools/setup-physical.sh fills).
# Usage: tools/formal.sh [task ...]      default: bmc prove cover
#        FORMAL_SBY=other.sby FORMAL_OUT=dir tools/formal.sh bmc
# Work directories: build/formal/engine_<task>; log: build/formal/<task>.log
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
YOSYS_ENV=/nix/store/fiqpq74gj36lsgbxww1cqwsqyv2a6fnh-yosys-with-plugins-0.66-python3-3.13.13-env
YICES=/nix/store/3andv44wvvf7zmfrx2zwp7pnk86jbcfj-yices-2.7.0
SBY_FILE="${FORMAL_SBY:-$ROOT/formal/engine.sby}"
OUT="${FORMAL_OUT:-$ROOT/build/formal}"
mkdir -p "$OUT"
cd "$(dirname "$SBY_FILE")"
status=0
for task in ${*:-bmc prove cover}; do
  nix-portable nix shell --accept-flake-config "$YOSYS_ENV" "$YICES" --command bash -c "
    yosys -V; yices-smt2 --version | head -1; sby --help | head -1
    sby -f --prefix '$OUT/engine' '$(basename "$SBY_FILE")' $task
  " > "$OUT/$task.log" 2>&1 || status=$?
  grep -E "summary: (engine|  )|DONE" "$OUT/$task.log"
done
exit $status
