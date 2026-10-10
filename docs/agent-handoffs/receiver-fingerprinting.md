# Receiver fingerprinting

## Status
Done, October 10, 2026. Firmware, models and host tooling only: no RTL change,
no re-layout. The outcome and the deviations from the plan come first below;
the original plan follows unchanged for the record. Full write-up:
`docs/verification.md`, "Receiver fingerprinting".

## Outcome (October 10, 2026)

Acceptance criteria:
- **Cross-check, every run: met.** In all 1,061 engine runs, the verdict decoded
  from captures equals each attached model's own verdict. Each attached
  receiver reports exactly once, and the fixture's lane-0 edges equal the probe
  waveform clock for clock. `page(10)` reads 0 and there is no overflow (at
  most five entries).
- **Pairwise separation: met.** All 10 pairs of main receivers are separable,
  both at phase 0 and across tick phases. `separation` in the report gives the
  first separating probe and the per-family counts.
- **Blind identification: met after one rebuild.** Round 1, with the tree built
  from the phase-0 map, got 5/9 right: Majority16 at phase 1 and Majority8 at
  phases 1–3 were named EdgeResync, and the confirmations did not catch it.
  Those two receivers were then signed by their signature sets across phases
  and the tree was rebuilt. Round 2 got 9/9 right in 5–6 probes each. The
  report keeps both rounds.
- **Negative controls: four as stated, one recorded as a limit.** The twin
  lands in the class {MidSample, MidSampleTwin}. MidSamplePlus1 in the map is
  identified as itself, with 16 separating probes (P1 L=17 among them).
  Shuffled labels: 9/9 wrong, detected. Shifted decode widths: the cross-check
  fails on 895/895 map runs. **MidSamplePlus1 left out of the map was
  identified as Majority16, not unknown:** the leaf's three confirmations
  missed it, and 4 of the 174 unused probes would have exposed it. Recorded as
  a limit of the probe set, and the probes were not tuned.
- **`just fingerprint` reproduces the report, and CI cmp's it: met locally.**
  Two consecutive runs were byte-identical. CI has not run on this change yet.

Findings against the hypothesis:
- **P1 does not separate the mid-bit receivers, as expected.** At phase 0,
  MidSample, Majority16, Majority8 and EdgeResync all flip between L = 16 and 17.
- **Only P2 separates the three mid-bit samplers.** The predicted glitches
  behave as written: a 3-clock glitch centred at 16 flips MidSample only, and a
  5-clock one flips Majority16 but not Majority8. Removing P2 makes the three
  pairwise inseparable.
- **P3 as specified separates only LenientStop.** A receiver that accepts a
  short false start is two bits out of step with the real frame, and 0x55
  repeats every two bits, so it still decodes 0x55. In the pure-Python models
  only, byte 0x0F with the same timing would separate MidSample from the
  start-validating receivers. That is a candidate change for the next owner,
  not made here.
- **P4 separates EdgeResync and LenientStop,** not the three mid-bit samplers.

Deviations from the plan:
- **Wall time is not in `reports/fingerprint.json`,** because it would break
  the byte-for-byte check. The report records the run count and bus clocks;
  wall time goes to `build/fingerprint-timing.json`, and to
  `test/fingerprint-timing.json` as a CI artifact. Locally it is 51–55 s.
- **No reduced grid.** Ten runs took 0.56 s, so the full grid runs in CI and
  there is no `FINGERPRINT_FULL`.
- **`identify` is async,** because engine runs are coroutines. It still sees
  only the `run_probe` callable.
- **Tick phase is defined against the fixture's time zero** (the first clock
  lane 0's output enable is asserted). Ticks fall where t mod tick == p, and
  every probe's first start edge is at t = T, so phase p means the edge is
  detected p clocks late.
- **Confirmation rule.** The plan said only "chosen deterministically". The
  rule used: unused probes on which all of the leaf's variants agree,
  preferring probes next to one of the leaf's own verdict boundaries, one
  family at a time and lowest index first, then the rest by index. It was fixed
  before the engine runs and has not been changed since. It often picks the
  side of a boundary where every receiver agrees (P1 L=16, P3 W=16), which is
  why the round-1 phase errors and the left-out control got through. A
  map-informed rule (probes where the leaf's verdict is rare among mapped
  receivers) is the obvious next step. Re-run the left-out control afterwards
  and say that the rule changed after seeing it.
