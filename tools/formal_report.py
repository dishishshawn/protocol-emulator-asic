"""Summarize the sby logs and formal negative controls into reports/formal.json."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/formal"


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def summary(task):
    log = (OUT / f"{task}.log").read_text()
    done = re.search(r"DONE \((\w+), rc=(\d+)\)", log)
    result = {"status": done.group(1) if done else "missing",
              "elapsed_s": next((int(m) for m in re.findall(r"Elapsed clock time.*\((\d+)\)", log)), None)}
    if task == "prove":
        steps = [int(m) for m in re.findall(r"Trying induction in step (\d+)", log)]
        result["induction_step"] = min(steps) if steps else None
    if task == "cover":
        # The engine log names every reached cover; sby's summary can omit one.
        reached = {}
        for step, where in re.findall(r"Reached cover statement in step (\d+) at \S+ (properties\.vh:\S+)", log):
            reached[where] = min(int(step), reached.get(where, 10**9))
        result["reached"] = sorted(reached.items())
        result["unreached"] = sorted(set(re.findall(r"Unreached cover statement at \S+ (properties\.vh:\S+)", log)))
    return result


def main():
    sby = (ROOT / "formal/engine.sby").read_text()
    log = (OUT / "bmc.log").read_text()
    versions = {"yosys": re.search(r"Yosys (\S+)", log).group(1) if re.search(r"Yosys (\S+)", log) else None,
                "yices": re.search(r"Yices (\S+)", log).group(1) if re.search(r"Yices (\S+)", log) else None}
    controls = json.loads((ROOT / "build/formal-mutations/results.json").read_text())
    report = {
        "method": "SymbiYosys with smtbmc/Yices on src/engine.v with formal/properties.vh included under FORMAL; run by tools/formal.sh.",
        "sources": {p: sha(p) for p in ["src/engine.v", "formal/properties.vh", "formal/engine.sby"]},
        "tools": versions,
        "depths": {"bmc": int(re.search(r"bmc: depth (\d+)", sby).group(1)),
                   "prove": int(re.search(r"prove: depth (\d+)", sby).group(1)),
                   "cover": int(re.search(r"cover: depth (\d+)", sby).group(1))},
        "tasks": {task: summary(task) for task in ["bmc", "prove", "cover"]},
        "negative_controls": controls,
    }
    (ROOT / "reports/formal.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report["tasks"].items()}, indent=1))


if __name__ == "__main__":
    main()
