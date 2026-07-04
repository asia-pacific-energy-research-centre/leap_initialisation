"""Compare independent aggregated-demand references with resolved demand rows."""

#%%

from pathlib import Path
import hashlib

import pandas as pd


CONSERVATION_KEY_COLUMNS = (
    "economy",
    "scenario",
    "sector_context",
    "esto_product",
    "year",
)

TOTAL_DEMAND_CONTEXT = "All demand after detailed-sector exclusions"

BREAKDOWN_KEY_COLUMNS = (
    "economy",
    "scenario",
    "sector_context",
    "year",
)


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
    source["source_system"] = source["year"].map(
        lambda year: "ESTO" if int(year) == int(base_year) else "NINTH"
    )
    source["source_fuel_or_product"] = source["fuel_code"].astype(str)
    source["source_sector_or_flow"] = source.get(
        "sector", pd.Series("", index=source.index, dtype=str)
    ).fillna("").astype(str)
    source["source_row_id"] = _deterministic_row_ids(
        source,
        columns=[
            "source_system",
            "economy",
            "scenario",
            "source_sector_or_flow",
            "source_fuel_or_product",
            "year",
            "value",
        ],
        prefix="source",
    )
    source["value_classification"] = "exact_aggregated"
    source["sector_context"] = TOTAL_DEMAND_CONTEXT
    source["esto_product"] = "__all_fuels__"
    return source.rename(columns={"value": "reference_total"})[
        [
            *CONSERVATION_KEY_COLUMNS,
            "reference_total",
            "source_system",
            "source_row_id",
            "source_sector_or_flow",
            "source_fuel_or_product",
            "value_classification",
        ]
    ].reset_index(drop=True)


def build_balance_demand_conservation_breakdown(
    reference_rows: pd.DataFrame,
    expected_mapped_rows: pd.DataFrame,
    resolved_rows: pd.DataFrame,
) -> pd.DataFrame:
    """Explain the total gap as mapping loss plus product-level resolution gaps.

    The mapping bridge deliberately stays at all-fuels level. Raw Ninth fuel
    codes and ESTO products are different vocabularies, so forcing a product
    join would imply lineage that the current workflow has not retained.
    """
    _require_columns(reference_rows, [*CONSERVATION_KEY_COLUMNS, "reference_total"], "reference_rows")
    _require_columns(
        expected_mapped_rows,
        ["economy", "scenario", "esto_product", "year", "demand_value"],
        "expected_mapped_rows",
    )
    _require_columns(resolved_rows, [*CONSERVATION_KEY_COLUMNS, "resolved_total"], "resolved_rows")

    reference = _aggregate_side(reference_rows, "reference_total")
    reference = reference.groupby(list(BREAKDOWN_KEY_COLUMNS), as_index=False)["reference_total"].sum()

    expected = expected_mapped_rows[
        ["economy", "scenario", "esto_product", "year", "demand_value"]
    ].copy()
    expected["sector_context"] = TOTAL_DEMAND_CONTEXT
    expected = _aggregate_side(
        expected.rename(columns={"demand_value": "expected_mapped_value"}),
        "expected_mapped_value",
    )
    resolved = _aggregate_side(resolved_rows, "resolved_total")

    expected_totals = expected.groupby(list(BREAKDOWN_KEY_COLUMNS), as_index=False)[
        "expected_mapped_value"
    ].sum()
    mapping_bridge = reference.merge(expected_totals, on=list(BREAKDOWN_KEY_COLUMNS), how="outer")
    mapping_bridge[["reference_total", "expected_mapped_value"]] = mapping_bridge[
        ["reference_total", "expected_mapped_value"]
    ].fillna(0.0)
    mapping_bridge["breakdown_stage"] = "source_to_expected_mapping"
    mapping_bridge["component"] = "__all_fuels__"
    mapping_bridge["original_source_value"] = mapping_bridge["reference_total"]
    mapping_bridge["actual_resolved_value"] = pd.NA
    mapping_bridge["difference"] = (
        mapping_bridge["expected_mapped_value"] - mapping_bridge["original_source_value"]
    )

    product_bridge = expected.merge(
        resolved,
        on=list(CONSERVATION_KEY_COLUMNS),
        how="outer",
    )
    product_bridge[["expected_mapped_value", "resolved_total"]] = product_bridge[
        ["expected_mapped_value", "resolved_total"]
    ].fillna(0.0)
    product_bridge["breakdown_stage"] = "expected_mapping_to_actual_resolved"
    product_bridge["component"] = product_bridge["esto_product"]
    product_bridge["original_source_value"] = pd.NA
    product_bridge["actual_resolved_value"] = product_bridge["resolved_total"]
    product_bridge["difference"] = (
        product_bridge["actual_resolved_value"] - product_bridge["expected_mapped_value"]
    )

    columns = [
        *BREAKDOWN_KEY_COLUMNS,
        "breakdown_stage",
        "component",
        "original_source_value",
        "expected_mapped_value",
        "actual_resolved_value",
        "difference",
    ]
    return (
        pd.concat([mapping_bridge[columns], product_bridge[columns]], ignore_index=True)
        .sort_values([*BREAKDOWN_KEY_COLUMNS, "breakdown_stage", "component"])
        .reset_index(drop=True)
    )


