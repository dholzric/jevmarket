"""Build the arXiv submission bundle and verify it compiles standalone.

arXiv compiles the uploaded sources itself, in an isolated tree, so the bundle
must be self-contained: no `../figures/` paths, every graphic inside the
bundle, no external .bib (the bibliography is inline). This script

  1. copies paper/main.tex, rewriting `../figures/` to `figures/`;
  2. copies exactly the graphics the manuscript includes;
  3. compiles the copy twice with pdflatex -halt-on-error in a scratch tree,
     and fails on missing files, undefined references, or undefined citations;
  4. writes dist/arxiv/jevmarket-arxiv.tar.gz plus dist/arxiv/metadata.txt
     (title, author, plain-text abstract with its character count, suggested
     categories, comments line).

    python scripts/make_arxiv.py
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEX = ROOT / "paper" / "main.tex"
DIST = ROOT / "dist" / "arxiv"
ARXIV_ABSTRACT_LIMIT = 1920

# The paper's abstract is ~2,900 characters; arXiv's metadata field allows
# 1,920. This is the condensation for the form. The PDF keeps the full one.
# Every number here must also appear in the paper's abstract (checked below),
# so the two cannot drift apart.
METADATA_ABSTRACT = """\
We populate a continuous double auction with traders whose decisions come from \
a typed language model that returns a probability distribution over actions, \
and vary only how that distribution is consumed. Taking the modal action \
increases non-trading periods after shocks in this simulated market: after a \
positive shock the market clears in 63.2% of periods against 92.3% after a \
negative one, a gap of 29.1 percentage points (95% CI [19.1, 39.1], t=6.08, \
n=20, preregistered, with an independent live call for every trader decision). \
A memoised confirmatory run gave 25.8 points; the difference between regimes \
is -3.3 points (95% CI [-13.9, +7.2]), so the halt is not an artefact of \
memoisation. Sampling from the same distribution reduces the gap to 1.7 \
points; two symmetric algorithmic baselines show none. The mechanism is \
counterparty scarcity: a shared public signal and modal action selection \
concentrate decisions on the same side, and unanimous buyers have no \
counterparty. 100% of non-trading periods under modal decoding had one side of \
the book empty, against 3.4% for a zero-intelligence baseline. A preregistered \
prediction that could have failed held: the effect weakens as the market \
grows, from 37.0 points at four traders to 4.2 at thirty-two (seed-paired \
t=-7.78). Separately, ordinary domain wording induces a 25-point asymmetry in \
the model's stated conviction that vanishes under mirror phrasing and, in a \
preregistered test, has no detected effect on pricing error. Of twelve registered \
predictions, six were confirmed, four failed, one is unresolved and one is not \
identified at the sample size reached; all are reported. These results concern \
one model and do not establish effects on real-market liquidity or welfare."""


def plain_abstract(tex: str) -> str:
    """The abstract as arXiv's metadata form wants it: plain text, no macros."""
    body = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", tex, re.S).group(1)
    text = body
    text = text.replace("---", " -- ").replace("~", " ")
    text = re.sub(r"\\emph\{(.*?)\}", r"\1", text)
    text = re.sub(r"\\textbf\{(.*?)\}", r"\1", text)
    text = re.sub(r"\\%", "%", text)
    text = re.sub(r"\$([^$]*)\$", r"\1", text)      # drop math delimiters
    text = re.sub(r"\\\\", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    paragraphs = [re.sub(r"\s*\n\s*", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p)


def main() -> int:
    tex = TEX.read_text(encoding="utf-8")
    graphics = re.findall(r"\\includegraphics\[[^\]]*\]\{([^}]*)\}", tex)
    if DIST.exists():
        shutil.rmtree(DIST)
    stage = DIST / "src"
    (stage / "figures").mkdir(parents=True)

    rewritten = tex.replace("../figures/", "figures/")
    (stage / "main.tex").write_text(rewritten, encoding="utf-8")
    for g in graphics:
        src = (TEX.parent / g).resolve()
        if not src.is_file():
            print(f"FAIL: manuscript includes {g} but {src} does not exist")
            return 1
        shutil.copy2(src, stage / "figures" / src.name)

    # Compile the STAGED copy in a scratch tree, exactly as arXiv would.
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        shutil.copytree(stage, work / "src")
        for _ in range(2):
            build = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
                cwd=work / "src", capture_output=True, text=True,
            )
            if build.returncode != 0:
                print(build.stdout[-3000:])
                print("FAIL: staged bundle does not compile")
                return 1
        log = (work / "src" / "main.log").read_text(encoding="utf-8", errors="replace")
        for pattern, what in (
            (r"File `.*' not found", "missing file"),
            (r"LaTeX Warning: Reference `.*' undefined", "undefined reference"),
            (r"LaTeX Warning: Citation `.*' undefined", "undefined citation"),
            (r"There were undefined references", "undefined references"),
        ):
            if re.search(pattern, log):
                print(f"FAIL: {what} in the staged build log")
                return 1
        overfull = len(re.findall(r"Overfull \\hbox", log))
        pages = re.search(r"Output written on main.pdf \((\d+) pages", log)
        shutil.copy2(work / "src" / "main.pdf", DIST / "main-from-bundle.pdf")

    tarball = DIST / "jevmarket-arxiv.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                tf.add(f, arcname=str(f.relative_to(stage)).replace("\\", "/"))

    title = re.search(r"\\title\{(.*?)\}\s*\n\s*\n", tex, re.S).group(1)
    title = " ".join(title.replace("\\\\", " ").split())
    paper_abstract = plain_abstract(tex)
    abstract = METADATA_ABSTRACT
    # Drift guard: every number quoted in the short abstract must be a number
    # the paper's own abstract quotes.
    paper_numbers = set(re.findall(r"-?\d+(?:\.\d+)?", paper_abstract))
    stray = sorted(n for n in set(re.findall(r"-?\d+(?:\.\d+)?", abstract))
                   if n not in paper_numbers)
    if stray:
        print(f"FAIL: metadata abstract quotes numbers absent from the paper's abstract: {stray}")
        return 1
    metadata = f"""ARXIV SUBMISSION METADATA (paste into the form)

Title:
{title}

Authors:
D. Holzricher

Abstract for the form ({len(abstract)} characters; arXiv limit {ARXIV_ABSTRACT_LIMIT};
a condensation of the paper's {len(paper_abstract)}-character abstract, every
number checked against it):
{abstract}

Suggested primary category:  q-fin.TR (Trading and Market Microstructure)
Suggested cross-lists:       cs.MA (Multiagent Systems); cs.CL (Computation and Language); econ.GN

Comments line (edit):
{pages.group(1) if pages else '?'} pages, 2 figures. Preregistered; code, response archives and
the registration record at https://github.com/dholzric/jevmarket

License: arXiv perpetual non-exclusive licence is the minimal choice; CC BY 4.0
if you want reuse without asking. Your call.

Bundle: {tarball.name} ({tarball.stat().st_size:,} bytes), compiles standalone
with pdflatex x2; overfull hboxes in the staged build: {overfull}.
"""
    (DIST / "metadata.txt").write_text(metadata, encoding="utf-8")
    print(metadata)
    if len(abstract) > ARXIV_ABSTRACT_LIMIT:
        print(f"FAIL: abstract is {len(abstract)} characters; arXiv allows {ARXIV_ABSTRACT_LIMIT}")
        return 1
    print(f"wrote {tarball}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
