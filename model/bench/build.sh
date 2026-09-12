#!/usr/bin/env bash
set -euo pipefail

BENCH=${1:?usage: build.sh <bench-c-file-without-extension> [use_custom: 0 or 1]}
USE_CUSTOM=${2:-"1"}
TC=${CV_SW_PREFIX:-/home/chips/Storage/kushal/profiler/riscv-gnu-toolchain/bin/riscv32-unknown-elf-}

FLAGS="-Os -g -static -mabi=ilp32 -march=rv32imc -w -nostdlib -nostartfiles -DSTACK_TOP=0x00300000 -DUSE_PG_SDOT4=$USE_CUSTOM -DUSE_PG_MAC=$USE_CUSTOM"

${TC}gcc $FLAGS -T link_spike.ld -o ${BENCH}_spike.elf crt.S harness.c ${BENCH}.c report_spike.c 2>&1 | grep -v RWX || true
${TC}gcc $FLAGS -T link_rtl.ld   -o ${BENCH}_rtl.elf   crt.S harness.c ${BENCH}.c report_rtl.c report_rtl_io.c 2>&1 | grep -v RWX || true
${TC}objcopy -O verilog ${BENCH}_rtl.elf ${BENCH}_rtl.hex

echo "[$BENCH] build completed successfully: ${BENCH}_rtl.hex generated (USE_CUSTOM=$USE_CUSTOM)."
