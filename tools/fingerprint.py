"""Receiver fingerprinting: probes, firmware, verdict decoding and the decision tree.

The classifier side never sees a receiver model. It has the probes (lane-0
waveforms), the firmware built from them, and verdicts decoded from capture
entries. test/test_fingerprint.py supplies the engine runs.

Verdict report convention (a fixture convention, not a chip feature): each
receiver under test owns one of lanes 1-4, which UART programs never enable.
REPORT_AT clocks after lane 0's output enable first asserts, every receiver
raises its lane for WIDTHS[verdict] clocks, the verdict being that of its
first completed frame. All rising edges coincide, so a run with four receivers
uses at most five capture entries. Decoding uses only fall - rise per lane.
"""
from program import HALT, drive, encode, hold
from streaming import capture, stream

CLOCKS = 32
VERDICTS = ("OK", "DATA", "FRAME", "NONE")
WIDTHS = {"OK": 4, "DATA": 8, "FRAME": 12, "NONE": 16}
LETTERS = {"OK": "O", "DATA": "D", "FRAME": "F", "NONE": "N"}
REPORT_LANES = (1, 2, 3, 4)
REPORT_MASK = 0b11110
REPORT_AT = 480  # after the longest probe (P3, W=24: 440 clocks) and every first frame
MARGIN = 8  # capture stays on this long past the widest pulse (synchronizer + echo)

FAMILIES = ("P1", "P2", "P3", "P4")
P2_WIDTHS = (1, 2, 3, 4, 5, 6, 8)
P3_WIDTHS = (1, 2, 4, 8, 12, 15, 16, 17, 20, 24)
P4_BYTES = (0x55, 0x0F)


def verdict(frames, sent):
    """OK / DATA / FRAME from the first completed frame, NONE if there is none."""
    if not frames:
        return "NONE"
    value, stop = frames[0]
    if not stop:
        return "FRAME"
    return "OK" if value == sent else "DATA"


def merge(segments):
    """Drop empty segments and join adjacent equal levels."""
    merged = []
    for level, clocks in segments:
        if level not in (0, 1) or clocks < 0:
            raise ValueError(f"bad segment {(level, clocks)}")
        if not clocks:
            continue
        if merged and merged[-1][0] == level:
            merged[-1] = (level, merged[-1][1] + clocks)
        else:
            merged.append((level, clocks))
    return merged


def _data(byte, clocks):
    return [((byte >> bit) & 1, clocks) for bit in range(8)]


def _probe(family, row, name, byte, segments):
    return {"family": family, "row": row, "id": name, "byte": byte, "segments": merge(segments)}