- **Model details the plan left open:**
  - Majority16 and Majority8 share one `_Majority` implementation with the
    ratio as a parameter; the other models are independent.
  - LenientStop takes the stop sample at T/2 + 9T but ignores it.
  - In EdgeResync, a transition on the clock a sample was due moves that sample.
- **P2 order:** probes are enumerated with W outer and offset inner, which sets
  the tie-break order.
- **Local simulator.** This machine had no `iverilog`, so Icarus 12.0 was
  extracted from the Ubuntu package into `~/.local/opt/iverilog-12.0`; wrapper
  scripts in its `bin/` pass `-B`/`-M`. CI uses apt's 12.0 on ubuntu-24.04.

## Requested outcome
Turn the fault demo from "the chip can inject a fault" into "the chip can tell
which receiver it is talking to." Drive families of precisely timed, malformed
UART frames at several independently written receiver models. Read each
receiver's verdict back through the capture FIFO. Show that the verdicts alone
identify the receiver, using a short adaptive probe sequence that reports
equivalence classes honestly and answers "unknown" when nothing fits.

Why: in the current demo the response latency (103 / 59 clocks) is a model
parameter. The demo therefore shows that the instrument works, not that it can
find anything out. Here the measured quantity is where each receiver's
accept/reject boundaries fall. That is a property of the receiver's algorithm,
not of a number we chose. A likely finding to confirm or refute is that the
existing stop-bit-shortening probe cannot separate receivers that sample
symmetrically around mid-bit, and that mid-bit glitches, idle false starts and
bit-period skew can.

## Constraints and acceptance criteria

Constraints:
- `src/` is untouched. The 22 RTL tests, `reports/fault-demo.json` and
  `reports/fault-sweep.json` stay byte-identical (CI already `cmp`s them).
- The engine is a black box. Stimulus is firmware loaded through the host port,
  and verdicts come from `Host.captures()`. The fixture may read model
  internals only to cross-check decoding, never to feed the classifier.
- Every program fits in 64 words and every `hold` is ≤ 8,192 clocks. `capture`
  follows `stream`. The sticky error page (`page(10)`) is 0 after every run,
  so there is no capture overflow.
- Deterministic: fixed seeds, sorted keys, and a byte-identical report across
  runs.
- The default is 32 clocks/bit, matching the existing sweep.

Acceptance criteria:
- Every run: the verdict decoded from captures equals each attached model's
  own verdict, and every attached receiver reports exactly once. The fixture's
  observed lane-0 edges equal the probe waveform clock for clock, in the same
  spirit as `measured == fault` in `test_sweep.py`.
- The map states, for every pair of main receivers, whether some probe
  separates them, and which probe.
- Blind identification names each main receiver correctly, including every
  tick phase of the oversampling receivers. The report records the probes
  used per identification.
- Every negative control in the table below behaves as stated, and each is
  recorded in the report.
- `just fingerprint` reproduces `reports/fingerprint.json`, and CI checks it
  byte for byte.

## Design

### Receiver models: `test/receivers.py`

These models are independent of the engine and of each other. Each is a
per-clock callable in the style of `UARTReceiver`: it reads the driven lane-0
level, treating released as idle high. Times below are engine clocks from the
start edge the receiver detected, at T clocks/bit.

| Model | Start handling | Sampling | Stop check |
| --- | --- | --- | --- |
| `MidSample` | Any falling edge from idle starts a frame; no validation | One sample at T/2 + kT | Yes |
| `Majority16` | Edge seen at a tick (tick = T/16, phase p); start-bit majority must be 0, else return to idle | Majority of ticks 7, 8, 9 of each bit (clocks 14, 16, 18 at T=32) | Yes |
| `Majority8` | As `Majority16`, tick = T/8 | Majority of ticks 3, 4, 5 (clocks 12, 16, 20) | Yes |
| `EdgeResync` | Falling edge; start validated at T/2 | After every transition inside a frame, the next sample is at transition + T/2, then every T | Yes |
| `LenientStop` | Falling edge; start validated at T/2 | One sample at T/2 + kT | No (never reports FRAME) |

Controls, used only by the negative controls:

| Model | Definition |
| --- | --- |
| `MidSampleTwin` | Same behavior as `MidSample`, written separately with a different code structure |
| `MidSamplePlus1` | `MidSample` sampling one clock later (T/2 + 1 + kT) |

Each model's docstring states its algorithm in one paragraph. Don't name a
commercial part as equivalent unless the write-up cites its datasheet.

