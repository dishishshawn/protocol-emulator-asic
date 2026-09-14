"""Black-box pin-level tests, usable against RTL or the gate-level wrapper."""
import random
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from program import HALT, SAMPLE, drive, encode, jump, uart_tx, wait_pin


async def tick(d, n=1):
    for _ in range(n):
        d.clk.value = 0
        await Timer(50, unit="ns")
        d.clk.value = 1
        await Timer(50, unit="ns")


async def reset(d):
    d.clk.value = 0
    d.ena.value = 1
    d.rst_n.value = 0
    d.ui_in.value = 0
    d.uio_in.value = 0
    await tick(d, 5)
    d.rst_n.value = 1
    await tick(d, 5)
    assert int(d.uio_oe.value) == 0


async def load_bytes(d, data):
    for byte in data:
        d.ui_in.value = byte
        d.uio_in.value = 0
        await tick(d, 4)
        d.uio_in.value = 0x80
        await tick(d, 4)
        d.uio_in.value = 0
        await tick(d, 4)


async def load(d, words):
    d.uio_in.value = 0
    await tick(d, 5)
    d.uio_in.value = 0x20
    await tick(d, 5)
    d.uio_in.value = 0
    await tick(d, 5)
    await load_bytes(d, encode(words))


async def start(d, inputs=0):
    d.uio_in.value = 0x40 | inputs
    for _ in range(8):
        await tick(d)
        if int(d.uo_out.value) & 0xC0:
            return
    raise AssertionError("engine did not start or signal fault")


async def expect_halt(d, fault=False):
    for _ in range(8):
        if int(d.uo_out.value) & 0x20:
            assert int(d.uo_out.value) & 0xE0 == (0xA0 if fault else 0x20)
            assert int(d.uio_oe.value) == 0
            return
        await tick(d)
    raise AssertionError("engine did not halt")


@cocotb.test()
async def all_uart_bytes(d):
    await reset(d)
    for byte in range(256):
        cycles = [1, 2, 3, 7, 87][byte % 5]
        await load(d, uart_tx(byte, cycles))
        await start(d)
        await tick(d)  # first DRIVE
        # Independent UART framing oracle, checking every clock, not just edges.
        expected = [1, 0] + [(byte >> bit) & 1 for bit in range(8)] + [1]
        for level in expected:
            for _ in range(cycles):
                assert int(d.uio_oe.value) == 1, (byte, cycles)
                assert int(d.uio_out.value) & 1 == level, (byte, cycles)
                await tick(d)
        await expect_halt(d)


@cocotb.test()
async def random_pin_timing_and_max_delay(d):
    await reset(d)
    rng = random.Random(20260914)
    vectors = [(rng.randrange(32), rng.randrange(32), rng.randrange(1, 100)) for _ in range(62)]
    vectors.append((21, 31, 262144))
    await load(d, [drive(*v) for v in vectors] + [HALT])
    await start(d)
    await tick(d)
    for value, enable, cycles in vectors:
        for _ in range(cycles):
            assert int(d.uio_out.value) == value
            assert int(d.uio_oe.value) == enable
            await tick(d)
    await expect_halt(d)


@cocotb.test()
async def wait_sample_jump_and_open_drain(d):
    await reset(d)
    await load(d, [drive(0, 1, 3), drive(0, 0, 1), wait_pin(0, 1), SAMPLE,
                   jump(6), drive(31, 31, 100), HALT])
    await start(d)
    await tick(d)
    for _ in range(3):
        assert int(d.uio_oe.value) == 1
        assert int(d.uio_out.value) == 0
        await tick(d)
    await tick(d, 20)
    assert int(d.uio_oe.value) == 0  # released open-drain lane
    assert int(d.uo_out.value) == 0x40  # waiting, no timeout in this ISA
    d.uio_in.value = 0x40 | 0x15
    await tick(d, 8)
    await expect_halt(d)
    assert int(d.uo_out.value) & 31 == 0x15


@cocotb.test()
async def malformed_programs_fail_closed(d):
    bad_programs = [[0xC0000000], [0x10000007], [jump(63)], [drive(31, 31, 1)],
                    [drive(1, 1, 1)] * 64]
    for words in bad_programs:
        await reset(d)
        await load(d, words)
        await start(d)
        await tick(d, 70)
        await expect_halt(d, fault=True)
    for data in [b"", b"\x00", encode([HALT]) + b"\x00", encode([HALT] * 64) + b"\x00"]:
        await reset(d)
        await load_bytes(d, data)
        await start(d)
        await expect_halt(d, fault=True)


@cocotb.test()
async def abort_reset_and_reload(d):
    for action in ["abort", "reset", "deselect"]:
        await reset(d)
        await load(d, [drive(31, 31, 262144), jump(0)])
        await start(d)
        await tick(d, 6)
        assert int(d.uio_oe.value) == 31
        if action == "abort":
            d.uio_in.value = 0
        elif action == "reset":
            d.rst_n.value = 0
        else:
            d.ena.value = 0
        await tick(d, 4)
        assert int(d.uio_oe.value) == 0
        d.rst_n.value = 1
        d.ena.value = 1
        await load(d, [HALT])
        await start(d)
        await expect_halt(d)


@cocotb.test()
async def writes_while_running_are_ignored(d):
    await reset(d)
    await load(d, [wait_pin(0, 1), HALT])
    await start(d)
    d.ui_in.value = 0xFF
    for _ in range(5):
        d.uio_in.value = 0xE0  # LOAD and REWIND while RUN is high
        await tick(d, 5)
        d.uio_in.value = 0x40
        await tick(d, 5)
    d.uio_in.value = 0x41
    await tick(d, 6)
    await expect_halt(d)
    d.uio_in.value = 0
    await tick(d, 5)
    await start(d, 1)  # same image still works
    await tick(d, 6)
    await expect_halt(d)
