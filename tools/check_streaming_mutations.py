"""Prove selected streaming regressions reject deliberate bugs in isolated copies."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("tx_simultaneous_count", "src/engine.v",
     "2'b01: tx_used <= tx_used - 1'b1;",
     "2'b01: tx_used <= tx_used - 1'b1;\n                2'b11: tx_used <= tx_used + 1'b1;",
     "simultaneous_fifo_operations"),
    ("rx_simultaneous_count", "src/engine.v",
     "2'b01: rx_used <= rx_used - 1'b1;",
     "2'b01: rx_used <= rx_used - 1'b1;\n                2'b11: rx_used <= rx_used + 1'b1;",
     "simultaneous_fifo_operations"),
    ("double_timestamp_rate", "src/engine.v",
     "timestamp <= timestamp + 1'b1;", "timestamp <= timestamp + 2'd2;",
     "timestamp_capture_and_fault_demo"),
    ("ack_final_i2c_byte", "tools/streaming.py",
     "w[final] = last_byte(ack_clock)", "w[final] = hold(1)",
     "multibyte_i2c_write_and_read"),
    ("host_skips_readiness", "tools/streaming.py",
     "        await self.ready()\n", "",
     "host_waits_for_stream_enable"),
]


def main():
    work = ROOT / "build/streaming-mutations"
    work.mkdir(parents=True, exist_ok=True)
    report = {"method": "Isolated source copies, deliberate one-bug edits; each must compile and fail its named cocotb assertion.",
              "sources": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                          for p in ["src/engine.v", "tools/streaming.py", "test/test_streaming.py"]},
              "cases": []}
    env = os.environ.copy()
    env["PATH"] = str(ROOT / ".venv/bin") + os.pathsep + env["PATH"]
    env.pop("DEMO_REPORT", None)
    for name, file, before, after, test in CASES:
        directory = work / name
        directory.mkdir(exist_ok=True)
        for sub, pattern in [("src", "*.v"), ("test", "*.py"), ("tools", "*.py")]:
            (directory / sub).mkdir(exist_ok=True)
            for source in (ROOT / sub).glob(pattern):
                shutil.copy2(source, directory / sub / source.name)
        for file_name in ["Makefile", "tb.v"]:
            shutil.copy2(ROOT / "test" / file_name, directory / "test" / file_name)
        target = directory / file
        source = target.read_text()
        if before not in source:
            raise RuntimeError(f"Mutation no longer applies: {name}")
        target.write_text(source.replace(before, after))
        results = directory / "test/results.xml"
        results.unlink(missing_ok=True)
        with (directory / "run.log").open("w") as log:
            run = subprocess.run(["make", "-C", str(directory / "test"),
                                  "COCOTB_TEST_MODULES=test_streaming",
                                  f"COCOTB_TEST_FILTER={test}"], env=env,
                                 stdout=log, stderr=subprocess.STDOUT, timeout=180)
        # cocotb lists filtered-out tests as skipped; only executed cases count.
        cases = [c for c in ET.parse(results).iter("testcase")
                 if c.find("skipped") is None] if results.exists() else []
        detected = run.returncode != 0 and len(cases) == 1 and cases[0].get("name") == test and cases[0].find("failure") is not None
        report["cases"].append({"mutation": name, "file": file, "before": before,
                                "after": after, "test": test, "detected": detected})
        print(f"{name}: {'detected' if detected else 'NOT DETECTED'}", flush=True)
    (work / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    if not all(case["detected"] for case in report["cases"]):
        raise SystemExit("At least one negative control did not fail as expected")


if __name__ == "__main__":
    main()
