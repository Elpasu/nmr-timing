"""
Parsers for extracting wall-time and core counts from NMR calculation outputs.

Three supported formats, auto-detected by content:
  - ReSpect (SLURM .out)   -> reports real wall-time per step ("elapsed time")
  - Gaussian (.log)        -> reports CPU time; wall is ESTIMATED as cpu/ncores
  - ADF/ZORA (.log)        -> no elapsed line; wall = last_timestamp - first_timestamp

Each parser returns a CalcResult. The time source is recorded per record so the
exactness of every number is explicit (important for the methods section).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------- #
# Common record
# --------------------------------------------------------------------------- #
@dataclass
class CalcResult:
    path: str
    calc_type: str                 # 'respect' | 'gaussian' | 'zora' | 'unknown'
    system: str = ""               # molecule / system label (from folder name)
    method: str = ""               # e.g. '4c-mDKS', 'mPW1PW91', 'ZORA-SO'
    basis: str = ""                # e.g. 'upcS-3' (best-effort)
    n_cores: Optional[int] = None
    wall_seconds: Optional[float] = None
    time_source: str = ""          # 'respect_elapsed' | 'gaussian_cpu/ncores' | 'zora_timestamp_diff'
    n_steps: int = 1               # ReSpect: number of sub-jobs summed
    n_restarts: int = 0            # ReSpect: number of --restart invocations
    completed: bool = False        # normal termination found
    machine: str = ""
    notes: str = ""

    @property
    def wall_hours(self) -> Optional[float]:
        return None if self.wall_seconds is None else self.wall_seconds / 3600.0

    @property
    def core_hours(self) -> Optional[float]:
        if self.wall_seconds is None or self.n_cores is None:
            return None
        return (self.wall_seconds / 3600.0) * self.n_cores

    def to_row(self) -> dict:
        d = asdict(self)
        d["wall_hours"] = round(self.wall_hours, 3) if self.wall_hours is not None else None
        d["core_hours"] = round(self.core_hours, 3) if self.core_hours is not None else None
        return d


# --------------------------------------------------------------------------- #
# Type detection
# --------------------------------------------------------------------------- #
def detect_type(path: Path, sniff_lines: int = 60) -> str:
    try:
        with open(path, "r", errors="ignore") as fh:
            head = "".join(fh.readline() for _ in range(sniff_lines))
    except OSError:
        return "unknown"

    if "ReSpect program, version" in head:
        return "respect"
    if "Entering Gaussian System" in head or "Gaussian(R)" in head:
        return "gaussian"
    if "NMR 2019" in head or re.search(r"<\w{3}\d{2}-\d{4}>\s+<\d{2}:\d{2}:\d{2}>", head):
        return "zora"
    return "unknown"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _hms_to_seconds(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


def _system_from_path(path: Path) -> str:
    """Best-effort system label: the parent folder name."""
    return path.parent.name or path.stem


# --------------------------------------------------------------------------- #
# ReSpect parser
# --------------------------------------------------------------------------- #
_RES_ELAPSED = re.compile(r"elapsed time\s+(\d+):(\d{2}):(\d{2})")
_RES_NT = re.compile(r"--nt=(\d+)")
_RES_CALLARGS = re.compile(r"Call arguments\s+are\s+(.+)")
_RES_MACHINE = re.compile(r"Machine name\s+is\s+(\S+)")
_RES_VERSION = re.compile(r"ReSpect program, version\s+(\S+)")


def parse_respect(path: Path) -> CalcResult:
    """
    Sum the reported 'elapsed time' over every sub-job (--scf, --cs, ...).
    These are REAL wall-times from ReSpect, so this is the most reliable source.
    """
    text = Path(path).read_text(errors="ignore")

    res = CalcResult(path=str(path), calc_type="respect",
                     system=_system_from_path(Path(path)),
                     time_source="respect_elapsed")

    total = 0.0
    steps = 0
    restarts = 0
    nt_vals = set()
    steps_present = []

    for block in text.split("ReSpect program, version")[1:]:
        steps += 1
        m_call = _RES_CALLARGS.search(block)
        if m_call:
            args = m_call.group(1)
            if "--restart" in args:
                restarts += 1
            for flag in ("--scf", "--cs", "--rsp", "--esr"):
                if flag in args:
                    steps_present.append(flag.lstrip("-"))
        m_nt = _RES_NT.search(block)
        if m_nt:
            nt_vals.add(int(m_nt.group(1)))
        m_el = _RES_ELAPSED.search(block)
        if m_el:
            total += _hms_to_seconds(*m_el.groups())

    m_mach = _RES_MACHINE.search(text)
    if m_mach:
        res.machine = m_mach.group(1)

    res.wall_seconds = total if steps else None
    res.n_steps = steps
    res.n_restarts = restarts
    res.completed = text.count("ReSpect job is done") >= steps and steps > 0
    res.method = "4c-mDKS" if "4c" in text else "ReSpect"
    if len(nt_vals) == 1:
        res.n_cores = nt_vals.pop()
    elif len(nt_vals) > 1:
        res.n_cores = max(nt_vals)
        res.notes = f"mixed --nt across steps: {sorted(nt_vals)}"
    if steps_present:
        res.notes = (res.notes + "; " if res.notes else "") + "steps=" + "+".join(steps_present)
    return res


# --------------------------------------------------------------------------- #
# Gaussian parser
# --------------------------------------------------------------------------- #
_G_NPROC = re.compile(r"%nprocshared=(\d+)", re.IGNORECASE)
_G_NPROC2 = re.compile(r"Will use up to\s+(\d+)\s+processors", re.IGNORECASE)
_G_CPU = re.compile(
    r"Job cpu time:\s+(\d+)\s+days?\s+(\d+)\s+hours?\s+(\d+)\s+minutes?\s+([\d.]+)\s+seconds")
_G_ELAPSED = re.compile(
    r"Elapsed time:\s+(\d+)\s+days?\s+(\d+)\s+hours?\s+(\d+)\s+minutes?\s+([\d.]+)\s+seconds")
_G_METHOD = re.compile(r"#\s*(\S+)")
_G_BASIS = re.compile(r"/(\S*ECP|\S*6-31\S*|\S*def2\S*|\S*cc-\S*)", re.IGNORECASE)
_G_NORMAL = re.compile(r"Normal termination of Gaussian")


def parse_gaussian(path: Path) -> CalcResult:
    """
    Gaussian (esp. G09) usually prints CPU time, not wall. If an 'Elapsed time'
    line exists (G16) use it directly; otherwise estimate wall = cpu / ncores.
    """
    text = Path(path).read_text(errors="ignore")

    res = CalcResult(path=str(path), calc_type="gaussian",
                     system=_system_from_path(Path(path)))

    m_np = _G_NPROC.search(text) or _G_NPROC2.search(text)
    if m_np:
        res.n_cores = int(m_np.group(1))

    # CPU time can appear once per link; sum them all
    cpu_total = 0.0
    for d, h, m, s in _G_CPU.findall(text):
        cpu_total += int(d) * 86400 + int(h) * 3600 + int(m) * 60 + float(s)

    m_el = _G_ELAPSED.search(text)
    if m_el:
        d, h, m, s = m_el.groups()
        res.wall_seconds = int(d) * 86400 + int(h) * 3600 + int(m) * 60 + float(s)
        res.time_source = "gaussian_elapsed"
    elif cpu_total and res.n_cores:
        res.wall_seconds = cpu_total / res.n_cores
        res.time_source = "gaussian_cpu/ncores"
        res.notes = "wall ESTIMATED from CPU time / ncores"
    elif cpu_total:
        res.wall_seconds = cpu_total
        res.time_source = "gaussian_cpu_only"
        res.notes = "no ncores found; reporting raw CPU seconds"

    m_meth = _G_METHOD.search(text)
    if m_meth:
        res.method = m_meth.group(1)
    res.completed = bool(_G_NORMAL.search(text))
    return res


# --------------------------------------------------------------------------- #
# ADF / ZORA parser
# --------------------------------------------------------------------------- #
_Z_LINE = re.compile(r"<(\w{3})(\d{2})-(\d{4})>\s+<(\d{2}):(\d{2}):(\d{2})>")
_Z_PROCS = re.compile(r"Procs:\s+(\d+)")
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def parse_zora(path: Path) -> CalcResult:
    """
    No elapsed line in this log flavor: wall = last_timestamp - first_timestamp.
    Each line carries its own date, so midnight crossings are handled correctly.
    """
    text = Path(path).read_text(errors="ignore")

    res = CalcResult(path=str(path), calc_type="zora",
                     system=_system_from_path(Path(path)),
                     method="ZORA", time_source="zora_timestamp_diff")

    stamps = []
    for mon, day, year, hh, mm, ss in _Z_LINE.findall(text):
        if mon not in _MONTHS:
            continue
        stamps.append(datetime(int(year), _MONTHS[mon], int(day),
                               int(hh), int(mm), int(ss)))
    if len(stamps) >= 2:
        res.wall_seconds = (max(stamps) - min(stamps)).total_seconds()

    m_p = _Z_PROCS.search(text)
    if m_p:
        res.n_cores = int(m_p.group(1))

    res.completed = "NORMAL TERMINATION" in text
    res.notes = "wall = timestamp span (includes IO/setup)"
    return res


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
_PARSERS = {"respect": parse_respect, "gaussian": parse_gaussian, "zora": parse_zora}


def parse_file(path: Path) -> CalcResult:
    path = Path(path)
    ctype = detect_type(path)
    if ctype in _PARSERS:
        return _PARSERS[ctype](path)
    return CalcResult(path=str(path), calc_type="unknown",
                      system=_system_from_path(path),
                      notes="could not detect format")