`MidSample` must reproduce the existing `UARTReceiver` verdicts on the
existing sweep's probes, as a consistency check. `UARTReceiver` itself stays
unchanged.

Pure-Python checks against hand-built waveforms run without the simulator
(plain asserts, invoked from CI). Cover each model's boundary cases:
- glitch widths straddling each sample set
- false starts
- skew that drifts one sample across a bit edge

### Verdict report convention

This is a fixture convention, and the write-up says so. Each receiver owns one
report lane: lanes 1–4, which the UART programs never enable. Every receiver
raises its lane at the same fixed time, a constant offset after lane 0's
output enable first asserts. It holds the lane high for a width that encodes
its first completed frame's verdict:

| Verdict | Meaning | Width (clocks) |
| --- | --- | --- |
| OK | Stop high, byte equals the sent byte | 4 |
| DATA | Stop high, byte differs | 8 |
| FRAME | Stop sampled low | 12 |
| NONE | No frame completed before the report time | 16 |

All rising edges coincide, so they share one capture entry, and the falling
edges add at most four more. That leaves at most five entries in an
eight-entry FIFO, regardless of which receivers are attached or what they
decide. Decoding uses only fall − rise per lane, so it doesn't depend on
synchronizer depth or on when a receiver decided. Capture mask:
`0b11110`. Don't capture lane 0, because the fixture verifies the stimulus
instead.

### Probes and firmware: `tools/fingerprint.py`

`waveform_program(segments, report_at, mask)` returns:

```
[stream(1), capture(mask)]
+ [drive(level, 1, clocks) for each merged segment]
+ [drive(1, 1, 1)]
+ [hold(...) until report_at + 16 + margin]
+ [capture(0), HALT]
```

Adjacent equal-level segments merge, and the function raises `ValueError` on
any limit violation.

Probe families at T = 32. The total is 179 probes per receiver group:

| Family | Waveform | Grid | Probes |
| --- | --- | --- | --- |
| P1 stop-short | Byte 0xFF; stop bit low for L clocks from its start | L = 0..31 | 32 |
| P2 mid-bit glitch | Byte 0xFF; low pulse inside data bit 3 | Offset o = 8..24 clocks into the bit × width W ∈ {1, 2, 3, 4, 5, 6, 8} | 119 |
| P3 idle false start | Byte 0x55; low pulse ending 2T before the real start bit | W ∈ {1, 2, 4, 8, 12, 15, 16, 17, 20, 24} | 10 |
| P4 bit-period skew | Whole frame at T + δ clocks/bit | δ = −4..+4, bytes 0x55 and 0x0F | 18 |

Four receivers share one run on lanes 1–4, so there are two groups:
- Group A: `MidSample`, `Majority16`, `Majority8`, `EdgeResync`
- Group B: `LenientStop`, `MidSampleTwin`, `MidSamplePlus1`

Before building the full grid, time 10 runs and extrapolate. If the CI step
would exceed about 10 minutes, use offset step 2 in P2 for CI and put the full
grid behind `FINGERPRINT_FULL=1`.

### Map, decision tree, blind identification

1. **Map.** For every probe, record each receiver's verdict as decoded from
   captures, and assert it equals the model's internal verdict. Build it at
   tick phase 0.
2. **Tree.** Build it greedily: at each node, pick the probe that minimizes
   the largest group of remaining candidates; break ties by lowest probe
   index. A leaf is a single receiver or an equivalence class that no probe
   separates.
3. **Identify.**
   - Inputs: `identify(run_probe)` receives only a callable that runs a probe
     and returns decoded verdicts. It never sees a model object.
   - Walking the tree: an outcome with no matching branch returns `unknown`.
   - Confirmation: at a leaf, run three confirmation probes, chosen
     deterministically from probes the tree did not use. Any mismatch returns
     `unknown`.
   - Phases: run each oversampling receiver at every tick phase. If a phase
     fails, make that receiver's signature the set of signatures across
     phases, rebuild the tree, and say so in the report.
4. **Ablation.** Rebuild the tree with each probe family removed, and report
   which receiver pairs become inseparable.

### Negative controls

| Control | Expected result |
| --- | --- |
| `MidSampleTwin` in the map | Identified as the class {`MidSample`, `MidSampleTwin`}, not one or the other |
| `MidSamplePlus1` in the map | Identified as itself; the separating probe is recorded (resolution: one clock) |
| `MidSamplePlus1` left out of the map | `unknown`. If the confirmation probes miss it, report that as a limit of the probe set; don't tune the probes until it passes |
| Labels shuffled in the map | Identification is wrong for at least one receiver, and the control detects it |
| Decode thresholds shifted by one width class | The verdict cross-check fails |

