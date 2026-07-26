from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from codebase.utilities.master_config import config_table_exists, read_config_table

DEFAULT_SCENARIO = "reference"
COAL_PARENT_ESTO_FLOW = "09.08 Coal transformation"
COAL_CHILD_ESTO_FLOWS = (
    "09.08.01 Coke ovens",
    "09.08.02 Blast furnaces",
    "09.08.03 Patent fuel plants",
    "09.08.04 BKB/PB plants",
    "09.08.05 Liquefaction (coal to oil)",
)
GAS_PARENT_NINTH_SECTOR = "09_06_gas_processing_plants"
GAS_PARENT_ESTO_FLOW = "09.06 Gas processing plants"
GAS_CHILD_NINTH_SECTORS = (
    "09_06_01_gas_works_plants",
    "09_06_02_liquefaction_regasification_plants",
    "09_06_03_natural_gas_blending_plants",
    "09_06_04_gastoliquids_plants",
)
GAS_CHILD_ESTO_FLOWS = (
    "09.06.01 Gas works plants",
    "09.06.02 Liquefaction/regasification plants",
    "09.06.03 Natural gas blending plants",
    "09.06.04 Gas-to-liquids plants",
)
NINTH_SECTOR_COLS = [
    "sub4sectors",
    "sub3sectors",
    "sub2sectors",
    "sub1sectors",
    "sectors",
]
NINTH_FUEL_COLS = ["subfuels", "fuels"]


def normalize_economy_key(value: str | None) -> str:
    """Return a canonical economy key for cross-dataset joins."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    return text.replace("_", "").upper()


def _clean_label_series(series: pd.Series) -> pd.Series:
    cleaned = series.fillna("").astype(str).str.strip()
    return cleaned.mask(cleaned.str.lower() == "x", pd.NA)


def add_ninth_pair_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add most-specific sector/fuel columns for 9th data."""
    working = df.copy()
    sector_cols = [col for col in NINTH_SECTOR_COLS if col in working.columns]
    fuel_cols = [col for col in NINTH_FUEL_COLS if col in working.columns]
    if sector_cols:
        sector_values = pd.DataFrame(
            {col: _clean_label_series(working[col]) for col in sector_cols}
        )
        working["ninth_sector"] = sector_values.bfill(axis=1).iloc[:, 0].fillna("")
    else:
        working["ninth_sector"] = ""
    if fuel_cols:
        fuel_values = pd.DataFrame(
            {col: _clean_label_series(working[col]) for col in fuel_cols}
        )
        working["ninth_fuel"] = fuel_values.bfill(axis=1).iloc[:, 0].fillna("")
    else:
        working["ninth_fuel"] = ""
    return working


def filter_ninth_projection_rows(
    df: pd.DataFrame, scenario: str = DEFAULT_SCENARIO
) -> pd.DataFrame:
    """Filter 9th data to the reference scenario and non-subtotal rows."""
    working = df.copy()
    if scenario and "scenarios" in working.columns:
        scenario_key = str(scenario).strip().lower()
        working = working[
            working["scenarios"].astype(str).str.strip().str.lower() == scenario_key
        ]
    if "subtotal_results" in working.columns:
        flag = (
            working["subtotal_results"]
            .fillna(False)
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"1", "true", "yes", "y", "t"})
        )
        working = working[~flag]
    return working


def build_ninth_projection_series(
    ninth_df: pd.DataFrame, projection_years: Sequence[int]
) -> pd.DataFrame:
    """Aggregate projected-year values by economy + 9th pair."""
    if not projection_years or ninth_df.empty:
        return pd.DataFrame()
    year_cols = [year for year in projection_years if year in ninth_df.columns]
    if not year_cols:
        return pd.DataFrame()
    working = ninth_df.copy()
    working = working[(working["ninth_sector"] != "") & (working["ninth_fuel"] != "")]
    if working.empty:
        return pd.DataFrame()
    for year in year_cols:
        working[year] = pd.to_numeric(working[year], errors="coerce").fillna(0.0)
    grouped = (
        working.groupby(["economy_key", "ninth_sector", "ninth_fuel"], dropna=False)[year_cols]
        .sum()
        .reset_index()
    )
    return grouped


def build_esto_base_year_values(
    esto_df: pd.DataFrame, base_year: int
) -> pd.DataFrame:
    """Return base-year values per economy/flow/product."""
    if esto_df.empty:
        return pd.DataFrame()
    year_col = base_year if base_year in esto_df.columns else str(base_year)
    if year_col not in esto_df.columns:
        return pd.DataFrame()
    working = esto_df.copy()
    working["economy_key"] = working["economy"].apply(normalize_economy_key)
    working["esto_flow"] = working["flows"].astype(str).str.strip()
    working["esto_product"] = working["products"].astype(str).str.strip()
    working[year_col] = pd.to_numeric(working[year_col], errors="coerce").fillna(0.0)
    grouped = (
        working.groupby(["economy_key", "esto_flow", "esto_product"], dropna=False)[
            year_col
        ]
        .sum()
        .reset_index()
        .rename(columns={year_col: "base_value"})
    )
    grouped["base_value_abs"] = grouped["base_value"].abs()
    return grouped


