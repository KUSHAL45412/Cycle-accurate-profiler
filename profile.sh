#!/usr/bin/env bash
# profile.sh — All-in-one Simulation + Profiling + Prediction Pipeline
set -euo pipefail

# ── Toolchain & Spike Environment ──────────────────────────────────────────
export CV_SW_TOOLCHAIN=/home/chips/Storage/kushal/profiler/riscv-gnu-toolchain/
export CV_SW_PREFIX=riscv32-unknown-elf-
export CV_SW_MARCH=rv32imc_zicsr_zifencei

export PATH=/home/chips/Storage/riscv/riscv-gnu-toolchain/installed-tools/riscv-pk/build:$PATH
export PATH=/home/chips/Storage/riscv/riscv-gnu-toolchain/installed-tools/riscv-isa-sim/build:$PATH
export PATH=/home/chips/Storage/riscv/riscv-gnu-toolchain/installed-tools/bin:$PATH
export PATH=${CV_SW_TOOLCHAIN}/installed-tools/bin:$PATH

TEST=${1:-"add"}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR=~/Storage/kushal/profiler/core-v-verif/cv32e40x/sim/core
CUSTOM_DIR=~/Storage/kushal/profiler/core-v-verif/cv32e40x/tests/programs/custom/${TEST}
SPIKE_FILE=~/Storage/riscv/demo/profiler/spike.txt

# ── Locate Hex, ELF, and Objdump ───────────────────────────────────────────
if [ -f "${HERE}/model/bench/${TEST}_rtl.hex" ]; then
    HEX_PATH="${HERE}/model/bench/${TEST}_rtl.hex"
    ELF_PATH="${HERE}/model/bench/${TEST}_rtl.elf"
    SPIKE_ELF="${HERE}/model/bench/${TEST}_spike.elf"
    OBJDUMP_PATH="${HERE}/model/bench/${TEST}_rtl.objdump"
elif [ -f "${CUSTOM_DIR}/${TEST}.hex" ]; then
    HEX_PATH="${CUSTOM_DIR}/${TEST}.hex"
    ELF_PATH="${CUSTOM_DIR}/${TEST}.elf"
    SPIKE_ELF="${ELF_PATH}"
    OBJDUMP_PATH="${CUSTOM_DIR}/${TEST}.objdump"
elif [ -f "${HERE}/rtl-tests/${TEST}/${TEST}.hex" ]; then
    HEX_PATH="${HERE}/rtl-tests/${TEST}/${TEST}.hex"
    ELF_PATH="${HERE}/rtl-tests/${TEST}/${TEST}.elf"
    SPIKE_ELF="${ELF_PATH}"
    OBJDUMP_PATH="${HERE}/rtl-tests/${TEST}/${TEST}.objdump"
else
    HEX_PATH="${CUSTOM_DIR}/${TEST}.hex"
    ELF_PATH="${CUSTOM_DIR}/${TEST}.elf"
    SPIKE_ELF="${ELF_PATH}"
    OBJDUMP_PATH="${CUSTOM_DIR}/${TEST}.objdump"
fi

# ── Step 0: Run Verilator RTL Simulation Automatically ────────────────────
echo "=== Step 0: Running Verilator RTL Simulation ==="
if [ -f "${HEX_PATH}" ] && [ -f "${SIM_DIR}/testbench_verilator" ]; then
    echo "Running Verilator with firmware: ${HEX_PATH}"
    (cd "${SIM_DIR}" && ./testbench_verilator +vcd "+firmware=${HEX_PATH}")
else
    echo "Notice: Using existing ${SIM_DIR}/verilator_tb.vcd"
fi

# Copy VCD if present
if [ -f "${SIM_DIR}/verilator_tb.vcd" ]; then
    cp "${SIM_DIR}/verilator_tb.vcd" ./verilator_tb.vcd
fi

# ── Step 1: Converting VCD → JSON ─────────────────────────────────────────
echo "=== Step 1: Converting VCD → JSON ==="
cd ${SIM_DIR}/vcd2json
python3 - << 'PYEOF'
import sys
sys.path.insert(0, '.')
from vcd2json import WaveExtractor
path_list = [
    'TOP/tb_top_verilator/cv32e40x_tb_wrapper_i/clk_i',
    'TOP/tb_top_verilator/cv32e40x_tb_wrapper_i/cv32e40x_core_i/if_stage_i/pc_if_o',
    'TOP/tb_top_verilator/cv32e40x_tb_wrapper_i/cv32e40x_core_i/id_stage_i/decoder_i/i_decoder_i/instr_rdata_i',
    'TOP/tb_top_verilator/cv32e40x_tb_wrapper_i/cv32e40x_core_i/wb_stage_i/ex_wb_pipe_i'
]
extractor = WaveExtractor('../verilator_tb.vcd', '../full_data.json', path_list)
extractor.wave_chunk = 1
extractor.start_time = 0
extractor.end_time = 0
extractor.execute()
PYEOF
cd - > /dev/null

# ── Step 2: Running Hardware Profiler (RTL Ground Truth) ──────────────────
echo "=== Step 2: Running Hardware Profiler (RTL Ground Truth) ==="
python3 cv32e40x_profiler3.py ${SIM_DIR}/full_data.json ${OBJDUMP_PATH} > profiler_output.tmp
cat profiler_output.tmp

# Extract actual cycle count
RTL_CYCLES=$(grep "Execution cycles" profiler_output.tmp | awk '{print $4}' | tr -d ',')
rm -f profiler_output.tmp

# ── Step 3: Generating Spike Trace & Running Model ────────────────────────
echo ""
echo "=== Step 3: Generating Spike Trace & Running Model ==="
mkdir -p $(dirname ${SPIKE_FILE})

SPIKE_FLAGS="--isa=rv32imc_zicntr_zicsr_zifencei -m0xf0000:0x310000,0x80000000:0x400000"

if command -v spike &> /dev/null; then
    spike -l --log-commits ${SPIKE_FLAGS} "${SPIKE_ELF}" > "${SPIKE_FILE}" 2>&1 || \
    spike -l ${SPIKE_FLAGS} "${SPIKE_ELF}" > "${SPIKE_FILE}" 2>&1 || true
else
    echo "Warning: spike command not found in PATH! Using existing ${SPIKE_FILE} if available."
fi

# Locate model script
if [ -f "./cv32e40x_model.py" ]; then
    MODEL_SCRIPT="./cv32e40x_model.py"
elif [ -f "./model/cv32e40x_model.py" ]; then
    MODEL_SCRIPT="./model/cv32e40x_model.py"
else
    MODEL_SCRIPT="cv32e40x_model.py"
fi

# Run model comparison
python3 ${MODEL_SCRIPT} "${SPIKE_FILE}" --actual ${RTL_CYCLES} --breakdown
