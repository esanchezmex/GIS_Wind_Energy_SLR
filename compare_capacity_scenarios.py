"""
Summarise capacity loss across multiple SLR (or flood) flag columns in one CSV.

QGIS workflow (yes, this is normal):
  - Build one point/polygon layer that still has all original attributes
    (capacity_individual_turbine, number_of_turbines, uk_beis_id, …).
  - For each scenario (2 m, 3 m, …), run your overlay / intersect / within
    against the corresponding flood footprint and write a **new field** on the
    same layer, e.g. ``affected_2m``, ``affected_3m`` (0/1 or yes/no), using the
    Field Calculator or successive joins.
  - Export **once** to CSV: all original columns plus ``affected_*``.
  - Run this script on that file to get baseline MW and lost/remaining MW per
    scenario column.

Alternatively use Processing → Graphical Modeler to loop over scenario layers
and aggregate results into one layer with many flag fields.

Usage:
  python compare_capacity_scenarios.py path/to/export.csv
  python compare_capacity_scenarios.py export.csv --prefix affected_
  python compare_capacity_scenarios.py export.csv --cols affected_2m,affected_3m --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from calculate_available_capacity import (
    _parse_true_values,
    capacity_summary,
)


def discover_scenario_columns(df: pd.DataFrame, prefix: str) -> list[str]:
    """Columns whose names start with ``prefix`` (e.g. ``affected_``)."""
    return [c for c in df.columns if c.startswith(prefix)]


def compare_scenarios(
    df: pd.DataFrame,
    scenario_columns: list[str],
    *,
    true_values: tuple[str | int | float | bool, ...] | None = None,
    invert_affected: bool = False,
    fallback_electrical: bool = False,
) -> tuple[dict, list[dict]]:
    """
    Return (baseline_summary, list of per-scenario summaries).

    Each scenario dict includes the same keys as ``capacity_summary`` for that
    affected column, plus ``scenario`` = column name.
    """
    baseline = capacity_summary(
        df,
        affected_column=None,
        fallback_electrical=fallback_electrical,
    )
    per_scenario: list[dict] = []
    for col in scenario_columns:
        s = capacity_summary(
            df,
            affected_column=col,
            true_values=true_values,
            invert_affected=invert_affected,
            fallback_electrical=fallback_electrical,
        )
        row = {"scenario": col, **{k: v for k, v in s.items() if k != "fallback_electrical"}}
        row["baseline_total_mw"] = baseline["total_mw"]
        row["baseline_n_sites"] = baseline["n_sites"]
        row["rows_missing_turbine_product"] = baseline["rows_missing_turbine_product"]
        row["fallback_electrical"] = fallback_electrical
        per_scenario.append(row)
    return baseline, per_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare capacity across many affected_* (or custom) columns in one CSV.",
    )
    parser.add_argument(
        "csv",
        type=Path,
        help="CSV from QGIS with turbine columns and one or more scenario flag columns.",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="affected_",
        help="Auto-pick columns starting with this prefix (default: affected_)",
    )
    parser.add_argument(
        "--cols",
        type=str,
        default=None,
        help="Comma-separated scenario column names (overrides --prefix discovery)",
    )
    parser.add_argument(
        "--true-values",
        type=str,
        default=None,
        help="Comma-separated values that count as affected (same as calculate_available_capacity)",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="Flag True means survives; affected = invert",
    )
    parser.add_argument(
        "--fallback-electrical",
        action="store_true",
        help="Use electrical_capacity when turbine product is NaN",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print baseline + scenarios as JSON",
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=None,
        help="Optional path to write a slim summary table (CSV)",
    )
    args = parser.parse_args(argv)

    if not args.csv.exists():
        print(f"File not found: {args.csv}", file=sys.stderr)
        return 1

    df = pd.read_csv(args.csv)
    if args.cols:
        scenario_cols = [c.strip() for c in args.cols.split(",") if c.strip()]
    else:
        scenario_cols = discover_scenario_columns(df, args.prefix)

    if not scenario_cols:
        print(
            f"No scenario columns found (prefix {args.prefix!r}). "
            f"Use --cols or name fields like affected_2m, affected_3m, …",
            file=sys.stderr,
        )
        return 1

    missing = [c for c in scenario_cols if c not in df.columns]
    if missing:
        print(f"Unknown columns: {missing}", file=sys.stderr)
        return 1

    tv = _parse_true_values(args.true_values)
    baseline, rows = compare_scenarios(
        df,
        scenario_cols,
        true_values=tv,
        invert_affected=args.invert,
        fallback_electrical=args.fallback_electrical,
    )

    if args.json:
        print(
            json.dumps(
                {"baseline": baseline, "scenarios": rows},
                indent=2,
            )
        )
    else:
        print("Baseline (all sites in file)")
        print(f"  Total derived MW: {baseline['total_mw']:.3f}")
        print(f"  Sites: {baseline['n_sites']}")
        if baseline["rows_missing_turbine_product"]:
            print(
                f"  Warning: {baseline['rows_missing_turbine_product']} row(s) "
                "missing turbine product (counted as 0 unless --fallback-electrical)"
            )
        print()
        print(f"{'Scenario':<24} {'Affected sites':>14} {'Lost MW':>12} {'Remaining MW':>14}")
        for r in rows:
            print(
                f"{r['scenario']:<24} "
                f"{r['n_affected_sites']:>14} "
                f"{r['capacity_lost_mw']:>12.3f} "
                f"{r['capacity_remaining_mw']:>14.3f}"
            )

    if args.out_csv:
        table = pd.DataFrame(rows)
        args.out_csv.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(args.out_csv, index=False)
        if not args.json:
            print(f"\nWrote {args.out_csv.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
