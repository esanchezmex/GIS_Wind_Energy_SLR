"""
Create quick electrical-capacity loss summaries and plots for SLR flags.

Input expected:
  processed_data/Affected_Farms.csv

Required columns:
  - electrical_capacity
  - Affected_1m, Affected_3m (binary-ish flags)

Outputs:
  - plots/capacity_summary_by_slr.csv
  - plots/capacity_remaining_vs_lost_mw.png
  - plots/capacity_loss_percent.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from calculate_available_capacity import affected_mask

INPUT_CSV = Path("processed_data/Affected_Farms.csv")
PLOTS_DIR = Path("plots")
SCENARIO_COLS = ["Affected_1m", "Affected_3m"]


def scenario_label(col: str) -> str:
    return col.replace("Affected_", "").replace("m", " m SLR")


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"Missing input CSV: {INPUT_CSV}")

    df = pd.read_csv(INPUT_CSV)
    cap = pd.to_numeric(df["electrical_capacity"], errors="coerce").fillna(0.0)
    total_mw = float(cap.sum())

    rows: list[dict] = []
    for col in SCENARIO_COLS:
        if col not in df.columns:
            raise KeyError(f"Missing scenario column: {col}")
        aff = affected_mask(df, col)
        lost_mw = float(cap[aff].sum())
        remaining_mw = float(cap[~aff].sum())
        rows.append(
            {
                "scenario": col,
                "scenario_label": scenario_label(col),
                "n_affected_sites": int(aff.sum()),
                "n_remaining_sites": int((~aff).sum()),
                "total_capacity_mw": total_mw,
                "lost_capacity_mw": lost_mw,
                "remaining_capacity_mw": remaining_mw,
                "lost_capacity_pct": (lost_mw / total_mw * 100.0) if total_mw else 0.0,
                "remaining_capacity_pct": (remaining_mw / total_mw * 100.0)
                if total_mw
                else 0.0,
            }
        )

    summary = pd.DataFrame(rows)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(PLOTS_DIR / "capacity_summary_by_slr.csv", index=False)

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
            "axes.titlesize": 13,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
        }
    )

    # Plot 1: remaining vs lost MW by scenario (stacked bars)
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    x = summary["scenario_label"]
    ax.bar(
        x,
        summary["remaining_capacity_mw"],
        label="Remaining capacity (MW)",
        color="#4C72B0",
        edgecolor="black",
        linewidth=0.6,
    )
    ax.bar(
        x,
        summary["lost_capacity_mw"],
        bottom=summary["remaining_capacity_mw"],
        label="Lost capacity (MW)",
        color="#C44E52",
        edgecolor="black",
        linewidth=0.6,
    )
    y1_max = float((summary["remaining_capacity_mw"] + summary["lost_capacity_mw"]).max())
    ax.set_ylim(0, y1_max * 1.10)
    ax.set_ylabel("Capacity (MW)")
    ax.set_title("Electrical capacity by SLR scenario")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="best")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "capacity_remaining_vs_lost_mw.png", dpi=300)
    plt.close(fig)

    # Plot 2: loss percentage by scenario
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.bar(
        x,
        summary["lost_capacity_pct"],
        color="#C44E52",
        edgecolor="black",
        linewidth=0.6,
    )
    y2_max = float(summary["lost_capacity_pct"].max())
    ax.set_ylim(0, y2_max * 1.20 if y2_max > 0 else 1)
    ax.set_ylabel("Capacity loss (%)")
    ax.set_title("Percent of electrical capacity affected by SLR")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "capacity_loss_percent.png", dpi=300)
    plt.close(fig)

    print(f"Baseline total electrical capacity: {total_mw:.3f} MW")
    print(summary[["scenario", "lost_capacity_mw", "remaining_capacity_mw", "lost_capacity_pct"]].to_string(index=False))
    print(f"Saved outputs to: {PLOTS_DIR.resolve()}")


if __name__ == "__main__":
    main()

