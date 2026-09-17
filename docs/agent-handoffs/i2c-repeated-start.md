# I²C repeated START (register read)

## Status
Done

## Requested outcome
A streaming I²C program that writes a register address then reads back data
without releasing the bus: START, address+W, k bytes, repeated START,
address+R, n bytes, NACK, STOP. This is the transaction every register-mapped
I²C device needs and the docs currently list it as missing.

## Constraints and acceptance criteria
- No RTL change unless the 64-word store cannot hold the program.
- The wired-AND target must observe exactly one START, one repeated START
  (START while a transaction is open), one STOP, and correct ACK polarity.
- Verified data: the target serves `registers[pointer]` and the host receives
  the bytes from the written pointer onward; a NACK on the write phase and a
  stretch timeout still terminate with STOP then TRAP.
- A mutation control that removes the repeated START must be caught.

## Evidence gathered
- `src/engine.v`: STREAM (C1) may be re-executed to reload the outer byte
  counter; LAST_BYTE (C5) branches when the counter is one. Neither touches
  `tx_shift`, so a repeated START can be inserted between PULL and the send loop.
- `tools/streaming.py`: `i2c_read` is 51 words. Inlining a second send macro
  would exceed 64 words, so the write phase pulls every byte, including the
  final address+R byte, from the TX FIFO and one send loop serves all of them.

## Proposed or completed changes
- `tools/streaming.py`: `i2c_transaction(write_count, read_count, ...)` and
  the `i2c-transaction` CLI protocol.
- `test/test_streaming.py`: `RegisterTarget` and `i2c_repeated_start_register_read`.
- `tools/check_streaming_mutations.py`: control that replaces the repeated START
  with a plain hold.
- Docs: `docs/streaming.md`, `docs/info.md`, `docs/roadmap.md`, README.

## Verification
- Ran: `make -C test` — TESTS=21 PASS=21 FAIL=0 (`build/rtl-regression-repstart.log`).
- Ran: `tools/check_streaming_mutations.py` — 6/6 detected, including
  `skip_repeated_start` (`reports/streaming-mutations.json`).
- Ran: `just synth` — 7,058 generic cells, unchanged (no RTL change).
- Program is 62 of 64 words; `encode()` enforces the limit.
- Not rerun: physical flow, SDF, CI gl_test (RTL is unchanged apart from the
  `ifdef FORMAL` include, which synthesis and Icarus ignore).

## Risks, open questions, and next owner
- The host supplies address+W, register bytes and address+R; the firmware is
  address-agnostic. A host that pushes the wrong final byte gets a write, not
  a read; the test covers the intended sequence and the NACK path.
