#!/usr/bin/env python3
import argparse, os, re, sys, time
from collections import namedtuple

SimResult = namedtuple("SimResult", ["cycles", "result", "success", "raw"])

_BENCH_LINE   = re.compile(r"BENCH\s+cycles=(\d+)\s+result=(-?\d+)")
_EXIT_SUCCESS = re.compile(r"EXIT\s+SUCCESS")

def run(sim_dir: str, hex_file: str, timeout: int = 180, testbench_bin: str = "./testbench_verilator") -> SimResult:
    sim_dir_abs = os.path.realpath(sim_dir)
    tb_bin = os.path.join(sim_dir_abs, "testbench_verilator")

    if not os.path.isfile(tb_bin):
        raise RuntimeError(f"testbench_verilator not found at: {tb_bin}")

    hex_file_abs = hex_file if os.path.isabs(hex_file) else os.path.join(sim_dir_abs, hex_file)
    if not os.path.isfile(hex_file_abs):
        raise FileNotFoundError(f"Firmware .hex not found: {hex_file_abs}")

    # Use short relative path so it never overflows Verilog's plusarg buffer
    rel_hex = os.path.relpath(hex_file_abs, sim_dir_abs)
    log_path = os.path.join(sim_dir_abs, "_sim_run.log")

    print(f"[verilator_runner] $ ./testbench_verilator +firmware={rel_hex}", flush=True)
    print(f"[verilator_runner] cwd={sim_dir_abs}  timeout={timeout}s", flush=True)

    cmd = f"cd {sim_dir_abs} && timeout {timeout} ./testbench_verilator +firmware={rel_hex} > {log_path} 2>&1"
    
    t0 = time.time()
    ret = os.system(cmd)
    elapsed = time.time() - t0

    if ret == 124 * 256:
        if os.path.exists(log_path):
            os.remove(log_path)
        raise RuntimeError(f"Verilator simulation timed out after {timeout}s.")

    raw_output = ""
    if os.path.exists(log_path):
        with open(log_path, "r", errors="ignore") as f:
            raw_output = f.read()
        try:
            os.remove(log_path)
        except OSError:
            pass

    m = _BENCH_LINE.search(raw_output)
    if not m:
        print("[verilator_runner] WARNING: No 'BENCH cycles=N result=R' line found.", flush=True)
        return SimResult(cycles=0, result=0, success=False, raw=raw_output)

    cycles  = int(m.group(1))
    result  = int(m.group(2))
    success = bool(_EXIT_SUCCESS.search(raw_output))

    print(f"[verilator_runner] Done in {elapsed:.1f}s → cycles={cycles}  result={result}  EXIT_SUCCESS={success}", flush=True)
    return SimResult(cycles=cycles, result=result, success=success, raw=raw_output)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sim-dir", required=True)
    p.add_argument("--hex",     required=True)
    p.add_argument("--timeout", type=int, default=180)
    args = p.parse_args()
    res = run(args.sim_dir, args.hex, args.timeout)
    sys.exit(0 if res.success else 1)