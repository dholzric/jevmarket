"""Run every gate, in dependency order, and fail if any fails.

The order matters and has bitten us: a previous verification reported all-clear
because the audits ran BEFORE `make_manifest.py` regenerated the manifest they
check against, so the green result was from stale inputs. The manifest is now
always rebuilt first, and this is the only command that should be quoted as
"everything passes".

    python scripts/check_all.py
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

STEPS = [
    ("regenerate the provenance manifest", ["scripts/make_manifest.py"]),
    ("test suite", ["-m", "pytest", "-q"]),
    ("data regression over pinned statistics", ["scripts/verify_paper.py"]),
    ("manuscript tables, provenance, strict build", ["scripts/audit_manuscript.py"]),
    ("manuscript prose, with mutation tests", ["scripts/audit_prose.py"]),
]


def main() -> int:
    failures = []
    for name, args in STEPS:
        result = subprocess.run(
            [sys.executable, *args], cwd=ROOT, capture_output=True, text=True
        )
        lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
        status = "ok  " if result.returncode == 0 else "FAIL"
        print(f"  [{status}] {name}")
        if lines:
            print(f"           {lines[-1].strip()}")
        if result.returncode != 0:
            failures.append((name, result.stdout, result.stderr))

    if failures:
        print(f"\n{len(failures)} gate(s) failed:\n")
        for name, out, err in failures:
            print(f"--- {name} ---")
            print((out or err)[-1500:])
        return 1

    print("\nall gates pass, manifest regenerated first")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
