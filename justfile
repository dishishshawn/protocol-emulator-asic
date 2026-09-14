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

map pdk:
    uv run --python .venv/bin/python tools/synth_cmos5l.py --pdk "{{pdk}}"

test-mapped pdk_root:
    PATH="{{justfile_directory()}}/.venv/bin:$PATH" make -C test PDK_ROOT="{{pdk_root}}" MAPPED_NETLIST="{{justfile_directory()}}/build/cmos5l/netlist.v"

setup-physical *args:
    tools/setup-physical.sh {{args}}

harden:
    tools/harden.sh
