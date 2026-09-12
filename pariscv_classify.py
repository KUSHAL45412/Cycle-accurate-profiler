#!/usr/bin/env python3
"""
PARISCV v2: Master Candidate Discovery & Classification Entry Point
===================================================================
Run this from your root directory:
    python3 pariscv_classify.py
"""
import sys
import argparse
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "tools"))

from auto_candidate_classifier import run_pipeline, _BENCH_DIR

def main():
    parser = argparse.ArgumentParser(description="PARISCV v2: Automated Custom-Instruction Discovery & Classification")
    parser.add_argument("bench", nargs="?", default=None, help="Optional specific benchmark name (e.g. crc32 or bench_mac_tinyml)")
    parser.add_argument("--bench-dir", default=str(_BENCH_DIR), help="Path to model/bench directory")
    parser.add_argument("--tc-prefix", default=None, help="Cross-compiler toolchain prefix")
    parser.add_argument("--spike", default=None, help="Path to spike simulator executable")
    parser.add_argument("--top", type=int, default=3, help="Number of top candidates to report per benchmark")
    args = parser.parse_args()
    
    run_pipeline(
        bench_dir=args.bench_dir,
        tc_prefix=args.tc_prefix,
        spike_bin=args.spike,
        top_n=args.top,
        target_bench=args.bench,
    )

if __name__ == "__main__":
    main()

