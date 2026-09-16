# First complete CMOS5L physical build

## Status
Done

## Requested outcome
Resolve the tile-allocation gap, establish a reproducible local place-and-route build at 10 MHz, and record real area, timing, DRC and LVS results so memory and feature decisions can be made from layout evidence.

## Constraints and acceptance criteria
- The build must reproduce what the official `gds` GitHub workflow does (tt-gds-action `ihp-cmos5l`, tt-support-tools `ihp-sg13cmos5l`, LibreLane 3.1.0.dev3, IHP-Open-PDK `2bbec755`).
- No root, no Docker: all tools installed user-level.
- Results recorded in `reports/` with tool and PDK versions.

## Evidence gathered
- Competition page (checked 2026-09-14) says: "Set the tile size in info.yaml to 6x4. The current maximum area is 6x4 tiles per design. We are working on the possibility of scaling up to 8x4 tiles." The earlier 8×4 assumption in this repository was wrong; 8×4 is not offered yet.
- tt-support-tools `ihp-sg13cmos5l` @ `da63c99` has `6x4` in `tile_sizes.yaml` (0 0 1289.28 710.64) and `def/tt_block_6x4_pgvdd.def`; there is no 8×4 entry or template. Templates are generated in tt-multiplexer (`py/gen_tt_defs.py`, `cfg/ihp-sg13cmos5l.yaml`, 12×20 tile grid), so an 8×4 template would be an organizer/upstream change, not a user-side file.
- tt-gds-action installs LibreLane with pip and runs `tt_tool.py --harden` with `--dockerized`; `tt_tool.py --harden --no-docker` exists for a native toolchain.
- Rootless user namespaces are blocked directly (AppArmor) but work through `/usr/bin/bwrap`, so `nix-portable` (v012) runs Nix without `/nix`. The LibreLane flake has no embedded cache config; without the FOSSi cache in `~/.nix-portable/conf/nix.conf` Nix compiled OpenSTA/OR-Tools from source.

## Proposed or completed changes
- `info.yaml`: tiles 8x4 -> 6x4 (supported and what the competition asks for).
- `tools/harden.sh`: local hardening wrapper; Docker mode by default (same command as the GitHub action), `NO_DOCKER=1` for the rootless nix-portable toolchain.
- `tools/setup-physical.sh`: one-time setup (tt-support-tools, pip LibreLane, PDK, Docker image; `--rootless` adds nix-portable and the flake tools).
- `tools/shim/python`, `tools/nix/ll-python/`: rootless-mode plumbing (venv on the flake's Python with tkinter and the Nix klayout module).
- `reports/cmos5l-layout.json`: layout evidence with tool/PDK pins and output hashes.
- `README.md`, `docs/verification.md`, `docs/roadmap.md`, `justfile`: results and how to run.
- `.gitignore`: ignore `/tt` symlink to `.tools/tt`.
- `docs/*`, `README.md`, `reports/`: to be updated with layout results.

## Verification
- Ran: `tools/harden.sh` (rootless mode) — Flow complete, exit 0, 0:50:15. 12,309 cells, 27.9% utilization, setup WS +57.18 ns (slow), hold WS +0.113 ns (fast), route DRC 0, Magic DRC 0, LVS 0 errors, antenna 0. Archived in `build/run-rootless/` (gitignored).
- Ran: `docker run ghcr.io/librelane/librelane:3.1.0.dev3` tool versions — identical to the flake (OpenROAD dcf36133, Yosys 0.66, KLayout 0.30.9, Magic 8.3.674, Netgen 1.5.320).
- Ran: `tools/harden.sh` (Docker mode) — Flow complete, exit 0; all 193 metrics equal to the rootless run, netlist/DEF byte-identical, GDS geometry identical by KLayout LayoutDiff. Archived in `build/run-docker/`.
- Ran: `just test-sdf` at all three corners locally and in the `sdf` workflow (run 35043986083): 60/60 passes; negative controls in `reports/sdf-tests.json`. Icarus does not enforce SDF timing checks (documented).
- Ran: `gds` workflow 35032646298 on main: gds, precheck (0 errors), gl_test (10/10) pass; viewer published at https://dishishshawn.github.io/protocol-emulator-asic/ after enabling Pages.
- Not run: KLayout DRC (disabled by the TT template); formal; FPGA; silicon.

## Risks, open questions, and next owner
- If 8×4 is offered later, only `info.yaml` changes; the flow is unchanged.
- LibreLane 3.1.0.dev3 bug: OPENROAD_THREADS unset becomes `-threads None` (single-threaded); harden.sh pins it. Worth an upstream issue.
- 2,276 hold-fix delay cells (18% of cells) come from the template's 0.1 ns hold margin; harmless at this utilization.
- Next owner: feature work (FIFOs, capture path, protocol completeness) per docs/roadmap.md.
