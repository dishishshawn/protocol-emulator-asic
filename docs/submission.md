# Programmable protocol emulator: submission write-up

Draft of September 23, 2026. The organizers will publish the final submission
form closer to the January 18, 2027 deadline; this page is the material it will
draw on. Every figure below links to machine-readable evidence in `reports/`.

## Summary

A firmware-programmable pin engine for IHP CMOS5L on 6×4 Tiny Tapeout tiles at
10 MHz. Protocols are programs, not hardware blocks: UART, SPI and I²C, including
write-then-read register transactions joined by a repeated START, all run on one
fifteen-opcode instruction set over five bidirectional lanes. A host streams
data through eight-byte TX and RX FIFOs, and an eight-entry capture FIFO records
every edge on selected lanes with a 24-bit timestamp.

The distinctive use is controlled fault injection: firmware breaks a protocol at
an exact clock, and the chip records when and how the target answered. The
verification is organized around one question asked of every checker: would it
notice if the design were wrong? Each test suite and property set is paired with
deliberately broken designs that it must reject.

## Distinctive functionality

**Protocols as firmware.** A 64 × 32-bit writable instruction store holds
programs built from exact-duration DRIVE and PATCH updates, bit shifts in and
out, counted loops, input branches, bounded waits and a transmit-contention
check ([instruction set](info.md)). Consecutive DRIVE or PATCH updates land
exactly the requested number of clocks apart. Python encoders
(`tools/program.py`, `tools/streaming.py`) generate the firmware, so a new
protocol variant is a new program, not a respin.

**Fault injection with timestamped capture.** `fault_demo` sends a UART byte,
holds its stop bit low for exactly N clocks, then watches the target's response
lane. A sweep of 20 fault lengths × 5 bytes at 32 clocks per bit
([evidence](../reports/fault-sweep.json)) puts the accept/reject boundary exactly
at the receiver's mid-bit sample: faults of 16 clocks or less are accepted and
17 or more are framing errors. The captured response latency switches between
the modeled 103 and 59 clocks at that boundary in every run. The
[interactive page](fault-sweep.html) plots each run; every slider position is a
real simulation. The firmware refuses fault lengths whose response it could not
observe, and a test pins that limit to the exact clock.

**Fail-closed by construction.** Fault and HALT release every lane, RUN low
releases them within two synchronized samples, a WAIT with a timeout completes
or faults within it, and host traffic cannot fault the engine. These are proven
properties, not only tested behavior; reset and deselection gate the output
enables combinationally and are tested at the pins.

## Verification methodology

**Black-box pin-level regression.** Twenty-two cocotb tests drive only the
external pins through the real host protocol. Independent models decode the bus
without looking inside the engine: a UART receiver, an SPI peer, I²C targets
with clock stretching, and a register-file target that distinguishes a repeated
START from a new transaction. Tests use randomized drive patterns and place
input transitions on both sides of the sampling clock edge. The same tests run
unchanged on the routed netlist with SDF delays.

**Formal proof.** SymbiYosys proves by k-induction, unbounded
([evidence](../reports/formal.json)): ten safety invariants (fail-closed outputs,
loader bounds, FIFO occupancy, the streaming gate, fault provenance, exact
DRIVE/PATCH countdown, timestamp wrap), termination of every bounded WAIT, and
data integrity for the TX, RX and capture FIFOs. Integrity uses a
nondeterministically tagged entry that must reach its consumer unchanged. Six
cover targets show the properties are not vacuous.

**Negative controls.** Every checker is shown to catch a deliberate bug:

| Checker | Deliberate bugs | Result |
| --- | --- | --- |
| Formal properties | 7 one-line engine mutations | each fails its named property ([evidence](../reports/formal.json)) |
| Streaming tests | 9 RTL and firmware mutations | each fails its named test ([evidence](../reports/streaming-mutations.json)) |
| Original protocol tests | 2 RTL mutations | each detected ([evidence](../reports/mutation-checks.json)) |
| Gate-level SDF simulation | path delays scaled 30× | fetch test fails, so delays are applied ([evidence](../reports/sdf-tests.json)) |
| Fault-demo timing bound | firmware built for a target one clock slower | faults on its bounded wait |

The controls have found real gaps. One formal property silently excluded the
CAPTURE instruction's guard: a design with that guard removed passed the old
property and fails the corrected one ([verification](verification.md), "Review
fixes").

**Physical and gate-level.** The streaming revision closed layout with 18,776
cells, 34.1% utilization, +57.4 ns setup and +0.12 ns hold slack, and clean DRC,
LVS and antenna checks ([evidence](../reports/cmos5l-layout.json)). In CI it
passed Tiny Tapeout precheck with 0 errors, gl_test 20/20 and SDF simulation
60/60 over three corners ([evidence](../reports/ci-gds-run.json)). The two tests
added since and the sweep pass on the same routed netlist with SDF at all three
corners (12/12, local). The RTL has not changed since that layout.

**Reproducibility.** Every push runs the regression and the sweep in CI, and CI
fails unless the demo and sweep evidence it produces match the committed reports
byte for byte. A separate workflow reruns the proofs, covers and all seven
formal controls with pinned OSS CAD Suite tools whenever the engine, properties
or formal tooling change. The physical flow is the official Tiny Tapeout `gds`
action, also runnable locally.

## Results

| Measure | Value |
| --- | --- |
| Process, area, clock | IHP CMOS5L, 6×4 tiles, 10 MHz |
| Cells, flip-flops, utilization | 18,776, 2,644, 34.1% |
| Setup / hold slack | +57.4 ns slow corner / +0.12 ns fast corner |
| RTL regression | 22/22 |
| Gate-level (CI) | precheck 0 errors, gl_test 20/20, SDF 60/60 |
| Formal | bmc, k-induction proof and cover pass |
| Negative controls | 7 formal, 9 streaming, 2 RTL, 1 SDF: all detected |

## Reproduce

```sh
just setup && just test      # 22-test RTL regression
just fault-sweep             # 100-run sweep -> build/fault-sweep.json
just capture-demo            # normal and faulted capture traces
just formal                  # bmc, prove, cover (needs sby on PATH or nix-portable)
just setup-physical && just harden   # full CMOS5L layout, about 50 minutes
just test-sdf nom_slow_1p08V_125C    # routed netlist with SDF delays
```

## Limitations

- Simulation only: no FPGA or silicon measurements. Electrical compliance
  (pull-ups, I²C rise times, UART levels) is not established.
- Target response latencies in the fault demo are model parameters, not device
  measurements.
- I²C is single-controller: no retries, bus recovery or multi-controller clock
  synchronization.
- Icarus applies SDF path delays but not setup/hold checks; STA is the timing
  signoff.
- Formal proofs cover the engine RTL, not the firmware or the netlist; the
  netlist is checked by simulation.
- The host byte bus uses bundled-data timing with no handshake; the host must
  respect four-clock phases.

## Before submitting

- The repository is private; the competition requires open source.
- The competition sign-up form has not been submitted.
- The final submission form has not been published yet.
- If the RTL changes before January, rerun the physical flow and gate-level
  regressions and tag the candidate ([roadmap](roadmap.md)).
