# Verification — September 14, 2026

## RTL regression

**Ten tests passed, zero failed**, both locally and in [GitHub CI](https://github.com/dishishshawn/protocol-emulator-asic/actions/runs/34901623208). [Machine-readable RTL results](../reports/rtl-tests.json). The six original UART/engine tests remain,
with four tests added for byte operations and independent SPI/I²C peers.
The strengthened first-bit contention test also passed after its model was
corrected to keep the competing controller's SDA low through the check.

| Coverage | Evidence |
| --- | --- |
| UART | All 256 bytes, checked each clock against independent 8N1 framing; bit durations 1, 2, 3, 7 and 87 clocks |
| Pin timing | 62 deterministic random value/OE/duration vectors plus 262144-clock DRIVE; maximum 8192-clock PATCH preserves unmasked lanes |
| Input/control | WAIT, SAMPLE, jumps, reset, abort, deselection, reload and protection against writes during RUN |
| Invalid instructions/images | Invalid opcodes and lanes, zero-count DJNZ, empty/partial/overflowed image, out-of-image jump and fallthrough, explicit TRAP |
| SPI | 480 full-duplex transfers: every byte in mode 0 MSB-first plus 32 cases in each remaining mode/bit-order pair; all four modes, both bit orders, randomized receive bytes and hold times |
| I²C normal | 24 address/data writes, independent wired-AND target, per-edge randomized stretching, byte decoding, two ACKs and STOP |
| I²C errors | Address NACK and data NACK produce STOP then fault; overlong stretch times out; forced first-bit contention faults before ACK |
| Timeout limits | WAIT limits 1, 2 and 17 checked against mismatch clock counts |

Versions: Icarus Verilog 12.0, cocotb 2.0.1, uv-managed Python 3.12.14.
Random seeds: pin vectors and I²C `20260914`; SPI `174283040`.
The SPI and I²C peers inspect external bus edges and do not read the engine's
program counter, instruction memory or shift registers.

## Test effectiveness checks

Two deliberate RTL mutations were tested in temporary copies, leaving canonical
RTL unchanged. Disabling CHECK_TX contention detection caused the I²C error test
to fail because the engine halted without the expected fault. Reversing IN shift
direction caused the SPI test to fail on its received byte. Both failures were
assertion failures after compilation and simulation, not tool/setup failures.
[Mutation evidence](../reports/mutation-checks.json) records the changes, mutant
hashes and observed assertions. This is a limited sanity check, not a measured
mutation-coverage score.

## CMOS5L area mapping

[Machine-readable evidence](../reports/cmos5l-area.json) records source/library
hashes and tools. Mapping completed with no remaining unmapped cells and
`check -assert` reported zero problems.

| Measurement | Result |
| --- | --- |
| Mapped standard cells | 7,963 |
| Cell area | 183,441.9636 µm² = 0.1834419636 mm² |
| Sequential cells | 2,192, including 2,048 instruction-storage bits |
| Library corner | Typical, 1.20 V, 25 °C |
| Yosys | 0.52, commit `fee39a3284c90249e1d9684cf6944ffbbcbb8f90` |
| PDK | IHP CMOS5L, commit `607e18d4bd9214a52575c194b4181ef449f9252f` |
| ABC target | 100 ns, buffer-4 input driver, 6 fF output load |

The 2,048 instruction-store flip-flops alone occupy 100,329.0624 µm², about
54.7% of the total mapped area, before counting their read/write multiplexers.
This makes program-memory implementation a significant future area decision.
The cell-type counts are recorded in the JSON report.

The pipeline synthesizes and flattens RTL, maps sequential cells with
`dfflibmap`, maps combinational logic with ABC using the Liberty library,
removes non-hardware scope metadata, checks the design and writes a mapped
Verilog netlist. The script rejects an unexpected PDK commit, a locally modified
Liberty library, or remaining generic cells.

This is a **pre-layout area estimate**, not final die area, utilization or timing
closure. It excludes clock-tree insertion, routing, pad cells, tie/filler cells
and physical repair. The requested 8×4 allocation and 10 MHz frequency still
need a complete Tiny Tapeout physical flow. The currently selected support-tools
[CMOS5L size table](https://github.com/TinyTapeout/tt-support-tools/blob/da63c9927411e3aca350977d653d24bbf5bca972/tech/ihp-sg13cmos5l/tile_sizes.yaml)
omits 8×4, and the corresponding DEF template is absent. The configuration
code directly indexes that table, so an upstream update or confirmed floorplan
is needed before full hardening.
This does not affect standalone Liberty area mapping.

## Mapped functional simulation

`just test-mapped` runs the same ten pin-level tests against the CMOS5L cell
netlist. The upstream Verilog timing-check models use delayed input nets that
Icarus leaves undriven. `tools/functional_cells.py` makes a generated copy with
specify blocks removed and each delayed net directly connected to its named
input. Cell logic, UDP behavior and copyright notices are preserved. The PDK
source and synthesis Liberty file are unchanged.

**All ten mapped tests passed**, with zero failures or skips. See the
[mapped result summary](../reports/mapped-tests.json) for per-test simulation
and wall times, exact netlist hash and functional-model hash. The RTL and mapped
regressions each exercise about one million engine clocks.

These copies are for **zero-delay functional testing only**, never SDF or analog
timing signoff. Passing these cases is not an exhaustive equivalence proof.

## What remains unverified

No place and route, extracted timing, DRC/LVS, formal proof, FPGA or silicon test
has completed. Tests do not model metastability, analog rise time, voltage
compatibility, asynchronous host phase sweeps or reset recovery/removal.
The I²C peer models wired-AND logic, not analog pull-up behavior. The I²C program
is a single-controller write demonstration and does not establish complete
multi-controller or electrical compliance.

The next physical milestone is a complete CMOS5L layout with area/timing and
DRC/LVS reports. Future functional work includes input streaming, receive FIFOs,
I²C reads/repeated START, UART receive and fault-injection/capture demonstrations.

## References

- [Pinned IHP CMOS5L PDK](https://github.com/IHP-GmbH/ihp-sg13cmos5l/tree/607e18d4bd9214a52575c194b4181ef449f9252f): Liberty area/timing data and Verilog cell models.
- [NXP UM10204](https://www.nxp.jp/docs/en/user-guide/UM10204.pdf): I²C START/STOP, ACK, open-drain signaling and clock stretching reference. This prototype implements the documented subset above.
