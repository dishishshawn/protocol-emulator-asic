set shell := ["bash", "-cu"]

setup:
    uv venv --python 3.12 .venv
    uv pip install --python .venv/bin/python -r test/requirements.txt

test:
    PATH="{{justfile_directory()}}/.venv/bin:$PATH" make -C test

demo:
    uv run --python .venv/bin/python tools/program.py uart-55.bin --byte 0x55 --cycles 87
    uv run --python .venv/bin/python tools/program.py spi-a5.bin --protocol spi --byte 0xa5 --mode 0
    uv run --python .venv/bin/python tools/program.py i2c-50-69.bin --protocol i2c --address 0x50 --byte 0x69

synth:
    mkdir -p build
    yosys -Q -T -p 'read_verilog src/project.v src/engine.v; synth -top tt_um_dishishshawn_protocol_emulator; check -assert; stat' > build/synthesis.log

capture-demo:
    mkdir -p build
    PATH="{{justfile_directory()}}/.venv/bin:$PATH" DEMO_REPORT="{{justfile_directory()}}/build/fault-demo.json" make -C test COCOTB_TEST_MODULES=test_streaming COCOTB_TEST_FILTER=timestamp_capture_and_fault_demo

# Fault-length sweep behind the live demo page: real engine runs, JSON evidence.
fault-sweep:
    mkdir -p build
    PATH="{{justfile_directory()}}/.venv/bin:$PATH" SWEEP_REPORT="{{justfile_directory()}}/build/fault-sweep.json" make -C test COCOTB_TEST_MODULES=test_sweep

stream-demo:
    uv run --python .venv/bin/python tools/streaming.py spi-stream.bin --protocol spi --count 32
    uv run --python .venv/bin/python tools/streaming.py uart-rx.bin --protocol uart-rx --count 16
    uv run --python .venv/bin/python tools/streaming.py i2c-read.bin --protocol i2c-read --count 8
    uv run --python .venv/bin/python tools/streaming.py i2c-regread.bin --protocol i2c-transaction --write-count 3 --count 4

map pdk:
    uv run --python .venv/bin/python tools/synth_cmos5l.py --pdk "{{pdk}}"

test-mapped pdk_root:
    PATH="{{justfile_directory()}}/.venv/bin:$PATH" make -C test PDK_ROOT="{{pdk_root}}" MAPPED_NETLIST="{{justfile_directory()}}/build/cmos5l/netlist.v"

setup-physical *args:
    tools/setup-physical.sh {{args}}

harden:
    tools/harden.sh

# Formal safety, bounded-wait and FIFO integrity checks (sby from PATH, else nix-portable).
formal *tasks:
    tools/formal.sh {{tasks}}

# Post-layout gate-level regression with SDF timing; corner is an STA corner name.
# run is the LibreLane run holding the current layout (build/run-docker is the
# pre-streaming baseline, kept for reports/sdf-tests.json).
test-sdf corner="nom_slow_1p08V_125C" run="build/run-streaming":
    PATH="{{justfile_directory()}}/.venv/bin:$PATH" COCOTB_RESULTS_FILE=results-sdf-{{corner}}.xml make -C test PDK_ROOT="{{justfile_directory()}}/.pdk/ihp-open-pdk" SDF_NETLIST="{{justfile_directory()}}/{{run}}/final/nl/tt_um_dishishshawn_protocol_emulator.nl.v" SDF_FILE="{{justfile_directory()}}/{{run}}/final/sdf/{{corner}}/tt_um_dishishshawn_protocol_emulator__{{corner}}.sdf"
