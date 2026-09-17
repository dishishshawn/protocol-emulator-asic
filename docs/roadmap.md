# Roadmap — updated September 17, 2026

## Design intent

A programmable protocol exerciser for bringing up and testing hardware. Build a small deterministic engine first, then establish a distinctive demonstration: inject a controlled timing/protocol fault and capture the target's response. Novelty is a proposal, not a claim that this capability is unprecedented.

## Completed

Repeated START and formal (September 17): `i2c_transaction` performs write-then-read register transactions joined by a repeated START (21 RTL regressions, six streaming mutation controls). SymbiYosys proves ten safety invariants, bounded WAIT termination and TX/RX/capture data integrity by k-induction, with six formal negative controls. A 100-run fault-length sweep feeds an interactive demo page (`docs/fault-sweep.html`). The physical flow has not yet been rerun on this revision.

Streaming milestone: eight-byte TX/RX FIFOs, an eight-entry timestamp FIFO, multi-byte UART TX/RX and SPI/I²C programs, and a timed UART stop-bit fault demo are implemented with twenty passing RTL regressions and five detected mutation controls. The streaming design completed layout on 6×4 tiles: 18,776 cells, 34.1% utilization, +57.4 ns setup slack, clean DRC/LVS/antenna.

Pre-streaming baseline: the programmable UART milestone, byte transmit/receive instructions, counted loops, conditional branches, bounded waits, SPI transfers and I²C writes are implemented. Ten RTL tests pass. CMOS5L mapping gives 7,963 cells / 183,441.9636 µm² before layout. The first complete layout on 6×4 tiles closes 10 MHz with +57 ns setup slack, 27.9% utilization, and clean DRC/LVS/antenna ([evidence](../reports/cmos5l-layout.json)); the flow runs locally via `tools/harden.sh`. The private GitHub repository is `dishishshawn/protocol-emulator-asic`.

## Milestones

| Target | Work | Exit evidence |
| --- | --- | --- |
| September 2026 | UART program, clock-accurate tests, initial synthesis; assess instruction set | Verified pin traces; mapped area estimate with exact process/tool versions |
| October 2026 | Input/output shift operations, bounded waits, conditional branches, host streaming; UART RX, SPI and I²C | Independent protocol models; randomized clock phase and I²C stretch/arbitration tests |
| November 2026 | Stabilize memory/host interface; gate-level simulation of routed netlist; precheck; select optional FPGA target | Done early: fits 6×4 with clean DRC/LVS and timing. Baseline SDF (three corners), precheck and gl_test passed. Rerun for new features; FPGA evidence if available |
| December 2026 | Fault injection + timestamped capture demo; formal properties; documentation | Done early: reproducible normal/faulted traces; safety, bounded-liveness and data-integrity properties proven. Remaining: submission write-up |
| January 1–10, 2027 | Freeze features, rerun physical flow and gate-level regressions | Tagged reproducible candidate and review packet |
| January 11–18, 2027 | Final checks and submission | Public source, build/test instructions, required final form completed |

These are targets, not scheduled automations. Final submission is due January 18, 2027; no cutoff timezone is specified in the announcement. Aim to finish ahead of it.

## Decisions to make from evidence

- **Memory:** the 2,048-bit flip-flop store fits comfortably: the whole design uses 27.9% of a 6×4 block. SRAM is not needed for the current size. Revisit only if program memory grows past roughly 4× or the freed area is wanted for FIFOs/capture buffers; foundry SRAM would need a different fetch pipeline and the `sg13cmos5l_sram` macros, which are not in the sparse PDK checkout.
- **Host connection:** the parallel loader now supports opt-in streaming with explicit FIFO backpressure and bundled-data timing. A serial host adapter remains optional.
- **Instruction set:** DRIVE can already produce exact output durations; byte shifts, loops, input branches and bounded waits are now implemented; streaming, timestamped capture and I²C repeated START are implemented with no RTL change; richer emulation remains.
- **Clock:** 10 MHz closes with +57 ns setup slack at the slow corner; the critical path is about 43 ns, so up to ~20 MHz is plausible without RTL changes. Higher rates need a re-run and input synchronization analysis.
- **I²C:** open-drain behavior is represented by value=0 and OE toggling. Wired-AND targets check writes, reads, register transactions with repeated START, clock stretching, ACK/NACK and contention. Analog pull-ups, bus recovery and full multi-controller behavior remain.
- **Novel demo:** UART stop-bit fault injection with timestamped modeled-target responses is implemented. USB and Ethernet remain optional stretch work, with physical interface requirements considered separately.
- **FPGA:** user currently has no board. Continue in simulation and defer hardware selection.

## Competition requirements and sources

[Jane Street announcement](https://blog.janestreet.com/protocol-emulator-asic-competition/): open-source general-purpose protocol emulator, IHP CMOS5L via Tiny Tapeout, 6×4 tiles (8×4 possible later), January 18 deadline, UART/SPI/I²C baseline. Fabrication prize targets March 2027 subject to foundry scheduling. Winners are selected for the organizers' favorite designs, including distinctive functionality and design/verification methods.

[Official template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l): CMOS5L flow. The competition page (re-read 2026-09-14) says "Set the tile size in info.yaml to 6x4. The current maximum area is 6x4 tiles per design. We are working on the possibility of scaling up to 8x4 tiles." `info.yaml` is therefore 6×4, which the support tools support; the earlier 8×4 assumption was wrong. If 8×4 is offered later, only `info.yaml` changes. Templates are generated in tt-multiplexer (`py/gen_tt_defs.py`), not by users.

[SRAM reference](https://www.tinytapeout.com/chips/ttihp0p2/tt_um_urish_sram_test): an IHP SRAM demonstration linked by the organizers. It does not establish compatibility, timing, or fit for this design.