def build_economy_specific_child_flow_profiles(
    esto_df: pd.DataFrame,
    base_year: int,
    parent_flow: str = COAL_PARENT_ESTO_FLOW,
    child_flows: Sequence[str] = COAL_CHILD_ESTO_FLOWS,
) -> pd.DataFrame:
    """Build current-run child-flow profiles for an aggregate ESTO flow.

    Profiles are derived from the ESTO dataframe supplied to the current run;
    no ratios are persisted in the mapping workbook.  A profile row represents
    one economy/product/child-flow cell and retains its signed base-year value
    so later allocation can distinguish simultaneous inputs and outputs.

    The parent flow is accepted as an explicit argument to keep this helper
    reusable, but is currently used for identification/provenance only.  The
    returned rows contain child-flow observations that can replace parent-flow
    mapping targets during an economy-specific projection allocation.
    """
    if esto_df is None or esto_df.empty:
        return pd.DataFrame(
            columns=[
                "economy_key",
                "esto_product",
                "child_flow",
                "base_value",
                "base_value_abs",
                "profile_parent_flow",
            ]
        )
    year_col = base_year if base_year in esto_df.columns else str(base_year)
    required = {"economy", "flows", "products", year_col}
    missing = required.difference(esto_df.columns)
    if missing:
        raise KeyError(
            "ESTO child-flow profile requires columns: "
            + ", ".join(sorted(missing))
        )

    working = esto_df.copy()
    if "is_subtotal" in working.columns:
        subtotal = (
            working["is_subtotal"]
            .fillna(False)
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"1", "true", "yes", "y", "t"})
        )
        working = working.loc[~subtotal].copy()
    working = working[working["flows"].isin(child_flows)].copy()
    if working.empty:
        return pd.DataFrame(
            columns=[
                "economy_key",
                "esto_product",
                "child_flow",
                "base_value",
                "base_value_abs",
                "profile_parent_flow",
            ]
        )

    working["economy_key"] = working["economy"].apply(normalize_economy_key)
    working["esto_product"] = working["products"].astype(str).str.strip()
    working["child_flow"] = working["flows"].astype(str).str.strip()
    working[year_col] = pd.to_numeric(working[year_col], errors="coerce").fillna(0.0)
    profile = (
        working.groupby(
            ["economy_key", "esto_product", "child_flow"],
            dropna=False,
        )[year_col]
        .sum()
        .reset_index()
        .rename(columns={year_col: "base_value"})
    )
    profile["base_value_abs"] = profile["base_value"].abs()
    profile["profile_parent_flow"] = parent_flow
    return profile


def compute_esto_base_year_shares(
    base_values: pd.DataFrame,
    economy_key: str,
    esto_flow: str,
    esto_products: Sequence[str],
) -> dict[str, float]:
    """Return absolute-share splits for a flow/product set in a given economy."""
    if not esto_products:
        return {}
    if base_values is None or base_values.empty:
        return {product: 1.0 / len(esto_products) for product in esto_products}
    subset = base_values[
        (base_values["economy_key"] == economy_key)
        & (base_values["esto_flow"] == esto_flow)
        & (base_values["esto_product"].isin(esto_products))
    ]
    grouped = (
        subset.groupby("esto_product", dropna=False)["base_value_abs"]
        .sum()
        .reindex(esto_products)
        .fillna(0.0)
    )
    total = float(grouped.sum())
    if total <= 0:
        return {product: 1.0 / len(esto_products) for product in esto_products}
    return {product: float(grouped.loc[product]) / total for product in esto_products}


def _build_conservation_diagnostics(
    source_by_pair: pd.DataFrame,
    allocated_rows: pd.DataFrame,
    year_cols: Sequence[int],
    tolerance: float = 1e-6,
) -> pd.DataFrame:
    """Return diagnostics proving allocation conserves source totals by 9th pair.

    For each (economy_key, ninth_sector, ninth_fuel), this compares:
    - source values: the original 9th series
    - allocated values: sum across mapped ESTO rows
    """
    if source_by_pair.empty or allocated_rows.empty or not year_cols:
        return pd.DataFrame()
    key_cols = ["economy_key", "ninth_sector", "ninth_fuel"]
    source_by_pair = source_by_pair[key_cols + list(year_cols)].copy()
    allocated_by_pair = (
        allocated_rows.groupby(key_cols, dropna=False)[list(year_cols)]
        .sum()
        .reset_index()
    )
    source_indexed = source_by_pair.set_index(key_cols)
    allocated_indexed = allocated_by_pair.set_index(key_cols)
    diff = allocated_indexed[list(year_cols)] - source_indexed[list(year_cols)]
    abs_diff = diff.abs()
    max_abs_diff = abs_diff.max(axis=1)
    mismatch_mask = max_abs_diff > tolerance
    if not mismatch_mask.any():
        return pd.DataFrame()

    mismatch_diff = diff[mismatch_mask]
    mismatch_abs = abs_diff[mismatch_mask]
    worst_years = mismatch_abs.idxmax(axis=1)
    rows = []
    for key, row in mismatch_diff.iterrows():
        worst_year = int(worst_years.loc[key])
        source_value = float(source_indexed.loc[key, worst_year])
        allocated_value = float(allocated_indexed.loc[key, worst_year])
        error_value = float(row[worst_year])
        rows.append(
            {
                "economy_key": key[0],
                "ninth_sector": key[1],
                "ninth_fuel": key[2],
                "diagnostic_type": "conservation_mismatch",
                "worst_year": worst_year,
                "source_value_worst_year": source_value,
                "allocated_value_worst_year": allocated_value,
                "allocation_error_worst_year": error_value,
                "max_abs_allocation_error": float(mismatch_abs.loc[key].max()),
                "sum_abs_allocation_error": float(mismatch_abs.loc[key].sum()),
                "year_count_above_tolerance": int((mismatch_abs.loc[key] > tolerance).sum()),
            }
        )
    return pd.DataFrame(rows)


