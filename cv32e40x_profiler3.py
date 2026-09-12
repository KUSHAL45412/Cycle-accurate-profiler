#!/usr/bin/env python3

import bisect
import json
import os
import sys
from collections import defaultdict
from riscv_decoder import RISCVDecoder

VALID_BIT      = 45
COMPRESSED_BIT = 46
TIMESCALE      = 10

AREA_COST = {
    'I': 100, 'M': 120, 'A': 102, 'F': 40, 'D': 60, 'C': 10,
    'Zba': 25, 'Zbb': 63, 'Zbc': 1, 'Zbs': 38, 'Zicsr': 5, 'Zifencei': 1,
}
TOTAL_AREA = sum(AREA_COST.values())


def get_parent_ext(ext):
    """M:MUL → M,  I:LW → I,  Zbb → Zbb"""
    return ext.split(':')[0] if ':' in ext else ext


def cpi_flag(cpi):
    if cpi > 3.0: return "!!"
    if cpi > 2.0: return "! "
    if cpi > 1.5: return "~ "
    return "OK"


def ext_verdict(ext, usage_pct):
    if ext == 'I':      return "mandatory"
    if usage_pct > 2:   return "keep"
    if usage_pct > 0.5: return "evaluate"
    return "exclude"


def is_rdcycle_instruction(encoding):
    """
    Checks if instruction is a CSR read of `cycle` (0xC00), `cycleh` (0xC80),
    `mcycle` (0xB00), or `mcycleh` (0xB80) — i.e. rdcycle / rdcycleh.
    """
    if encoding is None or encoding <= 0xFFFF:
        return False
    opcode = encoding & 0x7F
    funct3 = (encoding >> 12) & 0x7
    csr    = (encoding >> 20) & 0xFFF
    return opcode == 0x73 and (funct3 in (1, 2, 3, 5, 6, 7)) and (csr in (0xC00, 0xC80, 0xB00, 0xB80))


def is_call_instruction(encoding):
    if encoding > 0xFFFF:
        opcode = encoding & 0x7F
        rd     = (encoding >> 7) & 0x1F
        if opcode == 0x6F and rd == 1: return True
        if opcode == 0x67 and rd == 1: return True
        return False
    if (encoding & 0xE003) == 0x2001: return True
    if (encoding & 0xF07F) == 0x9002 and ((encoding >> 7) & 0x1F): return True
    return False


def is_return_instruction(encoding):
    if encoding > 0xFFFF:
        return (encoding & 0x000FFFFF) == 0x00008067
    return (encoding & 0xF07F) == 0x8002 and ((encoding >> 7) & 0x1F) == 1


def get_benchmark_entry_pc(objdump_path):
    if not objdump_path or not os.path.exists(objdump_path):
        return None

    with open(objdump_path, 'r') as f:
        lines = f.readlines()

    bench_pc = bench_idx = None
    target_labels = ['<benchmark>:', '<benchmark_run>:', '<bench_main>:', '<main>:']
    for label in target_labels:
        for i, line in enumerate(lines):
            if label in line:
                try:
                    bench_pc  = int(line.strip().split()[0], 16)
                    bench_idx = i
                    break
                except (ValueError, IndexError):
                    pass
        if bench_pc is not None:
            break

    if bench_pc is None:
        return None

    for line in lines[bench_idx + 1 : bench_idx + 5]:
        line = line.strip()
        if not line or line.startswith('<'): break
        parts    = line.split()
        mnemonic = parts[2] if len(parts) > 2 else ''
        if mnemonic in ('c.j', 'j'):
            for part in parts[3:]:
                try:
                    return int(part, 16)
                except ValueError:
                    continue

    return bench_pc


def _record(instr_count, compressed_count, extension_counts, extension_cycles,
            instruction_trace, instr_num, pc, encoding, is_compressed,
            extension, prev_cycle, cycle):
    """Shared bookkeeping for retired instructions."""
    instr_count      += 1
    compressed_count += is_compressed
    extension_counts[extension] += 1
    start     = cycle if prev_cycle is None else prev_cycle + 1
    end       = cycle
    cyc_taken = max(1, end - start + 1)
    extension_cycles[extension] += cyc_taken
    instruction_trace.append((instr_num, pc, encoding, is_compressed,
                               extension, start, end, cyc_taken))
    return instr_count, compressed_count, cycle