def make_probes(clocks=CLOCKS, p2_offsets=None):
    """The four probe families, in index order (rows keep neighbouring grid points adjacent).

    All waveforms start with one idle bit, so the (first) start edge is at t = T.
    """
    t = clocks
    probes = []
    for length in range(t):  # P1: 0xFF, stop bit low for L clocks from its start
        segments = [(1, t), (0, t)] + _data(0xFF, t) + [(0, length), (1, t - length)]
        probes.append(_probe("P1", "P1", f"P1 L={length}", 0xFF, segments))
    offsets = p2_offsets or range(t // 4, 3 * t // 4 + 1)
    for width in P2_WIDTHS:  # P2: 0xFF, low pulse inside data bit 3
        for offset in offsets:
            if offset + width > t:
                raise ValueError("P2 glitch must stay inside data bit 3")
            bits = _data(0xFF, t)
            bits[3:4] = [(1, offset), (0, width), (1, t - offset - width)]
            segments = [(1, t), (0, t)] + bits + [(1, t)]
            probes.append(_probe("P2", f"P2 W={width}", f"P2 W={width} o={offset}", 0xFF, segments))
    for width in P3_WIDTHS:  # P3: 0x55, low pulse ending 2T before the real start bit
        segments = [(1, t), (0, width), (1, 2 * t), (0, t)] + _data(0x55, t) + [(1, t)]
        probes.append(_probe("P3", "P3", f"P3 W={width}", 0x55, segments))
    for byte in P4_BYTES:  # P4: whole frame at T + delta clocks/bit
        for delta in range(-4, 5):
            bit = t + delta
            segments = [(1, t), (0, bit)] + _data(byte, bit) + [(1, bit)]
            probes.append(_probe("P4", f"P4 0x{byte:02X}", f"P4 0x{byte:02X} d={delta:+d}", byte, segments))
    for index, probe in enumerate(probes):
        probe["index"] = index
    return probes


def waveform_program(segments, report_at=REPORT_AT, mask=REPORT_MASK, margin=MARGIN):
    """Firmware that drives the waveform on lane 0 and captures the report lanes.

    The line ends driven high; capture stays on until every report pulse has
    ended (report_at + widest pulse + margin, counted from the first DRIVE).
    """
    segments = merge(segments)
    length = sum(clocks for _, clocks in segments)
    if length + 1 > report_at:
        raise ValueError(f"waveform ({length} clocks) must end before the report time {report_at}")
    rest = report_at + max(WIDTHS.values()) + margin - (length + 1)
    if not 1 <= rest <= 8192:
        raise ValueError(f"tail hold {rest} outside 1..8192")
    w = [stream(1), capture(mask)] + [drive(level, 1, clocks) for level, clocks in segments]
    w += [drive(1, 1, 1), hold(rest), capture(0), HALT]
    encode(w)  # enforce the 64-word instruction store
    return w


def expected_edges(segments):
    """Lane-0 transitions (t, level) the waveform should produce; the line starts and ends high."""
    edges, level, t = [], 1, 0
    for new, clocks in merge(segments) + [(1, 1)]:
        if new != level:
            edges.append((t, new))
        level, t = new, t + clocks
    return edges


def shifted(widths=WIDTHS, by=1):
    """Decode table with every verdict moved by one width class (negative control)."""
    return {v: widths[VERDICTS[(i + by) % len(VERDICTS)]] for i, v in enumerate(VERDICTS)}


def decode(events, widths=WIDTHS):
    """Verdict per report lane from capture entries: the width of the lane's single pulse.

    Raises if a lane pulses twice, never falls, or has a width outside the table.
    """
    by_width = {w: v for v, w in widths.items()}
    state, rises, pulses = 0, {}, {}
    for event in events:
        pins = event["pins"] & REPORT_MASK
        for lane in REPORT_LANES:
            bit = 1 << lane
            if pins & bit and not state & bit:
                if lane in rises or lane in pulses:
                    raise ValueError(f"lane {lane} reported more than once")
                rises[lane] = event["cycle"]
            elif state & bit and not pins & bit:
                pulses[lane] = event["cycle"] - rises.pop(lane)
        state = pins
    if rises:
        raise ValueError(f"lanes {sorted(rises)} never fell")
    unknown = {lane: width for lane, width in pulses.items() if width not in by_width}
    if unknown:
        raise ValueError(f"pulse widths {unknown} match no verdict")
    return {lane: by_width[width] for lane, width in sorted(pulses.items())}


def signature(verdicts):
    return "".join(LETTERS[v] for v in verdicts)


def separable(a, b, allowed):
    """Every variant of a differs from every variant of b on some allowed probe."""
    return all(any(x[q] != y[q] for q in allowed) for x in a for y in b)


def separating(a, b, allowed):
    """Allowed probes on which the verdict sets of a and b are disjoint."""
    return [q for q in allowed if not {x[q] for x in a} & {y[q] for y in b}]


def _neighbours(probes, q):
    return [n for n in (q - 1, q + 1) if 0 <= n < len(probes) and probes[n]["row"] == probes[q]["row"]]


def _confirmations(probes, signatures, unused, count):
    """Confirmation probes for a leaf: unused probes on which all its variants agree.

    Preference goes to probes next to one of the leaf's own verdict boundaries
    (a neighbouring grid point in the same row gives a different verdict),
    taken lowest index first, one family at a time in family order; then the
    remaining agreeing probes by index. A near-miss receiver most likely
    differs where the leaf's verdict changes.
    """
    agree = [q for q in unused if len({s[q] for s in signatures}) == 1]
    boundary = [q for q in agree
                if any(s[q] != s[n] for s in signatures for n in _neighbours(probes, q))]
    queues = {f: [q for q in boundary if probes[q]["family"] == f] for f in FAMILIES}
    picks = []
    while len(picks) < count and any(queues.values()):
        for family in FAMILIES:
            if queues[family] and len(picks) < count:
                picks.append(queues[family].pop(0))
    picks += [q for q in agree if q not in picks][:count - len(picks)]
    picks += [q for q in unused if q not in picks][:count - len(picks)]
    return sorted(picks)


def build_tree(probes, variants, allowed=None, confirm=3):
    """Greedy decision tree over (label, signature) variants.

    A label may have several variants (one per tick phase). At each node the
    probe chosen minimises the most labels left in any branch, then the most
    variants, then the probe index. A leaf holds one label, or an equivalence
    class of labels that no allowed probe separates. Each leaf gets `confirm`
    confirmation probes from the allowed probes the tree does not use.
    """
    allowed = sorted(range(len(probes)) if allowed is None else allowed)

    def grow(group):
        labels = sorted({label for label, _ in group})
        if len(labels) == 1:
            return {"leaf": labels, "_variants": group}
        best = None
        for q in allowed:
            branches = {}
            for label, sig in group:
                branches.setdefault(sig[q], []).append((label, sig))
            if len(branches) < 2:
                continue
            cost = (max(len({label for label, _ in b}) for b in branches.values()),
                    max(len(b) for b in branches.values()))
            if best is None or cost < best[0]:
                best = (cost, q, branches)
        if best is None:
            return {"leaf": labels, "_variants": group}
        _, q, branches = best
        return {"probe": q, "id": probes[q]["id"],
                "branches": {_verdict(letter): grow(b) for letter, b in sorted(branches.items())}}

    tree = grow(sorted(set(variants)))
    used = set(tree_probes(tree))
    unused = [q for q in allowed if q not in used]
    for leaf in leaves(tree):
        signatures = [sig for _, sig in leaf.pop("_variants")]
        leaf["confirm"] = [{"probe": q, "id": probes[q]["id"],
                            "expect": sorted({_verdict(s[q]) for s in signatures})}
                           for q in _confirmations(probes, signatures, unused, confirm)]
    return tree


def _verdict(letter):
    return next(v for v in VERDICTS if LETTERS[v] == letter)


def leaves(tree):
    if "leaf" in tree:
        return [tree]
    return [leaf for branch in tree["branches"].values() for leaf in leaves(branch)]


def tree_probes(tree):
    if "leaf" in tree:
        return []
    return [tree["probe"]] + [q for b in tree["branches"].values() for q in tree_probes(b)]


def route(tree, sig):
    """The leaf a known signature reaches (None if it leaves the tree)."""
    while "probe" in tree:
        tree = tree["branches"].get(_verdict(sig[tree["probe"]]))
        if tree is None:
            return None
    return tree


def depth(tree):
    return 0 if "leaf" in tree else 1 + max(depth(b) for b in tree["branches"].values())


async def identify(run_probe, tree):
    """Identify an unknown receiver from verdicts alone.

    await run_probe(index) runs one probe against the receiver and returns its
    decoded verdict. An outcome with no branch, or a confirmation mismatch at
    the leaf, gives "unknown"; otherwise the answer is the leaf's label set.
    """
    used, node = [], tree
    while "probe" in node:
        outcome = await run_probe(node["probe"])
        used.append(node["probe"])
        if outcome not in node["branches"]:
            return {"answer": "unknown", "probes": used,
                    "reason": f"{node['id']}: {outcome} matches no branch"}
        node = node["branches"][outcome]
    for check in node["confirm"]:
        outcome = await run_probe(check["probe"])
        used.append(check["probe"])
        if outcome not in check["expect"]:
            return {"answer": "unknown", "probes": used,
                    "reason": f"leaf {node['leaf']}: {check['id']} gave {outcome}, "
                              f"expected {'/'.join(check['expect'])}"}
    return {"answer": node["leaf"], "probes": used}
