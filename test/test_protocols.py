"""Protocol peers decode pins and electrical bus edges, without reading the ISA."""
import random

import cocotb

from test_engine import tick, reset, load, start, expect_halt
from program import (HALT, TRAP, SAMPLE, drive, hold, patch, load_byte, shift_out,
                     shift_in, djnz, branch_pin, check_tx, wait_pin, spi_transfer, i2c_write)


async def read_result(d, inputs=0):
    d.uio_in.value = 0x60 | inputs
    await tick(d, 5)
    result = int(d.uo_out.value)
    d.uio_in.value = 0x40 | inputs
    await tick(d, 5)
    return result


async def spi_peer(d, tx, response, mode, lsb, half_period):
    await load(d, spi_transfer(tx, mode, lsb, half_period))
    cpol, cpha = mode >> 1, mode & 1
    order = list(range(8)) if lsb else list(range(7, -1, -1))
    miso = 0
    prev_cs, prev_sck = 1, cpol
    selected = False
    samples = []
    edge_count = 0
    d.uio_in.value = 0x40
    for _ in range(2000):
        await tick(d)
        oe, out = int(d.uio_oe.value), int(d.uio_out.value)
        cs = ((out >> 3) & 1) if (oe & 8) else 1
        sck = (out & 1) if (oe & 1) else cpol
        if prev_cs and not cs:
            assert sck == cpol
            selected = True
            if not cpha:
                miso = (response >> order[0]) & 1
        if not cs and selected and sck != prev_sck:
            edge_count += 1
            leading = sck != cpol
            sample_edge = leading != bool(cpha)
            if sample_edge:
                assert oe & 2
                samples.append((out >> 1) & 1)
                assert len(samples) <= 8, "extra SPI clock"
            else:
                idx = len(samples)
                if idx < 8:
                    miso = (response >> order[idx]) & 1
        if not prev_cs and cs:
            assert sck == cpol, "CS released before final trailing edge"
            selected = False
        prev_cs, prev_sck = cs, sck
        d.uio_in.value = 0x40 | (miso << 2)
        if int(d.uo_out.value) & 0x20:
            break
    else:
        raise AssertionError("SPI transaction did not complete")
    await expect_halt(d)
    assert edge_count == 16
    assert samples == [(tx >> bit) & 1 for bit in order], (tx, mode, lsb, samples)
    assert await read_result(d, miso << 2) == response, (response, mode, lsb)


@cocotb.test()
async def spi_all_modes_and_bit_orders(d):
    await reset(d)
    rng = random.Random(174283040)
    for mode in range(4):
        for lsb in (False, True):
            values = range(256) if mode == 0 and not lsb else [0, 255, 0x55, 0xAA] + [rng.randrange(256) for _ in range(28)]
            for tx in values:
                await spi_peer(d, tx, rng.randrange(256), mode, lsb, rng.randrange(4, 9))


class I2CPeer:
    """Wired-AND target with configurable ACKs, per-edge stretching and contention."""
    def __init__(self, ack=(True, True), stretches=None, contend=False):
        self.ack = ack
        self.stretches = stretches or {}
        self.contend = contend
        self.prev_scl = self.prev_sda = 1
        self.prev_oe = 0
        self.target_sda_low = False
        self.stretch_left = 0
        self.release_count = 0
        self.started = False
        self.starts = self.stops = 0
        self.bits = []
        self.bytes = []
        self.ack_bits = []
        self.phase = 0
        self.scl_rises = []
        self.cycle = 0

    def observe(self, d):
        self.cycle += 1
        oe = int(d.uio_oe.value) & 3
        out = int(d.uio_out.value) & 3
        assert not (oe & out), "I2C must never actively drive high"
        if self.prev_oe & 1 and not oe & 1:
            self.release_count += 1
            self.stretch_left = self.stretches.get(self.release_count, 0)
        scl = int(not (oe & 1) and self.stretch_left == 0)
        if self.stretch_left:
            self.stretch_left -= 1
        # Competing controller wins on the first address bit (test address MSB=1).
        competitor_low = self.contend and self.started
        sda = int(not (oe & 2) and not self.target_sda_low and not competitor_low)
        if self.prev_sda and not sda and scl and self.prev_scl:
            self.started = True
            self.starts += 1
            self.phase = 0
        if not self.prev_sda and sda and scl and self.prev_scl:
            self.stops += 1
            self.started = False
        if self.started and not self.prev_scl and scl:
            self.scl_rises.append(self.cycle)
            if self.phase < 8:
                self.bits.append(sda)
                self.phase += 1
                if self.phase == 8:
                    value = 0
                    for bit in self.bits:
                        value = (value << 1) | bit
                    self.bytes.append(value)
                    self.bits = []
            elif self.phase == 8:
                self.ack_bits.append(sda)
                self.phase = 9
        if self.started and self.prev_scl and not scl:
            if self.phase == 8:
                index = len(self.bytes) - 1
                self.target_sda_low = self.ack[index] if index < len(self.ack) else False
            elif self.phase == 9:
                self.target_sda_low = False
                self.phase = 0
            sda = int(not (oe & 2) and not self.target_sda_low and not competitor_low)
        self.prev_scl, self.prev_sda, self.prev_oe = scl, sda, oe
        d.uio_in.value = 0x40 | scl | (sda << 1)


