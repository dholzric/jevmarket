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

    results = {}
    for f in sorted(DATA.glob("*.json")):
        if f.name == "manifest.json":
            continue
        results[f.name] = {"bytes": f.stat().st_size, "sha256": sha256(f)}

    manifest = {
        "responses": responses,
        "live_calls": responses,  # one cached entry per distinct live request
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
        "caches": per_cache,
        "archive_bundles": bundles,
        "result_files": results,
    }
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"responses      {responses:,}")
    for name, count in per_cache.items():
        print(f"    {name:<18} {count:,}")
    print(f"input tokens   {input_tokens:,}")
    print(f"output tokens  {output_tokens:,}")
    print(f"estimated cost ${cost:.2f}")
    print(f"\nwrote {DATA / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
