"""One zero-intelligence price path against the jumping fundamental.

Weekend deliverable 5. Run it, look at it, and confirm two things by eye:
the fundamental really is piecewise constant with visible jumps, and ZI trade
prices really do chase it. Everything after this weekend is measured against
this picture.

    python scripts/zi_price_path.py --periods 600 --traders 40 --seed 7
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.fundamental import Fundamental, Signal  # noqa: E402
from jevmarket.metrics import post_jump_rmse, rmse_vs_fundamental  # noqa: E402
from jevmarket.simulation import RunConfig, run  # noqa: E402

# Okabe-Ito blue / vermillion. Validated: adjacent-pair CVD dE 21.9 (protan),
# normal-vision dE 31.2, both above the surface contrast floor.
FUNDAMENTAL_COLOR = "#0072B2"
PRICE_COLOR = "#D55E00"
INK = "#1a1a19"
MUTED = "#6b6b68"
GRID = "#e4e4e1"
SURFACE = "#fcfcfb"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", type=int, default=600)
    parser.add_argument("--traders", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--jump-prob", type=float, default=0.02)
    parser.add_argument("--jump-sd", type=float, default=10.0)
    parser.add_argument("--private-value-sd", type=float, default=5.0)
    parser.add_argument(
        "--out", type=pathlib.Path, default=pathlib.Path("figures/zi_price_path.png")
    )
    return parser.parse_args(argv)


def build_config(args) -> RunConfig:
    return RunConfig(
        n_traders=args.traders,
        periods=args.periods,
        seed=args.seed,
        arm="zi",
        private_value_sd=args.private_value_sd,
        fundamental=Fundamental(
            initial=100.0,
            jump_prob=args.jump_prob,
            jump_sd=args.jump_sd,
            seed=args.seed,
        ),
        signal=Signal(delay=0, noise_sd=0.0, seed=args.seed),
    )


def plot(result, out_path: pathlib.Path) -> None:
    periods = range(len(result.fundamental_path))
    prices = [p if p is not None else float("nan") for p in result.trade_prices]

    fig, ax = plt.subplots(figsize=(9.0, 4.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for jump in result.jump_times:
        ax.axvline(jump, color=GRID, linewidth=1.0, zorder=0)

    ax.plot(
        periods,
        result.fundamental_path,
        drawstyle="steps-post",
        color=FUNDAMENTAL_COLOR,
        linewidth=2.0,
        label="Fundamental $F_t$",
        zorder=2,
    )
    ax.plot(
        periods,
        prices,
        color=PRICE_COLOR,
        linewidth=1.2,
        alpha=0.9,
        label="ZI trade price (per-period VWAP)",
        zorder=3,
    )

    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)

    ax.set_xlabel("Period", color=MUTED, fontsize=9)
    ax.set_ylabel("Price (ticks)", color=MUTED, fontsize=9)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.set_xlim(0, len(result.fundamental_path) - 1)

    config = result.config
    ax.set_title(
        f"Zero-intelligence traders chase a jumping fundamental "
        f"({config.n_traders} traders, seed {config.seed}, "
        f"{len(result.jump_times)} jumps)",
        color=INK,
        fontsize=10.5,
        loc="left",
        pad=12,
    )

    legend = ax.legend(loc="upper left", frameon=False, fontsize=9)
    for text in legend.get_texts():
        text.set_color(INK)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, facecolor=SURFACE)
    fig.savefig(out_path.with_suffix(".pdf"), facecolor=SURFACE)
    plt.close(fig)


def main(argv=None) -> int:
    args = parse_args(argv)
    result = run(build_config(args))
    result.exchange.check_invariants()

    traded = sum(1 for p in result.trade_prices if p is not None)
    overall = rmse_vs_fundamental(result.trade_prices, result.fundamental_path)
    post_jump = post_jump_rmse(
        result.trade_prices, result.fundamental_path, result.jump_times
    )

    print(f"periods              {args.periods}")
    print(f"traders              {args.traders}")
    print(f"jumps                {len(result.jump_times)}")
    print(f"trades               {result.exchange.trade_count}")
    print(f"periods with a trade {traded} / {args.periods}")
    print(f"rejected orders      {result.rejections}")
    print(f"cash conserved       {result.exchange.total_cash}")
    print(f"units conserved      {result.exchange.total_inventory}")
    print(f"RMSE vs F_t          {overall:.3f}")
    print(f"post-jump RMSE (20)  {post_jump:.3f}")

    plot(result, args.out)
    print(f"\nwrote {args.out} and {args.out.with_suffix('.pdf')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