## Evidence gathered (repo, October 10, 2026)

- `fault_demo` builds the frame from `uart_tx(...)[:-2]` DRIVEs and then
  drives the stop-bit fault. `capture(17)` records lanes 0 and 4. The
  eight-entry capture FIFO stores simultaneous lane changes as one entry,
  which is why the existing sweep restricts bytes to at most 8 edges.
- UART programs enable only lane 0, so lanes 1–4 are free for report pins.
- DRIVE holds 1–262,144 clocks; PATCH/`hold` holds 1–8,192. `encode` enforces
  64 words, and `capture` requires `stream` first.
- The lane-4 synchronizer is 3 clocks (`SYNC_CLOCKS`). Pulse widths survive
  synchronization; the sweep asserts width 11.
- `UARTReceiver` samples once at T/2 + kT and asserts that the start sample is
  0. Its stop sample at clock 16 is the sweep's 16/17 boundary.
- Hypothesis to test: `MidSample`, `Majority16` and `Majority8` all center on
  clock 16, so P1 alone may not separate them. Expect P2 to: a 3-clock glitch
  centered at 16 flips `MidSample` only, and a 5-clock one flips `Majority16`
  but not `Majority8`. Report what actually happens; don't fit the models to
  these expectations.

## Proposed changes

- `test/receivers.py`: models, plus the pure-Python checks in a
  CI-invocable script.
- `tools/fingerprint.py`: probe definitions, `waveform_program`, verdict
  decoding, tree builder, `identify`.
- `test/test_fingerprint.py`: cocotb map, identification and controls; it
  writes `FINGERPRINT_REPORT`.
- `justfile`: a `fingerprint` recipe.
- `.github/workflows/test.yaml`: a fingerprint step plus `cmp` against
  `reports/fingerprint.json`.
- `reports/fingerprint.json`, containing:
  - receivers with parameters, and probes
  - the map and the tree
  - identifications (receiver, phase, probes used, answer)
  - controls, ablation, run count and wall time
- `docs/verification.md`: a new "Receiver fingerprinting" section.
- `docs/submission.md`: under distinctive functionality, add "identifies which
  of N receiver algorithms is attached in K probes, at one-clock resolution,
  in simulation," plus rows in the results table.
- `README.md` and `docs/roadmap.md`: one line each.
- This handoff: set status Done and fill in the evidence.

## Verification

```sh
python test/receivers.py                         # model checks, no simulator
just test                                        # 22/22, unchanged
just fault-sweep && cmp build/fault-sweep.json reports/fault-sweep.json
just fingerprint && cmp build/fingerprint.json reports/fingerprint.json
```

Results, October 10, 2026 (local; Icarus 12.0, Python 3.12, cocotb 2.0.1):
- `python test/receivers.py`: passed. It includes all 100 recorded sweep
  verdicts, and four planted model errors each fail it.
- 22/22 RTL tests, and `fault-demo.json` is byte-identical.
- `just fault-sweep`: 1/1 test, and `fault-sweep.json` is byte-identical.
- `just fingerprint`: 1/1 test, 1,061 runs, 51–55 s. `fingerprint.json` was
  byte-identical over four runs, one after the review fix below.
- `git status src`: clean.
- A diff-only review found one defect: the identification round loop could
  spin forever if a receiver without tick phases ever failed. It now stops
  and fails, and the report is unchanged. The review also found the
  shuffled-label control wrong by construction; the verification write-up now
  says so.

## Risks, open questions, and next owner

- **Scope of the claim.** The models are idealized. Real receivers run on
  their own asynchronous clocks, with ppm error and metastability. The claim
  is that the instrument distinguishes these algorithms in simulation, not
  that it identifies real parts.
- **The report pins are a fixture.** A real device would expose its verdict
  through its own firmware, for example an echo or an error flag.
- **Simulation time** is the main schedule risk; measure it before committing
  to the grid.
- **Next owner: on-chip closed-loop search.** That step is a separate RTL
  handoff: a duration register plus a register-timed DRIVE, so firmware walks
  this tree itself and pushes only the answer. It requires re-layout, formal
  updates and gate-level reruns, and should land by mid-December. This work
  defines the probes that step would run.
