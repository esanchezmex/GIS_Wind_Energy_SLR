"""
Compute onshore wind capacity (MW) from turbine-level columns, optionally split by
affected vs remaining plants (e.g. after an SLR overlay in QGIS).

Recommended workflow (one file, no edits to your original CSV on disk):
  - In QGIS, add a field like ``affected`` (0/1) on the layer that already has
    ``capacity_individual_turbine`` and ``number_of_turbines`` (join back to the
    original table if your overlay only returned geometries).
  - File → Save features as… a **new** CSV path, e.g.
    ``processed_data/land_wind_farms_scenario_a.csv``.
  - Run: ``python calculate_available_capacity.py that.csv --affected-col affected``
  You are not mutating ``land_wind_farms.csv``; you only point the script at the
  export you choose each time.

Alternative workflow (two files): QGIS exports a small table of site IDs + flag.
  Use ``--flags-csv`` + ``--join-on`` to merge onto the full-capacity table
  (see CLI help).

Row capacity defaults to: capacity_individual_turbine * number_of_turbines (MW).
Optional fallback fills missing products with electrical_capacity (site total).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

COL_PER_TURBINE = "capacity_individual_turbine"
COL_N_TURBINES = "number_of_turbines"
COL_SITE_TOTAL = "electrical_capacity"


def turbine_capacity_mw(
    df: pd.DataFrame,
    *,
    fallback_electrical: bool = False,
) -> pd.Series:
    """MW per row from nameplate * count. NaN if either factor is missing."""
    if COL_PER_TURBINE not in df.columns or COL_N_TURBINES not in df.columns:
        raise KeyError(
            f"Expected columns {COL_PER_TURBINE!r} and {COL_N_TURBINES!r}. "
            f"Got: {list(df.columns)}"
        )
    per = pd.to_numeric(df[COL_PER_TURBINE], errors="coerce")
    n = pd.to_numeric(df[COL_N_TURBINES], errors="coerce")
    out = per * n
    if fallback_electrical and COL_SITE_TOTAL in df.columns:
        site = pd.to_numeric(df[COL_SITE_TOTAL], errors="coerce")
        out = out.fillna(site)
    return out


def affected_mask(
    df: pd.DataFrame,
    column: str,
    *,
    true_values: tuple[str | int | float | bool, ...] | None = None,
    invert: bool = False,
) -> pd.Series:
    """
    Boolean mask: rows marked as affected (e.g. inundated) unless invert=True.

    If true_values is None, treats common QGIS patterns as True:
    1, 1.0, True, '1', 'yes', 'Yes', 'Y', 'true', 'affected', etc.
    """
    if column not in df.columns:
        raise KeyError(
            f"Column {column!r} not found. Available columns: {list(df.columns)}"
        )
    s = df[column]
    if true_values is not None:
        mask = s.isin(true_values)
    else:
        if pd.api.types.is_bool_dtype(s):
            mask = s.fillna(False).astype(bool)
        else:
            truthy = {
                1,
                True,
                "1",
                1.0,
                "yes",
                "Yes",
                "Y",
                "y",
                "true",
                "True",
                "T",
                "affected",
                "Affected",
            }
            mask = s.isin(truthy)
            num = pd.to_numeric(s, errors="coerce")
            mask = mask | (num == 1.0)
    if invert:
        mask = ~mask
    return mask.fillna(False)


def capacity_summary(
    df: pd.DataFrame,
    *,
    affected_column: str | None = None,
    true_values: tuple[str | int | float | bool, ...] | None = None,
    invert_affected: bool = False,
    fallback_electrical: bool = False,
) -> dict:
    """
    Return totals for baseline and (optional) affected vs remaining capacity.

    Assumes rows flagged as affected lose all derived MW for that row (binary loss).
    """
    cap = turbine_capacity_mw(df, fallback_electrical=fallback_electrical)
    missing_n = int(cap.isna().sum())
    cap_filled = cap.fillna(0.0)
    total_mw = float(cap_filled.sum())

    out: dict = {
        "total_mw": total_mw,
        "n_sites": int(len(df)),
        "rows_missing_turbine_product": missing_n,
        "fallback_electrical": fallback_electrical,
    }

    if affected_column:
        aff = affected_mask(
            df,
            affected_column,
            true_values=true_values,
            invert=invert_affected,
        )
        affected_mw = float(cap_filled[aff].sum())
        remaining_mw = float(cap_filled[~aff].sum())
        out.update(
            {
                "affected_column": affected_column,
                "n_affected_sites": int(aff.sum()),
                "n_remaining_sites": int((~aff).sum()),
                "capacity_affected_mw": affected_mw,
                "capacity_remaining_mw": remaining_mw,
                "capacity_lost_mw": affected_mw,
            }
        )

    return out


def _parse_true_values(raw: str | None) -> tuple[str | int | float | bool, ...] | None:
    if raw is None or raw.strip() == "":
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    parsed: list[str | int | float | bool] = []
    for p in parts:
        low = p.lower()
        if low in ("true", "false"):
            parsed.append(low == "true")
            continue
        try:
            parsed.append(int(p))
            continue
        except ValueError:
            pass
        try:
            parsed.append(float(p))
            continue
        except ValueError:
            parsed.append(p)
    return tuple(parsed)


def merge_flags_from_file(
    base: pd.DataFrame,
    flags_path: Path,
    join_on: str,
    affected_col: str,
) -> pd.DataFrame:
    """
    Left-merge QGIS flag rows onto the full site table. Sites missing from the
    flags file are treated as not affected (0).
    """
    flags = pd.read_csv(flags_path)
    for name, df in (("base", base), ("flags", flags)):
        if join_on not in df.columns:
            raise KeyError(f"{name!r} CSV missing join column {join_on!r}. Columns: {list(df.columns)}")
    if affected_col not in flags.columns:
        raise KeyError(
            f"Flags CSV missing {affected_col!r}. Columns: {list(flags.columns)}"
        )
    right = flags[[join_on, affected_col]].drop_duplicates(subset=[join_on])
    out = base.merge(right, on=join_on, how="left")
    # Not in the overlay export → assume not affected
    s = out[affected_col]
    if pd.api.types.is_bool_dtype(s):
        out[affected_col] = s.fillna(False)
    elif pd.api.types.is_numeric_dtype(s):
        out[affected_col] = s.fillna(0)
    else:
        out[affected_col] = s.fillna("no")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarise onshore wind MW from turbine columns; optional SLR flag column.",
    )
    parser.add_argument(
        "csv",
        type=Path,
        help="Primary CSV: must include turbine capacity columns (and optionally "
        "the same --affected-col if produced in one QGIS export).",
    )
    parser.add_argument(
        "--affected-col",
        type=str,
        default=None,
        help="Column for affected=1 / yes / true = lost capacity. Required when "
        "using --flags-csv; optional when the flag is already in the primary CSV.",
    )
    parser.add_argument(
        "--flags-csv",
        type=Path,
        default=None,
        help="Optional second CSV from QGIS with only site id + flag columns "
        "(merge onto primary with --join-on). Omitted sites = not affected.",
    )
    parser.add_argument(
        "--join-on",
        type=str,
        default="uk_beis_id",
        help="Column present in both CSVs when using --flags-csv (default: uk_beis_id)",
    )
    parser.add_argument(
        "--true-values",
        type=str,
        default=None,
        help="Comma-separated values that count as affected, e.g. '1,yes,A'. "
        "If omitted, uses common defaults.",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="Interpret flag as 'survives' (True = not lost); affected = ~mask",
    )
    parser.add_argument(
        "--fallback-electrical",
        action="store_true",
        help=f"If turbine product is NaN, use {COL_SITE_TOTAL!r} for that row",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print one JSON object on stdout",
    )
    args = parser.parse_args(argv)

    if not args.csv.exists():
        print(f"File not found: {args.csv}", file=sys.stderr)
        return 1
    if args.flags_csv is not None and not args.flags_csv.exists():
        print(f"Flags file not found: {args.flags_csv}", file=sys.stderr)
        return 1
    if args.flags_csv is not None and not args.affected_col:
        print(
            "--affected-col is required when using --flags-csv "
            "(name of the flag column in the flags CSV).",
            file=sys.stderr,
        )
        return 1

    df = pd.read_csv(args.csv)
    if args.flags_csv is not None:
        df = merge_flags_from_file(
            df, args.flags_csv, join_on=args.join_on, affected_col=args.affected_col
        )

    summary = capacity_summary(
        df,
        affected_column=args.affected_col,
        true_values=_parse_true_values(args.true_values),
        invert_affected=args.invert,
        fallback_electrical=args.fallback_electrical,
    )

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print("Capacity summary (MW)")
    print(f"  CSV: {args.csv.resolve()}")
    print(f"  Sites: {summary['n_sites']}")
    print(f"  Total (derived): {summary['total_mw']:.3f} MW")
    if summary["rows_missing_turbine_product"]:
        print(
            f"  Warning: {summary['rows_missing_turbine_product']} row(s) had NaN "
            f"turbine product (treated as 0 in sums unless --fallback-electrical)"
        )
    if args.affected_col:
        print(f"  Affected column: {args.affected_col}")
        print(f"  Affected sites: {summary['n_affected_sites']}")
        print(f"  Capacity on affected sites: {summary['capacity_affected_mw']:.3f} MW")
        print(f"  Capacity on remaining sites: {summary['capacity_remaining_mw']:.3f} MW")
        print(f"  Implied loss (if affected sites fully lost): {summary['capacity_lost_mw']:.3f} MW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
