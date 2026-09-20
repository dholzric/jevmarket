"""Generate provenance numbers from disk, so the paper cannot drift from them.

Both reviewers caught the paper quoting 110,805 archived responses and ~95,000
live calls while the cache on disk held 118,483. Counting by hand once and
typing the result into a manuscript is how that happens.

Writes data/manifest.json, which `audit_manuscript.py` checks the paper against.

    python scripts/make_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# Dollars per million tokens, fitted to the account meter (see jev/budget.py).
INPUT_PER_MTOK = 0.028
OUTPUT_PER_MTOK = 0.14


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    caches = sorted(d for d in DATA.glob("cache*") if d.is_dir())
    responses = 0
    input_tokens = 0
    output_tokens = 0
    per_cache = {}

    for cache in caches:
        files = list(cache.rglob("*.json"))
        per_cache[cache.name] = len(files)
        responses += len(files)
        for f in files:
            try:
                entry = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            resp = entry.get("response", {})
            input_tokens += int(resp.get("input_tokens", 0) or 0)
            output_tokens += int(resp.get("output_tokens", 0) or 0)

    cost = (input_tokens * INPUT_PER_MTOK + output_tokens * OUTPUT_PER_MTOK) / 1_000_000

    bundles = {}
    archive = DATA / "archive"
    if archive.is_dir():
        for bundle in sorted(archive.glob("*.tar.gz")):
            bundles[bundle.name] = {
                "bytes": bundle.stat().st_size,
                "sha256": sha256(bundle),
            }

    # Prereg 10h: ordered per-run archives of independent live calls. These are
    # raw round-trips, one per trader decision, NOT unique-per-state entries,
    # so they are counted separately from the content-addressed caches.
    independent = {}
    independent_calls = 0
    independent_input = 0
    independent_output = 0
    independent_dir = DATA / "independent"
    if independent_dir.is_dir():
        import gzip
        for f in sorted(independent_dir.glob("*.json.gz")):
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                entries = json.load(fh)
            calls = len(entries)
            inp = sum(int(e["response"].get("input_tokens", 0) or 0) for e in entries)
            out = sum(int(e["response"].get("output_tokens", 0) or 0) for e in entries)
            independent[f.name] = {"calls": calls, "bytes": f.stat().st_size,
                                   "sha256": sha256(f)}
            independent_calls += calls
            independent_input += inp
            independent_output += out
    independent_cost = (independent_input * INPUT_PER_MTOK
                        + independent_output * OUTPUT_PER_MTOK) / 1_000_000

    raw_repeats_file = DATA / "raw_repeats.json"
    raw_repeats_calls = 0
    if raw_repeats_file.is_file():
        try:
            raw_repeats_calls = len(json.loads(raw_repeats_file.read_text(encoding="utf-8")))
        except Exception:
            pass

    results = {}
    for f in sorted(DATA.glob("*.json")):
        if f.name == "manifest.json":
            continue
        results[f.name] = {"bytes": f.stat().st_size, "sha256": sha256(f)}

    manifest = {
        # A cache file is one surviving DISTINCT request, not a counted wire
        # round-trip. Retries, repeated uncached requests and overwrites of the
        # same key do not appear separately, so this is a lower bound on live
        # calls, not a meter. Labelled accordingly after external review.
        "unique_archived_responses": responses,
        "estimated_live_calls_lower_bound": responses,
        "responses": responses,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
        "cost_basis": "summed from archived token counts at the fitted rate; "
                      "not a provider invoice",
        "caches": per_cache,
        "archive_bundles": bundles,
        "raw_repeats_calls": raw_repeats_calls,
        "independent_calls": independent_calls,
        "independent_input_tokens": independent_input,
        "independent_output_tokens": independent_output,
        "independent_estimated_cost_usd": round(independent_cost, 4),
        "independent_archives": independent,
        "result_files": results,
    }
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"responses      {responses:,}")
    for name, count in per_cache.items():
        print(f"    {name:<18} {count:,}")
    print(f"input tokens   {input_tokens:,}")
    print(f"output tokens  {output_tokens:,}")
    print(f"estimated cost ${cost:.2f}")
    print(f"independent calls (10h archives)  {independent_calls:,}  "
          f"${independent_cost:.2f}")
    print(f"raw repeats calls (estimand test) {raw_repeats_calls:,}")
    print(f"\nwrote {DATA / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
