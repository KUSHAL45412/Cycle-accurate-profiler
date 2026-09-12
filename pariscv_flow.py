#!/usr/bin/env python3
"""
pariscv_flow.py — PARISCV v2 End-to-End Push-Button C-to-Silicon Flow
======================================================================
Single entry point for the automated custom instruction acceleration pipeline.

Takes a plain C source file, automatically detects vectorizable idioms,
rewrites the C source with hardware intrinsic calls, compiles both the
baseline and accelerated firmware, runs cycle-accurate Verilator RTL
simulation on both, verifies functional correctness (checksum match),
and prints a side-by-side speedup report.
"""

import argparse
import os
import sys
import textwrap
import time

# ─────────────────────────────────────────────────────────────────────────────
# Robust toolchain and module path detection
# ─────────────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))

# Add all candidate tool directories to sys.path so modules are always found
_CANDIDATE_PATHS = [
    os.path.join(_HERE, "mouna_reference", "tools"),
    os.path.join(_HERE, "tools"),
    os.path.join(_HERE, "..", "tools"),
    _HERE,
]

for p in _CANDIDATE_PATHS:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

try:
    from idiom_detector  import detect          # noqa: E402
    from c_rewriter      import rewrite         # noqa: E402
    from firmware_builder import build          # noqa: E402
    from verilator_runner import run as sim_run # noqa: E402
except ModuleNotFoundError as e:
    sys.exit(
        f"\n[ERROR] Failed to import PARISCV tool modules: {e}\n"
        f"Searched paths:\n" + "\n".join(f"  - {p}" for p in _CANDIDATE_PATHS) + "\n"
        f"Please ensure idiom_detector.py, c_rewriter.py, firmware_builder.py, "
        f"and verilator_runner.py exist in one of the above folders."
    )

# ─────────────────────────────────────────────────────────────────────────────
# Idiom → compile-time define mapping
# ─────────────────────────────────────────────────────────────────────────────

_IDIOM_DEFINES = {
    "sdot4": "USE_PG_SDOT4",
    "sdot2": "USE_PG_SDOT2",
    "rol":   "USE_PG_ROL",
    "idx":   "USE_PG_IDX",
}

_IDIOM_DESCRIPTION = {
    "sdot4": "4-Lane Signed INT8 Dot-Product & Accumulate (pg.sdot4)",
    "sdot2": "2-Lane Signed INT16 Dot-Product & Accumulate (pg.sdot2)",
    "rol":   "32-bit Rotate-Left (pg.rol)",
    "idx":   "Byte-Indexed Word-Table Address (pg.idx)",
}


# ─────────────────────────────────────────────────────────────────────────────
# Report printer
# ─────────────────────────────────────────────────────────────────────────────

_SEP = "=" * 78

