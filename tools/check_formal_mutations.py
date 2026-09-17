"""Prove the formal properties reject deliberate bugs: each mutated engine must FAIL bmc."""
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("fault_keeps_outputs", "            fault <= 1;\n            out_enable <= 0;\n        end\n    endtask",
     "            fault <= 1;\n        end\n    endtask", "S1 fail-closed"),
    ("tx_count_on_push_and_pop", "2'b01: tx_used <= tx_used - 1'b1;",
     "2'b01: tx_used <= tx_used - 1'b1;\n                2'b11: tx_used <= tx_used + 1'b1;", "S4 occupancy"),
    ("wait_timeout_off_by_one", "if (wait_elapsed == instruction[27:10] - 1'b1)",
     "if (wait_elapsed == instruction[27:10])", "S7 bounded WAIT"),
    ("pull_without_stream", "if (!stream_enabled) fail_closed();\n                                    else if (tx_used != 0) begin",
     "if (tx_used != 0) begin", "S5 streaming gate"),
    ("rx_fifo_writes_wrong_slot", "if (rx_push) begin rx_fifo[rx_wr] <= rx_shift;",
     "if (rx_push) begin rx_fifo[rx_wr + 1'b1] <= rx_shift;", "D2 RX integrity"),
    ("host_command_faults_engine", "            end else if (running) begin\n                if (delay_left != 0) begin",
     "            end else if (running) begin\n                if (command && host_data == 8'h83) fail_closed();\n                else if (delay_left != 0) begin", "S6 fault provenance"),
]


def main():
    work = ROOT / "build/formal-mutations"
    work.mkdir(parents=True, exist_ok=True)
    engine = (ROOT / "src/engine.v").read_text()
    sby = (ROOT / "formal/engine.sby").read_text().replace("bmc: depth 40", "bmc: depth 40")
    report = {"method": "One-bug edits to an isolated copy of src/engine.v; formal/properties.vh unchanged; sby bmc depth 40 must FAIL.",
              "cases": []}
    for name, before, after, expected in CASES:
        directory = work / name
        shutil.rmtree(directory, ignore_errors=True)
        (directory / "src").mkdir(parents=True)
        (directory / "formal").mkdir()
        if before not in engine:
            raise RuntimeError(f"Mutation no longer applies: {name}")
        (directory / "src/engine.v").write_text(engine.replace(before, after, 1))
        (directory / "formal/engine.sby").write_text(sby)
        shutil.copy2(ROOT / "formal/properties.vh", directory / "formal/properties.vh")
        env = dict(os.environ, FORMAL_SBY=str(directory / "formal/engine.sby"),
                   FORMAL_OUT=str(directory / "out"))
        run = subprocess.run([str(ROOT / "tools/formal.sh"), "bmc"], env=env,
                             capture_output=True, text=True, timeout=3600)
        log = (directory / "out/bmc.log").read_text() if (directory / "out/bmc.log").exists() else ""
        failed = [line.split("failed assertion", 1)[1].strip() for line in log.splitlines()
                  if "failed assertion" in line]
        detected = "DONE (FAIL" in log and bool(failed)
        report["cases"].append({"mutation": name, "before": before, "after": after,
                                "expected_property": expected, "detected": detected,
                                "failed_assertions": failed})
        print(f"{name}: {'detected' if detected else 'NOT DETECTED'} {failed}", flush=True)
    (work / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    if not all(case["detected"] for case in report["cases"]):
        raise SystemExit("At least one formal negative control did not fail as expected")


if __name__ == "__main__":
    main()
