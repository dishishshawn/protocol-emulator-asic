# Programmable protocol emulator ASIC

A simulation-first entry for the [Jane Street ASIC competition](https://blog.janestreet.com/protocol-emulator-asic-competition/), due **January 18, 2027**. This repository belongs to [dishishshawn](https://github.com/dishishshawn/protocol-emulator-asic) and is private during development; the competition submission must be open source.

The chip executes firmware that drives, samples and shifts data through five bidirectional lanes. UART, SPI and I²C are programs using the same engine. The working direction is a protocol exerciser with precise timing, controlled fault injection and eventual timestamped capture.

## Current milestone

- 64 × 32-bit writable instruction store, byte transmit/receive registers, counted loops and input-dependent branches.
- UART 8N1 transmit; SPI full-duplex byte transfer in all four modes and both bit orders.
- I²C single-controller address + data write, ACK/NACK, bounded clock stretching and detection of transmitted-bit contention.
- All ten regression tests pass in RTL and again on the CMOS5L mapped netlist, including independent pin-level SPI and wired-AND I²C peers. GitHub RTL CI is green.
- CMOS5L mapping: **7,963 cells, 183,441.9636 µm² (0.18344 mm²)**, typical 1.2 V / 25 °C library. This is pre-layout cell area, not final chip area or timing closure.

The allocation is 8×4 Tiny Tapeout tiles with a provisional 10 MHz clock. See [verification](docs/verification.md), [architecture](docs/info.md), [mapped-area evidence](reports/cmos5l-area.json) and [roadmap](docs/roadmap.md).

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

## CI and next work

Pushes run the RTL regression. The retained official GDS, documentation and FPGA workflows are manually dispatched while the physical flow is being brought up. No competition signup or final submission has been made.

Next: first complete CMOS5L layout, then host streaming/FIFOs, multi-byte transactions, I²C read/repeated START, UART receive and formal safety/liveness properties. No FPGA is required for the current work.

## Provenance

Apache-2.0. Based on [TinyTapeout/ttihp-verilog-template, cmos5l](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l), commit `b86a2a781484bcab7ba522dc5de540086695a430`. The engine, firmware tools, tests and reports are new. Template wrapper, metadata, clock period, documentation and workflows have been modified. The PDK license remains with its upstream repository.