def _print_report(
    source_file: str,
    core: str,
    idioms: list,
    accel_file: str,
    base_cycles: int,
    accel_cycles: int,
    base_result: int,
    accel_result: int,
    base_ok: bool,
    accel_ok: bool,
):
    checksum_ok = (base_result == accel_result)
    speedup     = base_cycles / accel_cycles if accel_cycles > 0 else float("inf")
    reduction   = (1.0 - accel_cycles / base_cycles) * 100.0 if base_cycles > 0 else 0.0

    idiom_names   = ", ".join(m.name for m in idioms)
    idiom_descs   = "\n".join(f"     {_IDIOM_DESCRIPTION.get(m.name, m.name)}" for m in idioms)
    hw_module     = "pg_xif_tinyml.sv" if core == "cv32e40x" else "cv32e40p_alu.sv (ALU patch)"

    checksum_str  = (
        f"PASS  (Baseline: {base_result:#010x} == Accelerated: {accel_result:#010x})"
        if checksum_ok
        else f"FAIL  (Baseline: {base_result:#010x} != Accelerated: {accel_result:#010x})"
    )
    verify_str = "SUCCESS (100% Bit-Exact)" if checksum_ok else "MISMATCH — results differ!"

    print()
    print(_SEP)
    print("         PARISCV v2: C-to-Silicon End-to-End Acceleration Report")
    print(_SEP)
    print(f"  Source File           : {os.path.basename(source_file)}")
    print(f"  Accelerated File      : {os.path.basename(accel_file)}")
    print(f"  Detected Idiom(s)     : {idiom_names}")
    print(f"  Idiom Description     :")
    print(idiom_descs)
    print(f"  Target Core           : OpenHW {core.upper()}")
    print(f"  Hardware Module       : {hw_module}")
    print("-" * 78)
    print(f"  Baseline Cycles       :  {base_cycles:>10,}  (no custom instruction)")
    print(f"  Accelerated Cycles    :  {accel_cycles:>10,}  (custom HW instruction)")
    print(f"  Cycle Reduction       :  {reduction:>9.1f}%")
    print(f"  Hardware Speedup      :  {speedup:>9.2f}x")
    print("-" * 78)
    print(f"  Functional Checksum   : {checksum_str}")
    print(f"  Verification Status   : {verify_str}")
    print(f"  Baseline EXIT SUCCESS : {'YES' if base_ok  else 'NO (check simulation output)'}")
    print(f"  Accel    EXIT SUCCESS : {'YES' if accel_ok else 'NO (check simulation output)'}")
    print(_SEP)
    print()

    if not checksum_ok:
        print("  *** WARNING: Checksum mismatch — the accelerated version produces")
        print("  *** different numerical results. Check the rewritten source and RTL.")
        print()

# ─────────────────────────────────────────────────────────────────────────────
# Main flow
# ─────────────────────────────────────────────────────────────────────────────

