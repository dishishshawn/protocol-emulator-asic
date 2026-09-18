"""External-pin checks for streaming, bounded queues and timestamped capture."""
import json
import os
import random
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

from test_engine import expect_halt, load, reset, tick
from test_protocols import I2CPeer
from program import HALT, SAMPLE, djnz, drive, hold, load_byte, shift_in, shift_out, wait_pin
from streaming import (FAULT_PULSE, FAULT_RESPONSE, Host, PULL, PUSH, byte_loop, capture,
                       fault_demo, fault_demo_limit, i2c_read, i2c_transaction,
                       i2c_write_stream, spi_stream, stream, uart_rx, uart_tx_stream)


UNKNOWN_TO_ZERO = str.maketrans("xzXZ", "0000")


def driven(d):
    """(oe, out) of the bidirectional pins as integers.

    Gate-level flops that nothing has written yet read X; that is acceptable only
    on lanes whose output is disabled, where the pin is released anyway.
    """
    oe = int(d.uio_oe.value)
    raw = str(d.uio_out.value)
    unknown = int("".join("1" if c in "xzXZ" else "0" for c in raw), 2)
    assert unknown & oe == 0, f"unknown value on an enabled lane: oe={oe:05b} out={raw}"
    return oe, int(raw.translate(UNKNOWN_TO_ZERO), 2)


class Bus:
    """One clock owner; host exchanges and protocol peer advance together."""
    def __init__(self, d, peer=None, inputs=0):
        self.d, self.peer, self.inputs = d, peer, inputs
        self.control = 0x40
        self.cycle = 0
        self.phase = 0
        self.host = Host(self.exchange)

    async def step(self, n=1):
        for _ in range(n):
            if self.phase:
                # Move external transitions across both sides of the rising edge.
                self.d.clk.value = 0
                if self.phase < 50:
                    await Timer(self.phase, unit="ns")
                    self.d.uio_in.value = self.control | self.inputs
                    await Timer(50 - self.phase, unit="ns")
                    self.d.clk.value = 1
                    await Timer(50, unit="ns")
                else:
                    await Timer(50, unit="ns")
                    self.d.clk.value = 1
                    await Timer(self.phase - 50, unit="ns")
                    self.d.uio_in.value = self.control | self.inputs
                    await Timer(100 - self.phase, unit="ns")
            else:
                self.d.uio_in.value = self.control | self.inputs
                await tick(self.d)
            self.cycle += 1
            if self.peer:
                self.inputs = self.peer(self)

    async def exchange(self, value, command):
        self.d.ui_in.value = value
        self.control = 0x40 | (0x20 if command else 0)
        await self.step(4)
        self.control |= 0x80
        await self.step(4)
        self.control &= ~0x80
        await self.step(4)
        return int(self.d.uo_out.value)

    async def finish(self, limit=30000, fault=False):
        self.control = 0x40
        await self.step(4)
        for _ in range(limit):
            if int(self.d.uo_out.value) & 0x20:
                await expect_halt(self.d, fault)
                return
            await self.step()
        raise AssertionError("stream program did not finish")


