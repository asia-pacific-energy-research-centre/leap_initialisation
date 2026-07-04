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

TOTAL_DEMAND_CONTEXT = "Demand rows included in conservation scope (see lineage scope audit)"

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
    return_scope_audit: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
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

    scope_audit = _build_raw_source_scope_audit(
        esto=esto,
        ninth=ninth,
        scenarios=scenarios,
        base_year=base_year,
        final_year=final_year,
        exclude_own_use_td_losses=exclude_own_use_td_losses,
        excluded_sectors=excluded_sectors,
    )

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
    result = source.rename(columns={"value": "reference_total"})[
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
    return (result, scope_audit) if return_scope_audit else result


def prepare_reconciliation_sector_demand_totals(
    sector_demand: pd.DataFrame,
    excluded_sectors: list[str] | None,
    collapse_products: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the same sector exclusions to LEAP rows and retain branch evidence."""
    required = [
        "economy", "scenario", "sheet", "esto_product", "esto_flow",
        "year", "demand_value",
    ]
    _require_columns(sector_demand, required, "sector_demand")
    from codebase.aggregated_demand_workflow import _esto_flow_is_excluded

    audit = sector_demand[required].copy()
    excluded = {str(value).strip() for value in (excluded_sectors or []) if str(value).strip()}
    audit["included"] = ~audit["esto_flow"].map(
        lambda flow: _esto_flow_is_excluded(flow, excluded)
    )
    audit["exclusion_reason"] = ""
    audit.loc[~audit["included"], "exclusion_reason"] = "configured_detailed_sector_exclusion"
    audit = audit.rename(
        columns={
            "sheet": "leap_branch",
            "demand_value": "branch_contribution_value",
        }
    )

    included = audit[audit["included"]].rename(
        columns={"branch_contribution_value": "demand_value"}
    )
    totals = prepare_reconciliation_demand_totals(
        included,
        collapse_products=collapse_products,
    )
    return totals, audit.reset_index(drop=True)


def build_balance_demand_conservation_breakdown(
    reference_rows: pd.DataFrame,
    expected_mapped_rows: pd.DataFrame,
    resolved_rows: pd.DataFrame,
    expected_provenance: pd.DataFrame | None = None,
    resolved_provenance: pd.DataFrame | None = None,
    source_scope_audit: pd.DataFrame | None = None,
    resolved_scope_audit: pd.DataFrame | None = None,
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
    product_bridge = _merge_provenance_summary(
        product_bridge, expected_provenance, prefix="expected"
    )
    product_bridge = _merge_provenance_summary(
        product_bridge, resolved_provenance, prefix="actual"
    )
    product_bridge = _merge_scope_summary(
        product_bridge,
        source_scope_audit=source_scope_audit,
        resolved_scope_audit=resolved_scope_audit,
    )

    provenance_columns = [
        "expected_source_system", "expected_source_fuels",
        "expected_source_flows",
        "expected_allocation_methods", "expected_allocation_share_min",
        "expected_allocation_share_max", "expected_value_quality",
        "actual_source_system", "actual_source_fuels",
        "actual_source_flows",
        "actual_allocation_methods", "actual_allocation_share_min",
        "actual_allocation_share_max", "actual_value_quality",
        "excluded_source_flows", "included_leap_branches",
        "excluded_leap_branches", "included_leap_branch_contributions",
        "excluded_leap_branch_contributions",
    ]
    for column in provenance_columns:
        if column not in mapping_bridge:
            mapping_bridge[column] = pd.NA

    columns = [
        *BREAKDOWN_KEY_COLUMNS,
        "breakdown_stage",
        "component",
        "original_source_value",
        "expected_mapped_value",
        "actual_resolved_value",
        "difference",
        *provenance_columns,
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
    expected_provenance: pd.DataFrame | None = None,
    resolved_provenance: pd.DataFrame | None = None,
    source_scope_audit: pd.DataFrame | None = None,
    resolved_scope_audit: pd.DataFrame | None = None,
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
    expected = _merge_provenance_summary(expected, expected_provenance, prefix="expected")

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
    actual = _merge_provenance_summary(actual, resolved_provenance, prefix="actual")

    columns = [
        "lineage_stage", "row_id", "linked_source_row_id", "source_system",
        "economy", "scenario", "year", "source_sector_or_flow",
        "source_fuel_or_product", "esto_product", "value",
        "value_classification", "mapping_status", "allocation_share",
        "source_fuels", "allocation_methods", "allocation_share_min",
        "allocation_share_max", "allocation_quality",
    ]
    source["source_fuels"] = source["source_fuel_or_product"]
    source["allocation_methods"] = "not_yet_mapped"
    source["allocation_share_min"] = pd.NA
    source["allocation_share_max"] = pd.NA
    source["allocation_quality"] = "source_observation"
    for frame, prefix in [(expected, "expected"), (actual, "actual")]:
        frame["source_fuels"] = frame.get(f"{prefix}_source_fuels", "")
        frame["allocation_methods"] = frame.get(f"{prefix}_allocation_methods", "unknown")
        frame["allocation_share_min"] = frame.get(f"{prefix}_allocation_share_min", pd.NA)
        frame["allocation_share_max"] = frame.get(f"{prefix}_allocation_share_max", pd.NA)
        frame["allocation_quality"] = frame.get(f"{prefix}_value_quality", "unknown")
    parts = [source[columns], expected[columns], actual[columns]]
    if source_scope_audit is not None and not source_scope_audit.empty:
        scope = source_scope_audit.copy()
        scope["lineage_stage"] = "source_scope"
        scope["row_id"] = _deterministic_row_ids(
            scope,
            [
                "source_system", "economy", "scenario", "year",
                "source_flow_or_sector", "source_fuel_or_product", "value",
                "included", "exclusion_reason",
            ],
            "scope",
        )
        scope["linked_source_row_id"] = ""
        scope["source_sector_or_flow"] = scope["source_flow_or_sector"]
        scope["esto_product"] = ""
        scope["value_classification"] = "exact_source_scope"
        scope["mapping_status"] = scope["included"].map(
            {True: "included", False: "excluded"}
        )
        scope["allocation_share"] = pd.NA
        scope["source_fuels"] = scope["source_fuel_or_product"]
        scope["allocation_methods"] = "not_yet_mapped"
        scope["allocation_share_min"] = pd.NA
        scope["allocation_share_max"] = pd.NA
        scope["allocation_quality"] = scope["exclusion_reason"].where(
            ~scope["included"], "included"
        )
        parts.append(scope[columns])
    if resolved_scope_audit is not None and not resolved_scope_audit.empty:
        branch = resolved_scope_audit.copy()
        branch["lineage_stage"] = "actual_resolved_branch"
        branch["source_system"] = "LEAP_BALANCE"
        branch["source_sector_or_flow"] = branch["leap_branch"]
        branch["source_fuel_or_product"] = branch["esto_product"]
        branch["value"] = branch["branch_contribution_value"]
        branch["row_id"] = _deterministic_row_ids(
            branch,
            [
                "economy", "scenario", "year", "leap_branch", "esto_product",
                "branch_contribution_value", "included", "exclusion_reason",
            ],
            "branch",
        )
        branch["linked_source_row_id"] = ""
        branch["value_classification"] = "exact_branch_contribution"
        branch["mapping_status"] = branch["included"].map(
            {True: "included", False: "excluded"}
        )
        branch["allocation_share"] = pd.NA
        branch["source_fuels"] = branch["esto_product"]
        branch["allocation_methods"] = "resolved_branch"
        branch["allocation_share_min"] = pd.NA
        branch["allocation_share_max"] = pd.NA
        branch["allocation_quality"] = branch["exclusion_reason"].where(
            ~branch["included"], "included"
        )
        parts.append(branch[columns])
    return pd.concat(parts, ignore_index=True)


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


def _merge_provenance_summary(
    rows: pd.DataFrame,
    provenance: pd.DataFrame | None,
    prefix: str,
) -> pd.DataFrame:
    """Attach compact allocation evidence to product-level rows."""
    output = rows.copy()
    text_columns = {
        f"{prefix}_source_system": "unknown",
        f"{prefix}_source_fuels": "",
        f"{prefix}_source_flows": "",
        f"{prefix}_allocation_methods": "unknown",
        f"{prefix}_value_quality": "unknown",
    }
    numeric_columns = [
        f"{prefix}_allocation_share_min",
        f"{prefix}_allocation_share_max",
    ]
    if provenance is None or provenance.empty:
        for column, default in text_columns.items():
            output[column] = default
        for column in numeric_columns:
            output[column] = pd.NA
        return output

    work = provenance.copy()
    required = ["economy", "scenario", "year", "esto_product", "allocation_method"]
    _require_columns(work, required, f"{prefix}_provenance")
    for column in ["source_system", "source_fuel_or_product", "source_sector_or_flow"]:
        if column not in work:
            work[column] = ""
    if "allocation_share" not in work:
        work["allocation_share"] = pd.NA
    keys = ["economy", "scenario", "year", "esto_product"]
    work["allocation_share"] = pd.to_numeric(work["allocation_share"], errors="coerce")

    def _join(values: pd.Series) -> str:
        return "|".join(sorted({str(value).strip() for value in values if str(value).strip()}))

    summary = work.groupby(keys, as_index=False, dropna=False).agg(
        source_system=("source_system", _join),
        source_fuels=("source_fuel_or_product", _join),
        source_flows=("source_sector_or_flow", _join),
        allocation_methods=("allocation_method", _join),
        allocation_share_min=("allocation_share", "min"),
        allocation_share_max=("allocation_share", "max"),
    )
    estimated_methods = {"equal_split", "equal_split_fallback"}
    summary["value_quality"] = summary["allocation_methods"].map(
        lambda methods: (
            "estimated"
            if estimated_methods.intersection(str(methods).split("|"))
            else "allocated"
            if any(method != "direct" for method in str(methods).split("|"))
            else "exact_direct"
        )
    )
    summary = summary.rename(columns={
        column: f"{prefix}_{column}" for column in summary.columns if column not in keys
    })
    return output.merge(summary, on=keys, how="left")


def _merge_scope_summary(
    rows: pd.DataFrame,
    source_scope_audit: pd.DataFrame | None,
    resolved_scope_audit: pd.DataFrame | None,
) -> pd.DataFrame:
    """Attach explicit included/excluded source flows and LEAP branches."""
    output = rows.copy()
    base_keys = ["economy", "scenario", "year"]
    if source_scope_audit is not None and not source_scope_audit.empty:
        source = source_scope_audit.copy()
        excluded = source[
            ~source["included"].astype(bool)
            & source["exclusion_reason"].ne("subtotal")
        ]
        excluded_summary = excluded.groupby(base_keys, as_index=False).agg(
            excluded_source_flows=(
                "source_flow_or_sector",
                lambda values: "|".join(sorted({str(value).strip() for value in values if str(value).strip()})),
            )
        )
        output = output.merge(excluded_summary, on=base_keys, how="left")
    else:
        output["excluded_source_flows"] = ""

    if resolved_scope_audit is not None and not resolved_scope_audit.empty:
        branch = resolved_scope_audit.copy()
        keys = [*base_keys, "esto_product"]
        records: list[dict[str, object]] = []
        for key, group in branch.groupby(keys, dropna=False, sort=False):
            included = group[group["included"].astype(bool)]
            excluded = group[~group["included"].astype(bool)]

            def _branches(frame: pd.DataFrame) -> str:
                return "|".join(sorted({str(value).strip() for value in frame["leap_branch"] if str(value).strip()}))

            def _contributions(frame: pd.DataFrame) -> str:
                if frame.empty:
                    return ""
                totals = frame.groupby("leap_branch", dropna=False)["branch_contribution_value"].sum()
                return "|".join(
                    f"{branch_name}={float(value):.12g}"
                    for branch_name, value in sorted(totals.items(), key=lambda item: str(item[0]))
                )

            records.append(
                {
                    **dict(zip(keys, key)),
                    "included_leap_branches": _branches(included),
                    "excluded_leap_branches": _branches(excluded),
                    "included_leap_branch_contributions": _contributions(included),
                    "excluded_leap_branch_contributions": _contributions(excluded),
                }
            )
        output = output.merge(pd.DataFrame(records), on=keys, how="left")
    else:
        for column in [
            "included_leap_branches", "excluded_leap_branches",
            "included_leap_branch_contributions", "excluded_leap_branch_contributions",
        ]:
            output[column] = ""
    text_columns = [
        "excluded_source_flows", "included_leap_branches", "excluded_leap_branches",
        "included_leap_branch_contributions", "excluded_leap_branch_contributions",
    ]
    for column in text_columns:
        if column not in output:
            output[column] = ""
        output[column] = output[column].fillna("")
    return output


def _build_raw_source_scope_audit(
    esto: pd.DataFrame,
    ninth: pd.DataFrame,
    scenarios: list[str],
    base_year: int,
    final_year: int,
    exclude_own_use_td_losses: bool,
    excluded_sectors: list[str] | None,
) -> pd.DataFrame:
    """Record every relevant raw demand row and why it is included or excluded."""
    from codebase import aggregated_demand_workflow as aggregated

    excluded = {str(value).strip() for value in (excluded_sectors or []) if str(value).strip()}
    records: list[pd.DataFrame] = []

    esto_work = esto.copy()
    if not {"flows", "products", "is_subtotal", str(base_year)}.issubset(esto_work.columns):
        esto_work = pd.DataFrame(columns=["economy", "flows", "products", "is_subtotal", str(base_year)])
    esto_flows = esto_work["flows"].fillna("").astype(str).str.strip()
    esto_products = esto_work["products"].fillna("").astype(str).str.strip()
    own_use = esto_flows.str.startswith("10.01")
    td_losses = esto_flows.str.startswith("10.02")
    other_demand = esto_flows.str.startswith(("04", "05", "14", "15", "16", "17"))
    esto_work = esto_work[own_use | td_losses | other_demand].copy()
    esto_flows = esto_work["flows"].fillna("").astype(str).str.strip()
    esto_products = esto_work["products"].fillna("").astype(str).str.strip()
    esto_work["included"] = True
    esto_work["exclusion_reason"] = ""
    esto_work.loc[esto_work["is_subtotal"].astype(bool), ["included", "exclusion_reason"]] = [
        False, "subtotal"
    ]
    if exclude_own_use_td_losses:
        own_or_loss = esto_flows.str.startswith(("10.01", "10.02"))
        esto_work.loc[own_or_loss, ["included", "exclusion_reason"]] = [
            False, "handled_by_other_loss_own_use_proxy"
        ]
    else:
        td_electricity = esto_flows.str.startswith("10.02") & esto_products.str.startswith("17")
        esto_work.loc[td_electricity, ["included", "exclusion_reason"]] = [
            False, "electricity_td_loss_exclusion"
        ]
    configured = esto_flows.map(lambda flow: aggregated._esto_flow_is_excluded(flow, excluded))
    esto_work.loc[configured, ["included", "exclusion_reason"]] = [
        False, "configured_detailed_sector_exclusion"
    ]
    esto_audit = pd.DataFrame(
        {
            "source_system": "ESTO",
            "economy": esto_work["economy"],
            "scenario": "Current Accounts",
            "year": int(base_year),
            "source_flow_or_sector": esto_flows,
            "source_fuel_or_product": esto_products,
            "value": pd.to_numeric(esto_work[str(base_year)], errors="coerce").abs().fillna(0.0),
            "included": esto_work["included"].astype(bool),
            "exclusion_reason": esto_work["exclusion_reason"],
        }
    )
    esto_parts = []
    for scenario in scenarios:
        part = esto_audit.copy()
        part["scenario"] = str(scenario).strip()
        esto_parts.append(part)
    if esto_parts:
        records.append(pd.concat(esto_parts, ignore_index=True))

    required_ninth = {
        "scenarios", "sectors", "sub1sectors", "sub2sectors", "fuels",
        "subfuels", "subtotal_results",
    }
    for scenario in scenarios:
        if str(scenario).strip() == "Current Accounts":
            continue
        if not required_ninth.issubset(ninth.columns):
            continue
        csv_scenario = aggregated.SCENARIO_CSV_MAP.get(str(scenario).strip(), "reference").lower()
        work = ninth[ninth["scenarios"].astype(str).str.lower().eq(csv_scenario)].copy()
        sector_family = (
            work["sectors"].isin(aggregated.NINTH_SECTORS)
            & work["sub1sectors"].isin(aggregated.NINTH_SUB1_SECTORS)
            & work["sub2sectors"].isin(aggregated.NINTH_SUB2_SECTORS)
        )
        work = work[sector_family].copy()
        if work.empty:
            continue
        work["included"] = True
        work["exclusion_reason"] = ""
        work.loc[work["subtotal_results"].astype(bool), ["included", "exclusion_reason"]] = [
            False, "subtotal"
        ]
        if exclude_own_use_td_losses:
            own_or_loss = work["sub1sectors"].isin(
                aggregated.OWN_USE_SECTORS | aggregated.TD_LOSSES_SECTORS
            )
            work.loc[own_or_loss, ["included", "exclusion_reason"]] = [
                False, "handled_by_other_loss_own_use_proxy"
            ]
        else:
            td_electricity = (
                work["sub1sectors"].eq(aggregated.TD_LOSSES_SUB1)
                & work["fuels"].eq(aggregated.TD_LOSSES_EXCLUDE_FUEL)
            )
            work.loc[td_electricity, ["included", "exclusion_reason"]] = [
                False, "electricity_td_loss_exclusion"
            ]
        configured = work["sectors"].isin(excluded) | work["sub1sectors"].isin(excluded)
        work.loc[configured, ["included", "exclusion_reason"]] = [
            False, "configured_detailed_sector_exclusion"
        ]
        work["source_flow_or_sector"] = work.apply(
            lambda row: next(
                (
                    str(row[column]).strip()
                    for column in ["sub2sectors", "sub1sectors", "sectors"]
                    if str(row[column]).strip().lower() not in {"", "x", "nan", "none"}
                ),
                "",
            ),
            axis=1,
        )
        work["source_fuel_or_product"] = aggregated._resolve_fuel_code(
            work["fuels"], work["subfuels"]
        )
        years = [str(year) for year in range(aggregated.PROJECTION_START_YEAR, final_year + 1) if str(year) in work]
        if not years:
            continue
        long = work[
            [
                "economy", "source_flow_or_sector", "source_fuel_or_product",
                "included", "exclusion_reason", *years,
            ]
        ].melt(
            id_vars=[
                "economy", "source_flow_or_sector", "source_fuel_or_product",
                "included", "exclusion_reason",
            ],
            value_vars=years,
            var_name="year",
            value_name="value",
        )
        long["source_system"] = "NINTH"
        long["scenario"] = str(scenario).strip()
        long["year"] = pd.to_numeric(long["year"], errors="raise").astype(int)
        long["value"] = pd.to_numeric(long["value"], errors="coerce").abs().fillna(0.0)
        records.append(long)

    columns = [
        "source_system", "economy", "scenario", "year",
        "source_flow_or_sector", "source_fuel_or_product", "value",
        "included", "exclusion_reason",
    ]
    return pd.concat(records, ignore_index=True)[columns] if records else pd.DataFrame(columns=columns)


#%%