def run_flow(args):
    source_file = os.path.realpath(args.auto_accelerate)
    if not os.path.isfile(source_file):
        sys.exit(f"ERROR: Source file not found: {source_file}")

    print()
    print(_SEP)
    print("  PARISCV v2 — Push-Button C-to-Silicon Accelerator")
    print(_SEP)
    print(f"  Input  : {source_file}")
    print(f"  Core   : {args.core}")
    print()

    # ── Stage 1: Idiom Detection ─────────────────────────────────────────────
    print("[Stage 1/5] Scanning for acceleratable idioms ...")
    idioms = detect(source_file)
    if not idioms:
        print("  No acceleratable idioms detected in this file.")
        print("  Tip: PARISCV currently detects sdot4 / rol / idx patterns.")
        sys.exit(0)

    for m in idioms:
        print(f"  [+] Detected: {m.name!r} at line {m.line_start} -> {_IDIOM_DESCRIPTION.get(m.name, m.name)}")
    print()


    # ── Stage 2: Source-to-Source Rewriting ─────────────────────────────────
    print("[Stage 2/5] Rewriting C source with hardware intrinsics ...")
    accel_file = rewrite(source_file, idioms)
    print(f"  Accelerated source -> {accel_file}")
    print()

    if args.rewrite_only:
        print("[pariscv_flow] --rewrite-only mode. Stopping after C rewrite.")
        print(f"  Review the generated file: {accel_file}")
        return

    bench_dir = os.path.realpath(args.bench_dir)
    sim_dir   = os.path.realpath(args.sim_dir)

    # ── Stage 3: Build baseline firmware ────────────────────────────────────
    print("[Stage 3/5] Compiling BASELINE firmware (no custom instruction) ...")
    first_idiom = idioms[0]
    define_key  = _IDIOM_DEFINES.get(first_idiom.name, f"USE_{first_idiom.name.upper()}")

    base_hex = build(
        bench_c   = source_file,
        bench_dir = bench_dir,
        core      = args.core,
        out_tag   = "baseline",
        defines   = {define_key: "0"},
        tc_prefix = args.tc_prefix or None,
    )
    print()

    # ── Stage 4: Build accelerated firmware ─────────────────────────────────
    print("[Stage 4/5] Compiling ACCELERATED firmware (with custom instruction) ...")

    accel_defines = {}
    if first_idiom.name != "sdot4":
        accel_defines[define_key] = "1"

    accel_hex = build(
        bench_c   = accel_file,
        bench_dir = bench_dir,
        core      = args.core,
        out_tag   = "accel",
        defines   = accel_defines,
        tc_prefix = args.tc_prefix or None,
    )
    print()

    # ── Stage 5: Simulate both and compare ──────────────────────────────────
    print("[Stage 5/5] Running Verilator cycle-accurate RTL simulation ...")
    print()

    print("  [5a] Baseline simulation:")
    t0 = time.time()
    base_res = sim_run(
        sim_dir  = sim_dir,
        hex_file = base_hex,
        timeout  = args.timeout,
    )
    print(f"  -> Done in {time.time()-t0:.1f}s")
    print()

    print("  [5b] Accelerated simulation:")
    t0 = time.time()
    accel_res = sim_run(
        sim_dir  = sim_dir,
        hex_file = accel_hex,
        timeout  = args.timeout,
    )
    print(f"  -> Done in {time.time()-t0:.1f}s")
    print()


    # ── Print final report ───────────────────────────────────────────────────
    _print_report(
        source_file  = source_file,
        core         = args.core,
        idioms       = idioms,
        accel_file   = accel_file,
        base_cycles  = base_res.cycles,
        accel_cycles = accel_res.cycles,
        base_result  = base_res.result,
        accel_result = accel_res.result,
        base_ok      = base_res.success,
        accel_ok     = accel_res.success,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI argument parser
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # Smart default for bench-dir (checks mouna_reference/model/bench first)
    if os.path.isdir(os.path.join(_HERE, "mouna_reference", "model", "bench")):
        default_bench_dir = os.path.join(_HERE, "mouna_reference", "model", "bench")
    elif os.path.isdir(os.path.join(_HERE, "model", "bench")):
        default_bench_dir = os.path.join(_HERE, "model", "bench")
    else:
        default_bench_dir = _HERE

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            PARISCV v2 — Push-Button C-to-Silicon Automated Rewriter
            =========================================================
            Detects acceleratable idioms in a C source file, rewrites them
            with PARISCV hardware intrinsics, compiles both versions, runs
            Verilator RTL simulation, and prints a speedup report.
        """),
    )

    parser.add_argument(
        "--auto-accelerate", metavar="SOURCE.C", required=True,
        help="Plain C benchmark source file to accelerate",
    )
    parser.add_argument(
        "--core", choices=["cv32e40x", "cv32e40p"], default="cv32e40x",
        help="Target OpenHW core (default: cv32e40x)",
    )
    parser.add_argument(
        "--bench-dir", metavar="DIR",
        default=default_bench_dir,
        help="Directory containing crt.S, link_rtl.ld, harness.c, report_*.c "
             f"(default: {default_bench_dir})",
    )
    parser.add_argument(
        "--sim-dir", metavar="DIR",
        default=_HERE,
        help="Directory containing testbench_verilator binary "
             f"(default: {_HERE})",
    )
    parser.add_argument(
        "--rewrite-only", action="store_true",
        help="Only rewrite the C source (no compilation or simulation). "
             "Useful for testing on any machine without GCC/Verilator.",
    )
    parser.add_argument(
        "--tc-prefix", metavar="PREFIX", default=None,
        help="RISC-V toolchain prefix override (e.g. riscv32-unknown-elf-). "
             "Auto-detected from PATH if not given.",
    )
    parser.add_argument(
        "--timeout", type=int, default=180,
        help="Verilator simulation timeout in seconds (default: 180)",
    )

    args = parser.parse_args()
    run_flow(args)


if __name__ == "__main__":
    main()