def profile_cv32e40x(json_path, objdump_path=None):
    benchmark_name = os.path.splitext(os.path.basename(json_path))[0].replace("_full_data", "")
    print(f"\nCV32E40X Profiler  —  {benchmark_name}")
    print("=" * 70)

    with open(json_path, "r") as f:
        data = json.load(f)

    if "signal" not in data:
        raise RuntimeError("Invalid WaveJSON format (missing 'signal')")

    ex_wb_data, pc_data, instr_data = [], [], []
    for entry in data["signal"]:
        if not isinstance(entry, list) or len(entry) < 2: continue
        timestamp = int(entry[0])
        for sig in entry[1:]:
            if not isinstance(sig, dict): continue
            name  = sig.get("name")
            value = sig.get("data", "0")
            if   name == "ex_wb_pipe_i":  ex_wb_data.append((timestamp, value))
            elif name == "pc_if_o":       pc_data.append((timestamp, value))
            elif name == "instr_rdata_i": instr_data.append((timestamp, value))

    if not ex_wb_data:
        raise RuntimeError("No ex_wb_pipe_i data found")

    pc_data_sorted    = sorted([(t, int(v, 16)) for t, v in pc_data if v and v.strip()])
    instr_data_sorted = sorted([(t, int(v, 16)) for t, v in instr_data if v and v.strip()])

    pc_times    = [t for t, v in pc_data_sorted]
    pc_vals     = [v for t, v in pc_data_sorted]
    instr_times = [t for t, v in instr_data_sorted]
    instr_vals  = [v for t, v in instr_data_sorted]

    def get_signal_at(times, vals, t):
        if not times: return 0
        idx = bisect.bisect_right(times, t) - 1
        return vals[idx] if idx >= 0 else 0

    decoder = RISCVDecoder()

    # Scan ID stage (instr_data) directly for rdcycle CSR reads
    rdcycle_times = []
    for t, val_int in instr_data_sorted:
        if is_rdcycle_instruction(val_int):
            if not rdcycle_times or t - rdcycle_times[-1] > 50:
                rdcycle_times.append(t)

    use_rdcycle_bracket = (len(rdcycle_times) >= 2)
    t_start = rdcycle_times[0] if use_rdcycle_bracket else 0
    t_end   = rdcycle_times[1] if use_rdcycle_bracket else 0

    bench_entry_pc = None
    if objdump_path is None:
        base = os.path.splitext(json_path)[0]
        for c in [base + ".objdump",
                  os.path.join(os.path.dirname(json_path), benchmark_name + ".objdump")]:
            if os.path.exists(c):
                objdump_path = c
                break
    if objdump_path and os.path.exists(objdump_path):
        bench_entry_pc = get_benchmark_entry_pc(objdump_path)

    def extract_trace(mode):
        counts = defaultdict(int)
        cycs   = defaultdict(int)
        icount = ccount = 0
        trace  = []
        pcycle = None
        in_bench = False
        depth  = 0

        for timestamp, hex_val in ex_wb_data:
            try:
                val = int(hex_val, 16)
            except ValueError:
                continue

            if not ((val >> VALID_BIT) & 0x1):
                continue

            cycle         = timestamp // TIMESCALE
            pc            = get_signal_at(pc_times, pc_vals, timestamp)
            encoding      = get_signal_at(instr_times, instr_vals, timestamp)
            is_compressed = bool((val >> COMPRESSED_BIT) & 0x1)
            extension     = decoder.decode(encoding, is_compressed)

            if mode == "rdcycle":
                if timestamp < t_start:
                    pcycle = cycle
                    continue
                if timestamp > t_end:
                    break

            elif mode == "entry_pc":
                if not in_bench and pc == bench_entry_pc:
                    in_bench = True
                    depth    = 0
                if not in_bench:
                    pcycle = cycle
                    continue

                ret  = is_return_instruction(encoding)
                call = is_call_instruction(encoding)

            icount, ccount, pcycle = _record(
                icount, ccount, counts, cycs,
                trace, icount + 1, pc, encoding, is_compressed,
                extension, pcycle, cycle)

            if mode == "entry_pc":
                if call:
                    depth += 1
                elif ret:
                    if depth == 0:
                        in_bench = False
                        break
                    else:
                        depth -= 1

        return trace, icount, ccount, counts, cycs

    instruction_trace = []
    active_window = "unfiltered"

    if use_rdcycle_bracket:
        instruction_trace, instr_count, compressed_count, extension_counts, extension_cycles = extract_trace("rdcycle")
        if instruction_trace:
            active_window = "rdcycle"
            print("Benchmark window: bracketed between 1st and 2nd rdcycle CSR reads")

    if not instruction_trace and bench_entry_pc is not None:
        instruction_trace, instr_count, compressed_count, extension_counts, extension_cycles = extract_trace("entry_pc")
        if instruction_trace:
            active_window = "entry_pc"
            print(f"Benchmark window: filtered from entry PC 0x{bench_entry_pc:08x}")

    if not instruction_trace:
        instruction_trace, instr_count, compressed_count, extension_counts, extension_cycles = extract_trace("unfiltered")
        active_window = "unfiltered"
        print("Benchmark window: unfiltered (whole trace)")

    if not instruction_trace:
        raise RuntimeError("No valid instructions detected in simulation trace")

    first_cycle = instruction_trace[0][5]
    last_cycle  = instruction_trace[-1][6]
    exec_cycles = last_cycle - first_cycle + 1
    cpi = exec_cycles / instr_count
    ipc = instr_count / exec_cycles

    parent_counts = defaultdict(int)
    parent_cycles = defaultdict(int)
    for key, cnt in extension_counts.items():
        parent_counts[get_parent_ext(key)] += cnt
    for key, cyc in extension_cycles.items():
        parent_cycles[get_parent_ext(key)] += cyc

    print("\n[ Performance ]\n")
    print(f"  Retired instructions : {instr_count:,}")
    print(f"  Compressed (16-bit)  : {compressed_count:,}  ({compressed_count/instr_count:.1%})")
    print(f"  Regular (32-bit)     : {instr_count - compressed_count:,}")
    print(f"  Execution cycles     : {exec_cycles:,}")
    print(f"  CPI / IPC            : {cpi:.3f} / {ipc:.3f}  [{cpi_flag(cpi)}]")

    print("\n[ ISA Extension Usage ]\n")
    print(f"  {'Ext':<10} {'Count':>9} {'Use%':>6} {'Cycles':>9} {'Cyc%':>6} "
          f"{'AvgCPI':>7} {'Area%':>6}  Verdict")
    print("  " + "-" * 72)

    for ext in AREA_COST:
        count  = parent_counts.get(ext, 0)
        cycles = parent_cycles.get(ext, 0)
        if count == 0 and ext != 'I': continue
        avg_cpi  = cycles / count if count else 0
        use_pct  = count  / instr_count * 100
        cyc_pct  = cycles / exec_cycles * 100
        area_pct = AREA_COST[ext] / TOTAL_AREA * 100
        verdict  = ext_verdict(ext, use_pct)
        print(f"  {ext:<10} {count:>9,} {use_pct:>5.1f}% {cycles:>9,} "
              f"{cyc_pct:>5.1f}% {avg_cpi:>7.3f} {area_pct:>5.1f}%  {verdict}")

    print("  " + "-" * 72)
    print(f"  {'TOTAL':<10} {instr_count:>9,} {'100.0%':>6} {exec_cycles:>9,} "
          f"{'100.0%':>6} {cpi:>7.3f}")

    multi     = [x for x in instruction_trace if x[7] > 1]
    multi_pct = len(multi) / instr_count * 100
    print(f"\n[ Multi-cycle Instructions ]\n")
    print(f"  Single-cycle : {instr_count - len(multi):,}")
    print(f"  Multi-cycle  : {len(multi):,}  ({multi_pct:.1f}%)", end="")
    if multi:
        avg   = sum(x[7] for x in multi) / len(multi)
        worst = max(multi, key=lambda x: x[7])
        print(f"  avg={avg:.2f}  max={worst[7]} @ PC 0x{worst[1]:08x} ({worst[4]})")
    else:
        print()
    print("=" * 70)

    result = {
        "benchmark":        benchmark_name,
        "window_method":    active_window,
        "instructions":     instr_count,
        "compressed":       compressed_count,
        "regular":          instr_count - compressed_count,
        "cycles":           exec_cycles,
        "cpi":              cpi,
        "ipc":              ipc,
        "extension_counts": dict(parent_counts),
        "extension_cycles": dict(parent_cycles),
    }

    out_name = os.path.splitext(json_path)[0] + "_profile.json"
    with open(out_name, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nProfile saved → {out_name}")
    return result


if __name__ == "__main__":
    json_file    = "full_data.json"
    objdump_file = None

    if len(sys.argv) > 1:
        if sys.argv[1] in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        json_file = sys.argv[1]

    if len(sys.argv) > 2:
        objdump_file = sys.argv[2]

    profile_cv32e40x(json_file, objdump_file)
