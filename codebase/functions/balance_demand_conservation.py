"""Compare independent aggregated-demand references with resolved demand rows."""

#%%

from pathlib import Path

import pandas as pd


CONSERVATION_KEY_COLUMNS = (
    "economy",
    "scenario",
    "sector_context",
    "esto_product",
    "year",
)


def build_balance_demand_conservation_diagnostics(
    reference_rows: pd.DataFrame,
    resolved_rows: pd.DataFrame,
    tolerance_pj: float = 1e-6,
) -> pd.DataFrame:
    """Return an outer-join conservation comparison at sector/product/year level.

    Inputs must already represent the intended comparison surface. In particular,
    subtotal and deliberately excluded rows should be removed by their source
    workflows rather than inferred here. This keeps the check independent of the
    mapping and subtotal rules that it is intended to verify.
    """
    if tolerance_pj < 0:
        raise ValueError("tolerance_pj must be non-negative")

    required_reference = [*CONSERVATION_KEY_COLUMNS, "reference_total"]
    required_resolved = [*CONSERVATION_KEY_COLUMNS, "resolved_total"]
    _require_columns(reference_rows, required_reference, "reference_rows")
    _require_columns(resolved_rows, required_resolved, "resolved_rows")

    reference = _aggregate_side(
        rows=reference_rows,
        value_column="reference_total",
    )
    resolved = _aggregate_side(
        rows=resolved_rows,
        value_column="resolved_total",
    )
    diagnostics = reference.merge(
        resolved,
        on=list(CONSERVATION_KEY_COLUMNS),
        how="outer",
        indicator=True,
    )
    diagnostics["reference_total"] = diagnostics["reference_total"].fillna(0.0)
    diagnostics["resolved_total"] = diagnostics["resolved_total"].fillna(0.0)
    diagnostics["difference"] = (
        diagnostics["resolved_total"] - diagnostics["reference_total"]
    )
    diagnostics["absolute_difference"] = diagnostics["difference"].abs()
    diagnostics["status"] = "match"
    diagnostics.loc[diagnostics["_merge"].eq("left_only"), "status"] = "missing_resolved"
    diagnostics.loc[diagnostics["_merge"].eq("right_only"), "status"] = "unexpected_resolved"
    value_mismatch = (
        diagnostics["_merge"].eq("both")
        & diagnostics["absolute_difference"].gt(float(tolerance_pj))
    )
    diagnostics.loc[value_mismatch, "status"] = "value_mismatch"
    diagnostics["is_mismatch"] = diagnostics["status"].ne("match")
    diagnostics["tolerance_pj"] = float(tolerance_pj)
    diagnostics = diagnostics.drop(columns="_merge")
    return diagnostics.sort_values(list(CONSERVATION_KEY_COLUMNS)).reset_index(drop=True)


def write_balance_demand_conservation_diagnostics(
    diagnostics: pd.DataFrame,
    output_path: Path | str,
) -> Path:
    """Write the diagnostic table to CSV and return the resolved path."""
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics.to_csv(path, index=False)
    return path


def _require_columns(rows: pd.DataFrame, columns: list[str], frame_name: str) -> None:
    missing = [column for column in columns if column not in rows.columns]
    if missing:
        raise KeyError(f"{frame_name} is missing required columns: {missing}")


def _aggregate_side(rows: pd.DataFrame, value_column: str) -> pd.DataFrame:
    work = rows[[*CONSERVATION_KEY_COLUMNS, value_column]].copy()
    for column in CONSERVATION_KEY_COLUMNS[:-1]:
        work[column] = work[column].fillna("").astype(str).str.strip()
    work["year"] = pd.to_numeric(work["year"], errors="raise").astype(int)
    work[value_column] = pd.to_numeric(work[value_column], errors="raise")
    return (
        work.groupby(list(CONSERVATION_KEY_COLUMNS), as_index=False, dropna=False)[value_column]
        .sum(min_count=1)
    )


#%%
