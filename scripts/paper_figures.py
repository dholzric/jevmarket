"""Figures for the paper. Reads only saved results; makes no API calls.

    python scripts/paper_figures.py
"""

from __future__ import annotations

import json
import pathlib
import statistics
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

# Okabe-Ito blue / vermillion, validated: adjacent-pair CVD dE 21.9 (protan),
# normal-vision dE 31.2, both clear of the surface contrast floor.
ARGMAX = "#D55E00"
SAMPLE = "#0072B2"
CONTROL = "#9a9a97"
INK = "#1a1a19"
MUTED = "#6b6b68"
GRID = "#e4e4e1"
SURFACE = "#ffffff"

FIGDIR = pathlib.Path("figures")


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)


def se(values):
    return statistics.stdev(values) / len(values) ** 0.5


def figure_market_size():
    """The central result: herding, and its collapse with market size."""
    data = json.loads((pathlib.Path("data") / "market_size.json").read_text())
    sizes = [4, 8, 16, 32]

    fig, ax = plt.subplots(figsize=(5.6, 3.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    style(ax)

    series = [
        ("jev_argmax", ARGMAX, "Jev, argmax", 2.0, "o", 1.0),
        ("jev_sample", SAMPLE, "Jev, sampled", 2.0, "s", 1.0),
        ("zi", CONTROL, "zero-intelligence", 1.2, "^", 0.9),
        ("nbr", CONTROL, "noisy best-response", 1.2, "v", 0.9),
    ]
    for arm, colour, label, width, marker, alpha in series:
        means = [data[f"{arm}|{n}"]["gap"] * 100 for n in sizes]
        errs = [se(data[f"{arm}|{n}"]["gaps"]) * 100 for n in sizes]
        ax.errorbar(
            sizes, means, yerr=errs, color=colour, linewidth=width, alpha=alpha,
            marker=marker, markersize=5, capsize=3, elinewidth=1.0,
            label=label, zorder=3 if arm.startswith("jev") else 2,
            linestyle="-" if arm.startswith("jev") else "--",
        )

    ax.axhline(0, color=GRID, linewidth=1.0, zorder=1)
    ax.set_xscale("log", base=2)
    ax.set_xticks(sizes)
    ax.set_xticklabels([str(n) for n in sizes])
    ax.set_xlabel("Traders in the market", color=MUTED, fontsize=9)
    ax.set_ylabel("Liquidity gap after a shock\n(down $-$ up, percentage points)",
                  color=MUTED, fontsize=9)
    ax.set_title(
        "Argmax herding collapses as the market grows",
        color=INK, fontsize=10.5, loc="left", pad=10,
    )
    legend = ax.legend(loc="upper right", frameon=False, fontsize=8)
    for text in legend.get_texts():
        text.set_color(INK)

    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(FIGDIR / f"fig1_market_size.{ext}", facecolor=SURFACE)
    plt.close(fig)
    print("wrote figures/fig1_market_size.pdf / .png")


def figure_wording():
    """Conviction against mispricing, under the two question wordings."""
    rows = json.loads((pathlib.Path("data") / "wording.json").read_text())["rows"]

    fig, ax = plt.subplots(figsize=(5.6, 3.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    style(ax)

    for variant, colour, label, marker in (
        ("original", ARGMAX, "domain wording", "o"),
        ("mirror", SAMPLE, "mirror wording", "s"),
    ):
        pts = sorted(
            [(r["edge"], r["p_correct"]) for r in rows if r["variant"] == variant]
        )
        ax.plot([e for e, _ in pts], [p for _, p in pts], color=colour, linewidth=2.0,
                marker=marker, markersize=5, label=label, zorder=3)

    ax.axvline(0, color=GRID, linewidth=1.0, zorder=1)
    ax.set_ylim(0.5, 1.02)
    ax.set_xlabel("Mispricing (private value $-$ mid price, ticks)", color=MUTED, fontsize=9)
    ax.set_ylabel("Probability on the profitable side", color=MUTED, fontsize=9)
    ax.set_title(
        "Domain wording costs conviction on one side only",
        color=INK, fontsize=10.5, loc="left", pad=10,
    )
    ax.annotate("sell is correct", xy=(-8, 0.54), color=MUTED, fontsize=8, ha="center")
    ax.annotate("buy is correct", xy=(8, 0.54), color=MUTED, fontsize=8, ha="center")
    legend = ax.legend(loc="lower right", frameon=False, fontsize=8)
    for text in legend.get_texts():
        text.set_color(INK)

    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(FIGDIR / f"fig2_wording.{ext}", facecolor=SURFACE)
    plt.close(fig)
    print("wrote figures/fig2_wording.pdf / .png")


def main() -> int:
    FIGDIR.mkdir(exist_ok=True)
    figure_market_size()
    figure_wording()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
