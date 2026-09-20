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

# Read provenance from the manifest rather than hard-coding it. Hard-coding
# 118,628 here was the same transcription hole the table audit had: when the
# archive grew, this file would have demanded the stale number.
import json as _json
_MANIFEST = _json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
ARCHIVE_COUNT = f"{_MANIFEST['unique_archived_responses']:,}".replace(",", "{,}")

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
    (r"Both registered criteria held", "F1 does not hold; this claim is withdrawn"),
    (r"47/50", "superseded F1 sample from the wrong population"),
    (r"standing (directional|buy) bias", "the two-component mechanism was withdrawn"),
    (r"decomposes into\s+two parts", "the two-component mechanism was withdrawn"),
    (r"in two parts", "the two-component mechanism was withdrawn"),
    (r"Nothing in its judgement was wrong", "false at the shock: 34.6% buy after a down shock"),
    (r"110\{,\}805|118\{,\}628|118\{,\}728",
     "a stale archive count; only the manifest's current value may appear"),
    # Backslash-eating has bitten three times: \texttt -> TAB+exttt,
    # \approx -> BEL+pprox, \ref -> CR+ef. Each produced legal plain text, so
    # the strict build passed and the PDF printed garbage. Catch the whole
    # class: any control byte, and the specific mangled command names.
    (r"(?<!\\)\b(exttt|pprox|ef\{|imes|ambda|extbf|extit)\b",
     "a LaTeX command lost its backslash to a string escape"),
    (r"[\x00-\x08\x0b\x0c\x0e-\x1f]",
     "control character in the source; a backslash was eaten by an escape"),
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
    (re.escape(ARCHIVE_COUNT), f"archive count matching the manifest ({ARCHIVE_COUNT})"),
    (r"Every confirmatory hypothesis test was preregistered",
     "scoped preregistration claim, replacing 'all experiments'"),
    # The registration record, by hypothesis ID. Searching for a sentence like
    # "four preregistered predictions" let a post-hoc mechanism story be filed
    # among registered failures for two drafts; only the IDs pin it.
    (r"three failed \(C1, C2", "C1 and C2 named as the failures"),
    (r"three were\s*\n?confirmed \(D1, D2, E1\)", "D1/D2/E1 named as confirmed"),
    (r"unresolved \(E2\)", "E2 named as unresolved"),
    (r"post-hoc two-component account|\\emph\{post-hoc\} two-component",
     "the withdrawn mechanism identified as post-hoc, not registered"),
    (r"memoised|memoized", "the cache estimand limitation"),
    (r"one archived response per distinct state", "the estimand stated explicitly"),
    (r"\+2\.84", "F2 upper bound on memoisation inflation"),
    (r"0\.887", "F1 lower bound, which fails its criterion"),
    (r"does not hold", "F1 reported as not holding"),
    (r"60/60", "option-naming control on the registered population"),
]

# Claims that must never be filed under the registration record.
REGISTRATION_TRAPS = [
    (r"[Ff]our preregistered predictions did not survive",
     "counts a post-hoc account among registered failures"),
    (r"preregistered[^.]{0,80}two-component",
     "the two-component account was never registered"),
]


def audit(text: str) -> list[str]:
    problems = []
    for pattern, why in FORBIDDEN + REGISTRATION_TRAPS:
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

    for pattern, why in FORBIDDEN + REGISTRATION_TRAPS:
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
        ("restore a stale archive count",
         lambda s: s.replace(ARCHIVE_COUNT, "110{,}805")),
        ("break a texttt", lambda s: s.replace("\\texttt{data/manifest.json}",
                                               "\texttt{data/manifest.json}")),
        ("file a post-hoc story among registered failures",
         lambda s: s.replace(
             "\\textbf{Three preregistered predictions failed}",
             "Four preregistered predictions did not survive")),
        ("drop the cache estimand limitation",
         lambda s: re.sub(r"memoised|memoized|one archived response per distinct state",
                          "XXX", s)),
        ("drop the hypothesis IDs from the tally",
         lambda s: s.replace("three failed (C1, C2", "three failed (various")),
        ("eat a backslash into a control character",
         lambda s: s.replace("$p \\approx 0.90$", "$p \x07pprox 0.90$")),
        ("eat a backslash into a bare command name",
         lambda s: s.replace("\\texttt{data/manifest.json}", "exttt{data/manifest.json}")),
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