@cocotb.test()
async def fifo_boundaries_backpressure_and_reset(d):
    await reset(d)
    # Echo TX through physical lane 0, with lane 4 gating the initial consume.
    w = [stream(20), wait_pin(4, 1), PULL, shift_out(0), hold(4),
         shift_in(0), djnz(3), PUSH, byte_loop(2), HALT]
    await load(d, w)
    gate = 0

    def loopback(b):
        oe, out = driven(d)
        return gate | (out & oe & 1)

    b = Bus(d, loopback)
    await b.step(10)
    values = [0, 255, 0x55, 0xAA] + list(range(16))
    for value in values[:8]:
        await b.host.send(value)
    assert await b.host.page(2) == 8
    await b.exchange(0xEE, False)  # rejected; must not corrupt the oldest byte
    await b.exchange(0x80, True)
    await b.exchange(0x81, True)
    await b.exchange(0xFF, True)
    assert await b.host.page(10) == 0x17
    await b.exchange(0x82, True)
    assert await b.host.page(10) == 0
    gate = 16
    await b.step(800)
    assert await b.host.page(3) == 8
    assert await b.host.page(2) == 0
    # Fill output, send a ninth byte: PUSH must preserve it while RX is full.
    await b.host.send(values[8])
    await b.step(100)
    assert await b.host.page(3) == 8
    received = [await b.host.receive()]
    await b.step(80)
    assert await b.host.page(3) == 8
    received += [await b.host.receive() for _ in range(8)]
    assert received == values[:9]
    # Exercise pointer wrap and interleaved producer/consumer service.
    for value in values[9:]:
        await b.host.send(value)
        received.append(await b.host.receive())
    await b.finish()
    assert received == values
    assert await b.host.page(10) == 0
    for action in ("abort", "deselect", "reset"):
        await load(d, [stream(1), capture(1), PULL, HALT])
        b = Bus(d)
        await b.step(12)
        if action == "abort":
            b.control = 0
        elif action == "deselect":
            d.ena.value = 0
        else:
            d.rst_n.value = 0
        await b.step(5)
        assert int(d.uio_oe.value) == 0
        d.ena.value = d.rst_n.value = 1
        await load(d, [stream(1), PULL, HALT])
        b = Bus(d)
        await b.step(12)
        assert await b.host.page(2) == 0
        assert await b.host.page(3) == 0
        assert await b.host.page(5) == 0
        assert await b.host.page(10) == 0
        await b.host.send(0)
        await b.finish()


class SPIPeer:
    def __init__(self, response, mode, lsb):
        self.response, self.mode, self.lsb = response, mode, lsb
        self.prev_cs, self.prev_sck = 1, mode >> 1
        self.samples = []
        self.edges = self.starts = self.stops = 0
        self.miso = 0

    def __call__(self, b):
        oe, out = driven(b.d)
        cpol, cpha = self.mode >> 1, self.mode & 1
        cs = (out >> 3) & 1 if oe & 8 else 1
        sck = out & 1 if oe & 1 else cpol
        if self.prev_cs and not cs:
            self.starts += 1
            if not cpha:
                self.miso = (self.response[0] >> (0 if self.lsb else 7)) & 1
        if not cs and sck != self.prev_sck:
            self.edges += 1
            sample = (sck != cpol) != bool(cpha)
            if sample:
                self.samples.append((out >> 1) & 1)
            elif len(self.samples) < len(self.response) * 8:
                i, bit = divmod(len(self.samples), 8)
                self.miso = (self.response[i] >> (bit if self.lsb else 7 - bit)) & 1
        if not self.prev_cs and cs:
            self.stops += 1
            assert sck == cpol
        self.prev_cs, self.prev_sck = cs, sck
        return self.miso << 2


@cocotb.test()
async def host_waits_for_stream_enable(d):
    await reset(d)
    # SAMPLE bit 4 intentionally resembles the streaming-ready status bit.
    await load(d, [SAMPLE, hold(100), stream(1), load_byte(0), PUSH, HALT])
    b = Bus(d, inputs=16)
    assert await b.host.receive() == 0
    await b.finish()
    await load(d, [SAMPLE, hold(100), stream(1), PULL, HALT])
    b = Bus(d, inputs=16)
    await b.host.send(0xA5)
    await b.finish()
    assert await b.host.page(2) == 0
    await load(d, [hold(100), stream(1), capture(1), wait_pin(4, 1), HALT])
    b = Bus(d)
    assert await b.host.captures() == []
    assert b.cycle > 100
    b.inputs = 16
    await b.finish()
    # Legacy programs never acknowledge streaming, even if RX looks like a count.
    await load(d, [HALT])
    b = Bus(d)
    b.host.poll_limit = 3
    try:
        await b.host.receive()
    except TimeoutError:
        pass
    else:
        raise AssertionError("legacy status was accepted as a streamed byte")


