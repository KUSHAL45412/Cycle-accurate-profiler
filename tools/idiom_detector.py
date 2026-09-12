#!/usr/bin/env python3
"""
tools/idiom_detector.py — PARISCV v2 C Source Idiom Detector
=============================================================
Scans a user's plain .c file and identifies loop/expression patterns
that can be replaced by a PARISCV custom hardware instruction.

Three idioms are currently detected:

  1. sdot4  (CV32E40X, CV-X-IF coprocessor)
       - int8_t / int32_t MAC accumulation loop
       - Pattern: acc += (int32_t)a[i] * (int32_t)b[i];
       - Replaced by: __builtin_pg_sdot4(packed_a, packed_b, acc)

  2. rol    (CV32E40P, native ALU instruction)
       - 32-bit rotate-left idiom
       - Pattern: (x << n) | (x >> (32 - n))
       - Replaced by: __builtin_pg_rol(x, n)

  3. idx    (CV32E40P, native ALU instruction)
       - Byte-indexed word-table lookup
       - Pattern: table[expr & 0xff]
       - Replaced by: __builtin_pg_idx(expr, table)

Returns a list of IdiomMatch(name, lines, variables) for the rewriter.
"""

import re
from collections import namedtuple

# ─────────────────────────────────────────────────────────────────────────────
# Public data structure
# ─────────────────────────────────────────────────────────────────────────────

IdiomMatch = namedtuple(
    "IdiomMatch",
    [
        "name",        # str  : 'sdot4' | 'rol' | 'idx'
        "target_core", # str  : 'cv32e40x' | 'cv32e40p'
        "line_start",  # int  : 1-based first line of the idiom
        "line_end",    # int  : 1-based last line of the idiom
        "variables",   # dict : named captures from the regex match
        "original",    # str  : verbatim matched text
    ],
)

# ─────────────────────────────────────────────────────────────────────────────
# Regex patterns
# ─────────────────────────────────────────────────────────────────────────────

# sdot4 — finds the raw scalar loop:
#   acc += (int32_t)va[i] * (int32_t)vb[i];
# Also matches without explicit casts: acc += a[i] * b[i]
_SDOT4_PATTERNS = [
    # Pattern A: explicit (int32_t) cast with int8_t arrays
    re.compile(
        r"(?P<acc>\w+)\s*\+=\s*"
        r"\(\s*int32_t\s*\)\s*(?P<va>\w+)\s*\[\s*\w+\s*\]\s*\*\s*"
        r"\(\s*int32_t\s*\)\s*(?P<vb>\w+)\s*\[\s*\w+\s*\]"
    ),
    # Pattern B: plain: acc += a[i] * b[i]  (no casts)
    re.compile(
        r"(?P<acc>\w+)\s*\+=\s*(?P<va>\w+)\s*\[\s*\w+\s*\]\s*\*\s*(?P<vb>\w+)\s*\[\s*\w+\s*\]"
    ),
    # Pattern C: already packed (dot4_scalar call that we can replace)
    re.compile(
        r"(?P<acc>\w+)\s*=\s*dot4_scalar\s*\(\s*(?P<va>\w+)\s*,\s*(?P<vb>\w+)\s*,\s*(?P=acc)\s*\)"
    ),
]

# sdot2 — already packed (dot2_scalar call that we can replace)
_SDOT2_PATTERN = re.compile(
    r"(?P<acc>\w+)\s*=\s*dot2_scalar\s*\(\s*(?P<va>\w+)\s*,\s*(?P<vb>\w+)\s*,\s*(?P=acc)\s*\)"
)

# rol — matches: (x << n) | (x >> (32 - n))

_ROL_PATTERN = re.compile(
    r"\(\s*(?P<x>\w+)\s*<<\s*(?P<n>\w+)\s*\)"
    r"\s*\|\s*"
    r"\(\s*(?P=x)\s*>>\s*\(\s*32\w*\s*-\s*(?P=n)\s*\)\s*\)"
)

# ror that should become rol (compiler sometimes flips it)
_ROR_BECOMES_ROL_PATTERN = re.compile(
    r"\(\s*(?P<x>\w+)\s*>>\s*(?P<n>\w+)\s*\)"
    r"\s*\|\s*"
    r"\(\s*(?P=x)\s*<<\s*\(\s*32\w*\s*-\s*(?P=n)\s*\)\s*\)"
)

# rotl with bitmask (e.g. SHA-256 ROTL32: (((x)<<(n)) | ((x)>>((-(n)&31)))) )
_ROTL_BITMASK_PATTERN = re.compile(
    r"\(\s*\(\s*(?P<x>\w+)\s*\)\s*<<\s*\(\s*(?P<n>\w+)\s*\)\s*\)"
    r"\s*\|\s*"
    r"\(\s*\(\s*(?P=x)\s*\)\s*>>\s*\(\s*\(\s*-\s*\(\s*(?P=n)\s*\)\s*&\s*31\s*\)\s*\)\s*\)"
)

