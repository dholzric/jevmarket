# arXiv submission checklist

Build the bundle and the form text:

```bash
python scripts/check_all.py        # every gate green first
python scripts/make_arxiv.py       # dist/arxiv/jevmarket-arxiv.tar.gz + metadata.txt
```

`make_arxiv.py` stages `main.tex` with `../figures/` rewritten to `figures/`,
copies only the graphics the manuscript includes, compiles the staged copy
twice in a scratch tree with `-halt-on-error`, fails on any missing file or
undefined reference, and checks that the rendered text matches nothing else:
compare `dist/arxiv/main-from-bundle.pdf` against `paper/main.pdf` by eye or
with pypdf (they were text-identical at 4cd32cc). The bibliography is inline
(`thebibliography`), so no `.bbl` is needed.

## Decisions only the author can make

1. **Repository link.** The paper says "the repository" (Reproducibility
   section) without a URL, and `github.com/dholzric/jevmarket` is **private**.
   arXiv readers cannot reproduce anything without it. Either make the repo
   public and add the URL to the Reproducibility section and the comments
   line, or leave the paper as is and accept that the reproducibility claims
   are not checkable by readers. Making the repo public is a one-line change
   in the paper plus `ALLOW_PUBLIC_REPO=1 gh repo edit dholzric/jevmarket --visibility public`
   (the hook blocks it otherwise). Before flipping: the secret scan on tracked
   files is clean as of 4cd32cc, and `data/cache` is gitignored (published as
   `data/archive/*.tar.gz`).
2. **Licence.** arXiv perpetual non-exclusive (minimal) or CC BY 4.0.
3. **Categories.** Suggested primary `q-fin.TR`; cross-lists `cs.MA`, `cs.CL`,
   `econ.GN`. `cs.MA` primary is defensible if you want the multi-agent
   audience first.
4. **Author name and affiliation** as they should appear; the tex has
   "D. Holzricher" and an email, no affiliation.

## Form fields

All in `dist/arxiv/metadata.txt`: title, author, a 1,9xx-character abstract
condensed from the paper's (the paper's own abstract is ~2,900 characters,
over arXiv's 1,920 limit; the PDF keeps the long one), categories, comments
line. The script fails if the short abstract quotes a number the paper's
abstract does not.

## Upload

1. Upload `dist/arxiv/jevmarket-arxiv.tar.gz`. arXiv will detect pdflatex.
2. Check the arXiv-rendered PDF page count (14) and both figures.
3. Paste the metadata. Set the licence.
4. After the arXiv ID arrives, add it to README.md and tag the commit
   (`git tag v1.1.1-arxiv && git push --tags`).

## Known cosmetic limits (reviewers said label, don't rerun)

- Figure 2 (probe grid) is n=1 per point.
- Table 3 and the abstract's 90.0% / 59.4% agreement figures are from the
  memoised confirmatory run; the headline halt is from the independent-calling
  replication. Both are labelled as such in the text.
