"""Seed-aware reanalysis of the market-size slope (E1/E2).

Both reviewers flagged that the sweep reuses the same 20 seeds at every market
size, so pooling all 80 observations into one OLS treats repeated measures as
independent. Estimating a slope within each seed and then testing over seeds
respects the design.

The correction moves E1 the right way and E2 the wrong way:

  E1  pooled t = -6.91   ->  seed-paired t = -7.78   (stronger)
  E2  pooled t = -2.53   ->  seed-paired t = -2.00, two-sided p = 0.060

E2 was registered as "no decay", so a significant slope would falsify it. At
p = 0.060 it does not, and the paper must not claim it was falsified. A
non-significant result is also not evidence of equivalence: no equivalence
margin was preregistered.

    python scripts/size_slope_clustered.py
"""

from __future__ import annotations

import json
import pathlib
import statistics
import sys

import numpy as np
import scipy.stats as st

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"
SIZES = [4, 8, 16, 32]


def main() -> int:
    ms = json.loads((DATA / "market_size.json").read_text(encoding="utf-8"))
    out = {}

    header = (f"{'':>12} {'pooled slope':>13} {'pooled t':>9} "
              f"{'paired slope':>13} {'paired t':>9} {'two-sided p':>12} {'neg/total':>10}")
    print(header)
    print("-" * len(header))

    for label, arm in (("E1 argmax", "jev_argmax"), ("E2 sample", "jev_sample")):
        xs, ys = [], []
        for n in SIZES:
            for g in ms[f"{arm}|{n}"]["gaps"]:
                xs.append(np.log2(n))
                ys.append(g)
        pooled = st.linregress(xs, ys)

        per_seed = []
        for i in range(len(ms[f"{arm}|4"]["gaps"])):
            per_seed.append(
                st.linregress([np.log2(n) for n in SIZES],
                              [ms[f"{arm}|{n}"]["gaps"][i] for n in SIZES]).slope
            )
        mean = statistics.fmean(per_seed)
        se = statistics.stdev(per_seed) / len(per_seed) ** 0.5
        t = mean / se
        p = 2 * st.t.sf(abs(t), len(per_seed) - 1)
        lo, hi = st.t.interval(0.95, len(per_seed) - 1, loc=mean, scale=se)
        negative = sum(1 for v in per_seed if v < 0)

        out[arm] = {"pooled_slope": pooled.slope,
                    "pooled_t": pooled.slope / pooled.stderr,
                    "paired_slope": mean, "paired_se": se, "paired_t": t,
                    "two_sided_p": p, "ci": [lo, hi],
                    "seeds_negative": negative, "n_seeds": len(per_seed),
                    "per_seed_slopes": per_seed}

        print(f"{label:>12} {pooled.slope:>13.4f} {pooled.slope / pooled.stderr:>9.2f} "
              f"{mean:>13.4f} {t:>9.2f} {p:>12.4f} "
              f"{f'{negative}/{len(per_seed)}':>10}")

    print("\nE1: negative slope confirmed and stronger under the seed-aware test.")
    print("E2: registered as 'no decay'. Two-sided p = "
          f"{out['jev_sample']['two_sided_p']:.3f} does not falsify it at 0.05, and")
    print("    no equivalence margin was preregistered, so it cannot be called")
    print("    confirmed either. Report as directionally consistent, inconclusive.")

    (DATA / "size_slope_clustered.json").write_text(json.dumps(out, indent=2),
                                                    encoding="utf-8")
    print(f"\nwrote {DATA / 'size_slope_clustered.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
