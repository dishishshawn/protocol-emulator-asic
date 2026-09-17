# Verification — September 17, 2026 (updated with repeated START and formal checks)

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

## Streaming revision

After the streaming FIFOs, capture and multi-byte protocols were added
(commit d4465ac; twenty RTL tests, five mutation controls,
[fault demo](../reports/fault-demo.json)), the full flow was rerun: 18,776
cells, 34.1% utilization, +57.4 ns setup and +0.12 ns hold slack, clean DRC,
LVS and antenna locally; in CI, precheck 0 errors, gl_test 20/20 and SDF
60/60 over three corners ([layout](../reports/cmos5l-layout.json),
[CI](../reports/ci-gds-run.json), [SDF](../reports/sdf-tests.json)).

## Repeated START (September 17, 2026)

`i2c_transaction` adds the write-then-read register transaction. The
twenty-first RTL test, `i2c_repeated_start_register_read`, drives a
register-file target model that counts a START during an open transaction as
repeated, serves `registers[pointer]` with auto-increment, and records the
controller's ACK bits. It checks 1-, 7- and 16-byte reads from three pointers at
4- and 50-clock half periods with and without 13-clock stretching, a write of
two registers followed by a read-back in the same transaction, an unmatched
address (STOP then TRAP with no repeated START and no data), and a stretch that
never ends during the repeated START (bounded-wait fault). The regression is
21/21 locally (`build/rtl-regression-repstart.log`); a sixth streaming
mutation control that deletes the repeated START is detected
([evidence](../reports/streaming-mutations.json)).

## Fault-length sweep (September 17, 2026)

`just fault-sweep` ([evidence](../reports/fault-sweep.json)) runs the stop-bit
fault demonstration for 20 fault lengths (0–20 clocks in fine steps around the
receiver's mid-bit sample, then 24–64) and five bytes: 100 engine runs, 50
accepted frames and 50 framing errors, with the boundary at 17 clocks exactly
where the receiver samples. Each run is checked as in the capture demo:
captured events equal the independent model's edge list, constant
synchronizer offset, an 11-clock response pulse, no overflow. The response
latency measured from the capture is 103 or 59 clocks in every run. The
interactive page `docs/fault-sweep.html` embeds this file; the target latencies
remain simulation parameters, not device measurements.

## Formal properties (September 17, 2026)

[Machine-readable evidence](../reports/formal.json). `just formal` runs
SymbiYosys (Yosys 0.66, Yices 2.7.0 from the pinned nix-portable store) on the
engine with `formal/properties.vh` included under `FORMAL`; the RTL used for
synthesis is unchanged by the include guard. Inputs, including the un-reset
program memory, are unconstrained beyond an initial reset.

| Task | Result |
| --- | --- |
| `bmc`, depth 40 | All assertions hold from reset for 40 clocks |
| `prove`, depth 24 | Base case and temporal induction pass: the properties hold for every reachable state, unbounded |
| `cover`, depth 60 | All six reachability targets reached between steps 13 and 28 |
| Negative controls | Six one-bug engine mutations each fail the named property (`tools/check_formal_mutations.py`) |

Safety (S1–S10): no output enable unless running, fault implies halted, running
and halted exclusive; every lane released within two synchronized samples of
RUN low; loader bounds; each queue's occupancy matches its pointers and never
exceeds eight; streaming instructions fault without STREAM; a fault can only
follow an executed instruction, a bad image at the RUN edge or running off the
end, never host traffic; exact DRIVE/PATCH countdown; timestamp wrap is
recorded; a running program has no partial loader word.

Bounded liveness (S7, L1): a WAIT with a nonzero timeout completes or faults
within that many clocks, proven as an invariant on the elapsed counter plus its
per-clock advance. PULL and PUSH stalls are host-controlled and unbounded by
design, as documented in the streaming interface.

Data integrity (D1–D3): a nondeterministically tagged TX byte, RX byte or
capture entry stays unchanged in its occupied slot and is delivered exactly to
the PULL, host head read or capture head that reaches it.

Limits: this proves the RTL against these properties only; the program memory,
synchronizer inputs and host timing are free, and nothing is proven about the
firmware or the routed netlist. Equivalence of the gate-level netlist rests on
the simulation evidence above.

## Post-layout gate-level simulation with SDF

[Machine-readable evidence](../reports/sdf-tests.json). `just test-sdf <corner>`
compiles the routed, unpowered netlist (`final/nl`) with the PDK cell models
and back-annotates the OpenSTA SDF for one corner through `$sdf_annotate`.
`tools/timing_cells.py` generates an Icarus-compatible copy of
`sg13cmos5l_stdcell.v`: it drops the delayed-net arguments of
`$setuphold`/`$recrem` that Icarus cannot drive, ties each `delayed_*` net to
its input, and makes `ifnone` paths unconditional (the SDF carries an
unconditional IOPATH for every such arc). Path delays are kept and annotated;
the tests already change inputs on the falling clock edge, so the host
contract is unchanged.

| Corner | Local (this laptop) | GitHub `sdf` workflow |
| --- | --- | --- |
| nom_slow_1p08V_125C | 10/10 pass | 10/10 pass |
| nom_typ_1p20V_25C | 10/10 pass | 10/10 pass |
| nom_fast_1p32V_m40C | 10/10 pass | 10/10 pass |

Each run simulates the same 100,333,200 ns as the RTL regression. Controls:
a clock-tree probe shows the annotated slow-corner latency (0.80 ns to a leaf,
8.0 ns with a 10× SDF), and scaling all path delays 30× makes the
instruction-fetch test fail, so the delays are applied and can break the design.

**Limitation.** Icarus Verilog parses but does not enforce SDF timing checks:
setting every SETUP limit to 50 ns changes nothing, and on a one-flop design a
violated 8 ns setup limit leaves Q at its captured value rather than X. These
runs therefore show that the routed netlist functions with the extracted path
delays at every corner; a setup failure would appear only as wrongly captured
data when a path exceeds the 100 ns period, and hold margins are covered only
by STA (+0.113 ns worst at the fast corner). STA remains the timing signoff.

## What remains unverified

No FPGA or silicon test has completed. Tests do not model metastability, analog rise time, voltage
compatibility, asynchronous host phase sweeps or reset recovery/removal.
The I²C peer models wired-AND logic, not analog pull-up behavior. The I²C program
is a single-controller write demonstration and does not establish complete
multi-controller or electrical compliance.

The physical evidence is now complete for this design revision; rerun `just harden`, `just test-sdf` and the `gds` workflow after RTL changes. Future functional work includes I²C bus recovery and multi-controller behavior.

## References

- [Pinned IHP CMOS5L PDK](https://github.com/IHP-GmbH/ihp-sg13cmos5l/tree/607e18d4bd9214a52575c194b4181ef449f9252f): Liberty area/timing data and Verilog cell models.
- [NXP UM10204](https://www.nxp.jp/docs/en/user-guide/UM10204.pdf): I²C START/STOP, ACK, open-drain signaling and clock stretching reference. This prototype implements the documented subset above.
