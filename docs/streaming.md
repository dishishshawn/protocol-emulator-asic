# Streaming and timestamped capture

`tools/streaming.py` supplies firmware for transfers of 1–255 bytes using the
same 64-word instruction store. Programs may loop or reinitialize the byte
counter to handle longer streams. TX and RX each have an eight-byte FIFO;
capture has eight 32-bit entries. These are flip-flop memories.

Generate example images with `just stream-demo`, or customize a transfer:

```sh
uv run --python .venv/bin/python tools/streaming.py spi.bin --protocol spi --count 32 --mode 3
uv run --python .venv/bin/python tools/streaming.py read.bin --protocol i2c-read --address 0x50 --count 8
uv run --python .venv/bin/python tools/streaming.py regread.bin --protocol i2c-transaction --write-count 3 --count 4
```

Load the generated image with the original loader, start RUN, then use the host
interface below to supply TX data or drain RX. Bytes are not embedded in the image.

## Host connection

Loading firmware with RUN low is unchanged. Firmware opts into streaming with
STREAM before the new commands are accepted. With RUN high:

- REWIND=0 and a LOAD rising edge enqueue ui[7:0] in the TX FIFO.
- REWIND=1 and a LOAD rising edge interpret ui[7:0] as a command.
- REWIND=0 selects the original status output.
- REWIND=1 selects the read page last chosen by a command. Page 0 is the default.

Hold ui and REWIND stable with LOAD low for four clocks, LOAD high for four
clocks, then LOAD low for four clocks before changing ui or REWIND. Read uo
after the final four clocks. Controls and protocol inputs pass through two
synchronizer stages; ui uses this bundled-data timing contract. One host owns
the interface; concurrent host callers must serialize complete transactions.

| Command | Meaning / byte returned on the selected page |
| --- | --- |
| 00 | Select legacy RX shift-register page |
| 01 | Select flags: bit 7 fault, 6 running, 5 halted, 4 streaming enabled, 3 any host error, 2 TX space, 1 RX available, 0 capture available |
| 02 | Select TX occupancy (0–8) |
| 03 | Select RX occupancy (0–8) |
| 04 | Select oldest RX byte; zero when empty |
| 05 | Select capture occupancy (0–8) |
| 06–09 | Select successive bytes of the oldest capture entry, least significant first; zero when empty |
| 0A | Select sticky errors, described below |
| 80 | Pop one RX byte; retain selected page |
| 81 | Pop one capture entry; retain selected page |
| 82 | Clear sticky errors; retain selected page |

Page reads are nondestructive. Read RX then pop it. Read all four capture bytes
then pop that entry; the head remains stable while new entries arrive. Unused
RAM entries are never exposed. Other commands are rejected with error bit 4.

Error bits: 0 TX push when full, 1 RX pop when empty, 2 capture pop when empty,
3 capture overflow, 4 invalid command, 5 timestamp wrapped while running.
Invalid host operations do not fault the protocol engine or change queue
contents. Clear and a new error on the same clock retains the new error.

Check streaming-ready and TX-space before pushing. Only the engine removes TX,
so free space cannot disappear between the host's check and push. Only the host
removes RX/capture, so an available head cannot disappear between check and pop.
Full/empty checks use occupancy before the clock edge: a push to a full queue
is rejected even when a pop occurs on the same edge. Retrying next clock is safe.

PULL stalls on empty TX; PUSH stalls on full RX. All outputs keep their state
during a stall. SPI programs stall with SCK at its idle level and CS asserted;
I²C programs stall with SCL low. UART TX stalls with its line idle. UART RX has
no flow-control wire: its sender must pause between frames if host service
cannot keep up. These are explicit firmware stall points, not automatic pauses
in the middle of a bit.

HALT/fault releases output enables but retains queues and read pages while RUN
stays high. Lowering RUN, deselecting, or resetting clears every queue, error,
and capture configuration. As before, lower REWIND before lowering RUN if you
want to preserve the loaded program. After deselection, toggle RUN low then high.

`Host(exchange)` is a transport-independent async helper. Its `send`, `receive`,
and `captures` methods implement polling, peeking and popping; `exchange` must
implement the timing above. `receive` handles a final PUSH followed by HALT
between status reads. Polls are bounded by `poll_limit`. It is not a USB/serial
driver and does not invent a physical host adapter.

## ISA additions

Opcodes C and D use [27:24] as a subopcode; unused subopcodes fault. Other
reserved bits are ignored, consistent with the original ISA.

| Word prefix | Instruction | Operands / behavior |
| --- | --- | --- |
| C1 | STREAM | [7:0] byte count, 1–255; enable host streaming and set independent outer counter. Does not flush queues. |
| C2 | PULL | Wait for TX byte, load TX, clear RX and set bit-loop count to 8 |
| C3 | PUSH | Wait for RX space, append RX shift register |
| C4 | BYTE_LOOP | [5:0] target; decrement outer counter and branch if still nonzero; initial zero faults |
| C5 | LAST_BYTE | [5:0] target; branch if outer counter=1; zero faults |
| D1 | CAPTURE | [4:0] input mask; record both edges of those synchronized inputs; zero disables |

