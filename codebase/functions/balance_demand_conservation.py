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

TOTAL_DEMAND_CONTEXT = "All demand after detailed-sector exclusions"


def build_raw_demand_conservation_reference(
    economy: str,
    scenarios: list[str],
    base_year: int,
    final_year: int,
    data_path: Path | str,
    esto_data_path: Path | str,
    exclude_own_use_td_losses: bool = False,
    excluded_sectors: list[str] | None = None,
) -> pd.DataFrame:
    """Build pre-mapping total-energy demand directly from ESTO/9th rows."""
    from codebase import aggregated_demand_workflow as aggregated

    esto = aggregated._load_esto_base_csv(
        Path(esto_data_path), economy=economy, base_year=base_year
    )
    ninth = aggregated._load_demand_csv(
        Path(data_path), economy=economy, final_year=final_year
    )
    economy_label = str(economy).strip()
    if aggregated._is_aggregate_economy(economy):
        esto = esto.copy()
        ninth = ninth.copy()
        esto["economy"] = economy_label
        ninth["economy"] = economy_label

    base = aggregated._extract_base_year(
        esto,
        base_year=base_year,
        exclude_own_use_td_losses=exclude_own_use_td_losses,
        excluded_sectors=excluded_sectors,
        use_sector_branches=False,
    )
    parts: list[pd.DataFrame] = []
    for scenario in scenarios:
        scenario_label = str(scenario).strip()
        scenario_parts = [base.copy()]
        if scenario_label != "Current Accounts":
            csv_scenario = aggregated.SCENARIO_CSV_MAP.get(
                scenario_label, "reference"
            ).lower()
            scenario_parts.append(
                aggregated._extract_projection_years(
                    ninth,
                    csv_scenario=csv_scenario,
                    final_year=final_year,
                    exclude_own_use_td_losses=exclude_own_use_td_losses,
                    excluded_sectors=excluded_sectors,
                    use_sector_branches=False,
                )
            )
        scenario_rows = pd.concat(scenario_parts, ignore_index=True)
        scenario_rows["scenario"] = scenario_label
        parts.append(scenario_rows)

    if not parts:
        return pd.DataFrame(
            columns=[*CONSERVATION_KEY_COLUMNS, "reference_total"]
        )
    source = pd.concat(parts, ignore_index=True)
    source["sector_context"] = TOTAL_DEMAND_CONTEXT
    source["esto_product"] = "__all_fuels__"
    return (
        source.rename(columns={"value": "reference_total"})
        [[*CONSERVATION_KEY_COLUMNS, "reference_total"]]
        .reset_index(drop=True)
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


def prepare_aggregated_demand_reference(
    aggregated_demand: pd.DataFrame,
    sector_context: str = TOTAL_DEMAND_CONTEXT,
    collapse_products: bool = False,
) -> pd.DataFrame:
    """Normalize aggregated-demand output as the independent reference side."""
    required = ["economy", "scenario", "esto_product", "year", "demand_value"]
    _require_columns(aggregated_demand, required, "aggregated_demand")
    reference = aggregated_demand[required].copy()
    reference["sector_context"] = str(sector_context)
    if collapse_products:
        reference["esto_product"] = "__all_fuels__"
    return reference.rename(columns={"demand_value": "reference_total"})[
        [*CONSERVATION_KEY_COLUMNS, "reference_total"]
    ]


def prepare_reconciliation_demand_totals(
    aggregated_placeholder: pd.DataFrame,
    detailed_sector_demand: pd.DataFrame | None = None,
    include_detailed_sectors: bool = False,
    sector_context: str = TOTAL_DEMAND_CONTEXT,
    collapse_products: bool = False,
) -> pd.DataFrame:
    """Normalize demand rows actually consumed by reconciliation.

    Baseline seed uses the aggregated placeholder plus projection-only detailed
    sector rows, so ``include_detailed_sectors`` is True. Results update checks
    only the residual aggregated placeholder and leaves detailed LEAP sectors out
    of both sides of this comparison.
    """
    required = ["economy", "scenario", "esto_product", "year", "demand_value"]
    _require_columns(aggregated_placeholder, required, "aggregated_placeholder")
    parts = [aggregated_placeholder[required].copy()]
    if include_detailed_sectors:
        if detailed_sector_demand is None:
            raise ValueError(
                "detailed_sector_demand is required when include_detailed_sectors=True"
            )
        _require_columns(detailed_sector_demand, required, "detailed_sector_demand")
        parts.append(detailed_sector_demand[required].copy())
    resolved = pd.concat(parts, ignore_index=True)
    resolved["sector_context"] = str(sector_context)
    if collapse_products:
        resolved["esto_product"] = "__all_fuels__"
    return resolved.rename(columns={"demand_value": "resolved_total"})[
        [*CONSERVATION_KEY_COLUMNS, "resolved_total"]
    ]


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