@cocotb.test()
async def simultaneous_fifo_operations(d):
    await reset(d)
    for occupancy in (2, 8):
        await load(d, [stream(1), wait_pin(4, 1), PULL, wait_pin(4, 0), HALT])
        b = Bus(d)
        await b.step(12)
        for value in range(occupancy):
            await b.host.send(value)
        d.ui_in.value = 0xAA
        b.control = 0x40
        await b.step(4)
        b.inputs = 16
        await b.step()  # WAIT exits one cycle before the synchronized LOAD strobe
        b.control = 0xC0
        await b.step(4)
        b.control = 0x40
        await b.step(4)
        assert await b.host.page(2) == (2 if occupancy == 2 else 7)
        assert await b.host.page(10) == (0 if occupancy == 2 else 1)
        b.inputs = 0
        await b.finish()
    for prefill in (False, True):
        await load(d, [stream(1), load_byte(0)] + ([PUSH] if prefill else []) +
                   [wait_pin(4, 1), PUSH, HALT])
        b = Bus(d)
        await b.step(12)
        d.ui_in.value = 0x80
        b.control = 0x60
        await b.step(4)
        b.inputs = 16
        await b.step()
        b.control = 0xE0
        await b.step(4)
        b.control = 0x60
        await b.step(4)
        assert await b.host.page(3) == 1
        assert await b.host.page(10) == (0 if prefill else 2)
        assert await b.host.receive() == 0
        await b.finish()
    await load(d, [stream(1), capture(1), wait_pin(4, 1), HALT])
    b = Bus(d)
    await b.step(12)
    b.inputs = 1
    await b.step(6)
    assert await b.host.page(5) == 1
    # Pop the rising edge on precisely the cycle the falling edge is recorded.
    d.ui_in.value = 0x81
    b.control = 0x60
    await b.step(4)
    b.inputs = 0
    b.control = 0xE0
    await b.step(4)
    b.control = 0x60
    await b.step(4)
    assert await b.host.page(5) == 1
    assert [e["pins"] for e in await b.host.captures()] == [0]
    assert await b.host.page(10) == 0
    b.inputs = 16
    await b.finish()


@cocotb.test()
async def multibyte_spi_all_modes(d):
    await reset(d)
    rng = random.Random(9162026)
    for mode in range(4):
        for lsb in (False, True):
            tx = [rng.randrange(256) for _ in range(19)]
            rx = [rng.randrange(256) for _ in tx]
            await load(d, spi_stream(len(tx), mode, lsb, rng.randrange(4, 9)))
            peer = SPIPeer(rx, mode, lsb)
            b = Bus(d, peer)
            await b.step(12)
            result = []
            for value in tx:
                await b.step(rng.randrange(50))  # TX starvation at idle SCK
                await b.host.send(value)
                result.append(await b.host.receive())
            await b.finish()
            assert result == rx
            order = range(8) if lsb else range(7, -1, -1)
            assert peer.samples == [(v >> bit) & 1 for v in tx for bit in order]
            assert (peer.starts, peer.stops, peer.edges) == (1, 1, len(tx) * 16)
            assert await b.host.page(10) == 0


class UARTReceiver:
    def __init__(self, clocks):
        self.clocks = clocks
        self.prev = 1
        self.start = None
        self.frames = []
        self.bits = []
        self.sample = 0

    def __call__(self, b):
        oe, out = driven(b.d)
        level = out & 1 if oe & 1 else 1
        if self.start is None and self.prev and not level:
            self.start = b.cycle
            self.sample = b.cycle + self.clocks // 2
            self.bits = []
        if self.start is not None and b.cycle == self.sample:
            self.bits.append(level)
            self.sample += self.clocks
            if len(self.bits) == 10:
                assert self.bits[0] == 0
                value = sum(v << bit for bit, v in enumerate(self.bits[1:9]))
                self.frames.append((value, self.bits[-1], b.cycle))
                self.start = None
        self.prev = level
        return level


