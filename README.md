# Programmable protocol emulator ASIC

A simulation-first entry for the [Jane Street ASIC competition](https://blog.janestreet.com/protocol-emulator-asic-competition/), due **January 18, 2027**. This repository belongs to [dishishshawn](https://github.com/dishishshawn/protocol-emulator-asic) and is private during development; the competition submission must be open source.

The chip executes firmware that drives, samples and shifts data through five bidirectional lanes. UART, SPI and I²C are programs using the same engine. Host FIFOs support streaming transfers; timestamped capture records a target's response to precisely timed protocol faults.

## Current milestone

- 64 × 32-bit writable instruction store, byte registers, independent bit/byte loops and input-dependent branches.
- Eight-byte TX and RX FIFOs, explicit backpressure, and an eight-entry timestamped input capture FIFO.
- Multi-byte UART 8N1 transmit/receive; SPI full-duplex transfers in all four modes and both bit orders.
- I²C single-controller writes, reads and write-then-read register transactions with repeated START; ACK/NACK, bounded clock stretching and transmitted-bit contention detection.
- Twenty-two RTL regressions pass: the original ten plus twelve streaming, framing, queue, capture, fault-timing, repeated-START and malformed-instruction tests, with nine streaming mutation controls detected (`tools/check_streaming_mutations.py`). [Streaming interface and limitations](docs/streaming.md).
- Reproducible UART stop-bit fault demonstration with timestamped modeled-target responses: `just capture-demo`. A 100-run sweep of fault length and byte (`just fault-sweep`, [evidence](reports/fault-sweep.json)) feeds the interactive [fault sweep page](docs/fault-sweep.html), where every slider position is a real simulation.
- Formal safety, bounded-wait and FIFO data-integrity properties proven by k-induction with SymbiYosys, with seven negative controls: `just formal` ([evidence](reports/formal.json)), rerun in CI with pinned OSS CAD Suite tools.

The **streaming design** completed layout on 6×4 tiles at 10 MHz: 18,776 cells
excluding fill (2,644 flip-flops), 34.1% utilization, +57.4 ns slow-corner setup
slack, +0.12 ns fast-corner hold slack, clean routing/Magic DRC, LVS and antenna
checks ([layout evidence](reports/cmos5l-layout.json), which also keeps the
pre-streaming baseline). In CI this revision passed precheck (0 errors), gl_test (20/20) and the three-corner SDF regression (60/60).

The allocation is 6×4 Tiny Tapeout tiles, the current competition maximum, with a provisional 10 MHz clock. See the [submission write-up](docs/submission.md), [verification](docs/verification.md), [architecture](docs/info.md), [mapped-area evidence](reports/cmos5l-area.json) and [roadmap](docs/roadmap.md).

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

The mapped test uses functional standard-cell models without extracted delays. Routed-netlist SDF tests and STA provide separate physical verification; silicon validation remains ahead.

## Physical build (local)

`tools/setup-physical.sh` prepares a local copy of the official `gds` workflow: tt-support-tools (`ihp-sg13cmos5l` branch), LibreLane 3.1.0.dev3 with its Docker image, and IHP-Open-PDK at the pinned commit. It needs Docker usable by your user. `tools/setup-physical.sh --rootless` instead installs nix-portable and the same pinned tools from the LibreLane Nix flake for machines without Docker (`NO_DOCKER=1 tools/harden.sh`); results are identical.

```sh
just setup-physical
just harden            # tt_tool.py --create-user-config, then --harden (Docker)
```

`just test-sdf <corner> [run-dir]` then runs the pin-level tests on the routed netlist with SDF back-annotation from one STA corner (`nom_slow_1p08V_125C`, `nom_fast_1p32V_m40C`, `nom_typ_1p20V_25C`). `tools/timing_cells.py` makes an Icarus-compatible copy of the cell models that keeps the path delays. Icarus does not enforce SDF setup/hold checks, so this shows the routed netlist functions with extracted delays; STA remains the timing signoff. For the pre-streaming baseline, all three corners passed locally and in the `sdf` GitHub workflow ([evidence](reports/sdf-tests.json)); the streaming layout passed the same three corners in CI (20 tests each).

Outputs land in `runs/wokwi/` exactly as in CI: `final/gds`, `final/nl`, `final/metrics.json`, DRC and LVS reports and a PNG render. A full run takes about 50 minutes on 8 cores, most of it single-threaded Magic DRC. `tools/harden.sh` pins OpenROAD to the machine's core count because LibreLane 3.1.0.dev3 otherwise runs it single-threaded.

## CI and next work

Pushes run the RTL regression and the fault sweep, and fail unless the demo and sweep evidence match `reports/` byte for byte. The `formal` workflow reruns the proofs, covers and formal negative controls whenever the engine, properties or formal tooling change. The official GDS, documentation and FPGA workflows are manually dispatched. No competition signup or final submission has been made.

Next: the [submission write-up](docs/submission.md) is drafted; before submitting, make the repository public and complete the sign-up and final forms. If the RTL changes, rerun the physical flow and gate-level regressions. No FPGA is required for the current work.

## Provenance

Apache-2.0. Based on [TinyTapeout/ttihp-verilog-template, cmos5l](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l), commit `b86a2a781484bcab7ba522dc5de540086695a430`. The engine, firmware tools, tests and reports are new. Template wrapper, metadata, clock period, documentation and workflows have been modified. The PDK license remains with its upstream repository.
