#!/usr/bin/env bash
set -euo pipefail
TAG=${1:-"dotprod_int8_custom"}
USESDOT4=${2:-"1"}
PREFIX=${CV_SW_PREFIX:-riscv32-unknown-elf-}

MARCH=${CV_SW_MARCH:-rv32imc}
if ! ${PREFIX}gcc -march=${MARCH} -mabi=ilp32 -E - < /dev/null &>/dev/null; then
    MARCH="rv32imc"
fi

FLAGS="-Os -g -static -mabi=ilp32 -march=${MARCH} -w -nostdlib -nostartfiles -DSTACK_TOP=0x00300000 -DUSE_PG_SDOT4=$USESDOT4"
C="crt.S harness.c bench_dotprod_int8.c"

${PREFIX}gcc $FLAGS -T link_spike.ld -o ${TAG}_spike.elf $C report_spike.c 2>&1 | grep -v RWX || true
${PREFIX}gcc $FLAGS -T link_rtl.ld   -o ${TAG}_rtl.elf   $C report_rtl.c report_rtl_io.c 2>&1 | grep -v RWX || true
${PREFIX}objcopy -O verilog ${TAG}_rtl.elf ${TAG}_rtl.hex
echo "[${TAG}] build completed successfully: ${TAG}_rtl.hex generated."
