"""Streaming ISA, firmware and transport-independent host helpers.

The host transport supplies async exchange(byte, command): pulse LOAD with the
bundled-data timing in docs/streaming.md, then return uo_out. Command exchanges
leave REWIND high so the selected read page is visible.
"""
from program import (HALT, TRAP, branch_pin, check_tx, djnz, drive, encode, hold,
                     jump, load_byte, patch, shift_in, shift_out, uart_tx, wait_pin)

PULL = 0xC2000000
PUSH = 0xC3000000


def stream(count):
    if not 1 <= count <= 255:
        raise ValueError("stream byte count must be 1..255")
    return 0xC1000000 | count


def byte_loop(address):
    if not 0 <= address < 64:
        raise ValueError("byte loop address must be 0..63")
    return 0xC4000000 | address


def last_byte(address):
    if not 0 <= address < 64:
        raise ValueError("last-byte branch address must be 0..63")
    return 0xC5000000 | address


def capture(mask):
    if not 0 <= mask < 32:
        raise ValueError("capture mask must be 0..31")
    return 0xD1000000 | mask


def spi_stream(count, mode=0, lsb_first=False, half_period=5):
    if mode not in range(4) or not 4 <= half_period <= 8192:
        raise ValueError("SPI mode must be 0..3 and half_period 4..8192")
    cpol, cpha = mode >> 1, mode & 1
    w = [stream(count), drive(8 | cpol, 11, half_period), patch(8, 0, 8, half_period)]
    byte = len(w)
    w += [PULL]
    bit = len(w)
    if not cpha:
        w += [shift_out(1, lsb_first), hold(half_period),
              patch(1, 1 - cpol, 1, half_period), shift_in(2, lsb_first),
              patch(1, cpol, 1, half_period)]
    else:
        w += [patch(1, 1 - cpol, 1), shift_out(1, lsb_first), hold(half_period),
              patch(1, cpol, 1, half_period), shift_in(2, lsb_first)]
    w += [djnz(bit), PUSH, byte_loop(byte), patch(8, 8, 8, half_period), HALT]
    return w


def uart_tx_stream(count, cycles_per_bit=87):
    if not 4 <= cycles_per_bit <= 8192:
        raise ValueError("streaming UART TX needs 4..8192 clocks/bit")
    w = [stream(count), drive(1, 1, cycles_per_bit)]
    byte = len(w)
    w += [PULL, drive(0, 1, cycles_per_bit)]
    bit = len(w)
    w += [shift_out(0, True), hold(cycles_per_bit - 2), djnz(bit),
          drive(1, 1, cycles_per_bit), byte_loop(byte), HALT]
    return w