async def i2c_peer(d, address, byte, peer, timeout=100, expect_fault=False):
    await load(d, i2c_write(address, byte, half_period=50, timeout=timeout))
    d.uio_in.value = 0x43  # external pull-ups
    for _ in range(20000):
        await tick(d)
        peer.observe(d)
        if int(d.uo_out.value) & 0x20:
            break
    else:
        raise AssertionError("I2C did not complete within test deadline")
    await expect_halt(d, fault=expect_fault)
    return peer


@cocotb.test()
async def i2c_address_data_ack_and_stretching(d):
    await reset(d)
    rng = random.Random(20260914)
    for byte in [0, 255, 0x55, 0xAA] + [rng.randrange(256) for _ in range(20)]:
        address = rng.randrange(8, 120)
        stretches = {edge: rng.randrange(1, 40) for edge in range(1, 20)}
        peer = await i2c_peer(d, address, byte, I2CPeer(stretches=stretches))
        assert peer.bytes == [address << 1, byte], peer.bytes
        assert peer.ack_bits == [0, 0]
        assert peer.starts == 1 and peer.stops == 1


@cocotb.test()
async def i2c_nack_timeout_and_contention(d):
    await reset(d)
    for ack, expected in [((False, True), [0xA0]), ((True, False), [0xA0, 0x69])]:
        peer = await i2c_peer(d, 0x50, 0x69, I2CPeer(ack=ack), expect_fault=True)
        assert peer.bytes == expected
        assert peer.ack_bits[-1] == 1
        assert peer.stops == 1, "NACK must get a STOP before TRAP"
    peer = await i2c_peer(d, 0x50, 0x69, I2CPeer(stretches={1: 1000}), timeout=25, expect_fault=True)
    assert len(peer.bytes) == 0
    assert peer.cycle < 1000, "stretch timeout was not bounded"
    peer = await i2c_peer(d, 0x50, 0x69, I2CPeer(contend=True), expect_fault=True)
    assert len(peer.bytes) == 0
    assert peer.cycle < 500, "contention must stop on the first bit, before any ACK"


@cocotb.test()
async def data_instruction_bounds_and_wait_timeout(d):
    await reset(d)
    for instruction in [0x50000007, 0x60000007, 0x80000007, 0x90000007, djnz(0), TRAP]:
        await load(d, [instruction])
        await start(d)
        await expect_halt(d, fault=True)
    for timeout in [1, 2, 17]:
        await load(d, [wait_pin(0, 1, timeout), HALT])
        await start(d)
        for index in range(timeout):
            assert int(d.uo_out.value) & 0x40
            await tick(d)
        await expect_halt(d, fault=True)
    # Distinguish loop count=1 from zero and verify masked update preserves other lanes.
    await load(d, [drive(31, 31, 1), load_byte(0, 1), patch(1, 0, 0, 8192), djnz(2), HALT])
    await start(d)
    await tick(d, 3)
    for _ in range(8192):
        assert int(d.uio_out.value) == 30
        assert int(d.uio_oe.value) == 30
        await tick(d)
    await expect_halt(d)
