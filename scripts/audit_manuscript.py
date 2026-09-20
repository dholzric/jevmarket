"""Audit the manuscript itself, not a transcription of it.

`verify_paper.py` compares saved data against numbers hard-coded in the
verifier. Both external reviewers identified the hole that creates: the paper
can disagree with the verifier and still report a clean pass. It did. Table 1
carried trading levels from the exploratory run alongside a gap from the
confirmatory run, and "55/55 claims match" never looked at it.

This script reads `paper/main.tex` directly:

  1. every table row is parsed, and its internal arithmetic checked
     (levels quoted beside a gap must actually produce that gap)
  2. every percentage in a table is matched against the dataset the table
     declares, so a table cannot silently mix two runs
  3. the build is run with -halt-on-error and must exit 0

    python scripts/audit_manuscript.py
"""

from __future__ import annotations

import json
import pathlib
import re
import statistics
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEX = ROOT / "paper" / "main.tex"
DATA = ROOT / "data"

problems: list[str] = []
notes: list[str] = []


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def numbers(row: str) -> list[float]:
    """Percentages and signed point values in a tabular row."""
    return [float(x) for x in re.findall(r"[-+]?\d+\.\d+", row)]


def tables(tex: str) -> dict[str, list[str]]:
    """label -> the tabular body rows of that table."""
    out = {}
    for block in re.findall(r"\\begin\{table\}(.*?)\\end\{table\}", tex, re.S):
        label = re.search(r"\\label\{(.*?)\}", block)
        body = re.search(r"\\begin\{tabular\}.*?\n(.*?)\\end\{tabular\}", block, re.S)
        if not (label and body):
            continue
        # Strip rules rather than dropping rows that contain them: a row
        # immediately after \midrule shares its chunk, and filtering on the
        # chunk silently skipped the first data row of every table.
        rows = []
        for chunk in body.group(1).split("\\\\"):
            cleaned = re.sub(r"\\(top|mid|bottom)rule|\\cmidrule(\(.*?\))?\{.*?\}",
                             " ", chunk).strip()
            if "&" in cleaned and numbers(cleaned):
                rows.append(cleaned)
        out[label.group(1)] = rows
    return out


tex = TEX.read_text(encoding="utf-8")
found = tables(tex)

# --- 1. internal arithmetic: levels beside a gap must produce that gap ------
liquidity = found.get("tab:liquidity", [])
ms = load("market_size.json")
cc = load("cessation_confirm.json")["gaps"]
expected = {
    "Jev-argmax": ("jev_argmax", "jev_argmax/original"),
    "Jev-sample": ("jev_sample", "jev_sample/original"),
    "ZI": ("zi", "zi"),
    "NBR": ("nbr", "nbr"),
}
for row in liquidity:
    arm = row.split("&")[0].strip()
    if arm not in expected:
        continue
    vals = numbers(row)
    if len(vals) < 3:
        continue
    up, down, gap = vals[0], vals[1], vals[2]
    size_key, gap_key = expected[arm]
    real_up = ms[f"{size_key}|8"]["up"] * 100
    real_down = ms[f"{size_key}|8"]["down"] * 100
    real_gap = statistics.fmean(cc[gap_key].values()) * 100

    if abs(up - real_up) > 0.1 or abs(down - real_down) > 0.1:
        problems.append(
            f"tab:liquidity {arm}: levels {up}/{down} do not match the "
            f"confirmatory dataset ({real_up:.1f}/{real_down:.1f}) -- mixed sources?"
        )
    if abs(gap - real_gap) > 0.1:
        problems.append(f"tab:liquidity {arm}: gap {gap} != data {real_gap:.1f}")
    # the arithmetic a referee does in their head
    if abs((down - up) - gap) > 1.5:
        problems.append(
            f"tab:liquidity {arm}: {down} - {up} = {down - up:.1f}, but the row "
            f"states a gap of {gap}. Internally inconsistent on its face."
        )
    else:
        notes.append(f"tab:liquidity {arm}: levels, gap and subtraction agree")

# --- 2. order-flow table against its dataset --------------------------------
flow = load("lag_flow.json") if (DATA / "lag_flow.json").is_file() else None
if flow:
    for row in found.get("tab:flow", []):
        label = row.split("&")[0].strip().replace("$", "")
        vals = numbers(row)
        if len(vals) != 6:
            continue
        key = "window" if "window" in label else label.replace("t+", "").replace("t", "0") or "0"
        if key not in flow:
            continue
        ref = flow[key]
        for got, want, name in zip(
            vals,
            [ref["up"]["buy"], ref["up"]["sell"], ref["up"]["pass"],
             ref["down"]["buy"], ref["down"]["sell"], ref["down"]["pass"]],
            ["up buy", "up sell", "up pass", "down buy", "down sell", "down pass"],
        ):
            if abs(got - want * 100) > 0.2:
                problems.append(f"tab:flow row {label} {name}: {got} != {want * 100:.1f}")
    notes.append("tab:flow checked against data/lag_flow.json")
else:
    problems.append("data/lag_flow.json missing; tab:flow cannot be audited")

# --- 3. provenance numbers --------------------------------------------------
manifest = DATA / "manifest.json"
if manifest.is_file():
    m = json.loads(manifest.read_text(encoding="utf-8"))
    for pattern, value, what in (
        (r"([\d,]+)\s+of them", m["unique_archived_responses"], "archived responses"),
        (r"All\s+([\d,]+)\s+archived responses", m["unique_archived_responses"],
         "archived responses (non-determinism section)"),
        (r"archive holds \$?([\d,]+)", m["unique_archived_responses"],
         "unique archived responses"),
    ):
        for match in re.findall(pattern, tex.replace("{,}", ",")):
            got = int(match.replace(",", ""))
            if got != value:
                problems.append(f"manuscript says {got:,} {what}; manifest says {value:,}")
            else:
                notes.append(f"{what} matches the manifest ({value:,})")
else:
    problems.append("data/manifest.json missing; provenance numbers unaudited")

# --- 4. the build must actually succeed -------------------------------------
build = subprocess.run(
    ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
    cwd=ROOT / "paper", capture_output=True, text=True,
)
if build.returncode != 0:
    problems.append(f"pdflatex -halt-on-error exited {build.returncode}")
else:
    notes.append("pdflatex -halt-on-error exits 0")
log = (ROOT / "paper" / "main.log").read_text(encoding="utf-8", errors="replace")
undefined = len(re.findall(r"Warning:.*(?:undefined|Citation)", log))
if undefined:
    problems.append(f"{undefined} undefined reference/citation warning(s)")
else:
    notes.append("no undefined references or citations")

# --- report -----------------------------------------------------------------
for n in notes:
    print(f"  [ok  ] {n}")
for p in problems:
    print(f"  [FAIL] {p}")
print(f"\n{len(notes)} checks passed, {len(problems)} problem(s).")
sys.exit(1 if problems else 0)
