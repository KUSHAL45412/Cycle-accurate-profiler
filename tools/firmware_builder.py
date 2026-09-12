#!/usr/bin/env python3
import argparse, os, subprocess, sys
from pathlib import Path

_TC_PREFIXES = [
    "/home/chips/Storage/kushal/profiler/riscv-gnu-toolchain/bin/riscv32-unknown-elf-",
    "riscv-none-elf-",
    "riscv32-unknown-elf-",
    "riscv64-unknown-elf-",
]

def _find_toolchain():
    import shutil
    for p in _TC_PREFIXES:
        if shutil.which(f"{p}gcc") or os.path.isfile(f"{p}gcc"):
            return p
    return _TC_PREFIXES[0]

def _detect_march(tc_prefix):
    for candidate in ["rv32imc_zicsr_zifencei", "rv32imc"]:
        res = subprocess.run([f"{tc_prefix}gcc", f"-march={candidate}", "-mabi=ilp32", "-E", "-"], input="", capture_output=True, text=True)
        if res.returncode == 0:
            return candidate
    return "rv32imc"

_CORE_PARAMS = {
    "cv32e40x": {"ld_script": "link_rtl.ld", "report_c": ["report_rtl.c", "report_rtl_io.c"]},
    "cv32e40p": {"ld_script": "link_rtl_40p.ld", "report_c": ["report_rtl_40p.c", "report_rtl_io_40p.c"]},
}

_COMMON_FLAGS = ["-Os", "-g", "-static", "-mabi=ilp32", "-Wall", "-w", "-nostdlib", "-nostartfiles", "-DSTACK_TOP=0x00300000"]

def build(bench_c, bench_dir, core="cv32e40x", out_tag="rtl", defines=None, tc_prefix=None, align_targets=False):
    if tc_prefix is None:
        tc_prefix = _find_toolchain()

    march = _detect_march(tc_prefix)
    params = _CORE_PARAMS[core]
    bench_p = Path(bench_c)
    bench_dir_p = Path(bench_dir)
    if not bench_p.is_absolute():
        bench_p = bench_dir_p / bench_p

    bench_p = bench_p.resolve()
    stem = bench_p.stem
    if stem.endswith(f"_{out_tag}"):
        stem = stem[:-len(f"_{out_tag}")]
    elf_out = bench_dir_p / f"{stem}_{out_tag}_rtl.elf"
    hex_out = bench_dir_p / f"{stem}_{out_tag}_rtl.hex"

    define_flags = [f"-D{k}={v}" for k, v in (defines or {}).items()]
    
    is_embench = "embench" in str(bench_p)
    include_flags = [f"-I{bench_dir_p}", f"-I{bench_dir_p / 'embench'}", f"-I{bench_p.parent}"]
    align_flags = ["-falign-loops=4", "-falign-jumps=4", "-falign-functions=4"] if align_targets else []
    extra_flags = include_flags + align_flags + (["-DCPU_MHZ=1"] if is_embench else [])
    embench_sources = []
    if is_embench:
        embench_dir = bench_dir_p / "embench" if bench_p.parent.name != "embench" else bench_p.parent
        for s in ["adapter.c", "beebsc.c", "libc_min.c"]:
            if (embench_dir / s).exists():
                embench_sources.append(str(embench_dir / s))

    sources = [str(bench_dir_p / "crt.S"), str(bench_dir_p / "harness.c")] + embench_sources + [str(bench_p)] + [str(bench_dir_p / r) for r in params["report_c"]]
    ld_script = bench_dir_p / params["ld_script"]

    cmd = [f"{tc_prefix}gcc"] + _COMMON_FLAGS + extra_flags + [f"-march={march}"] + define_flags + [f"-T{ld_script}", f"-o{elf_out}"] + sources + ["-lgcc"]

    print(f"[firmware_builder] Compiling {bench_p.name} ({core}, tag={out_tag}, align={align_targets}) ...")
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(bench_dir_p))
    if res.returncode != 0:
        raise RuntimeError(f"GCC failed: {res.stderr}")

    objcopy_cmd = [f"{tc_prefix}objcopy", "-O", "verilog", str(elf_out), str(hex_out)]
    subprocess.run(objcopy_cmd, capture_output=True, text=True, check=True)
    print(f"[firmware_builder] OK -> {hex_out}")
    return str(hex_out)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bench", required=True)
    p.add_argument("--bench-dir", required=True)
    p.add_argument("--core", default="cv32e40x")
    p.add_argument("--tag", default="rtl")
    p.add_argument("--align-targets", action="store_true", help="Align branch/jump loop targets to 4 bytes")
    args = p.parse_args()
    print(build(args.bench, args.bench_dir, args.core, args.tag, align_targets=args.align_targets))