# idx — matches: table[expr & 0xff]  or  table[expr & 0xFF]
_IDX_PATTERN = re.compile(
    r"(?P<table>\w+)\s*\[\s*(?P<expr>[^&\]]+)\s*&\s*0[xX][fF][fF]\s*\]"
)

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def detect(source_path: str) -> list:
    """
    Open source_path, scan for acceleratable idioms, and return
    a list of IdiomMatch objects (possibly empty).
    """
    with open(source_path, "r") as fh:
        source = fh.read()

    lines = source.splitlines()
    matches = []

    # ── 1. sdot4 scan ──────────────────────────────────────────────────────
    # Check if USE_PG_SDOT4 block or dot4_scalar already exists (packed form)
    if "USE_PG_SDOT4" in source or "__builtin_pg_sdot4" in source:
        m = _SDOT4_PATTERNS[2].search(source)  # Pattern C: dot4_scalar
        if m:
            lineno = source[: m.start()].count("\n") + 1
            matches.append(
                IdiomMatch(
                    name="sdot4",
                    target_core="cv32e40x",
                    line_start=lineno,
                    line_end=lineno,
                    variables={
                        "acc": m.group("acc"),
                        "va": m.group("va"),
                        "vb": m.group("vb"),
                        "already_packed": True,
                    },
                    original=m.group(0),
                )
            )
    elif "USE_PG_SDOT2" not in source and "dot2_scalar" not in source:
        # Look for raw scalar loop patterns (A and B)
        for pat in _SDOT4_PATTERNS[:2]:

            m = pat.search(source)
            if m:
                lineno = source[: m.start()].count("\n") + 1
                ctx_start = max(0, lineno - 6)
                ctx_lines = "\n".join(lines[ctx_start : lineno + 1])
                if "for" in ctx_lines or "while" in ctx_lines:
                    matches.append(
                        IdiomMatch(
                            name="sdot4",
                            target_core="cv32e40x",
                            line_start=lineno,
                            line_end=lineno,
                            variables={
                                "acc": m.group("acc"),
                                "va": m.group("va"),
                                "vb": m.group("vb"),
                                "already_packed": False,
                            },
                            original=m.group(0),
                        )
                    )
                    break

    # ── 1b. sdot2 scan ─────────────────────────────────────────────────────
    if "USE_PG_SDOT2" in source or "dot2_scalar" in source:
        m = _SDOT2_PATTERN.search(source)
        if m:
            lineno = source[: m.start()].count("\n") + 1
            matches.append(
                IdiomMatch(
                    name="sdot2",
                    target_core="cv32e40x",
                    line_start=lineno,
                    line_end=lineno,
                    variables={
                        "acc": m.group("acc"),
                        "va": m.group("va"),
                        "vb": m.group("vb"),
                        "already_packed": True,
                    },
                    original=m.group(0),
                )
            )

    # ── 2. rol scan ────────────────────────────────────────────────────────

    for pat, swapped in [(_ROL_PATTERN, False), (_ROR_BECOMES_ROL_PATTERN, True), (_ROTL_BITMASK_PATTERN, False)]:
        m = pat.search(source)
        if m:
            lineno = source[: m.start()].count("\n") + 1
            ctx_line = lines[lineno - 1]
            if "__builtin_pg_rol" not in ctx_line:
                matches.append(
                    IdiomMatch(
                        name="rol",
                        target_core="cv32e40p",
                        line_start=lineno,
                        line_end=lineno,
                        variables={
                            "x": m.group("x"),
                            "n": m.group("n"),
                            "swapped": swapped,
                        },
                        original=m.group(0),
                    )
                )
            break


    # ── 3. idx scan ────────────────────────────────────────────────────────
    for m in _IDX_PATTERN.finditer(source):
        lineno = source[: m.start()].count("\n") + 1
        ctx_line = lines[lineno - 1]
        if "__builtin_pg_idx" not in ctx_line:
            matches.append(
                IdiomMatch(
                    name="idx",
                    target_core="cv32e40p",
                    line_start=lineno,
                    line_end=lineno,
                    variables={
                        "table": m.group("table"),
                        "expr": m.group("expr").strip(),
                    },
                    original=m.group(0),
                )
            )
            break

    return matches


# ─────────────────────────────────────────────────────────────────────────────
# CLI: python3 tools/idiom_detector.py <source.c>
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 idiom_detector.py <source.c>")
        sys.exit(1)

    path = sys.argv[1]
    results = detect(path)

    if not results:
        print(f"[idiom_detector] No acceleratable idioms found in '{path}'.")
        sys.exit(0)

    print(f"[idiom_detector] Found {len(results)} idiom(s) in '{path}':\n")
    for r in results:
        print(f"  name       : {r.name}")
        print(f"  core       : {r.target_core}")
        print(f"  line       : {r.line_start}")
        print(f"  variables  : {r.variables}")
        print(f"  original   : {r.original!r}")
        print()