def _resolve_sign_stable_flow_set(
    mapping: pd.DataFrame,
    sign_stable_flows: Iterable[str] | str | None,
) -> set[str]:
    """Return normalized sign-stable flow names from iterable or mode string.

    Accepted string modes:
    - "all" / "*": apply sign-stable routing to every mapped ESTO flow.
    - "off" / "none" / "": disable sign-stable routing.
    - Any other string: treated as a single flow name.
    """
    if sign_stable_flows is None:
        return set()
    if isinstance(sign_stable_flows, str):
        mode = sign_stable_flows.strip().lower()
        if mode in {"", "off", "none", "false"}:
            return set()
        if mode in {"all", "*"}:
            return {
                str(flow).strip()
                for flow in mapping["esto_flow"].dropna().astype(str)
                if str(flow).strip()
                and str(flow).strip().lower() not in {"nan", "none"}
            }
        return {sign_stable_flows.strip()}
    return {
        str(flow).strip()
        for flow in sign_stable_flows
        if str(flow).strip() and str(flow).strip().lower() not in {"nan", "none"}
    }


def _disaggregate_parent_flow_allocations(
    allocated_rows: pd.DataFrame,
    child_flow_profiles: pd.DataFrame | None,
    year_cols: Sequence[int],
    parent_flow: str = COAL_PARENT_ESTO_FLOW,
    child_flows: Sequence[str] = COAL_CHILD_ESTO_FLOWS,
    tolerance: float = 1e-9,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split projected parent-flow rows into signed, economy-specific children.

    When the signed ESTO child profile has a nonzero net total, the complete
    signed child vector is scaled by the projected parent-product value.  This
    preserves simultaneous inputs and outputs for the same product and keeps
    the child sum exactly equal to the parent projection.  If the historical
    child profile nets to zero, the future split is underdetermined; a
    sign-stable gross fallback is used and a diagnostic row is returned.
    """
    if (
        allocated_rows.empty
        or child_flow_profiles is None
        or child_flow_profiles.empty
        or not year_cols
    ):
        return allocated_rows, pd.DataFrame()

    required = {"economy_key", "esto_product", "child_flow", "base_value", "base_value_abs"}
    missing = required.difference(child_flow_profiles.columns)
    if missing:
        raise KeyError(
            "Coal child-flow profiles require columns: "
            + ", ".join(sorted(missing))
        )

    profile = child_flow_profiles[
        child_flow_profiles["child_flow"].isin(child_flows)
    ].copy()
    if profile.empty:
        return allocated_rows, pd.DataFrame()

    parent_mask = allocated_rows["esto_flow"].eq(parent_flow)
    parent_rows = allocated_rows.loc[parent_mask].copy()
    if parent_rows.empty:
        return allocated_rows, pd.DataFrame()
    retained = allocated_rows.loc[~parent_mask].copy()
    child_rows: list[dict] = []
    diagnostics: list[dict] = []

    for _, parent_row in parent_rows.iterrows():
        economy_key = str(parent_row["economy_key"])
        product = str(parent_row["esto_product"]).strip()
        matching = profile[
            profile["economy_key"].astype(str).eq(economy_key)
            & profile["esto_product"].astype(str).eq(product)
        ].copy()
        if matching.empty:
            retained_parent = parent_row.to_dict()
            retained_parent["coal_allocation_method"] = "parent_flow_retained"
            child_rows.append(retained_parent)
            diagnostics.append(
                {
                    "economy_key": economy_key,
                    "esto_product": product,
                    "parent_flow": parent_flow,
                    "diagnostic_type": "coal_child_profile_missing",
                    "allocation_method": "parent_flow_retained",
                }
            )
            continue

        net_profile = float(matching["base_value"].sum())
        if abs(net_profile) > tolerance:
            for _, profile_row in matching.iterrows():
                child = parent_row.to_dict()
                child["esto_flow"] = profile_row["child_flow"]
                child["coal_allocation_method"] = "signed_profile_scale"
                scale = float(profile_row["base_value"]) / net_profile
                for year in year_cols:
                    child[year] = float(parent_row[year]) * scale
                child_rows.append(child)
            continue

        positive = matching["base_value"].gt(tolerance)
        negative = matching["base_value"].lt(-tolerance)
        positive_total = float(matching.loc[positive, "base_value_abs"].sum())
        negative_total = float(matching.loc[negative, "base_value_abs"].sum())
        absolute_total = float(matching["base_value_abs"].sum())
        for _, profile_row in matching.iterrows():
            child = parent_row.to_dict()
            child["esto_flow"] = profile_row["child_flow"]
            child["coal_allocation_method"] = "sign_stable_gross_fallback"
            child_base = float(profile_row["base_value"])
            for year in year_cols:
                source_value = float(parent_row[year])
                if source_value > tolerance and positive_total > tolerance:
                    share = (
                        float(profile_row["base_value_abs"]) / positive_total
                        if child_base > tolerance
                        else 0.0
                    )
                elif source_value < -tolerance and negative_total > tolerance:
                    share = (
                        float(profile_row["base_value_abs"]) / negative_total
                        if child_base < -tolerance
                        else 0.0
                    )
                elif absolute_total > tolerance:
                    share = float(profile_row["base_value_abs"]) / absolute_total
                else:
                    share = 1.0 / len(matching)
                child[year] = source_value * share
            child_rows.append(child)
        diagnostics.append(
            {
                "economy_key": economy_key,
                "esto_product": product,
                "parent_flow": parent_flow,
                "diagnostic_type": "coal_child_profile_net_zero",
                "allocation_method": "sign_stable_gross_fallback",
                "profile_net_value": net_profile,
                "profile_abs_total": absolute_total,
            }
        )

    result = pd.concat([retained, pd.DataFrame(child_rows)], ignore_index=True, sort=False)
    return result, pd.DataFrame(diagnostics)


def _allocate_gas_parent_residuals(
    allocated_rows: pd.DataFrame,
    child_flow_profiles: pd.DataFrame | None,
    year_cols: Sequence[int],
    tolerance: float = 1e-9,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Allocate a gas-parent residual only to missing base-year-active children."""
    if allocated_rows.empty or child_flow_profiles is None or child_flow_profiles.empty:
        return allocated_rows, pd.DataFrame()

    profile = child_flow_profiles[
        child_flow_profiles["child_flow"].isin(GAS_CHILD_ESTO_FLOWS)
    ].copy()
    parent_mask = (
        allocated_rows["esto_flow"].eq(GAS_PARENT_ESTO_FLOW)
        & ~allocated_rows["economy_key"].astype(str).eq("00APEC")
    )
    if profile.empty or not parent_mask.any():
        return allocated_rows, pd.DataFrame()

    retained = allocated_rows.loc[~parent_mask].copy()
    generated_rows: list[dict] = []
    diagnostics: list[dict] = []
    for _, parent_row in allocated_rows.loc[parent_mask].iterrows():
        economy_key = str(parent_row["economy_key"])
        product = str(parent_row["esto_product"]).strip()
        active_children = profile[
            profile["economy_key"].astype(str).eq(economy_key)
            & profile["esto_product"].astype(str).eq(product)
            & profile["base_value_abs"].gt(tolerance)
        ].copy()
        direct_rows = retained[
            retained["economy_key"].astype(str).eq(economy_key)
            & retained["esto_product"].astype(str).eq(product)
            & retained["ninth_sector"].isin(GAS_CHILD_NINTH_SECTORS)
            & retained["esto_flow"].isin(GAS_CHILD_ESTO_FLOWS)
        ]
        direct_by_flow = direct_rows.groupby("esto_flow", dropna=False)[list(year_cols)].sum()
        direct_flows = {
            flow for flow, values in direct_by_flow.iterrows()
            if values.abs().gt(tolerance).any()
        }
        residual = {
            year: float(parent_row[year]) - float(direct_by_flow[year].sum())
            if year in direct_by_flow.columns else float(parent_row[year])
            for year in year_cols
        }
        if not any(abs(value) > tolerance for value in residual.values()):
            continue

        missing_children = active_children[
            ~active_children["child_flow"].isin(direct_flows)
        ].copy()
        if missing_children.empty:
            raise ValueError(
                "Gas processing parent residual has no base-year-active missing child: "
                f"economy={economy_key}, product={product}, "
                f"direct_children={sorted(direct_flows)}."
            )
        profile_total = float(missing_children["base_value"].sum())
        if abs(profile_total) <= tolerance:
            raise ValueError(
                "Gas processing residual cannot be allocated because the base-year-active "
                f"missing child profile nets to zero: economy={economy_key}, product={product}."
            )
        for _, profile_row in missing_children.iterrows():
            child = parent_row.to_dict()
            child["esto_flow"] = profile_row["child_flow"]
            child["gas_allocation_method"] = "parent_residual_signed_profile_scale"
            scale = float(profile_row["base_value"]) / profile_total
            for year in year_cols:
                child[year] = residual[year] * scale
            generated_rows.append(child)
        diagnostics.append(
            {
                "economy_key": economy_key,
                "esto_product": product,
                "parent_flow": GAS_PARENT_ESTO_FLOW,
                "diagnostic_type": "gas_parent_residual_allocated",
                "allocation_method": "parent_residual_signed_profile_scale",
                "direct_children": "; ".join(sorted(direct_flows)),
                "missing_children": "; ".join(missing_children["child_flow"].astype(str)),
            }
        )
    return pd.concat([retained, pd.DataFrame(generated_rows)], ignore_index=True, sort=False), pd.DataFrame(diagnostics)


def allocate_ninth_projection_to_esto(
    mapping_df: pd.DataFrame,
    ninth_series: pd.DataFrame,
    base_values: pd.DataFrame,
    projection_years: Sequence[int],
    sign_stable_flows: Iterable[str] | str | None = None,
    strict_conservation: bool = False,
    return_allocation_provenance: bool = False,
    child_flow_profiles: pd.DataFrame | None = None,
    gas_child_flow_profiles: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame] | tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Allocate 9th projections to ESTO pairs using base-year share rules.

    How allocation works
    --------------------
    1. Build a source series by (economy_key, ninth_sector, ninth_fuel).
    2. Use the mapping table to fan each source series out to one or more
       ESTO (flow, product) rows.
    3. Compute shares from base-year ESTO magnitudes.

    Coal transformation exception
    ------------------------------
    9th projection rows for ``09_08_coal_transformation`` can be aggregate
    while ESTO contains detailed child flows.  Parent-flow products are first
    allocated using the economy's current ESTO data, then their full signed
    child-flow vectors are scaled.  This preserves simultaneous child inputs
    and outputs.  A net-zero historical child vector uses an explicit
    sign-stable gross fallback and emits a diagnostic; APEC shares are never
    used for this coal reconstruction.

    Legacy mode (default)
    ---------------------
    - Share is based on absolute base-year values.
    - Positive source values can be distributed into base-year-negative rows.
    - This preserves totals but can flip detailed row signs.

    Optional sign-stable mode (`sign_stable_flows`)
    ----------------------------------------------
    - Accepts a flow list or a mode string ("all", "off"/"none").
    - Triggered by ESTO flows listed in `sign_stable_flows`.
    - Once triggered for any mapped row, it is applied to the whole
      (economy_key, ninth_sector, ninth_fuel) source pair to preserve totals.
    - Positive source years are split only across base-year-positive targets.
    - Negative source years are split only across base-year-negative targets.
    - If no same-sign targets exist for a given sign, it falls back to legacy
      shares for that sign/year to avoid dropping totals.

    Concrete example (08_JPN, coal products split)
    ----------------------------------------------
    Source pair: (09_08_coal_transformation, 02_coal_products)
    Source 2023 value: +877.277
    Base-year target signs include:
    - 09.08.01 Coke ovens | 02.01 Coke oven coke = +833.544
    - 09.08.02 Blast furnaces | 02.01 Coke oven coke = -693.349

    Legacy split allocates to both rows by abs-share:
    - Coke ovens coke: 335.251
    - Blast furnaces coke: 278.865

    Sign-stable split (positive source) allocates only to positive-sign targets:
    - Coke ovens coke increases to 491.481
    - Blast furnaces coke becomes 0.0
    - Total remains +877.277

    Tradeoff
    --------
    Sign-stable mode reduces sign-flip artifacts from aggregated mappings but may
    suppress legitimate sign transitions in future years. Keep it scoped to flows
    known to be affected by aggregation artifacts.
    """
    if mapping_df.empty or ninth_series.empty or not projection_years:
        empty_result = (pd.DataFrame(), pd.DataFrame())
        return (*empty_result, pd.DataFrame()) if return_allocation_provenance else empty_result
    mapping = mapping_df.copy()
    mapping["ninth_sector"] = mapping["ninth_sector"].fillna("").astype(str).str.strip()
    mapping["ninth_fuel"] = mapping["ninth_fuel"].fillna("").astype(str).str.strip()
    mapping["esto_flow"] = mapping["esto_flow"].fillna("").astype(str).str.strip()
    mapping["esto_product"] = mapping["esto_product"].fillna("").astype(str).str.strip()
    mapping = mapping[(mapping["ninth_sector"] != "") & (mapping["ninth_fuel"] != "")]
    mapping = mapping.drop_duplicates(
        subset=["ninth_sector", "ninth_fuel", "esto_flow", "esto_product"]
    )
    if mapping.empty:
        empty_result = (pd.DataFrame(), pd.DataFrame())
        return (*empty_result, pd.DataFrame()) if return_allocation_provenance else empty_result
    sign_stable_flow_set = _resolve_sign_stable_flow_set(mapping, sign_stable_flows)

    base_values = base_values.copy()
    if not base_values.empty:
        base_values["esto_flow"] = base_values["esto_flow"].astype(str).str.strip()
        base_values["esto_product"] = base_values["esto_product"].astype(str).str.strip()
        base_values["economy_key"] = base_values["economy_key"].astype(str).str.strip()

    apec_base = (
        base_values.groupby(["esto_flow", "esto_product"], dropna=False)["base_value_abs"]
        .sum()
        .reset_index()
    )
    mapping_apec = mapping.merge(apec_base, on=["esto_flow", "esto_product"], how="left")
    mapping_apec["base_value_abs"] = mapping_apec["base_value_abs"].fillna(0.0)
    mapping_apec["apec_group_total"] = mapping_apec.groupby(
        ["ninth_sector", "ninth_fuel"], dropna=False
    )["base_value_abs"].transform("sum")
    mapping_apec["apec_share"] = 0.0
    apec_mask = mapping_apec["apec_group_total"] > 0
    mapping_apec.loc[apec_mask, "apec_share"] = (
        mapping_apec.loc[apec_mask, "base_value_abs"]
        / mapping_apec.loc[apec_mask, "apec_group_total"]
    )

    merged = mapping.merge(
        ninth_series, on=["ninth_sector", "ninth_fuel"], how="inner"
    )
    merged = merged.merge(
        base_values[
            [
                "economy_key",
                "esto_flow",
                "esto_product",
                "base_value",
                "base_value_abs",
            ]
        ],
        on=["economy_key", "esto_flow", "esto_product"],
        how="left",
    )
    merged["base_value"] = pd.to_numeric(merged["base_value"], errors="coerce").fillna(0.0)
    merged["base_value_abs"] = merged["base_value_abs"].fillna(0.0)
    merged = merged.merge(
        mapping_apec[
            [
                "ninth_sector",
                "ninth_fuel",
                "esto_flow",
                "esto_product",
                "apec_group_total",
                "apec_share",
            ]
        ],
        on=["ninth_sector", "ninth_fuel", "esto_flow", "esto_product"],
        how="left",
    )
    merged["apec_group_total"] = merged["apec_group_total"].fillna(0.0)
    merged["apec_share"] = merged["apec_share"].fillna(0.0)
    merged["group_total"] = merged.groupby(
        ["economy_key", "ninth_sector", "ninth_fuel"], dropna=False
    )["base_value_abs"].transform("sum")
    # Equal-share fallback must be per economy + 9th pair (not global across economies).
    merged["group_count"] = merged.groupby(
        ["economy_key", "ninth_sector", "ninth_fuel"], dropna=False
    )["esto_flow"].transform("count").astype(float)
    merged["share"] = 0.0
    merged["share_source"] = "economy"
    economy_mask = merged["group_total"] > 0
    merged.loc[economy_mask, "share"] = (
        merged.loc[economy_mask, "base_value_abs"]
        / merged.loc[economy_mask, "group_total"]
    )
    fallback_mask = ~economy_mask
    # Coal parent-to-child reconstruction is deliberately economy-specific.
    # The APEC aggregate is a validation fixture only and must never supply a
    # production economy's coal allocation shares.
    coal_source_mask = merged["ninth_sector"].eq("09_08_coal_transformation")
    apec_mask = fallback_mask & ~coal_source_mask & (merged["apec_group_total"] > 0)
    merged.loc[apec_mask, "share"] = merged.loc[apec_mask, "apec_share"]
    merged.loc[apec_mask, "share_source"] = "apec"
    equal_mask = fallback_mask & ~apec_mask
    merged.loc[equal_mask, "share"] = (
        1.0
        / merged.loc[equal_mask, "group_count"].replace(0, pd.NA)
    )
    merged.loc[equal_mask, "share_source"] = "equal"
    merged["share"] = merged["share"].fillna(0.0)
    merged["apply_sign_stable"] = False
    merged["apply_sign_stable_pair"] = False
    if sign_stable_flow_set:
        merged["apply_sign_stable"] = merged["esto_flow"].isin(sign_stable_flow_set)
        key_cols = ["economy_key", "ninth_sector", "ninth_fuel"]
        merged["apply_sign_stable_pair"] = (
            merged.groupby(key_cols, dropna=False)["apply_sign_stable"]
            .transform("max")
            .astype(bool)
        )
        # Build sign-specific share pools from base-year values.
        merged["base_pos_abs"] = merged["base_value_abs"].where(merged["base_value"] > 0, 0.0)
        merged["base_neg_abs"] = merged["base_value_abs"].where(merged["base_value"] < 0, 0.0)
        merged["group_positive_total"] = merged.groupby(
            ["economy_key", "ninth_sector", "ninth_fuel"], dropna=False
        )["base_pos_abs"].transform("sum")
        merged["group_negative_total"] = merged.groupby(
            ["economy_key", "ninth_sector", "ninth_fuel"], dropna=False
        )["base_neg_abs"].transform("sum")
        merged["positive_share"] = 0.0
        merged["negative_share"] = 0.0
        positive_mask = (merged["base_value"] > 0) & (merged["group_positive_total"] > 0)
        merged.loc[positive_mask, "positive_share"] = (
            merged.loc[positive_mask, "base_value_abs"]
            / merged.loc[positive_mask, "group_positive_total"]
        )
        negative_mask = (merged["base_value"] < 0) & (merged["group_negative_total"] > 0)
        merged.loc[negative_mask, "negative_share"] = (
            merged.loc[negative_mask, "base_value_abs"]
            / merged.loc[negative_mask, "group_negative_total"]
        )

    year_cols = [year for year in projection_years if year in merged.columns]
    for year in year_cols:
        merged[year] = pd.to_numeric(merged[year], errors="coerce").fillna(0.0)
    # Capture original source series before replacing year columns with allocated values.
    source_by_pair = (
        merged[["economy_key", "ninth_sector", "ninth_fuel"] + year_cols]
        .drop_duplicates(subset=["economy_key", "ninth_sector", "ninth_fuel"])
        .copy()
    )
    for year in year_cols:
        source = merged[year]
        allocated = source * merged["share"]
        if sign_stable_flow_set:
            stable_mask = merged["apply_sign_stable_pair"]
            src_positive = stable_mask & (source > 0)
            src_negative = stable_mask & (source < 0)
            has_positive_group = merged["group_positive_total"] > 0
            has_negative_group = merged["group_negative_total"] > 0
            # Route source values by sign when sign-stable mode is enabled.
            # If a sign pool does not exist, legacy allocation remains in place.
            allocated.loc[src_positive & has_positive_group] = (
                source.loc[src_positive & has_positive_group]
                * merged.loc[src_positive & has_positive_group, "positive_share"]
            )
            allocated.loc[src_negative & has_negative_group] = (
                source.loc[src_negative & has_negative_group]
                * merged.loc[src_negative & has_negative_group, "negative_share"]
            )
        merged[year] = allocated

    merged["coal_allocation_method"] = "not_applicable"
    merged, child_profile_diagnostics = _disaggregate_parent_flow_allocations(
        merged,
        child_flow_profiles,
        year_cols,
    )
    merged, gas_profile_diagnostics = _allocate_gas_parent_residuals(
        merged,
        gas_child_flow_profiles,
        year_cols,
    )

    allocation_provenance = pd.DataFrame()
    if return_allocation_provenance:
        provenance = merged[
            [
                "economy_key", "ninth_sector", "ninth_fuel", "esto_flow",
                "esto_product", "share", "share_source", "group_count", *year_cols,
                "coal_allocation_method",
            ]
        ].copy()
        provenance["coal_allocation_method"] = provenance[
            "coal_allocation_method"
        ].fillna("not_applicable")
        provenance["allocation_method"] = "direct"
        multiple_targets = provenance["group_count"].gt(1)
        provenance.loc[multiple_targets & provenance["share_source"].eq("economy"), "allocation_method"] = (
            "proportional_esto_base_year"
        )
        provenance.loc[multiple_targets & provenance["share_source"].eq("apec"), "allocation_method"] = (
            "proportional_apec_fallback"
        )
        provenance.loc[multiple_targets & provenance["share_source"].eq("equal"), "allocation_method"] = (
            "equal_split_fallback"
        )
        allocation_provenance = provenance.melt(
            id_vars=[
                "economy_key", "ninth_sector", "ninth_fuel", "esto_flow",
                "esto_product", "share", "share_source", "allocation_method",
                "coal_allocation_method",
            ],
            value_vars=year_cols,
            var_name="year",
            value_name="allocated_value",
        )

    projection_df = (
        merged.groupby(["economy_key", "esto_flow", "esto_product"], dropna=False)[
            year_cols
        ]
        .sum()
        .reset_index()
    )
    diagnostics = merged.loc[
        merged["share_source"] != "economy",
        [
            "economy_key",
            "ninth_sector",
            "ninth_fuel",
            "esto_flow",
            "esto_product",
            "share_source",
            "group_total",
            "apec_group_total",
            "base_value_abs",
            "share",
            "apply_sign_stable",
            "apply_sign_stable_pair",
        ],
    ].copy()
    if not diagnostics.empty:
        diagnostics["diagnostic_type"] = "share_fallback"

    conservation_diagnostics = _build_conservation_diagnostics(
        source_by_pair.loc[
            ~source_by_pair["ninth_sector"].eq(GAS_PARENT_NINTH_SECTOR)
        ],
        merged,
        year_cols,
        tolerance=1e-6,
    )
    if not conservation_diagnostics.empty:
        max_err = float(conservation_diagnostics["max_abs_allocation_error"].max())
        message = (
            "Allocation conservation check failed for "
            f"{len(conservation_diagnostics)} source pairs. "
            f"Max abs allocation error={max_err:.6e}"
        )
        if strict_conservation:
            sample_cols = [
                "economy_key",
                "ninth_sector",
                "ninth_fuel",
                "worst_year",
                "allocation_error_worst_year",
                "max_abs_allocation_error",
            ]
            sample = (
                conservation_diagnostics.sort_values(
                    "max_abs_allocation_error", ascending=False
                )[sample_cols]
                .head(10)
                .to_string(index=False)
            )
            raise ValueError(f"{message}\nTop mismatches:\n{sample}")
        print(f"[WARN] {message}")
        diagnostics = pd.concat([diagnostics, conservation_diagnostics], ignore_index=True, sort=False)
    if not child_profile_diagnostics.empty:
        diagnostics = pd.concat(
            [diagnostics, child_profile_diagnostics],
            ignore_index=True,
            sort=False,
        )
    if not gas_profile_diagnostics.empty:
        diagnostics = pd.concat(
            [diagnostics, gas_profile_diagnostics],
            ignore_index=True,
            sort=False,
        )

    if sign_stable_flow_set and "apply_sign_stable" in diagnostics.columns:
        diagnostics["sign_stable_mode"] = diagnostics["apply_sign_stable"].map(
            {True: "enabled", False: "disabled"}
        )
    if return_allocation_provenance:
        return projection_df, diagnostics, allocation_provenance
    return projection_df, diagnostics


def build_esto_projection_table(
    ninth_data: pd.DataFrame,
    esto_data: pd.DataFrame,
    mapping_path: str | Path | tuple[str | Path, str],
    base_year: int,
    projection_years: Sequence[int],
    scenario: str = DEFAULT_SCENARIO,
    sign_stable_flows: Iterable[str] | str | None = None,
    strict_conservation: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return projected ESTO values plus allocation diagnostics.

    Args:
        sign_stable_flows:
            Optional ESTO flow names to allocate with sign-stable routing.
            Use `[]` or `"off"` for pure legacy abs-share behavior.
            Use `"all"` to apply sign-stable routing to every mapped ESTO flow.
        strict_conservation:
            If True, raise ValueError when allocated totals do not match source totals.
    """
    if isinstance(mapping_path, tuple):
        mapping_file, mapping_sheet = Path(mapping_path[0]), str(mapping_path[1])
    else:
        mapping_file, mapping_sheet = Path(mapping_path), None
    if not config_table_exists(mapping_file, mapping_sheet):
        return pd.DataFrame(), pd.DataFrame()
    mapping_df = read_config_table(
        mapping_file,
        sheet_name=mapping_sheet,
        dtype=str,
    ).fillna("")
    if mapping_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    ninth_filtered = filter_ninth_projection_rows(ninth_data, scenario=scenario)
    ninth_pairs = add_ninth_pair_columns(ninth_filtered)
    # 09.06 is exceptional: the aggregate parent is marked subtotal while its
    # children are not consistently projected.  Keep this parent as a source
    # for the residual policy below; all other subtotal rows stay excluded.
    ninth_with_subtotals = ninth_data.copy()
    if scenario and "scenarios" in ninth_with_subtotals.columns:
        ninth_with_subtotals = ninth_with_subtotals[
            ninth_with_subtotals["scenarios"].astype(str).str.strip().str.lower()
            == str(scenario).strip().lower()
        ]
    ninth_parent_pairs = add_ninth_pair_columns(ninth_with_subtotals)
    if "subtotal_results" in ninth_parent_pairs.columns:
        subtotal_mask = (
            ninth_parent_pairs["subtotal_results"].fillna(False).astype(str).str.strip().str.lower()
            .isin({"1", "true", "yes", "y", "t"})
        )
        ninth_parent_pairs = ninth_parent_pairs.loc[
            subtotal_mask & ninth_parent_pairs["ninth_sector"].eq(GAS_PARENT_NINTH_SECTOR)
        ]
        # The APEC aggregate is a validation fixture, never a production
        # allocation profile.  Do not activate the gas-parent residual rule
        # for its synthetic aggregate series.
        ninth_parent_pairs = ninth_parent_pairs.loc[
            ~ninth_parent_pairs["economy"].astype(str).eq("00_APEC")
        ]
        # Prefer the subtotal parent where both it and an equivalent regular
        # parent row are present (currently observed for PNG).  Otherwise the
        # parent would be counted twice before residual allocation.
        parent_keys = ["economy", "ninth_sector", "ninth_fuel"]
        if not ninth_parent_pairs.empty:
            subtotal_index = pd.MultiIndex.from_frame(ninth_parent_pairs[parent_keys])
            normal_index = pd.MultiIndex.from_frame(ninth_pairs[parent_keys])
            duplicate_parent = (
                ninth_pairs["ninth_sector"].eq(GAS_PARENT_NINTH_SECTOR)
                & normal_index.isin(subtotal_index)
            )
            ninth_pairs = ninth_pairs.loc[~duplicate_parent]
        ninth_pairs = pd.concat([ninth_pairs, ninth_parent_pairs], ignore_index=True, sort=False)
    ninth_pairs["economy_key"] = ninth_pairs["economy"].apply(normalize_economy_key)
    ninth_series = build_ninth_projection_series(ninth_pairs, projection_years)
    base_values = build_esto_base_year_values(esto_data, base_year)
    child_flow_profiles = build_economy_specific_child_flow_profiles(
        esto_data,
        base_year,
    )
    gas_child_flow_profiles = build_economy_specific_child_flow_profiles(
        esto_data,
        base_year,
        parent_flow=GAS_PARENT_ESTO_FLOW,
        child_flows=GAS_CHILD_ESTO_FLOWS,
    )
    return allocate_ninth_projection_to_esto(
        mapping_df,
        ninth_series,
        base_values,
        projection_years,
        sign_stable_flows=sign_stable_flows,
        strict_conservation=strict_conservation,
        child_flow_profiles=child_flow_profiles,
        gas_child_flow_profiles=gas_child_flow_profiles,
    )


def merge_projection_into_esto(
    esto_df: pd.DataFrame,
    projection_df: pd.DataFrame,
    projection_years: Sequence[int],
) -> pd.DataFrame:
    """Return an ESTO dataframe with projection years appended."""
    if not projection_years:
        return esto_df
    if projection_df is None or projection_df.empty:
        working = esto_df.copy()
        print(
            f"[INFO] No 9th projection data available; adding empty projection-year columns "
            f"({min(projection_years)}–{max(projection_years)}) to ESTO base-year data."
        )
        for year in projection_years:
            if year not in working.columns:
                working[year] = 0.0
        return working
    working = esto_df.copy()
    print(
        f"[INFO] Merging 9th projections into ESTO data for years "
        f"{min(projection_years)}–{max(projection_years)}."
    )
    working["economy_key"] = working["economy"].apply(normalize_economy_key)
    working["flows"] = working["flows"].astype(str).str.strip()
    working["products"] = working["products"].astype(str).str.strip()

    proj = projection_df.copy()
    proj["esto_flow"] = proj["esto_flow"].astype(str).str.strip()
    proj["esto_product"] = proj["esto_product"].astype(str).str.strip()
    proj_cols = [year for year in projection_years if year in proj.columns]
    if not proj_cols:
        return esto_df
    proj = proj.rename(columns={year: f"{year}_proj" for year in proj_cols})

    merged = working.merge(
        proj,
        left_on=["economy_key", "flows", "products"],
        right_on=["economy_key", "esto_flow", "esto_product"],
        how="left",
    )
    missing_match_mask = merged[[f"{year}_proj" for year in proj_cols]].isna().all(axis=1)
    if missing_match_mask.any():
        missing_rows = merged.loc[missing_match_mask, ["economy", "flows", "products"]]
        affected_flows = (
            missing_rows.groupby("flows", dropna=False)
            .size()
            .sort_values(ascending=False)
        )
        flow_summary = ", ".join(
            f"{flow} ({count})" for flow, count in affected_flows.head(8).items()
        )
        print(
            "[WARN] No mapped 9th projection match for "
            f"{len(missing_rows)} ESTO rows across {missing_rows['economy'].nunique()} economies; "
            "projection years will be zero-filled. "
            f"Affected flows: {flow_summary}"
        )
    for year in proj_cols:
        proj_col = f"{year}_proj"
        merged[year] = merged[proj_col].fillna(0.0)
    drop_cols = [
        "economy_key",
        "esto_flow",
        "esto_product",
    ] + [f"{year}_proj" for year in proj_cols]
    merged = merged.drop(columns=[col for col in drop_cols if col in merged.columns])

    base_cols = [col for col in esto_df.columns if col not in proj_cols]
    existing_years = [col for col in base_cols if str(col).isdigit()]
    non_year_cols = [col for col in base_cols if col not in existing_years]
    ordered_years = sorted(set(existing_years + proj_cols))
    ordered_cols = non_year_cols + ordered_years
    merged = merged[ordered_cols]
    return merged


def build_projection_lookup(projection_df: pd.DataFrame) -> pd.DataFrame | None:
    """Return a MultiIndex lookup for projection values."""
    if projection_df is None or projection_df.empty:
        return None
    grouped = (
        projection_df.groupby(
            ["economy_key", "esto_flow", "esto_product"], dropna=False
        )
        .sum(numeric_only=True)
    )
    return grouped