@cocotb.test()
async def streaming_uart_transmit_and_receive(d):
    await reset(d)
    rng = random.Random(917)
    values = [0, 255, 0x55, 0xAA] + [rng.randrange(256) for _ in range(12)]
    for clocks in (12, 33, 87):
        await load(d, uart_tx_stream(len(values), clocks))
        peer = UARTReceiver(clocks)
        b = Bus(d, peer)
        await b.step(12)
        for value in values:
            await b.host.send(value)
        await b.finish()
        assert [(v, stop) for v, stop, _ in peer.frames] == [(v, 1) for v in values]
        await load(d, uart_rx(len(values), clocks))
        b = Bus(d, inputs=1)
        await b.step(20)
        got = []
        for value in values:
            await b.step(rng.randrange(1, 13))
            for level in [0] + [(value >> i) & 1 for i in range(8)] + [1]:
                b.inputs = level
                await b.step(clocks)
            got.append(await b.host.receive())
        await b.finish()
        assert got == values
    # A framing error is a fault and must not deliver a valid RX byte.
    await load(d, uart_rx(1, 32, 100))
    b = Bus(d, inputs=1)
    await b.step(20)
    b.inputs = 0
    await b.step(32 * 11)
    await b.finish(fault=True)
    assert await b.host.page(3) == 0
    await load(d, uart_rx(1, 32, 25))
    b = Bus(d, inputs=1)
    await b.finish(fault=True, limit=100)


@cocotb.test()
async def uart_receive_back_to_back_and_false_start(d):
    await reset(d)
    values = [0, 255, 0x55, 0xAA, 128, 1, 127, 254]
    for clocks in (12, 87):
        for phase in (23, 77):
            await load(d, uart_rx(8, clocks, 2000))
            b = Bus(d, inputs=1)
            b.phase = phase
            await b.step(15)
            for value in values:
                for level in [0] + [(value >> i) & 1 for i in range(8)] + [1]:
                    b.inputs = level
                    await b.step(clocks)
            assert [await b.host.receive() for _ in values] == values
            await b.finish()
    await load(d, uart_rx(1, 32))
    b = Bus(d, inputs=1)
    await b.step(15)
    b.inputs = 0
    await b.step(4)
    b.inputs = 1
    await b.finish(fault=True, limit=100)
    assert await b.host.page(3) == 0


class ReadTarget:
    """I2C target: decode address; drive data only on falling edges; observe ACKs."""
    def __init__(self, values, stretch=0):
        self.values = values
        self.stretch = stretch
        self.left = 0
        self.prev_oe = 0
        self.prev_scl = self.prev_sda = 1
        self.low = False
        self.started = False
        self.phase = 0
        self.address_bits = []
        self.byte_index = -1
        self.acks = []
        self.starts = self.stops = 0

    def __call__(self, b):
        oe, out = driven(b.d)
        oe, out = oe & 3, out & 3
        assert not oe & out
        if self.prev_oe & 1 and not oe & 1:
            self.left = self.stretch
        scl = int(not oe & 1 and self.left == 0)
        self.left = max(0, self.left - 1)
        sda = int(not oe & 2 and not self.low)
        if self.prev_sda and not sda and scl and self.prev_scl:
            self.started = True
            self.starts += 1
        if not self.prev_sda and sda and scl and self.prev_scl:
            self.started = False
            self.stops += 1
        if self.started and not self.prev_scl and scl:
            if self.phase < 8:
                if self.byte_index == -1:
                    self.address_bits.append(sda)
                self.phase += 1
            else:
                if self.byte_index >= 0:
                    self.acks.append(sda)
                self.phase = 9
        if self.started and self.prev_scl and not scl:
            if self.phase == 9:
                self.byte_index += 1
                self.phase = 0
            if self.byte_index == -1:
                self.low = self.phase == 8  # address ACK
            elif self.phase < 8 and self.byte_index < len(self.values):
                self.low = not ((self.values[self.byte_index] >> (7 - self.phase)) & 1)
            else:
                self.low = False
            sda = int(not oe & 2 and not self.low)
        self.prev_scl, self.prev_sda, self.prev_oe = scl, sda, oe
        return scl | (sda << 1)


