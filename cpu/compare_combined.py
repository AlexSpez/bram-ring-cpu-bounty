#!/usr/bin/env python3
"""Build and run the four BRAM-ring CPU implementations with one harness.

Sources and attribution:
  original: Peter Rizun's cpu/verify_avx2.c (repository MIT license).
  scalar: cpu/verify_scalar_taps.c, the scalar-tap implementation.
  competitor: the exact MIT-licensed Git blob cpu/verify_avx2.c from
    kepler-ops-maker commit a15116f1a5bf92ad1caf3cb8070e4273554c4f14,
    retained unchanged as reference_inkier_a15116f.c.
  combined: cpu/verify_combined_taps.c; see its attribution header.

This helper requires Python 3 and an existing GCC-compatible C compiler with
AVX2, BMI2, and OpenMP support. It does not install dependencies or change CPU
affinity. Set OMP_NUM_THREADS and any desired affinity before invoking it.

Examples:
  python cpu/compare_combined.py --mode verify --group 4 --reverse 1
  OMP_NUM_THREADS=8 python cpu/compare_combined.py --mode bench --group 1
  python cpu/compare_combined.py --tables-dir work/fresh/cpu --mode verify

The selected tables.h and harness are staged beside the generated wrappers,
so quoted includes use the selected epoch consistently, including the harness.
The selected tables directory also precedes cpu/ in the compiler include path.
Imports perform no work; compilation and execution occur only from main().
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


HERE = Path(__file__).resolve().parent
VARIANTS = (
    ("original", "verify_avx2.c"),
    ("scalar", "verify_scalar_taps.c"),
    ("competitor", "reference_inkier_a15116f.c"),
    ("combined", "verify_combined_taps.c"),
)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("verify", "bench"), default="verify")
    parser.add_argument("--count", type=int,
                        help="nonce count: default 32 for verify, 800 for bench")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--group", type=int, choices=(1, 2, 4, 8), default=8)
    parser.add_argument("--reverse", type=int, choices=(0, 1), default=1)
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"),
                        help="GCC-compatible compiler command or executable path")
    parser.add_argument("--build-dir", type=Path,
                        default=HERE.parent / "work" / "compare-combined")
    parser.add_argument("--tables-dir", type=Path, default=HERE,
                        help="directory containing the selected epoch's tables.h")
    parser.add_argument("--variants", nargs="+", choices=tuple(name for name, _ in VARIANTS),
                        help="bench only: optional variant selection, in the specified order")
    args = parser.parse_args(argv)
    if args.count is None:
        args.count = 32 if args.mode == "verify" else 800
    if args.count < 1 or args.runs < 1:
        parser.error("--count and --runs must be positive")
    if args.variants and len(set(args.variants)) != len(args.variants):
        parser.error("--variants must not contain duplicates")
    if args.mode == "verify" and args.variants:
        parser.error("--variants applies only to bench; verify checks all four implementations")
    args.build_dir = args.build_dir.expanduser().resolve()
    args.tables_dir = args.tables_dir.expanduser().resolve()
    if args.build_dir == HERE:
        parser.error("--build-dir must differ from the cpu source directory")
    if not (args.tables_dir / "tables.h").is_file():
        parser.error(f"tables.h missing from {args.tables_dir}")
    return args


def wrapper_source(path, name):
    """Expose only the implementation's hash_state; omit its command modes."""
    code = path.read_text(encoding="utf-8")
    marker = "static void state_digest"
    if code.count(marker) != 1:
        raise ValueError(f"expected one state_digest boundary in {path}")
    code = code.split(marker, 1)[0]
    symbol = f"{name}_hash_state"
    code = re.sub(r"\bhash_state\b", symbol, code)
    code, changed = re.subn(r"\bstatic\s+void\s+" + symbol + r"(?=\s*\()",
                            "void " + symbol, code, count=1)
    if changed != 1:
        raise ValueError(f"expected one static hash_state definition in {path}")
    return code


def compiler_command(value):
    # A path with spaces is a single executable; otherwise allow commands
    # such as 'ccache gcc'. All execution uses argument lists, without a shell.
    if Path(value).is_file() or shutil.which(value):
        return [value]
    result = shlex.split(value)
    if not result:
        raise ValueError("--cc must name a compiler")
    return result


def build(args):
    build_dir = args.build_dir
    build_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    for name, source in VARIANTS:
        target = build_dir / f"bench_{name}.c"
        target.write_text(wrapper_source(HERE / source, name), encoding="utf-8", newline="\n")
        generated.append(target)

    # Staging the harness is necessary too: a quoted include in a source
    # compiled directly from cpu/ would find cpu/tables.h before any -I path.
    harness = build_dir / "compare_combined.c"
    harness.write_bytes((HERE / "compare_combined.c").read_bytes())
    selected_tables = args.tables_dir / "tables.h"
    staged_tables = build_dir / "tables.h"
    if staged_tables.resolve() != selected_tables.resolve():
        staged_tables.write_bytes(selected_tables.read_bytes())

    suffix = ".exe" if os.name == "nt" else ""
    executable = build_dir / ("compare_combined" + suffix)
    command = compiler_command(args.cc) + [
        "-O3", "-march=native", "-funroll-loops", "-fopenmp",
        f"-DBRAM_TAP_GROUP={args.group}", f"-DBRAM_REVERSE_TAPS={args.reverse}",
        "-I", str(args.tables_dir), "-I", str(HERE),
        *(str(path) for path in generated), str(HERE / "sha256.c"), str(harness),
        "-o", str(executable),
    ]
    print("Build:", shlex.join(command), flush=True)
    subprocess.run(command, cwd=build_dir, check=True)
    return executable


def main(argv=None):
    args = arguments(argv)
    executable = build(args)
    command = [str(executable), args.mode, str(args.count)]
    if args.mode == "bench":
        command.append(str(args.runs))
        if args.variants:
            command.extend(args.variants)
    print("Run:", shlex.join(command), flush=True)
    subprocess.run(command, cwd=args.build_dir, check=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
