"""
Command-line entry point.

Usage:
    python -m nmr_timing.cli /path/to/calcs_root
    python -m nmr_timing.cli /path/to/calcs_root --excel timing.xlsx --csv timing.csv
    python -m nmr_timing.cli file1.out file2.log ...      # explicit files

Reports per logical calculation:
    system, calc_type, method, basis, n_cores, wall_hours, core_hours,
    n_restarts, completed, time_source, notes

core_hours (= wall_hours x n_cores) is the fairest cross-machine comparator,
but treat it as order-of-magnitude only: 4c-ReSpect/upcS-3 and DFT do not
scale the same way.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .aggregate import collect, find_output_files

COLUMNS = ["system", "calc_type", "method", "basis", "n_cores",
           "wall_hours", "core_hours", "n_steps", "n_restarts",
           "completed", "time_source", "notes"]


def build_dataframe(results):
    import pandas as pd
    rows = [r.to_row() for r in results]
    df = pd.DataFrame(rows)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNS].sort_values(["calc_type", "system"]).reset_index(drop=True)
    return df


def main(argv=None):
    ap = argparse.ArgumentParser(description="NMR calculation timing analyzer")
    ap.add_argument("inputs", nargs="+",
                    help="root folder to scan, or explicit output files")
    ap.add_argument("--csv", help="write results to this CSV path")
    ap.add_argument("--excel", help="write results to this .xlsx path")
    ap.add_argument("--ext", default=".out,.log,.txt",
                    help="comma-separated extensions to scan (folder mode)")
    args = ap.parse_args(argv)

    # resolve inputs: a single existing dir => scan; otherwise treat as files
    paths = []
    for item in args.inputs:
        p = Path(item)
        if p.is_dir():
            exts = tuple(e if e.startswith(".") else "." + e
                         for e in args.ext.split(","))
            paths.extend(find_output_files(p, exts))
        elif p.exists():
            paths.append(p)
        else:
            print(f"warning: {item} not found", file=sys.stderr)

    if not paths:
        print("No input files found.", file=sys.stderr)
        return 1

    results = collect(paths)
    df = build_dataframe(results)

    with __import__("pandas").option_context("display.max_columns", None,
                                             "display.width", 200):
        print(df.to_string(index=False))

    # summary by method
    try:
        import pandas as pd
        summ = (df.dropna(subset=["core_hours"])
                  .groupby("calc_type")["core_hours"]
                  .agg(["count", "mean", "sum"]).round(2))
        print("\n=== core-hours by calc_type ===")
        print(summ.to_string())
    except Exception:
        pass

    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"\nwrote {args.csv}")
    if args.excel:
        df.to_excel(args.excel, index=False)
        print(f"wrote {args.excel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
