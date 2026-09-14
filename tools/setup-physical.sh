#!/usr/bin/env bash
# One-time, user-level setup for the local CMOS5L physical flow (tools/harden.sh).
#
# Default: Docker mode, identical to the GitHub `gds` workflow. Needs a working
# `docker` for this user (apt install docker.io; usermod -aG docker $USER).
# `--rootless`: additionally installs nix-portable and the pinned EDA tools from
# the LibreLane flake for machines without Docker (harden.sh with NO_DOCKER=1).
#
# Pins (keep in sync with .github/workflows/gds.yaml and its action):
#   tt-support-tools  branch ihp-sg13cmos5l      (tt-gds-action@ihp-cmos5l default)
#   LibreLane         3.1.0.dev3                 (tt-gds-action@ihp-cmos5l default)
#   IHP-Open-PDK      2bbec755dc67ca3db0261c3d6163e15735d66710 (install_sg13cmos5l.sh)
#   nix-portable      v012 (rootless only)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TT_REF="${TT_REF:-ihp-sg13cmos5l}"
LIBRELANE_REF="${LIBRELANE_REF:-3.1.0.dev3}"
PDK_REV="${PDK_REV:-2bbec755dc67ca3db0261c3d6163e15735d66710}"
NP_VERSION="${NP_VERSION:-v012}"
ROOTLESS=""; [ "${1:-}" = "--rootless" ] && ROOTLESS=1

mkdir -p .tools .pdk "$HOME/.local/bin"

# 1. tt-support-tools, LibreLane (pip; runs the tools in Docker) and a Python 3.11
#    environment (tt requirements pin numpy<2, which needs <=3.12).
[ -d .tools/tt ] || git clone -q --depth 1 -b "$TT_REF" https://github.com/TinyTapeout/tt-support-tools.git .tools/tt
[ -e tt ] || ln -s .tools/tt tt
[ -x .tools/venv-tt/bin/python ] || uv venv -q --python 3.11 .tools/venv-tt
uv pip install -q --python .tools/venv-tt/bin/python -r .tools/tt/requirements.txt "librelane==${LIBRELANE_REF}"

# 2. IHP-Open-PDK at the action's pinned commit. ihp-sg13cmos5l symlinks into
#    ihp-sg13g2/libs.tech, so both trees are needed; SRAM/QA links stay unresolved.
P=.pdk/ihp-open-pdk
if [ ! -f "$P/ihp-sg13cmos5l/SOURCES" ]; then
  git init -q "$P"
  git -C "$P" remote add origin https://github.com/IHP-GmbH/IHP-Open-PDK.git
  git -C "$P" sparse-checkout set ihp-sg13cmos5l ihp-sg13g2/libs.tech
  git -C "$P" fetch -q --depth 1 --filter=blob:none origin "$PDK_REV"
  git -C "$P" checkout -q FETCH_HEAD
  echo "IHP-Open-PDK $PDK_REV" > "$P/ihp-sg13cmos5l/SOURCES"
fi

# 3. Docker: pull the LibreLane image the action uses (a few GB, once).
if [ -z "$ROOTLESS" ]; then
  docker pull "ghcr.io/librelane/librelane:${LIBRELANE_REF}"
fi

if [ -n "$ROOTLESS" ]; then
export NP_RUNTIME="${NP_RUNTIME:-bwrap}"
# R1. nix-portable: Nix without /nix, using bubblewrap user namespaces.
if ! command -v nix-portable >/dev/null; then
  curl -sL -o "$HOME/.local/bin/nix-portable" \
    "https://github.com/DavHau/nix-portable/releases/download/${NP_VERSION}/nix-portable-x86_64"
  chmod +x "$HOME/.local/bin/nix-portable"
fi
export PATH="$HOME/.local/bin:$PATH"
nix-portable nix --version >/dev/null   # first run unpacks the store

# R2. FOSSi binary cache, otherwise OpenROAD/OpenSTA/OR-Tools compile from source.
CONF="$HOME/.nix-portable/conf/nix.conf"
grep -q nix-cache.fossi-foundation.org "$CONF" 2>/dev/null || cat >> "$CONF" <<'CONF_EOF'
extra-substituters = https://nix-cache.fossi-foundation.org
extra-trusted-public-keys = nix-cache.fossi-foundation.org:3+K59iFwXqKsL7BNu6Guy0v+uTlwsxYQxjspXzqLYQs=
CONF_EOF

# R3. Pre-fetch the EDA binaries from the LibreLane flake.
FLAKE="github:librelane/librelane/${LIBRELANE_REF}"
LEGACY="${FLAKE}#legacyPackages.x86_64-linux"
nix-portable nix build --accept-flake-config --no-link \
  "${FLAKE}#openroad" "${FLAKE}#opensta" "${LEGACY}.yosys" "${LEGACY}.klayout" \
  "${LEGACY}.magic-vlsi" "${LEGACY}.netgen" "${LEGACY}.verilator" "${LEGACY}.stdenv.cc.cc.lib"

# R4. LibreLane itself on the flake's Python (the interpreter Yosys/OpenROAD embed)
#    with tkinter and the Nix KLayout module; pip's klayout wheel is removed so the
#    Nix one, matching the klayout binary, is used.
PY="$(nix-portable nix build --accept-flake-config --no-link --print-out-paths "path:$ROOT/tools/nix/ll-python")"
nix-portable nix shell --accept-flake-config "${LEGACY}.python3" --command bash -c "
  set -e
  rm -rf .tools/venv-ll
  '$PY/bin/python3' -m venv --system-site-packages .tools/venv-ll
  .tools/venv-ll/bin/pip install -q 'librelane==${LIBRELANE_REF}'
  .tools/venv-ll/bin/pip uninstall -q -y klayout
  .tools/venv-ll/bin/python -c 'import tkinter, pya, librelane; print(\"librelane\", librelane.__version__)'
"
fi

echo "setup complete; run tools/harden.sh"
