"""Map RTL to a pinned, external CMOS5L library and save reproducible evidence."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

PDK_COMMIT = "607e18d4bd9214a52575c194b4181ef449f9252f"
TOP = "tt_um_dishishshawn_protocol_emulator"


def quoted(path):
    value = str(path)
    if any(char in value for char in ['"', '\n', '\r', '\\']):
        raise ValueError("Yosys paths cannot contain quotes, backslashes or newlines")
    return '"' + value + '"'


def run(args):
    root = Path(__file__).resolve().parents[1]
    pdk = args.pdk.resolve()
    lib = pdk / "libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib"
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "-C", str(pdk), "rev-parse", "HEAD"], text=True).strip()
    if commit != PDK_COMMIT:
        raise ValueError(f"Expected PDK commit {PDK_COMMIT}, found {commit}")
    if subprocess.check_output(["git", "-C", str(pdk), "status", "--porcelain", "--", str(lib)], text=True).strip():
        raise ValueError("The synthesis Liberty library has local modifications")
    constraints = out / "abc.constr"
    constraints.write_text("set_driving_cell sg13cmos5l_buf_4\nset_load 6.0\n")
    abc_exe = f" -exe {quoted(args.abc.resolve())}" if args.abc else ""
    script = "\n".join([
        f"read_liberty -lib {quoted(lib)}",
        f"read_verilog {quoted(root / 'src/project.v')} {quoted(root / 'src/engine.v')}",
        f"synth -top {TOP} -flatten -noabc",
        f"dfflibmap -liberty {quoted(lib)}",
        f"abc{abc_exe} -liberty {quoted(lib)} -constr {quoted(constraints)} -D 100000",
        "clean",
        "delete t:$scopeinfo",
        "check -assert",
        f"tee -o stat.json stat -json -liberty {quoted(lib)}",
        f"write_verilog -noattr -noexpr {quoted(out / 'netlist.v')}",
    ]) + "\n"
    (out / "synth.ys").write_text(script)
    with (out / "synthesis.log").open("w") as log:
        subprocess.run([args.yosys, "-Q", "-T", "-s", str(out / "synth.ys")], cwd=out, stdout=log, stderr=subprocess.STDOUT, check=True)
    stats = json.loads((out / "stat.json").read_text())
    top = stats["modules"]["\\" + TOP]
    if any(not cell.startswith("sg13cmos5l_") for cell in top["num_cells_by_type"]):
        raise ValueError("Design contains unmapped cells")
    summary = {
        "pdk_repository": "https://github.com/IHP-GmbH/ihp-sg13cmos5l",
        "pdk_commit": commit,
        "liberty": lib.name,
        "liberty_sha256": hashlib.sha256(lib.read_bytes()).hexdigest(),
        "yosys": subprocess.check_output([args.yosys, "-V"], text=True).strip(),
        "clock_target_ns": 100,
        "abc_output_load_ff": 6.0,
        "abc_driving_cell": "sg13cmos5l_buf_4",
        "standard_cell_area_um2": top["area"],
        "standard_cell_count": top["num_cells"],
        "cells_by_type": top["num_cells_by_type"],
        "rtl_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root / "src").glob("*.v"))},
        "limitations": "Pre-layout standard-cell area only. Excludes clock tree, routing, pads, tie/filler cells and physical repair. No timing closure claim.",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk", required=True, type=Path)
    parser.add_argument("--yosys", default="yosys")
    parser.add_argument("--abc", type=Path)
    parser.add_argument("--output", type=Path, default=Path("build/cmos5l"))
    run(parser.parse_args())