def uart_rx(count, cycles_per_bit=87, timeout=2000):
    """8N1 RX lane 0. Half-bit start validation; bad start/stop faults.

    A full RX FIFO stalls after the stop sample. The sender must leave enough
    idle time for host draining; there is no UART flow-control wire.
    """
    if not 12 <= cycles_per_bit <= 8192 or not 1 <= timeout < 262144:
        raise ValueError("UART RX needs 12..8192 clocks/bit and bounded timeout")
    w = [stream(count), drive(0, 0, 1)]
    byte = len(w)
    w += [wait_pin(0, 1, timeout), wait_pin(0, 0, timeout),
          hold(cycles_per_bit // 2 - 1)]
    start_check = len(w)
    w += [0, load_byte(0), hold(cycles_per_bit - 2)]
    bit = len(w)
    w += [shift_in(0, True), hold(cycles_per_bit - 2), djnz(bit)]
    stop_check = len(w)
    w += [0, PUSH, byte_loop(byte), HALT]
    error = len(w)
    w += [TRAP]
    w[start_check] = branch_pin(0, 1, error)
    w[stop_check] = branch_pin(0, 0, error)
    return w


def _i2c_parameters(address, half_period, timeout):
    if not 0 <= address < 128 or not 4 <= half_period <= 8192 or not 1 <= timeout < 262144:
        raise ValueError("I2C needs 7-bit address, half_period 4..8192, bounded timeout")


def _i2c_start(h, timeout):
    return [drive(0, 0, h), wait_pin(0, 1, timeout), wait_pin(1, 1, timeout),
            patch(2, 0, 2, h), patch(1, 0, 1, h)]


def _i2c_stop(h, timeout):
    return [patch(2, 0, 2, h), patch(1, 0, 0, 4), wait_pin(0, 1, timeout),
            hold(h), patch(2, 0, 0, h)]


def _i2c_send(w, h, timeout):
    bit = len(w)
    w += [shift_out(1, open_drain=True), hold(h), patch(1, 0, 0, 4),
          wait_pin(0, 1, timeout), hold(h), check_tx(1), patch(1, 0, 1, h),
          djnz(bit), patch(2, 0, 0, h), patch(1, 0, 0, 4),
          wait_pin(0, 1, timeout), hold(h)]
    nack = len(w)
    w += [0, patch(1, 0, 1, h)]
    return nack


def _i2c_finish(w, nacks, h, timeout):
    w += _i2c_stop(h, timeout) + [HALT]
    error = len(w)
    w += [patch(1, 0, 1, h)] + _i2c_stop(h, timeout) + [TRAP]
    for i in nacks:
        w[i] = branch_pin(1, 1, error)
    encode(w)
    return w


def i2c_write_stream(address, count, half_period=50, timeout=2000):
    _i2c_parameters(address, half_period, timeout)
    h = half_period
    w = [stream(count)] + _i2c_start(h, timeout) + [load_byte(address << 1)]
    nacks = [_i2c_send(w, h, timeout)]
    byte = len(w)
    w += [PULL]
    nacks += [_i2c_send(w, h, timeout)]
    w += [byte_loop(byte)]
    return _i2c_finish(w, nacks, h, timeout)


def i2c_read(address, count, half_period=50, timeout=2000):
    _i2c_parameters(address, half_period, timeout)
    h = half_period
    w = [stream(count)] + _i2c_start(h, timeout) + [load_byte((address << 1) | 1)]
    nacks = [_i2c_send(w, h, timeout)]
    byte = len(w)
    w += [load_byte(0), patch(2, 0, 0, h)]
    bit = len(w)
    w += [patch(1, 0, 0, 4), wait_pin(0, 1, timeout), hold(h), shift_in(1),
          patch(1, 0, 1, h), djnz(bit), PUSH]
    final = len(w)
    w += [0, patch(2, 0, 2, h)]  # ACK all but final byte
    ack_clock = len(w)
    w += [patch(1, 0, 0, 4), wait_pin(0, 1, timeout), hold(h),
          patch(1, 0, 1, h), patch(2, 0, 0, h), byte_loop(byte)]
    w[final] = last_byte(ack_clock)  # released SDA sends final NACK
    return _i2c_finish(w, nacks, h, timeout)


def i2c_transaction(write_count, read_count, half_period=50, timeout=2000):
    """Write then read in one transaction, joined by a repeated START.

    The host pushes write_count bytes: address+W first, then the payload
    (typically a register pointer), and finally address+R. The repeated START
    precedes that last pushed byte, so the firmware never embeds an address.
    read_count bytes are then received, ACKed except the final NACK, then STOP.
    """
    _i2c_parameters(0, half_period, timeout)
    if not 2 <= write_count <= 255 or not 1 <= read_count <= 255:
        raise ValueError("write_count 2..255 (address+W .. address+R), read_count 1..255")
    h = half_period
    w = [stream(write_count)] + _i2c_start(h, timeout)
    byte = len(w)
    w += [PULL]
    restart = len(w)
    w += [0]  # LAST_BYTE: repeated START before address+R
    send = len(w)
    nacks = [_i2c_send(w, h, timeout)]
    w += [byte_loop(byte), stream(read_count)]
    read_byte = len(w)
    w += [load_byte(0), patch(2, 0, 0, h)]
    bit = len(w)
    w += [patch(1, 0, 0, 4), wait_pin(0, 1, timeout), hold(h), shift_in(1),
          patch(1, 0, 1, h), djnz(bit), PUSH]
    final = len(w)
    w += [0, patch(2, 0, 2, h)]
    ack_clock = len(w)
    w += [patch(1, 0, 0, 4), wait_pin(0, 1, timeout), hold(h),
          patch(1, 0, 1, h), patch(2, 0, 0, h), byte_loop(read_byte)]
    w[final] = last_byte(ack_clock)
    _i2c_finish(w, nacks, h, timeout)
    # Repeated START: SDA released while SCL low, SCL released and checked
    # high (stretch), setup hold, SDA low while SCL high, then SCL low.
    w[restart] = last_byte(len(w))
    w += [patch(2, 0, 0, h), patch(1, 0, 0, 4), wait_pin(0, 1, timeout),
          wait_pin(1, 1, timeout), hold(h), patch(2, 0, 2, h), patch(1, 0, 1, h),
          jump(send)]
    encode(w)
    return w


# Fault demo target model: the modeled target answers RESPONSE_CLOCKS after the
# receiver's mid-stop sample with a PULSE_CLOCKS high pulse on lane 4. Lane 4
# reaches the engine through a SYNC_CLOCKS-deep synchronizer (measured in
# test_streaming.fault_demo_bounds).
FAULT_RESPONSE = {"clean": 103, "framing_error": 59}
FAULT_PULSE = 11
SYNC_CLOCKS = 3


def fault_demo_limit(cycles_per_bit, response_clocks=FAULT_RESPONSE["framing_error"],
                     pulse_clocks=FAULT_PULSE):
    """Longest fault whose response the firmware can still see.

    The firmware starts watching lane 4 one clock after the fault ends
    (fault_clocks + 1 clocks into the stop bit). The synchronized pulse is
    visible from cycles_per_bit // 2 + response + SYNC until pulse_clocks - 1
    later, so the watch must begin no later than that last clock.
    """
    return cycles_per_bit // 2 + response_clocks + pulse_clocks + SYNC_CLOCKS - 2


def fault_demo(faulted=False, cycles_per_bit=32, byte=255, fault_clocks=None,
               response_clocks=None, pulse_clocks=FAULT_PULSE):
    """Send a byte with a normal or shortened stop bit; capture UART echo and lane 4.

    fault_clocks drives the stop bit low for exactly that many clocks (0 is a
    clean frame; more than a bit period extends the fault past the frame).
    faulted=True is the original demo: the whole stop bit low. The line is
    released to idle one clock after the fault ends and the firmware then
    watches lane 4 for the response, so the stop bit is never shorter than a
    bit period. The response window is bounded by the modeled target: a fault
    longer than fault_demo_limit() ends after the response has passed, so the
    watch would time out and fault. response_clocks defaults to the modeled
    latency for the verdict the receiver will reach.
    """
    if fault_clocks is None:
        fault_clocks = cycles_per_bit if faulted else 0
    if not 4 <= cycles_per_bit <= 4096 or not 0 <= byte < 256 or fault_clocks < 0:
        raise ValueError("fault_demo needs 4..4096 clocks/bit, a byte and fault_clocks >= 0")
    if response_clocks is None:
        verdict = "clean" if fault_clocks <= cycles_per_bit // 2 else "framing_error"
        response_clocks = FAULT_RESPONSE[verdict]
    limit = fault_demo_limit(cycles_per_bit, response_clocks, pulse_clocks)
    if fault_clocks > limit:
        raise ValueError(f"fault_clocks {fault_clocks} exceeds {limit}: the modeled "
                         "response would end before the firmware watches lane 4")
    # Worst case the watch starts at the stop bit and waits for a clean response.
    timeout = cycles_per_bit // 2 + max(FAULT_RESPONSE.values()) + pulse_clocks + SYNC_CLOCKS + 64
    w = [stream(1), capture(17)] + uart_tx(byte, cycles_per_bit)[:-2]
    if fault_clocks:
        w += [drive(0, 1, fault_clocks)]
    w += [drive(1, 1, 1), wait_pin(4, 1, timeout), wait_pin(4, 0, timeout), hold(4),
          capture(0), HALT]
    return w


def decode_capture(word):
    return {"cycle": word >> 8, "pins": word & 31}


class Host:
    def __init__(self, exchange, poll_limit=10000):
        self.exchange = exchange
        self.poll_limit = poll_limit

    async def page(self, number):
        if not 0 <= number <= 10:
            raise ValueError("read page must be 0..10")
        return await self.exchange(number, True)

    async def ready(self):
        for _ in range(self.poll_limit):
            # Before STREAM, commands are ignored. A running legacy status is
            # >= 0x40, never a legal occupancy. A halted legacy RX page is fixed:
            # if it is <= 8, it cannot also have the streaming-ready bit set.
            if await self.page(2) <= 8 and await self.page(1) & 0x10:
                return
        raise TimeoutError("firmware did not enable streaming")

    async def send(self, value):
        if not 0 <= value < 256:
            raise ValueError("TX data must be a byte")
        await self.ready()
        for _ in range(self.poll_limit):
            flags = await self.page(1)
            if flags & 0xA0:
                raise RuntimeError("engine halted before TX could be delivered")
            if flags & 0x14 == 0x14:
                await self.exchange(value, False)
                return
        raise TimeoutError("TX FIFO did not become ready")

    async def receive(self):
        await self.ready()
        for _ in range(self.poll_limit):
            if await self.page(3):
                value = await self.page(4)
                await self.exchange(0x80, True)
                return value
            # PUSH and HALT can occur between the count read and status read.
            if await self.page(1) & 0xA0 and not await self.page(3):
                raise RuntimeError("engine halted without pending RX data")
        raise TimeoutError("RX FIFO stayed empty")

    async def captures(self):
        await self.ready()
        result = []
        # Drain a snapshot, so continuous input cannot keep this call alive forever.
        for _ in range(await self.page(5)):
            word = 0
            for byte in range(4):
                word |= (await self.page(6 + byte)) << (8 * byte)
            await self.exchange(0x81, True)
            result.append(decode_capture(word))
        return result


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Generate streaming protocol firmware")
    parser.add_argument("output", type=Path)
    parser.add_argument("--protocol", required=True,
                        choices=["spi", "uart-tx", "uart-rx", "i2c-write", "i2c-read",
                                 "i2c-transaction", "fault-demo"])
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--cycles", type=int, default=87)
    parser.add_argument("--mode", type=int, default=0)
    parser.add_argument("--lsb-first", action="store_true")
    parser.add_argument("--address", type=lambda s: int(s, 0), default=0x50)
    parser.add_argument("--half-period", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=2000)
    parser.add_argument("--write-count", type=int, default=2)
    parser.add_argument("--faulted", action="store_true")
    args = parser.parse_args()
    if args.protocol == "spi":
        words = spi_stream(args.count, args.mode, args.lsb_first, args.half_period)
    elif args.protocol == "uart-tx":
        words = uart_tx_stream(args.count, args.cycles)
    elif args.protocol == "uart-rx":
        words = uart_rx(args.count, args.cycles, args.timeout)
    elif args.protocol == "i2c-write":
        words = i2c_write_stream(args.address, args.count, args.half_period, args.timeout)
    elif args.protocol == "i2c-read":
        words = i2c_read(args.address, args.count, args.half_period, args.timeout)
    elif args.protocol == "i2c-transaction":
        words = i2c_transaction(args.write_count, args.count, args.half_period, args.timeout)
    else:
        words = fault_demo(args.faulted)
    args.output.write_bytes(encode(words))
