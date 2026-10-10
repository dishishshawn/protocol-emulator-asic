"""Independent UART receiver models for receiver fingerprinting.

Each model is a per-clock callable: call it once per engine clock with the
lane-0 level (released counts as idle high, which the fixture resolves). Times
are clocks from the start edge the receiver detected, at T clocks/bit. A model
appends (byte, stop_level) to self.frames when a frame completes. Models do
not touch the engine, the simulator or each other; the fixture turns their
first frame into a reported verdict.

Run directly for the pure-Python boundary checks (no simulator needed).
"""


class MidSample:
    """Single sample at mid-bit, no start validation.

    Any falling edge while idle starts a frame. The line is sampled once per
    bit at T/2 + kT for k = 0..9 (start, eight data bits LSB first, stop); the
    start sample is not checked, so a glitch is accepted as a start bit. The
    frame completes at the stop sample and the receiver returns to idle,
    watching for the next falling edge.
    """

    def __init__(self, clocks, offset=None):
        self.clocks = clocks
        self.offset = clocks // 2 if offset is None else offset
        self.t = 0
        self.prev = 1
        self.next = None
        self.bits = []
        self.frames = []

    def __call__(self, level):
        if self.next is None and self.prev and not level:
            self.next = self.t + self.offset
            self.bits = []
        if self.next == self.t:
            self.bits.append(level)
            self.next += self.clocks
            if len(self.bits) == 10:
                value = sum(v << bit for bit, v in enumerate(self.bits[1:9]))
                self.frames.append((value, self.bits[9]))
                self.next = None
        self.prev = level
        self.t += 1


