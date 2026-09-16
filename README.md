# Programmable protocol emulator ASIC

A simulation-first entry for the [Jane Street ASIC competition](https://blog.janestreet.com/protocol-emulator-asic-competition/), due **January 18, 2027**. This repository belongs to [dishishshawn](https://github.com/dishishshawn/protocol-emulator-asic) and is private during development; the competition submission must be open source.

The chip executes firmware that drives, samples and shifts data through five bidirectional lanes. UART, SPI and I²C are programs using the same engine. The working direction is a protocol exerciser with precise timing, controlled fault injection and eventual timestamped capture.

## Current milestone

- 64 × 32-bit writable instruction store, byte transmit/receive registers, counted loops and input-dependent branches.
- UART 8N1 transmit; SPI full-duplex byte transfer in all four modes and both bit orders.
- I²C single-controller address + data write, ACK/NACK, bounded clock stretching and detection of transmitted-bit contention.
- All ten regression tests pass in RTL and again on the CMOS5L mapped netlist, including independent pin-level SPI and wired-AND I²C peers. GitHub RTL CI is green.
- CMOS5L mapping: **7,963 cells, 183,441.9636 µm² (0.18344 mm²)**, typical 1.2 V / 25 °C library, pre-layout.
- **First complete layout** (LibreLane 3.1.0.dev3, 6×4 tiles, 10 MHz): 12,309 cells excluding fill, 27.9% core utilization, +57.2 ns setup slack at the slow corner, +0.11 ns hold slack at the fast corner, 0 routing DRC, 0 Magic DRC, LVS clean, 0 antenna violations. See [layout evidence](reports/cmos5l-layout.json).

The allocation is 6×4 Tiny Tapeout tiles, the current competition maximum, with a provisional 10 MHz clock. See [verification](docs/verification.md), [architecture](docs/info.md), [mapped-area evidence](reports/cmos5l-area.json) and [roadmap](docs/roadmap.md).

## Run

Prerequisites: Icarus Verilog 12, uv, make, and optionally just. Install Yosys/ABC for synthesis. Python is pinned to 3.12 for cocotb 2.0.1 compatibility.

```sh
just setup
just test
just demo
```

`just demo` generates little-endian firmware binaries for UART, SPI and I²C. To customize:

```sh
uv run --python .venv/bin/python tools/program.py spi.bin --protocol spi --byte 0xa5 --mode 3 --lsb-first --half-period 5
uv run --python .venv/bin/python tools/program.py i2c.bin --protocol i2c --address 0x50 --byte 0x69 --timeout 2000
```

The half-period parameter is a minimum phase hold in engine clocks. Instruction overhead lengthens some phases; it is not a uniform clock divider. At 10 MHz, the I²C default 50-clock holds target conservative Standard-mode timing in ideal digital simulation. Electrical compliance has not been measured.

At 10 MHz, the UART default 87 clocks/bit gives about 114,943 baud. HALT releases all lanes; a physical UART demo needs a pull-up to preserve idle.

Without just, set up `.venv` with `uv venv --python 3.12 .venv`, install `test/requirements.txt` using `uv pip install --python .venv/bin/python`, and run `PATH="$PWD/.venv/bin:$PATH" make -C test`.

## Map to CMOS5L

The PDK remains an external dependency, pinned to a verified commit:

```sh
git clone --filter=blob:none --no-checkout https://github.com/IHP-GmbH/ihp-sg13cmos5l.git .pdk/ihp-sg13cmos5l
git -C .pdk/ihp-sg13cmos5l sparse-checkout set libs.ref/sg13cmos5l_stdcell/lib libs.ref/sg13cmos5l_stdcell/verilog
git -C .pdk/ihp-sg13cmos5l checkout 607e18d4bd9214a52575c194b4181ef449f9252f
just map "$PWD/.pdk/ihp-sg13cmos5l"
just test-mapped "$PWD/.pdk"
```

Mapping produces `build/cmos5l/summary.json`, the full log, cell statistics and `netlist.v`. The script records RTL and library hashes and rejects unmapped logic. Alternate executable locations are supported via `--yosys` and `--abc`. Generic synthesis is also available with `just synth`.

The mapped test uses functional standard-cell models without extracted delays. Full physical design, static timing, DRC/LVS and silicon validation are still ahead.

## Physical build (local)

`tools/setup-physical.sh` prepares a local copy of the official `gds` workflow: tt-support-tools (`ihp-sg13cmos5l` branch), LibreLane 3.1.0.dev3 with its Docker image, and IHP-Open-PDK at the pinned commit. It needs Docker usable by your user. `tools/setup-physical.sh --rootless` instead installs nix-portable and the same pinned tools from the LibreLane Nix flake for machines without Docker (`NO_DOCKER=1 tools/harden.sh`); results are identical.

```sh
just setup-physical
just harden            # tt_tool.py --create-user-config, then --harden (Docker)
```

`just test-sdf <corner> [run-dir]` then runs the ten pin-level tests on the routed netlist with SDF back-annotation from one STA corner (`nom_slow_1p08V_125C`, `nom_fast_1p32V_m40C`, `nom_typ_1p20V_25C`). `tools/timing_cells.py` makes an Icarus-compatible copy of the cell models that keeps the path delays. Icarus does not enforce SDF setup/hold checks, so this shows the routed netlist functions with extracted delays; STA remains the timing signoff. All three corners pass locally and in the `sdf` GitHub workflow ([evidence](reports/sdf-tests.json)).

Outputs land in `runs/wokwi/` exactly as in CI: `final/gds`, `final/nl`, `final/metrics.json`, DRC and LVS reports and a PNG render. A full run takes about 50 minutes on 8 cores, most of it single-threaded Magic DRC. `tools/harden.sh` pins OpenROAD to the machine's core count because LibreLane 3.1.0.dev3 otherwise runs it single-threaded.

## CI and next work

Pushes run the RTL regression. The retained official GDS, documentation and FPGA workflows are manually dispatched while the physical flow is being brought up. No competition signup or final submission has been made.

Next: gate-level simulation on the routed netlist and the tt precheck, then host streaming/FIFOs, multi-byte transactions, I²C read/repeated START, UART receive and formal safety/liveness properties. No FPGA is required for the current work.

## Provenance

Apache-2.0. Based on [TinyTapeout/ttihp-verilog-template, cmos5l](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l), commit `b86a2a781484bcab7ba522dc5de540086695a430`. The engine, firmware tools, tests and reports are new. Template wrapper, metadata, clock period, documentation and workflows have been modified. The PDK license remains with its upstream repository.
