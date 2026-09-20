"""Audit the manuscript's prose claims, and prove the audit can fail.

Two review rounds found the same failure twice: a gate reported all-clear while
the paper said something false. Round one it was Table 1; round two it was the
abstract still arguing a withdrawn analysis while `audit_manuscript.py`
reported 9/9. A gate that only inspects what it already knows about certifies a
transcription, not a manuscript.

So this file does two things.

1. Asserts that superseded statistics and withdrawn claims do NOT appear
   anywhere in the manuscript, and that the current headline statistics DO --
   including in the abstract, contributions, failure tally, discussion and
   limitations, which the table-level audit never reads.

2. Runs mutation tests: it edits a copy of the manuscript to reintroduce each
   defect and requires the audit to catch it. An audit that cannot be made to
   fail is not evidence of anything.

    python scripts/audit_prose.py
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEX = ROOT / "paper" / "main.tex"

# (pattern, why it must not appear) -- withdrawn or superseded claims.
# A superseded statistic may appear when the sentence is retracting it. The
# rule is therefore "not asserted bare": the word `pooled` must be nearby,
# marking it as the old estimate rather than a current claim.
FORBIDDEN = [
    (r"(?<!pooled estimate, \$)t=-6\.91(?![^.]*understates)",
     "pooled E1 statistic asserted without marking it superseded"),
    (r"(?<!pooled \$)t=-2\.53",
     "pooled E2 statistic asserted without marking it superseded"),
    (r"was falsified", "E2 is unresolved, not falsified"),
    (r"standing (directional|buy) bias", "the two-component mechanism was withdrawn"),
    (r"decomposes into\s+two parts", "the two-component mechanism was withdrawn"),
    (r"in two parts", "the two-component mechanism was withdrawn"),
    (r"Nothing in its judgement was wrong", "false at the shock: 34.6% buy after a down shock"),
    (r"110\{,\}805", "stale archive count; the manifest says 118,628"),
    (r"(?<!\\)\bexttt\{", "lost backslash: \\texttt mangled by a \\t escape"),
    (r"\t", "literal tab in the source, usually a lost backslash"),
    (r"virtually every deployment", "uncited breadth claim"),
    (r"never short of buyers in any arm", "false for the sampling arm (4-7%)"),
    (r"It is never short of buyers", "false for the sampling arm (4-7%)"),
]

# (pattern, why it must appear) -- the corrected headline claims.
REQUIRED = [
    (r"t=-7\.78", "seed-paired E1 statistic"),
    (r"t=-2\.00", "seed-paired E2 statistic"),
    (r"unresolved", "E2's corrected status"),
    (r"90\.0\\%", "agreement at the shock, up side"),
    (r"59\.4\\%", "agreement at the shock, down side"),
    (r"118\{,\}628", "archive count from the manifest"),
    (r"Every confirmatory hypothesis test was preregistered",
     "scoped preregistration claim, replacing 'all experiments'"),
]


def audit(text: str) -> list[str]:
    problems = []
    for pattern, why in FORBIDDEN:
        for match in re.finditer(pattern, text):
            line = text[: match.start()].count("\n") + 1
            problems.append(f"line {line}: {why} -- found {match.group(0)!r}")
    for pattern, why in REQUIRED:
        if not re.search(pattern, text):
            problems.append(f"missing: {why} (no match for {pattern!r})")
    return problems


def main() -> int:
    text = TEX.read_text(encoding="utf-8")
    problems = audit(text)

    for pattern, why in FORBIDDEN:
        if not re.search(pattern, text):
            print(f"  [ok  ] absent: {why}")
    for pattern, why in REQUIRED:
        if re.search(pattern, text):
            print(f"  [ok  ] present: {why}")
    for p in problems:
        print(f"  [FAIL] {p}")

    # --- mutation tests: prove the audit can fail -------------------------
    print("\n  mutation tests (each must be caught):")
    mutations = [
        ("reintroduce pooled E1 t", lambda s: s.replace("$t=-7.78$", "$t=-6.91$")),
        ("call E2 falsified", lambda s: s.replace("is \\emph{unresolved}", "was falsified")),
        ("restore the standing-bias claim",
         lambda s: s + "\nThe arm carries a standing buy bias.\n"),
        ("restore the stale archive count",
         lambda s: s.replace("118{,}628", "110{,}805")),
        ("break a texttt", lambda s: s.replace("\\texttt{data/manifest.json}",
                                               "\texttt{data/manifest.json}")),
    ]
    mutation_failures = []
    for name, mutate in mutations:
        caught = bool(audit(mutate(text)))
        print(f"    [{'ok  ' if caught else 'FAIL'}] {name}")
        if not caught:
            mutation_failures.append(name)

    total = len(problems) + len(mutation_failures)
    if total:
        print(f"\n{total} problem(s).")
    else:
        print(f"\nprose audit clean; all {len(mutations)} mutations caught.")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
