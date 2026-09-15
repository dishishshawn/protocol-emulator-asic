# Verification — September 14, 2026 (updated with first layout)

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
and physical repair. See the layout section above for post-route area and timing.

## First complete CMOS5L layout

[Machine-readable evidence](../reports/cmos5l-layout.json). The full Tiny Tapeout
hardening flow (LibreLane 3.1.0.dev3, tt-support-tools `ihp-sg13cmos5l`
@ `da63c99`, IHP-Open-PDK @ `2bbec755`) completed on the 6×4 tile template
with a 100 ns clock. The flow was run twice, in the official LibreLane Docker image (the same
command as the `gds` GitHub workflow) and with the rootless nix-portable
toolchain; all 193 final metrics, the routed netlist, the DEF and the GDS
geometry are identical (`tools/harden.sh`).

| Measurement | Result |
| --- | --- |
| Die | 1289.28 × 710.64 µm (6×4 tiles, 916,214 µm²) |
| Cells excluding fill/tap | 12,309 (2,192 flip-flops, 2,276 hold-fix delay cells, 1,635 buffers) |
| Core utilization | 27.9% (about 252,000 µm² of standard cells) |
| Setup slack, slow corner 1.08 V / 125 °C | +57.18 ns (100 ns period) |
| Hold slack, fast corner 1.32 V / −40 °C | +0.113 ns |
| Detailed-route DRC | 0 errors after 5 iterations |
| Magic DRC on GDS | 0 errors, 0 illegal overlaps |
| Netgen LVS | 0 errors, 0 unmatched nets/devices/pins |
| Antenna | 0 violating nets or pins |
| Max slew / max cap | 0 violations; 135 advisory max-fanout (limit 10) |
| Wire length | 573,513 µm |

The critical path is about 43 ns at the slow corner, so 10 MHz closes with a
wide margin. The pre-layout cell area of 183,442 µm² grew to about 252,000 µm²
after buffering, hold fixing, clock tree and antenna diodes; about 45% of that
growth is the 2,276 hold-fix delay cells inserted under the template's
0.1 ns hold margin.

KLayout DRC is disabled in the TT template and was not run. The allocation was reduced from the previously assumed 8×4 to 6×4
because the competition page now states 6×4 is the current maximum and the
support tools have no 8×4 template.

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

## Tiny Tapeout CI on the merged main

[Run 35032646298](https://github.com/dishishshawn/protocol-emulator-asic/actions/runs/35032646298)
([summary](../reports/ci-gds-run.json)): the official `gds` job rebuilt the
layout on GitHub, `precheck` passed with 0 errors over 33 checks, and
`gl_test` passed all ten tests on the CI gate-level netlist. The CI GDS is
geometrically identical to the local Docker and rootless builds. The `viewer`
job fails only because GitHub Pages is not enabled on the private repository.

## Post-layout gate-level simulation with SDF

`just test-sdf <corner>` compiles the routed, unpowered netlist (`final/nl`)
with the PDK cell models and back-annotates the OpenSTA SDF for one corner
through `$sdf_annotate`. Icarus cannot drive the delayed nets of
`$setuphold`/`$recrem` and rejects `ifnone` on edge-sensitive paths, so
`tools/timing_cells.py` generates a copy of `sg13cmos5l_stdcell.v` that drops
the delayed-net arguments, ties each `delayed_*` net to its input, and makes
`ifnone` paths unconditional (the SDF carries an unconditional IOPATH for every
arc next to its COND variants). Path delays, SETUP/HOLD/RECOVERY/REMOVAL/WIDTH
checks and notifiers are kept, so a violation drives the flip-flop UDP output
to X and the pin-level checks fail. The SDF contains no negative limits. The
tests already change inputs on the falling clock edge, 50 ns before the next
rising edge, so the host contract itself is unchanged.

A single-test smoke run at the slow corner passes with no dropped paths. The
full ten-test regression at the slow, fast and typical corners runs in the
`sdf` GitHub workflow after each `gds` build (and locally with
`just test-sdf`); results are recorded in `reports/sdf-tests.json`.

## What remains unverified

No formal proof, FPGA or silicon test has completed. Tests do not model metastability, analog rise time, voltage
compatibility, asynchronous host phase sweeps or reset recovery/removal.
The I²C peer models wired-AND logic, not analog pull-up behavior. The I²C program
is a single-controller write demonstration and does not establish complete
multi-controller or electrical compliance.

The next physical milestone is the SDF-timed regression at all three corners. Future functional work includes input streaming, receive FIFOs,
I²C reads/repeated START, UART receive and fault-injection/capture demonstrations.

## References

- [Pinned IHP CMOS5L PDK](https://github.com/IHP-GmbH/ihp-sg13cmos5l/tree/607e18d4bd9214a52575c194b4181ef449f9252f): Liberty area/timing data and Verilog cell models.
- [NXP UM10204](https://www.nxp.jp/docs/en/user-guide/UM10204.pdf): I²C START/STOP, ACK, open-drain signaling and clock stretching reference. This prototype implements the documented subset above.
