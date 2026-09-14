#!/usr/bin/env bash
# Local Tiny Tapeout hardening for IHP CMOS5L, matching the GitHub `gds`
# workflow (tt-gds-action@ihp-cmos5l): tt-support-tools generates the LibreLane
# config from info.yaml, then `tt_tool.py --harden` runs LibreLane in its
# official Docker image, which carries the pinned OpenROAD/Yosys/Magic/KLayout/
# Netgen. See tools/setup-physical.sh for the one-time setup.
#
# NO_DOCKER=1 uses the rootless nix-portable toolchain instead (setup-physical.sh
# --rootless); results are identical, it is kept for machines without Docker.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIBRELANE_REF="${LIBRELANE_REF:-3.1.0.dev3}"
export PDK_ROOT="${PDK_ROOT:-$ROOT/.pdk/ihp-open-pdk}"
export PATH="$ROOT/.tools/venv-tt/bin:$PATH"

cd "$ROOT"
[ -e tt ] || ln -s .tools/tt tt
[ -f "$PDK_ROOT/ihp-sg13cmos5l/SOURCES" ] || { echo "PDK missing at $PDK_ROOT; run tools/setup-physical.sh" >&2; exit 1; }

python tt/tt_tool.py --create-user-config --ihp

# LibreLane 3.1.0.dev3 passes the literal string "None" to `openroad -threads`
# when OPENROAD_THREADS is unset (str(None) is truthy), which leaves OpenROAD
# single-threaded. Pin it to this machine's core count. src/user_config.json is
# regenerated above and ignored by git, so the upstream template stays untouched.
python - <<'PY'
import json, os
p = "src/user_config.json"
c = json.load(open(p)); c["OPENROAD_THREADS"] = os.cpu_count() or 1
json.dump(c, open(p, "w"), indent=2)
PY

if [ -n "${NO_DOCKER:-}" ]; then
  export NP_RUNTIME="${NP_RUNTIME:-bwrap}"
  export PATH="$ROOT/tools/shim:$PATH"
  FLAKE="github:librelane/librelane/${LIBRELANE_REF}"
  LEGACY="${FLAKE}#legacyPackages.x86_64-linux"
  # pip's compiled wheels in .tools/venv-ll need libstdc++; give the shim the flake's copy.
  LL_LIBSTDCXX="$(nix-portable nix build --accept-flake-config --no-link --print-out-paths "${LEGACY}.stdenv.cc.cc.lib")/lib"
  export LL_LIBSTDCXX
  nix-portable nix shell --accept-flake-config \
    "${FLAKE}#openroad" "${FLAKE}#opensta" "${LEGACY}.yosys" "${LEGACY}.klayout" \
    "${LEGACY}.magic-vlsi" "${LEGACY}.netgen" "${LEGACY}.verilator" "${LEGACY}.python3" \
    --command bash -c "export PATH='$ROOT/tools/shim:'\"\$PATH\"; cd '$ROOT' && python tt/tt_tool.py --harden --ihp --no-docker"
else
  # Same invocation as the GitHub action (python -m librelane --dockerized ...).
  python tt/tt_tool.py --harden --ihp
fi

python tt/tt_tool.py --print-stats --ihp || true
python tt/tt_tool.py --print-cell-category --ihp || true
