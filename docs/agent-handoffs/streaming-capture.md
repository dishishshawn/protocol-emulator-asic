# Streaming and timestamped capture

## Status
Done (reviewed and committed; CI gds/sdf on this revision pending)

## Requested outcome
Add buffered host transfers, multi-byte protocol programs, UART receive, I²C read,
and a reproducible timed-fault/target-response capture demonstration.

## Constraints and acceptance criteria
- Work in `/home/shawnion/Desktop/protocol-emulator-asic`; one implementation writer.
- Preserve the legacy loader, ISA programs, and halted receive-byte page.
- Keep the 64-word store and 6×4 allocation; FIFOs use available flip-flop area.
- Check FIFO backpressure, overflow, simultaneous operations, abort/reset, independent
  protocol peers, and exact timestamp deltas through the external pins.
- Rerun synthesis and the physical flow after RTL verification. Existing physical
  reports describe the earlier RTL until replaced by new evidence.

## Evidence gathered
- Clean main at b702e23, physical-build handoff, engine, assembler, tests, and justfile read.
- Existing interface uses five protocol lanes and three host controls. Streaming
  can reuse LOAD as a byte strobe and REWIND as data/command select while RUN is high.

## Proposed or completed changes
- `src/engine.v`: opt-in streaming, 8-byte TX/RX FIFOs, outer loop counter,
  8-entry timestamp capture FIFO; unchanged synchronous instruction fetch.
- `tools/program.py`, `tools/streaming.py`: encoders, streaming firmware and host helpers.
- `test/test_streaming.py`: black-box regressions and timed-fault demonstration.
- Documentation and evidence updated after verification.

## Verification
- Ran: `make -C test` (RTL, Icarus 12, cocotb 2.0.1) — TESTS=20 PASS=20 FAIL=0 (ten legacy + ten streaming), log `build/rtl-regression-astra.log`.
- Ran: `tools/check_streaming_mutations.py` — 5/5 mutations detected after fixing the harness (cocotb lists filtered-out tests as skipped, so the "exactly one testcase" check never matched). Report copied to `reports/streaming-mutations.json`.
- Ran: `just capture-demo` — pass; evidence copied to `reports/fault-demo.json` and rendered to `reports/fault-demo.svg` via `tools/plot_capture.py`.
- Ran: generic Yosys synth — 5,649 → 7,058 cells (+25%); the 6×4 block was 27.9% utilized before, so area is not a concern.
- Fixed: README/roadmap said eighteen regressions; it is twenty.
- Ran: `tools/harden.sh` on the new RTL — Flow complete; 18,776 cells, 34.1% utilization, setup WS +57.45 ns, hold WS +0.122 ns, route DRC 0, Magic DRC 0, LVS 0, antenna 0 (`reports/cmos5l-layout.json`). `gds` run 35117387247 and the `sdf` workflow are running on GitHub.
- Not run: `just test-mapped` on the new RTL; SDF corners on the new layout (CI will do these).

## Risks, open questions, and next owner
- Host service can stall the engine only at explicit FIFO instructions; firmware
  must place these at safe protocol boundaries. UART has no wire backpressure.
- Capture timestamps measure synchronized digital inputs, not analog edge times.
- Astra implements and verifies; independent diff review before commit.
