"""Fault-length sweep for the live demo: every point is a real engine run.

Run via `just fault-sweep`; writes SWEEP_REPORT (JSON). Not part of the regression.
"""
import json
import os
from pathlib import Path

import cocotb

from test_engine import load, reset
from test_streaming import Bus, UARTReceiver
from streaming import fault_demo

CLOCKS = 32
RESPONSE = {"clean": 103, "framing_error": 59}  # modeled target latencies, clocks
# Bytes are chosen so a frame plus fault plus response never exceeds the eight-entry
# capture FIFO (the test asserts no overflow); an alternating byte would need draining.
PULSE = 11


def lane0(edges, cycle):
    """Driven lane-0 level at a cycle, from the peer's edge list (idle high)."""
    return next((pins for t, pins in reversed(edges) if t <= cycle), 1) & 1


@cocotb.test()
async def fault_length_sweep(d):
    await reset(d)
    lengths = [int(v) for v in os.environ.get("SWEEP_LENGTHS", "0,2,4,6,8,10,12,14,15,16,17,18,20,24,28,32,40,48,56,64").split(",")]
    bytes_ = [int(v, 0) for v in os.environ.get("SWEEP_BYTES", "0xff,0x00,0xf0,0x0f,0xc3").split(",")]
    runs = []
    for byte in bytes_:
        for fault in lengths:
            await load(d, fault_demo(cycles_per_bit=CLOCKS, byte=byte, fault_clocks=fault))
            uart = UARTReceiver(CLOCKS)
            pulse_start = None
            edges = []
            last = 1

            def target(b):
                nonlocal pulse_start, last
                level = uart(b)
                if uart.frames and pulse_start is None:
                    verdict = "clean" if uart.frames[0][1] else "framing_error"
                    pulse_start = uart.frames[0][2] + RESPONSE[verdict]
                response = int(pulse_start is not None and pulse_start <= b.cycle < pulse_start + PULSE)
                pins = level | (response << 4)
                if pins != last:
                    edges.append((b.cycle, pins))
                last = pins
                return pins

            b = Bus(d, target, inputs=1)
            await b.finish()
            events = await b.host.captures()
            assert len(uart.frames) == 1
            value, stop, stop_cycle = uart.frames[0]
            assert value == byte
            assert len(events) == len(edges) and [e["pins"] for e in events] == [e[1] for e in edges]
            offsets = {event["cycle"] - edge[0] for event, edge in zip(events, edges)}
            assert len(offsets) == 1
            response = [e for e in events if e["pins"] & 16]
            assert len(response) == 1
            i = events.index(response[0])
            assert events[i + 1]["cycle"] - events[i]["cycle"] == PULSE
            assert await b.host.page(10) == 0
            # The requested fault really happened: from the start of the stop bit,
            # lane 0 stayed low for exactly fault clocks (edges are the driven pins,
            # equal to the captured events above), and the receiver's verdict follows
            # from whether its mid-bit sample fell inside that fault.
            stop_start = stop_cycle - CLOCKS // 2
            measured = 0
            while lane0(edges, stop_start + measured) == 0 and measured <= 4 * CLOCKS:
                measured += 1
            assert measured == fault
            assert lane0(edges, stop_start - 1) == (byte >> 7)
            assert stop == int(fault <= CLOCKS // 2)
            runs.append({"byte": byte, "fault_clocks": fault, "clocks_per_bit": CLOCKS,
                         "measured_fault_clocks": measured,
                         "received_byte": value, "stop_bit": stop,
                         "verdict": "clean" if stop else "framing_error",
                         "response_delay_from_stop_sample": RESPONSE["clean" if stop else "framing_error"],
                         "events": events, "synchronizer_offset": offsets.pop()})
    report = {"clocks_per_bit": CLOCKS, "response_model": RESPONSE, "pulse_clocks": PULSE,
              "runs": runs}
    if os.environ.get("SWEEP_REPORT"):
        Path(os.environ["SWEEP_REPORT"]).write_text(json.dumps(report) + "\n")