C2–C5 and D1 fault unless STREAM has run. C0 and opcode E remain invalid, so
the old invalid-opcode tests remain valid. No legacy instruction changed.

## Timestamps

The counter starts at zero on the accepted RUN rising edge and advances once
per engine clock. Each entry is `{timestamp[23:0], 3'b000, synchronized_pins[4:0]}`.
Capture watches input changes while the engine is running, including during
delays and FIFO stalls. Multiple changed lanes in one clock produce one entry.
Enabling capture does not synthesize an initial-state event. A mask update takes
effect on the next clock; an edge on the instruction's execution clock is
evaluated with the previous mask. Capture stops after HALT/fault, with any edge
on that final execution clock evaluated normally.

When full, capture drops new entries, preserves the first eight and sets its
overflow flag; it never stalls protocol execution. Host draining permits later
events to be recorded. Timestamp differences are modulo 2²⁴; wrap occurs every
1.6777216 seconds at 10 MHz. The wrap error remains sticky until cleared.

These are timestamps of synchronized digital observations at 100 ns resolution,
not analog measurements. Inputs must remain stable long enough to be sampled;
short pulses can be missed. Metastability can add uncertainty in physical use.
For output-loopback capture the board must feed the driven voltage back into the
lane input; the simulator peer supplies this electrical feedback explicitly.

## Firmware and limitations

- `spi_stream`: one CS assertion for 1–255 full-duplex bytes; all four modes and
  both orders. Host starvation stretches idle SCK phases, not active bits.
- `uart_tx_stream`: lane 0, 8N1, exact bit periods of 4–8192 clocks. Extra idle
  clocks between frames accommodate instruction overhead and host starvation.
- `uart_rx`: lane 0, 8N1, 12–8192 clocks/bit; checks the middle of start and stop
  bits, faults on bad framing or bounded wait timeout. No oversampling/baud
  detection. Tests include back-to-back frames and transitions on either side
  of the clock edge; they do not establish a guaranteed baud-error tolerance.
- `i2c_write_stream`: a 7-bit address and 1–255 data bytes, ACK/NACK, stretching,
  and transmitted-bit contention checks.
- `i2c_read`: address+read, 1–255 bytes, ACK every byte except a final NACK, then
  STOP. RX backpressure holds SCL low before the ACK/NACK clock.
- `i2c_transaction`: write then read joined by a repeated START, the register
  read every memory-mapped I²C device needs. The host pushes `write_count`
  bytes: address+W, the payload (usually a register pointer, optionally data),
  and address+R last; the firmware is address-agnostic. Before that final pushed
  byte it releases SDA with SCL low, releases SCL, waits for SCL and SDA high
  (bounded, so a stretching or stuck target times out), then pulls SDA low with
  SCL high: a START without an intervening STOP. It then re-arms the byte
  counter with STREAM and runs the `i2c_read` receive loop. Any NACK during the
  write phase produces STOP then TRAP, as for the other I²C programs. Still
  absent: bus recovery, arbitration loss handling beyond CHECK_TX, and full
  multi-controller mode.

I²C's default holds remain 50 clocks. Minimum holds are four clocks; this is a
digital synchronization minimum, not an electrical speed/compliance guarantee.

## Controlled-fault demonstration

`fault_demo(False)` sends UART FF with a valid stop bit. `fault_demo(True)` drives
that stop bit low for exactly 32 clocks, then restores idle. Both capture UART
echo on lane 0 and a modeled target response on lane 4. The independent UART
peer detects the framing result, then emits an eleven-clock response pulse:
103 clocks after a normal stop sample or 59 after a framing error. Those target
latencies are demonstration parameters, not measured hardware behavior.

`fault_demo(byte=..., fault_clocks=n)` generalizes this: the stop bit is driven
low for exactly `n` clocks (0 is a clean frame), the line is released to idle
one clock later and the firmware watches lane 4 from then on, so the stop bit
is never shorter than a bit period and the watch never waits for a full bit
first. The response window is bounded by the modeled target:
`fault_demo_limit(cycles_per_bit)` (half a bit plus 71 clocks: 59-clock
latency, 11-clock pulse, 3-clock synchronizer) is the longest fault whose
response the firmware can still see, and longer requests raise `ValueError`
instead of producing a firmware that times out. `fault_demo_bounds` runs the
limit and, as a negative control, the limit plus one built for a
one-clock-slower target, which faults on the bounded wait. `just fault-sweep`
runs `test/test_sweep.py`: 20 fault lengths × 5 bytes, each a full engine run
whose captured events must match the independent receiver's edge list with a
constant synchronizer offset and no capture overflow, whose measured low time
from the start of the stop bit must equal the requested fault length, and
whose framing verdict must follow from the receiver's mid-bit sample. The result
(`reports/fault-sweep.json`) is embedded in `docs/fault-sweep.html`, an
interactive page where the slider selects a real run. Bytes are chosen so a
frame, its fault and the response fit the eight-entry capture; an alternating
byte would need host draining mid-run.

Run `just capture-demo` to regenerate the JSON evidence under `build/`. The test
checks every recorded pin value against external edges and requires a constant
synchronizer offset, exact inter-edge intervals, no capture overflow, and the
expected valid/bad stop bit. It uses the real host port to read capture entries.
