"""Receiver fingerprinting: every verdict is a real engine run read back through capture.

Stimulus is firmware loaded through the host port (tools/fingerprint.py); verdicts
come only from Host.captures(). The fixture reads model internals solely to
cross-check the decoded verdicts, never to feed the classifier. Run via
`just fingerprint`; writes FINGERPRINT_REPORT (deterministic JSON) and
FINGERPRINT_TIMING (wall time). Not part of the regression.
"""
import inspect
import itertools
import json
import os
import random
import time
from pathlib import Path

import cocotb

import receivers
from test_engine import load, reset  # also puts tools/ on sys.path
from test_streaming import Bus, UARTReceiver, driven
from fingerprint import (CLOCKS, FAMILIES, MARGIN, REPORT_AT, REPORT_LANES, REPORT_MASK,
                         VERDICTS, WIDTHS, build_tree, decode, depth, expected_edges, identify,
                         make_probes, route, separable, separating, shifted, signature,
                         tree_probes, verdict, waveform_program)

GROUPS = {"A": ("MidSample", "Majority16", "Majority8", "EdgeResync"),
          "B": ("LenientStop", "MidSampleTwin", "MidSamplePlus1")}
MAIN = tuple(receivers.MAIN)
CONTROLS = tuple(receivers.CONTROLS)
SHUFFLE_SEED = 20261010


class Fixture:
    """Per-clock peer: echoes lane 0, runs the attached receivers, drives their report lanes.

    Time zero is the first clock lane 0's output enable is seen asserted. Each
    attached receiver (lane -> model) sees the lane-0 level (released = idle
    high) from then on; at REPORT_AT its first frame's verdict is latched and
    its lane is held high for WIDTHS[verdict] clocks.
    """

    def __init__(self, attached, sent, shadow=None):
        self.attached, self.sent, self.shadow = attached, sent, shadow
        self.t = None
        self.level = 1
        self.edges = []
        self.verdicts = {}

    def __call__(self, b):
        oe, out = driven(b.d)
        level = out & 1 if oe & 1 else 1
        if self.shadow:
            self.shadow(b)
        if self.t is None and oe & 1:
            self.t = 0
        if self.t is None:
            return level
        if level != self.level:
            self.edges.append((self.t, level))
        self.level = level
        if self.t == REPORT_AT:
            self.verdicts = {lane: verdict(m.frames, self.sent) for lane, m in self.attached.items()}
        for model in self.attached.values():
            model(level)
        pins = level
        for lane, v in self.verdicts.items():
            if self.t < REPORT_AT + WIDTHS[v]:
                pins |= 1 << lane
        self.t += 1
        return pins


class Session:
    def __init__(self, d, probes):
        self.d, self.probes = d, probes
        self.runs = self.clocks = 0

    async def run(self, q, attached, shadow=False):
        """One probe against attached receivers; returns (decoded verdicts by lane, events)."""
        probe = self.probes[q]
        await load(self.d, waveform_program(probe["segments"], REPORT_AT, REPORT_MASK))
        uart = UARTReceiver(CLOCKS) if shadow else None
        fixture = Fixture(attached, probe["byte"], uart)
        b = Bus(self.d, fixture, inputs=1)
        await b.finish()
        events = await b.host.captures()
        assert await b.host.page(10) == 0, probe["id"]
        # The stimulus really happened: lane 0 as driven, clock for clock.
        assert fixture.edges == expected_edges(probe["segments"]), probe["id"]
        assert len(events) <= 1 + len(set(fixture.verdicts.values())), (probe["id"], events)
        decoded = decode(events)
        assert decoded == fixture.verdicts, (probe["id"], decoded, fixture.verdicts)
        if uart:
            # MidSample (lane 1) reproduces the regression's UART receiver.
            assert [(v, stop) for v, stop, _ in uart.frames] == attached[1].frames, probe["id"]
        self.runs += 1
        self.clocks += b.cycle
        return decoded, events

    def runner(self, name, phase):
        """run_probe for blind identification: a fresh receiver on lane 1, verdict only."""
        async def run_probe(q):
            decoded, _ = await self.run(q, {1: receivers.create(name, CLOCKS, phase)})
            return decoded[1]
        return run_probe