@cocotb.test()
async def multibyte_i2c_write_and_read(d):
    await reset(d)
    values = [0, 255, 0x55, 0xAA, 1, 7, 128, 64, 23, 99, 156]
    for h in (4, 50):
        await load(d, i2c_write_stream(0x50, len(values), h, 100))
        peer = I2CPeer(ack=[True] * (1 + len(values)),
                       stretches={i: (i * 7) % 29 for i in range(1, 120)})

        def write_target(b):
            peer.observe(d)
            return peer.prev_scl | (peer.prev_sda << 1)

        b = Bus(d, write_target, inputs=3)
        await b.step(12)
        for value in values:
            try:
                await b.host.send(value)
            except RuntimeError:
                raise AssertionError((h, value, peer.bytes, peer.ack_bits, peer.starts, peer.stops))
        await b.finish()
        assert peer.bytes == [0xA0] + values
        assert peer.ack_bits == [0] * (1 + len(values))
        assert (peer.starts, peer.stops) == (1, 1)
        for count in (1, len(values)):
            await load(d, i2c_read(0x50, count, h, 100))
            target = ReadTarget(values[:count], stretch=13)
            b = Bus(d, target, inputs=3)
            await b.step(12)
            # Force RX backpressure before ACK: controller must hold SCL low.
            if count > 8:
                await b.step(25000)
                assert await b.host.page(3) == 8
                assert int(d.uio_oe.value) & 1
            result = [await b.host.receive() for _ in range(count)]
            await b.finish()
            assert result == values[:count]
            assert target.address_bits == [int(v) for v in f"{0xA1:08b}"]
            assert target.acks == [0] * (count - 1) + [1]
            assert (target.starts, target.stops) == (1, 1)
            assert await b.host.page(10) == 0


@cocotb.test()
async def streaming_i2c_nack_and_read_timeout(d):
    await reset(d)
    for words, acks, expected in (
        (i2c_read(0x50, 3), [False], [0xA1]),
        (i2c_write_stream(0x50, 3), [True, True, False], [0xA0, 0x55, 0x55]),
    ):
        await load(d, words)
        peer = I2CPeer(ack=acks)

        def target(b):
            peer.observe(d)
            return peer.prev_scl | (peer.prev_sda << 1)

        b = Bus(d, target, inputs=3)
        await b.step(15)
        for _ in range(3):
            await b.host.send(0x55)
        await b.finish(fault=True)
        assert peer.bytes == expected
        assert peer.stops == 1
    await load(d, i2c_read(0x50, 1, half_period=4, timeout=25))
    target = ReadTarget([0xFF], stretch=1000)
    b = Bus(d, target, inputs=3)
    await b.finish(fault=True, limit=300)
    assert await b.host.page(3) == 0


