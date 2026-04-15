"""
Assign a binary protection priority label to wind farms.

Rule used (transparent and tunable):
1) Compute a weighted risk-capacity score:
      score = electrical_capacity * (w1 * Affected_1m + w3 * Affected_3m)
   Default weights prioritize near-term exposure (1 m) slightly more:
      w1 = 0.6, w3 = 0.4
2) Rank farms by score (descending), excluding score == 0.
3) Mark farms as Priority_Save = 1 until cumulative score reaches target share
   of total score (default 50%). Others get 0.

This identifies the smallest set of farms covering most potential weighted loss.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create Priority_Save (0/1) from affected flags and capacity."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("processed_data/Affected_Farms.csv"),
        help="Input CSV with electrical_capacity, Affected_1m, Affected_3m",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("processed_data/Affected_Farms_priority.csv"),
        help="Output CSV path with Priority_Save column",
    )
    parser.add_argument(
        "--cover-share",
        type=float,
        default=0.50,
        help="Target cumulative share of weighted score to protect (0-1). Default 0.50",
    )
    parser.add_argument(
        "--w1",
        type=float,
        default=0.6,
        help="Weight for Affected_1m (default 0.6)",
    )
    parser.add_argument(
        "--w3",
        type=float,
        default=0.4,
        help="Weight for Affected_3m (default 0.4)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(f"Missing input: {args.input}")
    if not (0 < args.cover_share <= 1):
        raise ValueError("--cover-share must be in (0, 1].")

    df = pd.read_csv(args.input)
    needed = {"electrical_capacity", "Affected_1m", "Affected_3m"}
    missing = needed - set(df.columns)
    if missing:
        raise KeyError(f"Missing required columns: {sorted(missing)}")

    cap = pd.to_numeric(df["electrical_capacity"], errors="coerce").fillna(0.0)
    a1 = pd.to_numeric(df["Affected_1m"], errors="coerce").fillna(0.0).clip(0, 1)
    a3 = pd.to_numeric(df["Affected_3m"], errors="coerce").fillna(0.0).clip(0, 1)

    score = cap * (args.w1 * a1 + args.w3 * a3)
    df["Priority_Score"] = score
    df["Priority_Save"] = 0

    ranked = df[df["Priority_Score"] > 0].sort_values(
        "Priority_Score", ascending=False
    )
    total_score = float(ranked["Priority_Score"].sum())

    if total_score > 0:
        cshare = ranked["Priority_Score"].cumsum() / total_score
        selected_idx = cshare[cshare <= args.cover_share].index.tolist()
        # Ensure we include at least one row when there is positive risk.
        if not selected_idx and len(ranked):
            selected_idx = [ranked.index[0]]
        # Add first row crossing threshold for better target coverage.
        crossing = ranked.loc[cshare > args.cover_share]
        if not crossing.empty:
            selected_idx.append(crossing.index[0])
        df.loc[sorted(set(selected_idx)), "Priority_Save"] = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)

    n_priority = int(df["Priority_Save"].sum())
    n_any = int((df["Priority_Score"] > 0).sum())
    covered = (
        float(df.loc[df["Priority_Save"] == 1, "Priority_Score"].sum()) / total_score
        if total_score
        else 0.0
    )
    print(f"Saved: {args.output.resolve()}")
    print(f"Priority farms: {n_priority} / {len(df)}")
    print(f"At-risk farms (score>0): {n_any}")
    print(f"Covered weighted risk share: {covered:.3%}")


if __name__ == "__main__":
    main()