def waveform_text(segments):
    return " ".join(f"{level}:{clocks}" for level, clocks in segments)


def receiver_info(name):
    cls = {**receivers.MAIN, **receivers.CONTROLS}[name]
    doc = inspect.getdoc(cls)
    if issubclass(cls, receivers._Majority):
        doc = inspect.getdoc(receivers._Majority) + "\n\n" + doc
    model = receivers.create(name, CLOCKS)
    params = {"clocks_per_bit": CLOCKS, "stop_check": name != "LenientStop",
              "start_validation": name not in ("MidSample", "MidSampleTwin", "MidSamplePlus1")}
    if name in receivers.OVERSAMPLING:
        params.update(tick_clocks=model.tick, vote_clocks=model.sample_clocks(),
                      phases=list(receivers.phases(name, CLOCKS)))
    elif name == "EdgeResync":
        params["sample_after_transition"] = model.half
    else:
        params["sample_clock"] = getattr(model, "offset", CLOCKS // 2)
    group = next(g for g, names in GROUPS.items() if name in names)
    return {"role": "main" if name in MAIN else "control", "group": group,
            "lane": REPORT_LANES[GROUPS[group].index(name)], "parameters": params,
            "algorithm": " ".join(doc.split())}


def pair_table(probes, sets, names, allowed):
    rows = []
    for a, b in itertools.combinations(names, 2):
        qs = separating(sets[a], sets[b], allowed)
        rows.append({"pair": [a, b], "separable": separable(sets[a], sets[b], allowed),
                     "separating_probes": len(qs),
                     "first_probe": probes[qs[0]]["id"] if qs else None,
                     "by_family": {f: sum(probes[q]["family"] == f for q in qs) for f in FAMILIES}})
    return rows


def describe(probes, result, name, phase, truth):
    entry = {"receiver": name, "phase": phase, "answer": result["answer"],
             "probes": [probes[q]["id"] for q in result["probes"]],
             "probe_count": len(result["probes"])}
    if truth is not None:
        entry["correct"] = result["answer"] == truth
    if "reason" in result:
        entry["reason"] = result["reason"]
    return entry


async def identify_all(s, probes, tree):
    """Blind identification of every main receiver at every tick phase."""
    found = []
    for name in MAIN:
        for phase in receivers.phases(name, CLOCKS):
            result = await identify(s.runner(name, phase), tree)
            found.append(describe(probes, result, name, phase, [name]))
    return found


def check_program_limits(probes):
    """waveform_program refuses anything the engine or the report convention cannot run."""
    longest = max(probes, key=lambda p: sum(c for _, c in p["segments"]))["segments"]
    for bad in (dict(segments=longest, report_at=400),  # waveform runs past the report
                dict(segments=[(1, 32)], report_at=9000),  # tail hold above 8192
                dict(segments=[(i & 1, 1) for i in range(60)]),  # more than 64 words
                dict(segments=[(2, 32)])):
        try:
            waveform_program(**bad)
        except ValueError:
            continue
        raise AssertionError(f"waveform_program accepted {bad}")


@cocotb.test()
async def receiver_fingerprint(d):
    started = time.monotonic()
    await reset(d)
    probes = make_probes(CLOCKS)
    check_program_limits(probes)
    s = Session(d, probes)
    everything = range(len(probes))

    # Map: every probe against both groups. Group A runs once per Majority8 tick
    # phase (Majority16 takes phase mod 2); a model without phases must repeat.
    runs_a = len(receivers.phases("Majority8", CLOCKS))
    verdicts = {}
    raw = []
    example = None
    for q, probe in enumerate(probes):
        for group, names in GROUPS.items():
            for run_phase in range(runs_a if group == "A" else 1):
                phase_of = {n: run_phase % len(receivers.phases(n, CLOCKS)) for n in names}
                attached = {lane: receivers.create(n, CLOCKS, phase_of[n])
                            for lane, n in zip(REPORT_LANES, names)}
                shadow = group == "A" and run_phase == 0 and probe["family"] != "P3"
                decoded, events = await s.run(q, attached, shadow)
                raw.append((events, decoded))
                for lane, n in zip(REPORT_LANES, names):
                    seen = verdicts.setdefault((n, phase_of[n]), [])
                    if len(seen) == q:
                        seen.append(decoded[lane])
                    else:
                        assert seen[q] == decoded[lane], (n, phase_of[n], probe["id"])
                if group == "A" and run_phase == 0 and (
                        example is None or len(set(decoded.values())) > len(set(example["verdicts"].values()))):
                    example = {"probe": probe["id"], "events": events,
                               "verdicts": {GROUPS["A"][lane - 1]: v for lane, v in decoded.items()}}
    sig = {key: signature(v) for key, v in verdicts.items()}
    phase_sets = {n: [sig[(n, p)] for p in receivers.phases(n, CLOCKS)] for n in MAIN}
    phase0 = {n: [sig[(n, 0)]] for n in MAIN}

    # Tree from the phase-0 map; identify every phase. A receiver that fails at
    # any phase gets its signature set across phases and the tree is rebuilt.
    rounds = []
    sets = dict(phase0)
    while True:
        tree = build_tree(probes, [(n, x) for n in MAIN for x in sets[n]])
        found = await identify_all(s, probes, tree)
        failed = sorted({e["receiver"] for e in found if not e["correct"]})
        rounds.append({"signatures": {n: "phase set" if len(sets[n]) > 1 else "phase 0" for n in MAIN},
                       "tree_probes": [probes[q]["id"] for q in tree_probes(tree)],
                       "tree_depth": depth(tree), "identifications": found, "failed": failed})
        growable = [n for n in failed if len(phase_sets[n]) > len(sets[n])]
        if not growable:  # nothing left to widen: stop, and let the assert report it
            break
        for n in growable:
            sets[n] = phase_sets[n]
    assert all(e["correct"] for e in found), found
    variants = [(n, x) for n in MAIN for x in sets[n]]

    # Negative controls.
    controls = {}
    twin_plus = variants + [("MidSampleTwin", sig[("MidSampleTwin", 0)]),
                            ("MidSamplePlus1", sig[("MidSamplePlus1", 0)])]
    control_tree = build_tree(probes, twin_plus)
    twin = await identify(s.runner("MidSampleTwin", 0), control_tree)
    assert twin["answer"] == ["MidSample", "MidSampleTwin"], twin
    controls["twin_in_map"] = {
        "expected": "class {MidSample, MidSampleTwin}",
        "identification": describe(probes, twin, "MidSampleTwin", 0, ["MidSample", "MidSampleTwin"]),
        "separating_probes": len(separating([sig[("MidSample", 0)]], [sig[("MidSampleTwin", 0)]], everything)),
        "control_tree_probes": [probes[q]["id"] for q in tree_probes(control_tree)]}
    plus = await identify(s.runner("MidSamplePlus1", 0), control_tree)
    assert plus["answer"] == ["MidSamplePlus1"], plus
    apart = separating([sig[("MidSample", 0)]], [sig[("MidSamplePlus1", 0)]], everything)
    controls["plus1_in_map"] = {
        "expected": "identified as itself; one-clock resolution",
        "identification": describe(probes, plus, "MidSamplePlus1", 0, ["MidSamplePlus1"]),
        "probes_separating_from_MidSample": [probes[q]["id"] for q in apart]}
    blind = await identify(s.runner("MidSamplePlus1", 0), tree)
    used = set(tree_probes(tree))
    entry = describe(probes, blind, "MidSamplePlus1", 0, None)
    entry["expected"] = "unknown"
    entry["outcome"] = "unknown" if blind["answer"] == "unknown" else "missed: limit of the probe set"
    if blind["answer"] != "unknown":
        # Analysis only (the classifier never saw this receiver's map): which
        # probes the tree left unused would have exposed it at that leaf.
        leaf = route(tree, sig[("MidSamplePlus1", 0)])
        expect = [x for _, x in variants if route(tree, x) is leaf]
        unused = [q for q in everything if q not in used]
        exposing = [q for q in unused if sig[("MidSamplePlus1", 0)][q] not in {x[q] for x in expect}]
        entry["leaf_confirmations"] = [c["id"] for c in leaf["confirm"]]
        entry["unused_probes_that_expose_it"] = [probes[q]["id"] for q in exposing]
        entry["unused_probes"] = len(unused)
    controls["plus1_left_out"] = entry

    rng = random.Random(SHUFFLE_SEED)
    names = list(MAIN)
    while any(a == b for a, b in zip(names, MAIN)):
        rng.shuffle(names)
    relabel = dict(zip(MAIN, names))
    shuffled_tree = build_tree(probes, [(relabel[n], x) for n, x in variants])
    found_shuffled = await identify_all(s, probes, shuffled_tree)
    wrong = [e for e in found_shuffled if not e["correct"]]
    assert wrong
    controls["shuffled_labels"] = {"seed": SHUFFLE_SEED, "relabel": relabel,
                                   "wrong": len(wrong), "of": len(found_shuffled),
                                   "detected": bool(wrong)}

    moved = shifted()
    failures = sum(decode(events, moved) != decoded for events, decoded in raw)
    assert failures == len(raw)
    controls["decode_thresholds_shifted"] = {"widths": moved, "map_runs": len(raw),
                                             "cross_check_failures": failures}

    # Ablation: drop one probe family at a time.
    ablation = {}
    before = {tuple(r["pair"]) for r in pair_table(probes, sets, MAIN, everything) if r["separable"]}
    for family in FAMILIES:
        allowed = [q for q in everything if probes[q]["family"] != family]
        alone = [q for q in everything if probes[q]["family"] == family]
        after = {tuple(r["pair"]) for r in pair_table(probes, sets, MAIN, allowed) if r["separable"]}
        reduced = build_tree(probes, variants, allowed)
        ablation[family] = {
            "pairs_lost": [list(p) for p in sorted(before - after)],
            "tree_depth": depth(reduced), "tree_probes": [probes[q]["id"] for q in tree_probes(reduced)],
            "family_alone_separates": [r["pair"] for r in pair_table(probes, sets, MAIN, alone) if r["separable"]]}

    report = {
        "clocks_per_bit": CLOCKS,
        "convention": {
            "note": "fixture convention: each receiver owns one report lane and pulses its "
                    "first frame's verdict as a width; not a chip feature",
            "time_zero": "first clock lane 0's output enable is asserted",
            "report_at": REPORT_AT, "widths": WIDTHS, "report_lanes": list(REPORT_LANES),
            "capture_mask": REPORT_MASK, "capture_margin": MARGIN, "groups": GROUPS},
        "receivers": {n: receiver_info(n) for n in MAIN + CONTROLS},
        "probes": [{"index": p["index"], "id": p["id"], "family": p["family"], "byte": p["byte"],
                    "waveform": waveform_text(p["segments"])} for p in probes],
        "map": {"legend": {v[0]: v for v in VERDICTS},
                "phase0": {n: sig[(n, 0)] for n in MAIN + CONTROLS},
                "by_phase": {n: {str(p): sig[(n, p)] for p in receivers.phases(n, CLOCKS)}
                             for n in sorted(receivers.OVERSAMPLING)}},
        "separation": {"phase0": pair_table(probes, phase0, MAIN, everything),
                       "all_phases": pair_table(probes, phase_sets, MAIN, everything)},
        "tree": tree,
        "identification_rounds": rounds,
        "identifications": found,
        "controls": controls,
        "ablation": ablation,
        "example_run": example,
        "cost": {"engine_runs": s.runs, "bus_clocks": s.clocks},
    }
    if os.environ.get("FINGERPRINT_REPORT"):
        Path(os.environ["FINGERPRINT_REPORT"]).write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    if os.environ.get("FINGERPRINT_TIMING"):
        Path(os.environ["FINGERPRINT_TIMING"]).write_text(json.dumps(
            {"engine_runs": s.runs, "wall_seconds": round(time.monotonic() - started, 1)}) + "\n")
