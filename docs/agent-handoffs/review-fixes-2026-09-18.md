# Review fixes: demo timing, restart timeout, sweep fault check, S5 coverage

## Status
Done (committed a32bcdc; CI test run 35418119540 22/22; RTL 22/22, sweep 100/100, formal 7/7 and streaming 9/9 controls, SDF 12/12)

## Requested outcome
Fix the four issues found in the review of `main` at 3d35878 and add negative
controls for each, then rerun the firmware tests against the routed netlist.

## Constraints and acceptance criteria
- `fault_demo` never accepts settings whose modeled response the firmware
  cannot see; the bound is explicit and its tightness is tested.
- The repeated-START timeout test stretches only the SCL release before the
  repeated START, and a below-timeout stretch at the same point succeeds.
- The fault sweep checks that the requested fault length actually occurred and
  that the receiver's verdict follows from it.
- Property S5 covers every CAPTURE sub-op; a CAPTURE-guard mutation is detected.
- RTL unchanged; gate-level SDF regression rerun on the existing routed netlist.

## Evidence gathered
- Timing sweep in simulation: with the old firmware, 64 clocks/bit passed up to
  a 102-clock fault and failed from 103; faults shorter than a bit at 64
  clocks/bit and clean frames at 87 clocks/bit also missed the response, since
  the watch only began a full bit period after the stop bit started.
- Old timeout test set `stretch = 1000` after the host sends, i.e. during the
  address byte; the fault came from `_i2c_send`, not the restart sequence.
- Old S5 excluded `instruction[27:24] == 1` for both opcode C (STREAM) and
  opcode D (CAPTURE), so CAPTURE's guard was outside the property.

## Proposed or completed changes
- `tools/streaming.py`: `fault_demo` releases the line one clock after the
  fault and watches at once; `fault_demo_limit()` bounds the fault length from
  the modeled response (`FAULT_RESPONSE`, `FAULT_PULSE`, `SYNC_CLOCKS`);
  invalid settings raise `ValueError`; wait timeout derived from the model.
- `test/test_streaming.py`: `RegisterTarget(stretch_after_bytes=)` arms the
  stretch only after the Nth ACKed byte; timeout case asserts both write bytes
  were ACKed and no repeated START or read happened, plus a below-timeout
  control. New test `fault_demo_bounds` (limit passes, limit+1 rejected,
  limit+1 built for a slower target faults, wide-bit cases pass).
- `test/test_sweep.py`: measures the lane-0 low time from the stop-bit start,
  asserts it equals the requested fault and that the verdict matches the
  mid-bit sample; report gains `measured_fault_clocks`.
- `formal/properties.vh`: S5 covers all C sub-ops except STREAM and all D.
- `tools/check_formal_mutations.py`: `capture_without_stream` control.
- `tools/check_streaming_mutations.py`: module-qualified test names; controls
  `restart_wait_unbounded`, `fault_watch_after_full_stop_bit`, `clean_frames_only`.
- `docs/streaming.md`: fault-demo paragraph updated.
- `test/test_streaming.py`: `driven(d)` reads the bidirectional pins tolerating
  X only on lanes whose output enable is low (gate-level flops nothing has
  written yet), asserting otherwise; the peer models use it so a streaming test
  can run alone on the netlist.
- `justfile`: `test-sdf` defaults to `build/run-streaming`, the layout recorded
  in `reports/cmos5l-layout.json`; `build/run-docker` is the pre-streaming
  baseline and STREAM faults on it.

## Verification
See the section appended to `docs/verification.md` and the logs under `build/`
(`rtl-regression-review.log`, `sdf-review-*.log`, `formal-review.log`,
`streaming-mutations-review.log`).