class RegisterTarget:
    """Register-mapped I2C target: pointer write, auto-increment, repeated START.

    Only a START while a transaction is open counts as repeated; a STOP closes
    the transaction and a fresh START would count as a new one.
    """
    def __init__(self, address, registers, stretch=0, stretch_after_bytes=None):
        self.address = address
        self.registers = list(registers)
        self.stretch = stretch
        # None: stretch every clock. N: stretch only the SCL releases that follow
        # the ACK of the Nth received byte, i.e. the release before a repeated
        # START (and the first clock after it), not the transfers before.
        self.stretch_after_bytes = stretch_after_bytes
        self.left = 0
        self.prev_oe = 0
        self.prev_scl = self.prev_sda = 1
        self.low = False
        self.started = False
        self.phase = 0
        self.bits = []
        self.pointer = 0
        self.direction = None  # None: expecting address; 0 write; 1 read; 2 not us
        self.first = False
        self.serving = False
        self.starts = self.repeated = self.stops = 0
        self.bytes = []
        self.acks = []

    def __call__(self, b):
        oe, out = driven(b.d)
        oe, out = oe & 3, out & 3
        assert not oe & out
        if self.prev_oe & 1 and not oe & 1:
            armed = (self.stretch_after_bytes is None or
                     (len(self.bytes) >= self.stretch_after_bytes and self.phase == 0))
            self.left = self.stretch if armed else 0
        scl = int(not oe & 1 and self.left == 0)
        self.left = max(0, self.left - 1)
        sda = int(not oe & 2 and not self.low)
        if self.prev_sda and not sda and scl and self.prev_scl:
            if self.started:
                self.repeated += 1
            else:
                self.starts += 1
            self.started = True
            self.phase = 0
            self.bits = []
            self.direction = None
            self.serving = False
            self.low = False
        if not self.prev_sda and sda and scl and self.prev_scl:
            self.started = False
            self.stops += 1
            self.low = False
        if self.started and not self.prev_scl and scl:
            if self.phase < 8:
                if self.direction != 1:
                    self.bits.append(sda)
                self.phase += 1
            else:
                if self.direction == 1 and self.serving:
                    self.acks.append(sda)
                self.phase = 9
        if self.started and self.prev_scl and not scl:
            if self.phase == 9:
                self.phase = 0
                if self.direction == 1 and self.serving:
                    self.pointer += 1
                    if self.acks[-1]:
                        self.direction = 2  # controller NACK: release the bus
            if self.phase == 8:
                value = sum(v << (7 - i) for i, v in enumerate(self.bits))
                self.bits = []
                if self.direction is None:
                    matched = value >> 1 == self.address
                    self.direction = value & 1 if matched else 2
                    self.first = True
                    self.bytes.append(value)
                    self.low = matched
                elif self.direction == 0:
                    if self.first:
                        self.pointer = value
                        self.first = False
                    else:
                        self.registers[self.pointer % len(self.registers)] = value
                        self.pointer += 1
                    self.bytes.append(value)
                    self.low = True
                else:
                    self.low = False
            elif self.direction == 1:
                self.serving = True
                current = self.registers[self.pointer % len(self.registers)]
                self.low = not ((current >> (7 - self.phase)) & 1)
            else:
                self.low = False
            sda = int(not oe & 2 and not self.low)
        self.prev_scl, self.prev_sda, self.prev_oe = scl, sda, oe
        return scl | (sda << 1)


@cocotb.test()
async def i2c_repeated_start_register_read(d):
    await reset(d)
    rng = random.Random(20260917)
    registers = [rng.randrange(256) for _ in range(16)]
    for h, stretch in ((4, 0), (50, 13)):
        for pointer, count in ((3, 1), (9, 7), (0, 16)):
            await load(d, i2c_transaction(3, count, h, 200))
            target = RegisterTarget(0x50, registers, stretch)
            b = Bus(d, target, inputs=3)
            await b.step(12)
            for value in (0xA0, pointer, 0xA1):
                await b.host.send(value)
            result = [await b.host.receive() for _ in range(count)]
            await b.finish()
            assert result == [registers[(pointer + i) % 16] for i in range(count)]
            assert target.bytes == [0xA0, pointer, 0xA1]
            assert target.acks == [0] * (count - 1) + [1]
            assert (target.starts, target.repeated, target.stops) == (1, 1, 1)
            assert await b.host.page(10) == 0
    # Write two registers, then read them back after the repeated START.
    await load(d, i2c_transaction(5, 2, 4, 200))
    target = RegisterTarget(0x50, registers)
    b = Bus(d, target, inputs=3)
    await b.step(12)
    for value in (0xA0, 5, 0x12, 0x34, 0xA1):
        await b.host.send(value)
    assert [await b.host.receive() for _ in range(2)] == [registers[7], registers[8]]
    await b.finish()
    assert target.registers[5:7] == [0x12, 0x34]
    assert target.bytes == [0xA0, 5, 0x12, 0x34, 0xA1]
    assert (target.starts, target.repeated, target.stops) == (1, 1, 1)
    # Unmatched address is NACKed: STOP then TRAP, no repeated START, no data.
    await load(d, i2c_transaction(3, 4, 4, 200))
    target = RegisterTarget(0x51, registers)
    b = Bus(d, target, inputs=3)
    await b.step(12)
    for value in (0xA0, 0, 0xA1):
        await b.host.send(value)
    await b.finish(fault=True)
    assert target.bytes == [0xA0]
    assert (target.starts, target.repeated, target.stops) == (1, 0, 1)
    assert await b.host.page(3) == 0
    # A stretch that begins at the SCL release before the repeated START and never
    # ends must hit the restart's own bounded wait: both write bytes were ACKed
    # first, no repeated START was seen and no read byte was clocked.
    await load(d, i2c_transaction(3, 1, 4, 25))
    target = RegisterTarget(0x50, registers, stretch=1000, stretch_after_bytes=2)
    b = Bus(d, target, inputs=3)
    await b.step(12)
    for value in (0xA0, 0, 0xA1):
        await b.host.send(value)
    await b.finish(fault=True, limit=3000)
    assert target.bytes == [0xA0, 0]
    assert (target.starts, target.repeated, target.stops) == (1, 0, 0)
    assert await b.host.page(3) == 0
    # Control: the same restart stretch, shorter than the timeout, completes the read.
    await load(d, i2c_transaction(3, 1, 4, 25))
    target = RegisterTarget(0x50, registers, stretch=20, stretch_after_bytes=2)
    b = Bus(d, target, inputs=3)
    await b.step(12)
    for value in (0xA0, 0, 0xA1):
        await b.host.send(value)
    assert await b.host.receive() == registers[0]
    await b.finish()
    assert target.bytes == [0xA0, 0, 0xA1]
    assert (target.starts, target.repeated, target.stops) == (1, 1, 1)
    assert await b.host.page(10) == 0


