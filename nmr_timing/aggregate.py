"""
Aggregation layer.

Main job: merge ReSpect runs that were SPLIT across several output files
(the calculation died and was relaunched) into a single logical calculation,
summing wall-times and counting restarts.

Grouping key for ReSpect fragments: the 'Work directory' reported inside the
file (same molecule/run dir => same logical calc). If that can't be read, it
falls back to the parent folder name.

Gaussian and ZORA are treated as one-file-one-calc by default.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .parsers import CalcResult, parse_file, detect_type

_RES_WORKDIR = re.compile(r"Work\s+directory is\s+(\S+)")
_RES_START = re.compile(r"Starting time:\s+([\d\-: ]+)")


def _respect_group_key(path: Path) -> str:
    try:
        text = Path(path).read_text(errors="ignore")
    except OSError:
        return str(path.parent)
    m = _RES_WORKDIR.search(text)
    if m:
        return m.group(1).rstrip("/")
    return str(path.parent)


def _respect_first_start(path: Path) -> str:
    try:
        text = Path(path).read_text(errors="ignore")
    except OSError:
        return ""
    m = _RES_START.search(text)
    return m.group(1).strip() if m else ""


def merge_respect_fragments(results_with_paths: list[tuple[Path, CalcResult]]) -> CalcResult:
    """Combine several ReSpect CalcResults (same run dir) into one."""
    # order chronologically by first 'Starting time'
    ordered = sorted(results_with_paths, key=lambda rp: _respect_first_start(rp[0]))
    base = ordered[0][1]

    total_wall = 0.0
    steps = 0
    restarts = 0
    cores = set()
    all_done = True
    fragments = []

    for p, r in ordered:
        total_wall += r.wall_seconds or 0.0
        steps += r.n_steps
        restarts += r.n_restarts
        if r.n_cores:
            cores.add(r.n_cores)
        all_done = all_done and r.completed
        fragments.append(Path(p).name)

    merged = replace(
        base,
        path=" + ".join(fragments),
        wall_seconds=total_wall if total_wall else None,
        n_steps=steps,
        n_restarts=restarts,
        n_cores=(max(cores) if cores else None),
        completed=all_done,
        notes=(base.notes + "; " if base.notes else "")
        + f"merged from {len(ordered)} file(s)"
        + (f"; mixed cores {sorted(cores)}" if len(cores) > 1 else ""),
    )
    return merged


def collect(paths: Iterable[Path]) -> list[CalcResult]:
    """
    Parse every file, then merge split ReSpect fragments by run directory.
    Gaussian/ZORA/unknown pass through unchanged.
    """
    paths = [Path(p) for p in paths]

    respect_files: list[Path] = []
    others: list[Path] = []
    for p in paths:
        (respect_files if detect_type(p) == "respect" else others).append(p)

    out: list[CalcResult] = []

    # group respect by work dir
    groups: dict[str, list[tuple[Path, CalcResult]]] = {}
    for p in respect_files:
        groups.setdefault(_respect_group_key(p), []).append((p, parse_file(p)))

    for key, items in groups.items():
        merged = merge_respect_fragments(items) if len(items) > 1 else items[0][1]
        if not merged.system or merged.system in (".", ""):
            merged.system = Path(key).name
        out.append(merged)

    for p in others:
        out.append(parse_file(p))

    return out


def find_output_files(root: Path,
                      exts: tuple[str, ...] = (".out", ".log", ".txt")) -> list[Path]:
    """Recursively collect candidate output files under root."""
    root = Path(root)
    files = []
    for ext in exts:
        files.extend(root.rglob(f"*{ext}"))
    return sorted(set(files))
