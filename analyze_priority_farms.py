"""
Identify whether SLR capacity loss is concentrated in a few large farms.

Uses electrical_capacity and binary affected columns to quantify:
- total affected capacity
- concentration shares by top 1 / top 3 / top 5 affected farms
- a simple prioritization recommendation for protection investment

Default scenarios:
- Affected_1m
- Affected_3m
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from calculate_available_capacity import affected_mask

DEFAULT_CSV = Path("processed_data/Affected_Farms.csv")
DEFAULT_OUTDIR = Path("plots")
DEFAULT_SCENARIOS = ("Affected_1m", "Affected_3m")


def _scenario_row(df: pd.DataFrame, scenario_col: str) -> tuple[dict, pd.DataFrame]:
    cap = pd.to_numeric(df["electrical_capacity"], errors="coerce").fillna(0.0)
    base_total = float(cap.sum())
    mask = affected_mask(df, scenario_col)
    affected = df.loc[mask].copy()
    affected["electrical_capacity_num"] = cap[mask]
    affected = affected.sort_values("electrical_capacity_num", ascending=False)

    affected_total = float(affected["electrical_capacity_num"].sum())
    top1 = float(affected["electrical_capacity_num"].head(1).sum())
    top3 = float(affected["electrical_capacity_num"].head(3).sum())
    top5 = float(affected["electrical_capacity_num"].head(5).sum())

    def pct(part: float, whole: float) -> float:
        return (part / whole * 100.0) if whole else 0.0

    # Heuristic: strong concentration if top 3 account for >= 50% of affected MW.
    concentrated = pct(top3, affected_total) >= 50.0
    recommendation = (
        "Prioritize site-specific protection for a few high-capacity farms first."
        if concentrated
        else "Use broader regional protection and portfolio-wide adaptation."
    )

    summary = {
        "scenario": scenario_col,
        "n_affected_farms": int(mask.sum()),
        "baseline_total_mw": base_total,
        "affected_total_mw": affected_total,
        "affected_share_of_baseline_pct": pct(affected_total, base_total),
        "top1_affected_mw": top1,
        "top3_affected_mw": top3,
        "top5_affected_mw": top5,
        "top1_share_of_affected_pct": pct(top1, affected_total),
        "top3_share_of_affected_pct": pct(top3, affected_total),
        "top5_share_of_affected_pct": pct(top5, affected_total),
        "is_concentrated_top3_ge_50pct": concentrated,
        "priority_recommendation": recommendation,
    }

    detail_cols = [
        c
        for c in ["site_name", "uk_beis_id", "operator", "region", "country"]
        if c in affected.columns
    ]
    detail = affected[detail_cols + ["electrical_capacity_num"]].rename(
        columns={"electrical_capacity_num": "electrical_capacity_mw"}
    )
    return summary, detail


def _plot_lorenz(detail: pd.DataFrame, scenario_col: str, outdir: Path) -> None:
    """Plot cumulative share of affected capacity vs affected farms."""
    cap = pd.to_numeric(detail["electrical_capacity_mw"], errors="coerce").fillna(0.0)
    cap = cap.sort_values(ascending=True).reset_index(drop=True)
    n = len(cap)
    if n == 0:
        return
    x = (cap.index + 1) / n * 100.0
    y = cap.cumsum() / cap.sum() * 100.0 if cap.sum() else cap * 0.0

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
            "axes.titlesize": 12,
            "axes.labelsize": 11,
        }
    )
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    ax.plot(x, y, linewidth=2.0, color="#1f4e79", label="Lorenz curve")
    ax.plot([0, 100], [0, 100], linestyle="--", color="gray", linewidth=1.2, label="Equality line")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Cumulative share of affected farms (%)")
    ax.set_ylabel("Cumulative share of affected capacity (%)")
    ax.set_title(f"Capacity concentration curve ({scenario_col})")
    ax.grid(True, linestyle="--", alpha=0.3)
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(outdir / f"lorenz_capacity_{scenario_col}.png", dpi=300)
    plt.close(fig)


def _plot_topn(summary_df: pd.DataFrame, outdir: Path) -> None:
    """Plot top-1/top-3/top-5 share of affected capacity by scenario."""
    if summary_df.empty:
        return
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
            "axes.titlesize": 12,
            "axes.labelsize": 11,
        }
    )

    labels = summary_df["scenario"].tolist()
    x = list(range(len(labels)))
    w = 0.22

    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    ax.bar(
        [i - w for i in x],
        summary_df["top1_share_of_affected_pct"],
        width=w,
        label="Top 1 share",
        color="#4C72B0",
        edgecolor="black",
        linewidth=0.5,
    )
    ax.bar(
        x,
        summary_df["top3_share_of_affected_pct"],
        width=w,
        label="Top 3 share",
        color="#55A868",
        edgecolor="black",
        linewidth=0.5,
    )
    ax.bar(
        [i + w for i in x],
        summary_df["top5_share_of_affected_pct"],
        width=w,
        label="Top 5 share",
        color="#C44E52",
        edgecolor="black",
        linewidth=0.5,
    )
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Share of affected capacity (%)")
    ax.set_title("How concentrated are SLR losses in top farms?")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(outdir / "topn_share_by_scenario.png", dpi=300)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze concentration of affected capacity to prioritize farms."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help=f"Input CSV (default: {DEFAULT_CSV})",
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default=",".join(DEFAULT_SCENARIOS),
        help="Comma-separated affected columns (default: Affected_1m,Affected_3m)",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=DEFAULT_OUTDIR,
        help=f"Output directory (default: {DEFAULT_OUTDIR})",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        raise FileNotFoundError(f"Missing input CSV: {args.csv}")

    df = pd.read_csv(args.csv)
    if "electrical_capacity" not in df.columns:
        raise KeyError("Column 'electrical_capacity' is required.")

    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    for s in scenarios:
        if s not in df.columns:
            raise KeyError(f"Scenario column not found: {s}")

    args.outdir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []
    for s in scenarios:
        summary, detail = _scenario_row(df, s)
        summary_rows.append(summary)
        detail_path = args.outdir / f"priority_farms_{s}.csv"
        detail.to_csv(detail_path, index=False)
        _plot_lorenz(detail, s, args.outdir)

    summary_df = pd.DataFrame(summary_rows)
    summary_path = args.outdir / "priority_analysis_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    _plot_topn(summary_df, args.outdir)

    print("Priority analysis summary")
    print(summary_df.to_string(index=False))
    print(f"\nSaved: {summary_path.resolve()}")
    for s in scenarios:
        print(f"Saved: {(args.outdir / f'priority_farms_{s}.csv').resolve()}")
        print(f"Saved: {(args.outdir / f'lorenz_capacity_{s}.png').resolve()}")
    print(f"Saved: {(args.outdir / 'topn_share_by_scenario.png').resolve()}")


if __name__ == "__main__":
    main()

