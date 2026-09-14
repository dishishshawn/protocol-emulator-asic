# How it works

The engine executes up to 64 writable 32-bit instructions and operates five
bidirectional lanes. A byte transmit register, byte receive register and loop
counter support firmware-driven serial protocols. Program memory is not reset;
only completely loaded words are executable. The current instruction store
maps to flip-flops, not a foundry SRAM macro.

## Instruction encoding

All words use opcode [31:28]. Reserved operand bits are ignored.

| Op | Name | Operands | Execution |
| --- | --- | --- | --- |
| 0 | DRIVE | [27:10] clocks−1, [9:5] OE, [4:0] value | Set all lanes, hold 1–262144 clocks |
| 1 | WAIT | [27:10] mismatch limit, [3] level, [2:0] lane | Wait for synchronized input; zero limit means unbounded |
| 2 | JUMP | [5:0] address | Absolute branch, one clock |
| 3 | SAMPLE | None | Copy five synchronized inputs into status, one clock |
| 4 | LOAD | [15:8] count, [7:0] transmit byte | Set TX/count, clear RX, one clock |
| 5 | OUT | [4] open-drain, [3] LSB-first, [2:0] lane | Emit TX end bit and shift TX with zero fill, one clock |
| 6 | IN | [3] LSB-first, [2:0] lane | Shift synchronized bit into RX, one clock |
| 7 | DJNZ | [5:0] address | Decrement count and branch if still nonzero; initial zero faults |
| 8 | BRANCH | [9:4] address, [3] level, [2:0] lane | Branch on synchronized input, one clock |
| 9 | CHECK_TX | [2:0] lane | Fault if input differs from the bit emitted by the most recent OUT |
| A | TRAP | None | Explicit firmware fault, releases lanes |
| B | PATCH | [27:15] clocks−1, [14:10] mask, [9:5] OE, [4:0] value | Update selected lanes, hold 1–8192 clocks |
| F | HALT | None | Stop normally, release lanes |

C–E fault. Lane indices 5–7 fault. Falling or jumping outside the loaded image
faults; sequential execution cannot wrap past word 63. A bad jump target faults
on the next instruction-fetch clock. Firmware can ignore reserved bits, but
software encoders validate all defined fields.

MSB-first OUT emits TX[7], shifts left and fills bit zero. LSB-first emits TX[0]
and shifts right. MSB-first IN shifts RX left and appends the input; LSB-first IN
shifts RX right and inserts the input at bit seven. Eight IN operations recover
a byte in the selected order. OUT modifies only its lane. Open-drain OUT always
sets output data low, enables for a zero bit and releases for a one bit.

All instructions act on rising clock edges. Consecutive DRIVE or PATCH
instructions update exactly the requested number of clocks apart. Other
instructions consume their execution clocks while retaining outputs. A PATCH
with mask=0 acts as a pure delay.

WAIT counts nonmatching execution clocks, faults on the Nth mismatch for a
nonzero limit N, and clears its elapsed count on success or program start.
A match at the boundary succeeds. Inputs pass through two synchronizer
registers; a physically present change may therefore still count as a mismatch
until visible to the engine. CHECK_TX uses the same synchronized inputs, so
firmware must allow settling time. CHECK_TX alone is not a full multi-controller
arbitration/recovery implementation.

Fault/HALT release all output enables. Reset clears execution, program length,
loader state, TX/RX/count, and last transmitted bit. Reset/deselection also
combinationally gate off output enables. Assert reset for at least five clocks
with controls low; deassertion must meet clock setup/hold in hardware.

# How to test

Run `just setup`, `just test`, and `just demo`. The regression loads firmware
through the external host port and checks output pins. SPI and I²C peers decode
bus activity without inspecting internal engine signals or instruction memory.
See `verification.md` for measured results and limitations.

## Host interface

| Pins | Function |
| --- | --- |
| ui[7:0] | Host byte data |
| uio[7] | LOAD strobe input; rising edge captures a byte |
| uio[6] | RUN input; rising edge starts at word zero; low aborts |
| uio[5] | REWIND while RUN=0; RX result-page select while RUN=1 and halted |
| uio[4:0] | Protocol lanes |
| uo[7:0], normal page | {FAULT, RUNNING, HALTED, SAMPLE[4:0]} |
| uo[7:0], RX page | Full receive byte |

Control and lane inputs have two synchronizer stages. The host byte bus uses
a bundled-data contract: hold data with LOAD low for at least four clocks,
hold the same data and LOAD high for at least four clocks, then hold LOAD low
for at least four clocks before changing data. There is no ready/ack signal.

1. With RUN/LOAD low, hold REWIND high five clocks, then low five clocks.
2. Send four bytes per instruction, least significant byte first, at most 64 words.
3. After the final LOAD falling edge, wait five clocks, then raise RUN.
4. Observe HALTED/FAULT on the normal page. To read RX, keep RUN high, raise
   uio[5] for five clocks, and read all eight outputs. Lower uio[5] for five
   clocks to return to status. This does not erase memory while RUN remains high.
5. Lower RUN for five clocks before restarting. If uio[5] is still high when
   RUN goes low, it becomes REWIND and clears the image.

Empty, partially loaded or overflowed images fail at start. REWIND clears the
loader error. Loading/rewinding is ignored during RUN. Aborting preserves the
image; reset erases its validity. FAULT/HALTED clear when synchronized RUN goes
low or the design is deselected. Reselecting with RUN already high does not
restart; toggle RUN low then high.

## Firmware demonstrations

- UART: lane 0, one 8N1 byte, idle preamble, then release.
- SPI: lane 0 SCK, 1 MOSI, 2 MISO, 3 CSn. One full-duplex byte, CPOL/CPHA modes
  0–3, MSB- or LSB-first; RX page returns the target response. Minimum phase hold
  is four clocks for synchronization. Instruction overhead affects duty cycle.
- I²C: lane 0 SCL, 1 SDA; single controller, 7-bit address and one written byte.
  Default holds are 50 clocks at 10 MHz. ACK permits continuation; NACK emits
  STOP then faults. Bounded WAIT handles clock stretching; CHECK_TX detects
  contention while transmitting. Timeout or contention releases pins immediately,
  without promising a STOP on an externally held bus. Both ACK samples can be
  inspected during execution only through the last SAMPLE; there is no trace FIFO.

The I²C demonstration does not implement reads, repeated START, retries, bus
recovery or full multi-controller clock synchronization. It is not a general
replacement for a standards-compliant I²C controller yet.

# External hardware

None for simulation. A physical demo requires a clock and a host obeying the
loading contract. UART idle and I²C open-drain lines require external pull-ups.
An I²C line is only driven low or released; analog rise time and voltage limits
remain board-level concerns. These tests do not establish electrical compliance.