def build_balance_demand_conservation_lineage(
    reference_rows: pd.DataFrame,
    expected_mapped_rows: pd.DataFrame,
    resolved_rows: pd.DataFrame,
) -> pd.DataFrame:
    """Return honest stage rows without inventing unavailable cross-stage links."""
    source_columns = [
        "economy", "scenario", "year", "source_system", "source_row_id",
        "source_sector_or_flow", "source_fuel_or_product", "reference_total",
        "value_classification",
    ]
    _require_columns(reference_rows, source_columns, "reference_rows")

    source = reference_rows[source_columns].copy().rename(
        columns={"reference_total": "value", "source_row_id": "row_id"}
    )
    source["lineage_stage"] = "original_source"
    source["esto_product"] = ""
    source["mapping_status"] = "not_yet_mapped"
    source["allocation_share"] = pd.NA
    source["linked_source_row_id"] = ""

    expected = expected_mapped_rows[
        ["economy", "scenario", "year", "esto_product", "demand_value"]
    ].copy().rename(columns={"demand_value": "value"})
    expected["lineage_stage"] = "expected_mapped"
    expected["source_system"] = "ESTO_OR_NINTH"
    expected["source_sector_or_flow"] = ""
    expected["source_fuel_or_product"] = ""
    expected["value_classification"] = "mapped_aggregate_may_include_estimates"
    expected["mapping_status"] = "mapped_but_source_link_not_retained"
    expected["allocation_share"] = pd.NA
    expected["linked_source_row_id"] = ""
    expected["row_id"] = _deterministic_row_ids(
        expected,
        ["economy", "scenario", "year", "esto_product", "value"],
        "expected",
    )

    actual = resolved_rows[
        ["economy", "scenario", "year", "esto_product", "resolved_total"]
    ].copy().rename(columns={"resolved_total": "value"})
    actual["lineage_stage"] = "actual_resolved"
    actual["source_system"] = "LEAP_BALANCE"
    actual["source_sector_or_flow"] = ""
    actual["source_fuel_or_product"] = ""
    actual["value_classification"] = "exact_aggregated"
    actual["mapping_status"] = "resolved_but_source_link_not_retained"
    actual["allocation_share"] = pd.NA
    actual["linked_source_row_id"] = ""
    actual["row_id"] = _deterministic_row_ids(
        actual,
        ["economy", "scenario", "year", "esto_product", "value"],
        "resolved",
    )

    columns = [
        "lineage_stage", "row_id", "linked_source_row_id", "source_system",
        "economy", "scenario", "year", "source_sector_or_flow",
        "source_fuel_or_product", "esto_product", "value",
        "value_classification", "mapping_status", "allocation_share",
    ]
    return pd.concat([source[columns], expected[columns], actual[columns]], ignore_index=True)


def write_balance_demand_conservation_table(rows: pd.DataFrame, output_path: Path | str) -> Path:
    """Write one conservation support table and return its resolved path."""
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(path, index=False)
    return path


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


def _deterministic_row_ids(
    rows: pd.DataFrame,
    columns: list[str],
    prefix: str,
) -> pd.Series:
    """Build repeatable IDs, including a counter for duplicate natural keys."""
    keys = rows[columns].fillna("").astype(str).agg("|".join, axis=1)
    occurrence = keys.groupby(keys, sort=False).cumcount().astype(str)
    return (keys + "|" + occurrence).map(
        lambda value: f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"
    )


#%%