class MidSamplePlus1(MidSample):
    """MidSample sampling one clock late: once per bit at T/2 + 1 + kT.

    Negative control for resolution. Everything else (no start validation,
    stop check, return to idle at the stop sample) is MidSample's.
    """

    def __init__(self, clocks):
        super().__init__(clocks, clocks // 2 + 1)


class MidSampleTwin:
    """MidSample's algorithm, written separately as a countdown state machine.

    A falling edge while idle loads a half-bit countdown; when it expires the
    line is sampled and the countdown reloads with a full bit. The first sample
    is the (unchecked) start bit, the next eight shift into the byte LSB first,
    and the tenth is the stop bit, which completes the frame and returns to
    idle. Negative control: it must land in MidSample's equivalence class.
    """

    def __init__(self, clocks):
        self.period = clocks
        self.line = 1
        self.countdown = 0
        self.taken = None  # samples taken in the current frame; None when idle
        self.shift = 0
        self.frames = []

    def __call__(self, level):
        falling = self.line == 1 and level == 0
        self.line = level
        if self.taken is None:
            if falling:
                self.taken, self.shift, self.countdown = 0, 0, self.period // 2
            return
        self.countdown -= 1
        if self.countdown:
            return
        self.countdown = self.period
        self.taken += 1
        if 2 <= self.taken <= 9:
            self.shift = (self.shift >> 1) | (level << 7)
        elif self.taken == 10:
            self.frames.append((self.shift, level))
            self.taken = None


class _Majority:
    """Oversampling receiver: majority vote of three ticks around mid-bit.

    The line is looked at only on ticks, every T/ratio clocks, at tick phase p
    (ticks fall on the clocks where t mod (T/ratio) == p, t counted from the
    fixture's time zero). A frame starts at the first tick that reads low after
    a tick that read high, so the start edge is seen up to one tick late. Each
    bit's value is the majority of ticks ratio/2 - 1, ratio/2 and ratio/2 + 1
    of that bit, counted from the detecting tick. A start bit whose majority is
    high is a false start: the receiver returns to idle. The stop bit is the
    tenth majority; the frame completes there and the receiver returns to idle.
    """

    ratio = None

    def __init__(self, clocks, phase=0):
        if clocks % self.ratio:
            raise ValueError(f"T must be a multiple of {self.ratio}")
        self.tick = clocks // self.ratio
        if not 0 <= phase < self.tick:
            raise ValueError(f"tick phase must be 0..{self.tick - 1}")
        self.clocks, self.phase = clocks, phase
        self.picks = (self.ratio // 2 - 1, self.ratio // 2, self.ratio // 2 + 1)
        self.t = 0
        self.prev = 1  # level at the previous tick
        self.ticks = None  # ticks since the detecting tick; None when idle
        self.votes = []
        self.bits = []
        self.frames = []

    def sample_clocks(self):
        """Clocks after the detecting tick at which bit 0 is sampled."""
        return [self.tick * pick for pick in self.picks]

    def __call__(self, level):
        if self.t % self.tick == self.phase:
            self._on_tick(level)
        self.t += 1

    def _on_tick(self, level):
        if self.ticks is None:
            if self.prev and not level:
                self.ticks, self.votes, self.bits = 0, [], []
        else:
            self.ticks += 1
            bit, position = divmod(self.ticks, self.ratio)
            if position in self.picks:
                self.votes.append(level)
            if position == self.picks[-1]:
                value = int(sum(self.votes) >= 2)
                self.votes = []
                if bit == 0 and value:
                    self.ticks = None
                else:
                    self.bits.append(value)
                    if len(self.bits) == 10:
                        byte = sum(v << i for i, v in enumerate(self.bits[1:9]))
                        self.frames.append((byte, self.bits[9]))
                        self.ticks = None
        self.prev = level


class Majority16(_Majority):
    """16x oversampling: tick = T/16, vote of ticks 7, 8, 9 (clocks 14, 16, 18 at T=32).

    Algorithm as in _Majority: start edge seen at a tick, start-bit majority
    must be low or the receiver returns to idle, stop bit checked.
    """

    ratio = 16


class Majority8(_Majority):
    """8x oversampling: tick = T/8, vote of ticks 3, 4, 5 (clocks 12, 16, 20 at T=32).

    Algorithm as in _Majority: start edge seen at a tick, start-bit majority
    must be low or the receiver returns to idle, stop bit checked.
    """

    ratio = 8


class EdgeResync:
    """Single mid-bit sample that re-centres on every transition.

    A falling edge while idle starts a frame and schedules the start sample at
    T/2. Inside a frame, every transition of the line reschedules the next
    pending sample to the transition + T/2 (a transition on the clock a sample
    was due moves that sample; it is not taken first); after each sample the
    next is T later. Samples are start, eight data bits LSB first, stop. A high
    start sample is a false start (back to idle). The stop sample completes the
    frame and the receiver returns to idle.
    """

    def __init__(self, clocks):
        self.clocks = clocks
        self.half = clocks // 2
        self.t = 0
        self.prev = 1
        self.next = None
        self.bits = []
        self.frames = []

    def __call__(self, level):
        if self.next is None:
            if self.prev and not level:
                self.next = self.t + self.half
                self.bits = []
        elif level != self.prev:
            self.next = self.t + self.half
        if self.next == self.t:
            if not self.bits and level:
                self.next = None
            else:
                self.bits.append(level)
                self.next += self.clocks
                if len(self.bits) == 10:
                    value = sum(v << bit for bit, v in enumerate(self.bits[1:9]))
                    self.frames.append((value, self.bits[9]))
                    self.next = None
        self.prev = level
        self.t += 1


class LenientStop:
    """Single mid-bit sample with start validation and no stop check.

    A falling edge while idle starts a frame; the start sample at T/2 must be
    low, otherwise the receiver returns to idle. Data bits are sampled at
    T/2 + kT, LSB first. The stop bit's sample is taken at T/2 + 9T, which
    completes the frame, but its level is ignored: the frame always reports a
    high stop bit, so this receiver never reports a framing error.
    """

    def __init__(self, clocks):
        self.clocks = clocks
        self.t = 0
        self.prev = 1
        self.next = None
        self.bits = []
        self.frames = []

    def __call__(self, level):
        if self.next is None and self.prev and not level:
            self.next = self.t + self.clocks // 2
            self.bits = []
        if self.next == self.t:
            if not self.bits and level:
                self.next = None
            else:
                self.bits.append(level)
                self.next += self.clocks
                if len(self.bits) == 10:
                    value = sum(v << bit for bit, v in enumerate(self.bits[1:9]))
                    self.frames.append((value, 1))
                    self.next = None
        self.prev = level
        self.t += 1


MAIN = {"MidSample": MidSample, "Majority16": Majority16, "Majority8": Majority8,
        "EdgeResync": EdgeResync, "LenientStop": LenientStop}
CONTROLS = {"MidSampleTwin": MidSampleTwin, "MidSamplePlus1": MidSamplePlus1}
OVERSAMPLING = {"Majority16", "Majority8"}


def create(name, clocks, phase=0):
    """A fresh model; phase applies only to the oversampling receivers."""
    cls = {**MAIN, **CONTROLS}[name]
    return cls(clocks, phase) if name in OVERSAMPLING else cls(clocks)


def phases(name, clocks):
    """Tick phases a receiver can take (a single phase for non-oversampling models)."""
    return range(clocks // {**MAIN, **CONTROLS}[name].ratio) if name in OVERSAMPLING else range(1)


# --- Pure-Python checks against hand-built waveforms (plain asserts) ---------

T = 32


def uart(byte, bit_clocks=T, idle=T, tail=4 * T):
    """Per-clock levels: idle, start, data LSB first, stop, then idle."""
    levels = [1] * idle
    for level in [0] + [(byte >> bit) & 1 for bit in range(8)] + [1]:
        levels += [level] * bit_clocks
    return levels + [1] * tail


def low(levels, start, clocks):
    levels = list(levels)
    levels[start:start + clocks] = [0] * clocks
    return levels


def run(model, levels):
    for level in levels:
        model(level)
    return model.frames


STOP = T + 9 * T  # first clock of the stop bit, start edge at t = T
BIT3 = T + 4 * T  # first clock of data bit 3


def check_mid_sample(cls):
    assert run(cls(T), uart(0xFF)) == [(0xFF, 1)]
    assert run(cls(T), low(uart(0xFF), STOP, 16)) == [(0xFF, 1)]
    assert run(cls(T), low(uart(0xFF), STOP, 17)) == [(0xFF, 0)]
    # Glitch inside data bit 3: flips the byte only when it covers clock 16.
    assert run(cls(T), low(uart(0xFF), BIT3 + 16, 1)) == [(0xF7, 1)]
    assert run(cls(T), low(uart(0xFF), BIT3 + 15, 1)) == [(0xFF, 1)]
    assert run(cls(T), low(uart(0xFF), BIT3 + 17, 1)) == [(0xFF, 1)]
    assert run(cls(T), low(uart(0xFF), BIT3 + 14, 3)) == [(0xF7, 1)]
    assert run(cls(T), low(uart(0xFF), BIT3 + 14, 2)) == [(0xFF, 1)]
    # A one-clock false start on an idle line is accepted as a whole frame.
    assert run(cls(T), low([1] * 20 * T, T, 1)) == [(0xFF, 1)]
    # Skew: the stop sample (304 clocks after the edge) leaves the stop bit at
    # T+2, and the bit-7 sample (272) enters the stop bit at T-2.
    for delta, frame in ((-2, (0x8F, 1)), (-1, (0x0F, 1)), (1, (0x0F, 1)), (2, (0x0F, 0))):
        assert run(cls(T), uart(0x0F, T + delta)) == [frame], delta


def check_majority():
    # Phase 0: start edge at t = 32 lands on a tick, samples at 14/16/18 and 12/16/20.
    for cls in (Majority16, Majority8):
        assert run(cls(T), uart(0xFF)) == [(0xFF, 1)]
        assert run(cls(T), low(uart(0xFF), STOP, 16)) == [(0xFF, 1)]
        assert run(cls(T), low(uart(0xFF), STOP, 17)) == [(0xFF, 0)]
    # 3-clock glitch centred on 16 hits one vote of each; 14..16 hits two of Majority16's.
    for cls in (Majority16, Majority8):
        assert run(cls(T), low(uart(0xFF), BIT3 + 15, 3)) == [(0xFF, 1)]
    assert run(Majority16(T), low(uart(0xFF), BIT3 + 14, 3)) == [(0xF7, 1)]
    assert run(Majority8(T), low(uart(0xFF), BIT3 + 14, 3)) == [(0xFF, 1)]
    # 5-clock glitch centred on 16 (14..18): all of Majority16's votes, one of Majority8's.
    assert run(Majority16(T), low(uart(0xFF), BIT3 + 14, 5)) == [(0xF7, 1)]
    assert run(Majority8(T), low(uart(0xFF), BIT3 + 14, 5)) == [(0xFF, 1)]
    assert run(Majority8(T), low(uart(0xFF), BIT3 + 12, 5)) == [(0xF7, 1)]
    # A late tick phase delays detection and moves the stop boundary with it.
    assert run(Majority16(T, 1), low(uart(0xFF), STOP, 17)) == [(0xFF, 1)]
    assert run(Majority16(T, 1), low(uart(0xFF), STOP, 18)) == [(0xFF, 0)]
    assert run(Majority8(T, 3), low(uart(0xFF), STOP, 19)) == [(0xFF, 1)]
    assert run(Majority8(T, 3), low(uart(0xFF), STOP, 20)) == [(0xFF, 0)]
    # False starts: the start-bit vote rejects short pulses; pulses between
    # ticks are not seen at all.
    idle = [1] * 20 * T
    assert run(Majority16(T), low(idle, T, 1)) == []
    assert run(Majority16(T, 1), low(idle, T, 1)) == []
    assert run(Majority16(T), low(idle, T, 16)) == []
    assert run(Majority16(T), low(idle, T, 17)) == [(0xFF, 1)]
    assert run(Majority8(T), low(idle, T, 2)) == []
    assert run(Majority8(T, 2), low(idle, T, 2)) == []
    assert run(Majority8(T), low(idle, T, 16)) == []
    assert run(Majority8(T), low(idle, T, 17)) == [(0xFF, 1)]
    model = Majority8(T, 3)
    assert model.sample_clocks() == [12, 16, 20] and Majority16(T).sample_clocks() == [14, 16, 18]
    for bad in ((Majority8, 4), (Majority16, 2)):
        try:
            bad[0](T, bad[1])
        except ValueError:
            continue
        raise AssertionError(f"{bad} accepted an out-of-range phase")


def check_edge_resync():
    assert run(EdgeResync(T), uart(0xFF)) == [(0xFF, 1)]
    # The stop edge re-centres the stop sample on 16, so the boundary stays 16/17.
    assert run(EdgeResync(T), low(uart(0xFF), STOP, 15)) == [(0xFF, 1)]
    assert run(EdgeResync(T), low(uart(0xFF), STOP, 16)) == [(0xFF, 1)]
    assert run(EdgeResync(T), low(uart(0xFF), STOP, 17)) == [(0xFF, 0)]
    # Any glitch in an all-ones byte only moves the next sample past its end.
    for offset in (8, 15, 16, 24):
        for width in (1, 3, 5, 8):
            levels = low(uart(0xFF), BIT3 + offset, width)
            assert run(EdgeResync(T), levels) == [(0xFF, 1)], (offset, width)
    idle = [1] * 20 * T
    assert run(EdgeResync(T), low(idle, T, 16)) == []
    assert run(EdgeResync(T), low(idle, T, 17)) == [(0xFF, 1)]
    # 0x55 has an edge every bit, so skew never accumulates.
    for delta in range(-4, 5):
        assert run(EdgeResync(T), uart(0x55, T + delta)) == [(0x55, 1)], delta
    # 0x0F at T-4: four free-running samples drift onto the bit-4 edge, which
    # pushes the bit-3 sample into bit 4; the stop edge then pushes bit 6's
    # sample into the stop bit.
    assert run(EdgeResync(T), uart(0x0F, T - 4)) == [(0xC7, 1)]
    assert run(EdgeResync(T), uart(0x0F, T + 4)) == [(0x0F, 1)]


def check_lenient_stop():
    assert run(LenientStop(T), uart(0xFF)) == [(0xFF, 1)]
    assert run(LenientStop(T), low(uart(0xFF), STOP, 31)) == [(0xFF, 1)]
    assert run(LenientStop(T), low(uart(0xFF), BIT3 + 16, 1)) == [(0xF7, 1)]
    idle = [1] * 20 * T
    assert run(LenientStop(T), low(idle, T, 16)) == []
    assert run(LenientStop(T), low(idle, T, 17)) == [(0xFF, 1)]


def check_plus_one():
    assert run(MidSamplePlus1(T), low(uart(0xFF), STOP, 17)) == [(0xFF, 1)]
    assert run(MidSamplePlus1(T), low(uart(0xFF), STOP, 18)) == [(0xFF, 0)]
    assert run(MidSamplePlus1(T), low(uart(0xFF), BIT3 + 17, 1)) == [(0xF7, 1)]
    assert run(MidSamplePlus1(T), low(uart(0xFF), BIT3 + 16, 1)) == [(0xFF, 1)]


def check_twin(seed=20261010, count=400):
    """MidSampleTwin agrees with MidSample on random segment waveforms."""
    import random

    rng = random.Random(seed)
    for _ in range(count):
        levels, level = [1] * rng.randrange(1, 40), 1
        while len(levels) < 30 * T:
            level ^= 1
            levels += [level] * rng.choice([1, 2, 3, 8, 15, 16, 17, 31, 32, 33, 64])
        assert run(MidSample(T), levels) == run(MidSampleTwin(T), levels)


def check_against_sweep(path):
    """MidSample reproduces UARTReceiver's recorded verdicts on the fault sweep.

    Rebuilds each run's lane-0 waveform from its captured edges (pins bit 0).
    """
    import json

    report = json.loads(path.read_text())
    clocks = report["clocks_per_bit"]
    for entry in report["runs"]:
        changes = {e["cycle"]: e["pins"] & 1 for e in entry["events"]}
        model, level = MidSample(clocks), 1
        for cycle in range(max(changes) + 4 * clocks):
            level = changes.get(cycle, level)
            model(level)
        assert model.frames == [(entry["received_byte"], entry["stop_bit"])], entry["fault_clocks"]
    return len(report["runs"])


def check():
    from pathlib import Path

    check_mid_sample(MidSample)
    check_mid_sample(MidSampleTwin)
    check_majority()
    check_edge_resync()
    check_lenient_stop()
    check_plus_one()
    check_twin()
    runs = check_against_sweep(Path(__file__).resolve().parents[1] / "reports" / "fault-sweep.json")
    print(f"receiver model checks passed (MidSample matches {runs} recorded sweep verdicts)")


if __name__ == "__main__":
    check()
