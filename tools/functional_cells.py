"""Create simulation-only zero-delay copies of upstream standard-cell models.

Icarus does not drive the delayed input nets from $setuphold/$recrem timing
checks. Connect those nets to their original input pins and remove specify
blocks. Preserve cell logic, UDP instances and upstream license notices.
Never use this generated file for SDF timing validation.
"""
import argparse
import re
from pathlib import Path


def functional_model(source):
    source = re.sub(r"\bspecify\b.*?\bendspecify\b", "", source, flags=re.S)

    def connect(module):
        text = module.group(0)
        inputs = set()
        for declaration in re.findall(r"\binput\s+([^;]+);", text):
            inputs.update(re.findall(r"\b[A-Za-z_]\w*\b", declaration))
        delayed = set(re.findall(r"\bdelayed_\w+\b", text))
        for signal in sorted(delayed):
            original = signal.removeprefix("delayed_")
            if original not in inputs:
                raise ValueError(f"Cannot tie {signal}: {original} is not an input")
        assignments = "\n".join(f"  assign {signal} = {signal.removeprefix('delayed_')};" for signal in sorted(delayed))
        return text.replace("endmodule", assignments + "\nendmodule")

    converted, count = re.subn(r"\bmodule\s+.*?\bendmodule\b", connect, source, flags=re.S)
    if count == 0:
        raise ValueError("No standard-cell modules found")
    return "// GENERATED FUNCTIONAL COPY: no timing checks or path delays.\n" + converted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(functional_model(args.source.read_text()))