async def fault_run(d, words, clocks, fault=False, limit=30000):
    """Run a fault-demo program against the modeled target; return its frames and edges."""
    await load(d, words)
    uart = UARTReceiver(clocks)
    pulse_start = None
    edges = []
    last = 1

    def target(b):
        nonlocal pulse_start, last
        level = uart(b)
        if uart.frames and pulse_start is None:
            verdict = "clean" if uart.frames[0][1] else "framing_error"
            pulse_start = uart.frames[0][2] + FAULT_RESPONSE[verdict]
        response = int(pulse_start is not None and pulse_start <= b.cycle < pulse_start + FAULT_PULSE)
        pins = level | (response << 4)
        if pins != last:
            edges.append((b.cycle, pins))
        last = pins
        return pins

    b = Bus(d, target, inputs=1)
    await b.finish(limit=limit, fault=fault)
    return b, uart, edges


@cocotb.test()
async def fault_demo_bounds(d):
    """The accepted fault length is exactly the window in which the response is seen."""
    await reset(d)
    for bad in ({"cycles_per_bit": 64, "fault_clocks": 128}, {"cycles_per_bit": 3},
                {"cycles_per_bit": 32, "fault_clocks": -1}, {"byte": 256}):
        try:
            fault_demo(**bad)
        except ValueError:
            continue
        raise AssertionError(f"fault_demo accepted {bad}")
    for clocks in (32, 64):
        limit = fault_demo_limit(clocks)
        assert limit > clocks
        # Longest accepted fault: the response is still seen; one more is rejected.
        b, uart, edges = await fault_run(d, fault_demo(cycles_per_bit=clocks, fault_clocks=limit), clocks)
        events = await b.host.captures()
        assert [(v, stop) for v, stop, _ in uart.frames] == [(255, 0)]
        assert [e["pins"] for e in events] == [e[1] for e in edges]
        assert len([e for e in events if e["pins"] & 16]) == 1
        assert await b.host.page(10) == 0
        try:
            fault_demo(cycles_per_bit=clocks, fault_clocks=limit + 1)
        except ValueError:
            pass
        else:
            raise AssertionError("fault beyond the response window was accepted")
        # Negative control: a firmware built for a target one clock slower misses
        # the real response and faults on the bounded wait; the pulse is captured.
        words = fault_demo(cycles_per_bit=clocks, fault_clocks=limit + 1,
                           response_clocks=FAULT_RESPONSE["framing_error"] + 1)
        b, uart, edges = await fault_run(d, words, clocks, fault=True)
        events = await b.host.captures()
        assert len([e for e in events if e["pins"] & 16]) == 1
        assert [e["pins"] for e in events] == [e[1] for e in edges]
    # Faults shorter than a bit and clean frames at wider bit periods still see
    # the response, because the watch starts as soon as the line is released.
    for clocks, fault in ((64, 40), (87, 0), (87, 43), (87, 44)):
        b, uart, edges = await fault_run(d, fault_demo(cycles_per_bit=clocks, fault_clocks=fault), clocks)
        events = await b.host.captures()
        assert [(v, stop) for v, stop, _ in uart.frames] == [(255, int(fault <= clocks // 2))]
        response = [e for e in events if e["pins"] & 16]
        assert len(response) == 1
        assert await b.host.page(10) == 0


@cocotb.test()
async def timestamp_capture_and_fault_demo(d):
    await reset(d)
    evidence = []
    for faulted in (False, True):
        await load(d, fault_demo(faulted))
        uart = UARTReceiver(32)
        pulse_start = None
        edges = []
        last = 1

        def target(b):
            nonlocal pulse_start, last
            level = uart(b)
            if uart.frames and pulse_start is None:
                # Model reports bad framing sooner than normal processing completes.
                pulse_start = uart.frames[0][2] + (59 if faulted else 103)
            response = int(pulse_start is not None and pulse_start <= b.cycle < pulse_start + 11)
            pins = level | (response << 4)
            if pins != last:
                edges.append((b.cycle, pins))
            last = pins
            return pins

        b = Bus(d, target, inputs=1)
        await b.finish()
        assert [(v, stop) for v, stop, _ in uart.frames] == [(255, int(not faulted))]
        events = await b.host.captures()
        assert len(events) == len(edges)
        offsets = [event["cycle"] - edge[0] for event, edge in zip(events, edges)]
        assert len(set(offsets)) == 1  # equal synchronizer latency for every edge
        assert [e["pins"] for e in events] == [e[1] for e in edges]
        response = [e for e in events if e["pins"] & 16]
        assert len(response) == 1
        i = events.index(response[0])
        assert events[i + 1]["cycle"] - events[i]["cycle"] == 11
        if faulted:
            assert events[3]["cycle"] - events[2]["cycle"] == 32
        assert await b.host.page(10) == 0
        evidence.append({"faulted": faulted, "received_byte": uart.frames[0][0],
                         "stop_bit": uart.frames[0][1], "events": events,
                         "response_delay_from_stop_sample": 59 if faulted else 103})
    if os.environ.get("DEMO_REPORT"):
        Path(os.environ["DEMO_REPORT"]).write_text(json.dumps(evidence, indent=2) + "\n")
    # Capture is nonblocking and drops new events on full, keeping the first eight.
    await load(d, [stream(1), capture(1), wait_pin(4, 1), HALT])
    b = Bus(d)
    await b.step(15)
    for i in range(12):
        b.inputs = (i + 1) & 1
        await b.step(10)
    assert await b.host.page(5) == 8
    assert await b.host.page(10) == 8
    events = await b.host.captures()
    assert [e["pins"] for e in events] == [1, 0] * 4
    assert [events[i + 1]["cycle"] - events[i]["cycle"] for i in range(7)] == [10] * 7
    b.inputs = 16
    await b.finish()


@cocotb.test()
async def malformed_stream_instructions(d):
    await reset(d)
    for w in ([0xC1000000], [PULL], [PUSH], [capture(1)], [0xC6000000],
              [stream(1), 0xD0000000], [stream(1), byte_loop(1), byte_loop(1)],
              [stream(1), 0xC500003F]):
        # Last-byte branch targets unloaded instruction 63 and must fault.
        await load(d, w)
        b = Bus(d)
        await b.finish(fault=True, limit=100)
