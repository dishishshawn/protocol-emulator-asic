"""Create SDF-annotatable copies of upstream standard-cell models for Icarus.

Icarus Verilog does not implement the delayed-signal outputs of $setuphold and
$recrem (the trailing delayed_* arguments), and leaves those nets undriven. This
keeps every specify block, path delay, timing check and notifier so that
$sdf_annotate can apply IOPATH delays and SETUP/HOLD/RECOVERY/REMOVAL/WIDTH
limits, but drops the delayed-net arguments from $setuphold/$recrem and connects
each delayed_* net directly to its input pin. Violations still drive the
notifier and corrupt the flip-flop output to X, as in the upstream model.

Icarus also rejects `ifnone` on edge-sensitive paths ("sorry: ifnone with an
edge-sensitive path is not supported") and would drop them, leaving those arcs
with zero delay. The `ifnone` keyword is removed so the path becomes
unconditional; the SDF written by OpenSTA carries an unconditional IOPATH for
every such arc next to its COND variants, so the arc is still annotated.

Zero-delay functional copies are made by functional_cells.py instead.
"""
import argparse
import re
from pathlib import Path


def timing_model(source):
    def strip_delayed_args(match):
        # $setuphold(ref, data, s, h, notifier,,, delayed_ref, delayed_data)
        # $recrem  (ref, data, rec, rem, notifier,,, delayed_ref, delayed_data)
        head = match.group(1)
        args = [a.strip() for a in match.group(2).split(",")]
        return f"{head}({', '.join(args[:5])});"

    converted = re.sub(
        r"(\$(?:setuphold|recrem))\s*\(([^;]*?)\)\s*;", strip_delayed_args, source
    )

    def connect(module):
        text = module.group(0)
        inputs = set()
        for declaration in re.findall(r"\binput\s+([^;]+);", text):
            inputs.update(re.findall(r"\b[A-Za-z_]\w*\b", declaration))
        delayed = set(re.findall(r"\bdelayed_\w+\b", text))
        for signal in sorted(delayed):
            if signal.removeprefix("delayed_") not in inputs:
                raise ValueError(f"Cannot tie {signal}: not an input")
        assignments = "\n".join(
            f"  assign {s} = {s.removeprefix('delayed_')};" for s in sorted(delayed)
        )
        return text.replace("endmodule", assignments + "\nendmodule")

    converted = re.sub(r"\bifnone\s*\n(\s*\()", r"\1", converted)
    converted, count = re.subn(r"\bmodule\s+.*?\bendmodule\b", connect, converted, flags=re.S)
    if count == 0:
        raise ValueError("No standard-cell modules found")
    if re.search(r"\$(?:setuphold|recrem)\s*\([^;]*delayed_", converted):
        raise ValueError("delayed-net arguments remain in a timing check")
    if re.search(r"\bifnone\b", converted):
        raise ValueError("ifnone remains in a specify block")
    return "// GENERATED TIMING COPY: specify blocks kept; delayed nets tied to inputs.\n" + converted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(timing_model(args.source.read_text()))
