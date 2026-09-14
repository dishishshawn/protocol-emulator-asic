# Roadmap — updated September 14, 2026

## Design intent

A programmable protocol exerciser for bringing up and testing hardware. Build a small deterministic engine first, then establish a distinctive demonstration: inject a controlled timing/protocol fault and capture the target's response. Novelty is a proposal, not a claim that this capability is unprecedented.

## Completed

The programmable UART milestone, byte transmit/receive instructions, counted loops, conditional branches, bounded waits, SPI transfers and I²C writes are implemented. Ten RTL tests pass. CMOS5L mapping gives 7,963 cells / 183,441.9636 µm² before layout. The private GitHub repository is `dishishshawn/protocol-emulator-asic`.

## Milestones

| Target | Work | Exit evidence |
| --- | --- | --- |
| September 2026 | UART program, clock-accurate tests, initial synthesis; assess instruction set | Verified pin traces; mapped area estimate with exact process/tool versions |
| October 2026 | Input/output shift operations, bounded waits, conditional branches, host streaming; UART RX, SPI and I²C | Independent protocol models; randomized clock phase and I²C stretch/arbitration tests |
| November 2026 | Stabilize memory/host interface; first full place and route; select optional FPGA target | Fits 8×4; timing report; no unexplained DRC/LVS failures; FPGA evidence if available |
| December 2026 | Fault injection + timestamped capture demo; formal properties; documentation | Reproducible normal/faulted protocol traces; safety and liveness checks |
| January 1–10, 2027 | Freeze features, rerun physical flow and gate-level regressions | Tagged reproducible candidate and review packet |
| January 11–18, 2027 | Final checks and submission | Public source, build/test instructions, required final form completed |

These are targets, not scheduled automations. Final submission is due January 18, 2027; no cutoff timezone is specified in the announcement. Aim to finish ahead of it.

## Decisions to make from evidence

- **Memory:** current 2,048-bit store uses inferred logic storage and combinational fetch. Initial mapped area is available; measure area again before growing it. Foundry SRAM may require a different fetch pipeline; do not assume it is a drop-in replacement.
- **Host connection:** the simple parallel loader is for the initial prototype. A serial host interface could recover protocol lanes and add streaming; define clock-domain crossings and backpressure explicitly.
- **Instruction set:** DRIVE can already produce exact output durations; byte shifts, loops, input branches and bounded waits are now implemented; streaming receive/emulation still needs FIFOs and a fuller host interface.
- **Clock:** 10 MHz is a starting constraint, not a measured silicon capability. Higher rates require timing closure and input synchronization analysis.
- **I²C:** open-drain behavior is represented by value=0 and OE toggling. A wired-AND target now checks writes, clock stretching, ACK/NACK and contention. Analog pull-ups, bus recovery and full multi-controller behavior remain.
- **Novel demo:** choose one after the basic protocols work. USB and Ethernet remain optional stretch work, with physical interface requirements considered separately.
- **FPGA:** user currently has no board. Continue in simulation and defer hardware selection.

## Competition requirements and sources

[Jane Street announcement](https://blog.janestreet.com/protocol-emulator-asic-competition/): open-source general-purpose protocol emulator, IHP CMOS5L via Tiny Tapeout, 8×4 tiles, January 18 deadline, UART/SPI/I²C baseline. Fabrication prize targets March 2027 subject to foundry scheduling. Winners are selected for the organizers' favorite designs, including distinctive functionality and design/verification methods.

[Official template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l): CMOS5L flow. The active CMOS5L [tile-size table](https://github.com/TinyTapeout/tt-support-tools/blob/da63c9927411e3aca350977d653d24bbf5bca972/tech/ihp-sg13cmos5l/tile_sizes.yaml), checked at commit `da63c9927411e3aca350977d653d24bbf5bca972`, also omits 8×4. The competition explicitly requests this allocation, so keep `info.yaml` at 8×4 and obtain an upstream update or organizer-confirmed floorplan before full hardening. No flow override or invented die dimensions have been applied.

[SRAM reference](https://www.tinytapeout.com/chips/ttihp0p2/tt_um_urish_sram_test): an IHP SRAM demonstration linked by the organizers. It does not establish compatibility, timing, or fit for this design.
