from __future__ import annotations

import re
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
# Only the reviewed 09.06 and 09.08 process families may infer or enlarge a
# parent total. Broad mapping parents such as ``09 Total transformation sector``
# combine unrelated processes and must never become reconstruction families.
APPROVED_MISSING_NINTH_PARENT_FLOWS = {
    COAL_PARENT_ESTO_FLOW,
    GAS_PARENT_ESTO_FLOW,
}
NINTH_SECTOR_COLS = [
    "sub4sectors",
    "sub3sectors",
    "sub2sectors",
    "sub1sectors",
    "sectors",
]
NINTH_FUEL_COLS = ["subfuels", "fuels"]

MISSING_NINTH_FLOW_OWNER_BY_PREFIX = {
    "01": "supply_workflow",
    "02": "supply_workflow",
    "03": "supply_workflow",
    "04": "supply_workflow",
    "05": "supply_workflow",
    "06": "supply_workflow",
    "07": "supply_workflow",
    "08": "transfers_workflow",
    "09": "transformation_workflow",
    "10": "other_loss_own_use_proxy_workflow",
    "11": "supply_workflow",
    "12": "other_loss_own_use_proxy_workflow",
    "13": "aggregated_demand_workflow",
    "14": "aggregated_demand_workflow",
    "15": "aggregated_demand_workflow",
    "16": "aggregated_demand_workflow",
    "17": "aggregated_demand_workflow",
}


def _esto_flow_family(value: object) -> str:
    """Return the dotted parent code shared by an ESTO flow family."""
    match = re.match(r"^\s*(\d{2}\.\d{2})(?:\.|\s|$)", str(value or ""))
    return match.group(1) if match else ""


def _esto_flow_code(value: object) -> str:
    return str(value or "").strip().split(" ", 1)[0]


def _missing_ninth_owner(esto_flow: object) -> str:
    return MISSING_NINTH_FLOW_OWNER_BY_PREFIX.get(_esto_flow_code(esto_flow)[:2], "unassigned")


def build_general_child_flow_profiles(
    esto_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
    base_year: int,
) -> pd.DataFrame:
    """Return signed active-child profiles beneath mapped ESTO parent flows."""
    columns = [
        "economy_key", "esto_product", "child_flow", "base_value",
        "base_value_abs", "profile_parent_flow", "owner_workflow",
    ]
    if esto_df is None or esto_df.empty or mapping_df is None or mapping_df.empty:
        return pd.DataFrame(columns=columns)
    year_col = base_year if base_year in esto_df.columns else str(base_year)
    if year_col not in esto_df.columns:
        return pd.DataFrame(columns=columns)
    mapped_parent_flows = sorted({
        str(value).strip() for value in mapping_df.get("esto_flow", pd.Series(dtype=object))
        if str(value).strip()
    })
    parent_codes = {
        flow: _esto_flow_code(flow)
        for flow in mapped_parent_flows
    }
    working = esto_df.copy()
    if "is_subtotal" in working.columns:
        subtotal = (
            working["is_subtotal"].fillna(False).astype(str).str.strip().str.lower()
            .isin({"1", "true", "yes", "y", "t"})
        )
        working = working.loc[~subtotal].copy()
    rows: list[dict[str, object]] = []
    for _, row in working.iterrows():
        child_flow = str(row.get("flows", "")).strip()
        child_code = _esto_flow_code(child_flow)
        candidate_parents = [
            (flow, code) for flow, code in parent_codes.items()
            if code and child_code.startswith(code + ".")
        ]
        if not candidate_parents:
            continue
        parent_flow, _ = max(candidate_parents, key=lambda item: len(item[1]))
        value = float(pd.to_numeric(pd.Series([row.get(year_col)]), errors="coerce").fillna(0.0).iloc[0])
        if abs(value) <= 1e-12:
            continue
        rows.append({
            "economy_key": normalize_economy_key(row.get("economy")),
            "esto_product": str(row.get("products", "")).strip(),
            "child_flow": child_flow,
            "base_value": value,
            "base_value_abs": abs(value),
            "profile_parent_flow": parent_flow,
            "owner_workflow": _missing_ninth_owner(parent_flow),
        })
    if not rows:
        return pd.DataFrame(columns=columns)
    return (
        pd.DataFrame(rows)
        .groupby(
            ["economy_key", "esto_product", "child_flow", "profile_parent_flow", "owner_workflow"],
            dropna=False,
        )[["base_value", "base_value_abs"]]
        .sum()
        .reset_index()
        .reindex(columns=columns)
    )


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
    year_column_map: dict[int, object] = {}
    for year in projection_years:
        if year in ninth_df.columns:
            year_column_map[int(year)] = year
        elif str(int(year)) in ninth_df.columns:
            year_column_map[int(year)] = str(int(year))
    if not year_column_map:
        return pd.DataFrame()
    working = ninth_df.copy()
    working = working[(working["ninth_sector"] != "") & (working["ninth_fuel"] != "")]
    if working.empty:
        return pd.DataFrame()
    source_year_columns = list(year_column_map.values())
    for source_column in source_year_columns:
        working[source_column] = pd.to_numeric(
            working[source_column], errors="coerce"
        ).fillna(0.0)
    grouped = (
        working.groupby(
            ["economy_key", "ninth_sector", "ninth_fuel"], dropna=False
        )[source_year_columns]
        .sum()
        .reset_index()
    )
    grouped = grouped.rename(
        columns={source_column: year for year, source_column in year_column_map.items()}
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


def select_approved_parent_anchor_rows(
    esto_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
) -> pd.DataFrame:
    """Keep reviewed subtotal parents available for projection allocation only.

    The ESTO subtotal filter correctly removes aggregate rows from the output
    dataset. The 09.06 and 09.08 aggregate rows are nevertheless needed as
    base-year allocation anchors when their children must be reconstructed.
    This selects only mapped, reviewed parent rows; callers must not merge the
    result into their output ESTO table.
    """
    if esto_df is None or esto_df.empty or mapping_df is None or mapping_df.empty:
        return pd.DataFrame(columns=esto_df.columns if esto_df is not None else None)
    required_esto = {"flows", "products", "is_subtotal"}
    required_mapping = {"esto_flow", "esto_product"}
    if not required_esto.issubset(esto_df.columns) or not required_mapping.issubset(mapping_df.columns):
        return pd.DataFrame(columns=esto_df.columns)

    subtotal_mask = (
        esto_df["is_subtotal"].fillna(False).astype(str).str.strip().str.lower()
        .isin({"1", "true", "yes", "y", "t"})
    )
    parent_rows = esto_df.loc[
        subtotal_mask
        & esto_df["flows"].astype(str).isin(APPROVED_MISSING_NINTH_PARENT_FLOWS)
    ].copy()
    if parent_rows.empty:
        return parent_rows

    mapped_pairs = mapping_df.loc[
        mapping_df["esto_flow"].astype(str).isin(APPROVED_MISSING_NINTH_PARENT_FLOWS),
        ["esto_flow", "esto_product"],
    ].drop_duplicates()
    anchors = parent_rows.merge(
        mapped_pairs,
        left_on=["flows", "products"],
        right_on=["esto_flow", "esto_product"],
        how="inner",
    )
    return anchors[esto_df.columns].copy()


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
    fill_missing_ninth_sectors: bool = False,
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
        if fill_missing_ninth_sectors and not any(
            abs(float(parent_row[year])) > tolerance for year in year_cols
        ):
            # Keep an unavailable aggregate in place for the shared child
            # reconstruction below.  Splitting zero here would turn every
            # child into an indistinguishable zero placeholder.
            retained_parent = parent_row.to_dict()
            retained_parent["coal_allocation_method"] = "deferred_zero_parent_reconstruction"
            child_rows.append(retained_parent)
            continue
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
    fill_missing_ninth_sectors: bool = False,
    tolerance: float = 1e-9,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Allocate gas parent residuals, optionally filling missing 9th children."""
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
        if fill_missing_ninth_sectors:
            # The shared rule protects direct child projections and can enlarge
            # an insufficient parent. Retain this row until that reconstruction
            # step instead of applying the legacy gas-only residual split.
            generated_rows.append(parent_row.to_dict())
            continue
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
        parent_has_projection = any(
            abs(float(parent_row[year])) > tolerance for year in year_cols
        )
        if not parent_has_projection:
            # Let the shared reconstruction rule handle a zero/absent parent.
            # It can use surviving child projections as anchors; the old gas
            # path could only carry missing children forward unchanged.
            if fill_missing_ninth_sectors:
                generated_rows.append(parent_row.to_dict())
            continue
        if not any(abs(value) > tolerance for value in residual.values()):
            continue

        if active_children.empty:
            diagnostics.append(
                {
                    "economy_key": economy_key,
                    "esto_product": product,
                    "parent_flow": GAS_PARENT_ESTO_FLOW,
                    "diagnostic_type": "gas_parent_residual_no_active_child_profile",
                    "allocation_method": "skipped_no_base_year_active_child",
                    "direct_children": "; ".join(sorted(direct_flows)),
                }
            )
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
            for year in year_cols:
                diagnostics.append(
                    {
                        "economy_key": economy_key,
                        "esto_product": product,
                        "parent_flow": GAS_PARENT_ESTO_FLOW,
                        "diagnostic_type": "gas_parent_residual_unallocated",
                        "allocation_method": "unallocated_signed_profile_net_zero",
                        "year": int(year),
                        "parent_value": float(parent_row[year]),
                        "direct_children_value": float(direct_by_flow[year].sum())
                        if year in direct_by_flow.columns else 0.0,
                        "residual_value": residual[year],
                        "profile_net_value": profile_total,
                        "owner_workflow": "transformation_workflow",
                    }
                )
            continue
        for _, profile_row in missing_children.iterrows():
            child = parent_row.to_dict()
            child["esto_flow"] = profile_row["child_flow"]
            child["gas_allocation_method"] = "parent_residual_base_year_share"
            scale = float(profile_row["base_value"]) / profile_total
            for year in year_cols:
                child[year] = residual[year] * scale
                diagnostics.append(
                    {
                        "economy_key": economy_key,
                        "esto_product": product,
                        "parent_flow": GAS_PARENT_ESTO_FLOW,
                        "child_flow": profile_row["child_flow"],
                        "base_year_value": float(profile_row["base_value"]),
                        "direct_ninth_presence": False,
                        "existing_output_presence": False,
                        "owner_workflow": "transformation_workflow",
                        "diagnostic_type": "gas_parent_residual_allocated",
                        "allocation_method": "parent_residual_base_year_share",
                        "year": int(year),
                        "parent_value": float(parent_row[year]),
                        "direct_children_value": float(direct_by_flow[year].sum())
                        if year in direct_by_flow.columns else 0.0,
                        "residual_value": residual[year],
                        "allocation_share": scale,
                        "conservation_error": 0.0,
                        "base_year_continuity_error": pd.NA,
                        "duplicate_output_count": 0,
                    }
                )
            generated_rows.append(child)
    return pd.concat([retained, pd.DataFrame(generated_rows)], ignore_index=True, sort=False), pd.DataFrame(diagnostics)


def _fill_general_missing_ninth_children(
    allocated_rows: pd.DataFrame,
    child_profiles: pd.DataFrame | None,
    year_cols: Sequence[int],
    *,
    owner_workflow: str,
    existing_output_pairs: pd.DataFrame | None = None,
    tolerance: float = 1e-9,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reconstruct base-year-active children without changing direct 9th values.

    A projected parent is a lower-bound aggregate: if protected children have
    grown beyond their base-year share, the reconstructed parent is enlarged so
    missing siblings can retain their base-year proportions.  With no projected
    parent, surviving children provide the scale; with no surviving children,
    base-year values are carried forward.  Signed net-zero profiles are left
    unallocated because no meaningful scalar parent scale exists.
    """
    if allocated_rows.empty or child_profiles is None or child_profiles.empty or not year_cols:
        return allocated_rows, pd.DataFrame()
    owner = str(owner_workflow or "").strip()
    owner_mask = child_profiles["owner_workflow"].astype(str).eq(owner)
    # Direct callers historically omitted an owner for the dedicated gas
    # reconstruction. Keep that public behaviour while normal workflows use
    # their explicit ownership boundary.
    if not owner:
        owner_mask |= child_profiles["profile_parent_flow"].astype(str).eq(
            GAS_PARENT_ESTO_FLOW
        )
    profile = child_profiles[owner_mask].copy()
    profile = profile[
        profile["profile_parent_flow"].astype(str).isin(
            APPROVED_MISSING_NINTH_PARENT_FLOWS
        )
    ].copy()
    if profile.empty:
        return allocated_rows, pd.DataFrame()

    existing_pairs: set[tuple[str, str, str]] = set()
    existing_rows = pd.DataFrame()
    if existing_output_pairs is not None and not existing_output_pairs.empty:
        required = {"economy_key", "esto_flow", "esto_product"}
        if required.issubset(existing_output_pairs.columns):
            existing_rows = existing_output_pairs.copy()
            existing_pairs = {
                (str(row["economy_key"]), str(row["esto_flow"]), str(row["esto_product"]))
                for _, row in existing_output_pairs.iterrows()
            }

    parent_flows = set(profile["profile_parent_flow"].astype(str))
    parent_mask = (
        allocated_rows["esto_flow"].astype(str).isin(parent_flows)
        & ~allocated_rows["economy_key"].astype(str).eq("00APEC")
    )
    if not parent_mask.any():
        return allocated_rows, pd.DataFrame()

    retained = allocated_rows.loc[~parent_mask].copy()
    generated: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    for _, parent_row in allocated_rows.loc[parent_mask].iterrows():
        economy = str(parent_row["economy_key"])
        product = str(parent_row["esto_product"]).strip()
        parent_flow = str(parent_row["esto_flow"]).strip()
        active = profile[
            profile["economy_key"].astype(str).eq(economy)
            & profile["esto_product"].astype(str).eq(product)
            & profile["profile_parent_flow"].astype(str).eq(parent_flow)
            & profile["base_value_abs"].gt(tolerance)
        ].copy()
        child_flows = set(active["child_flow"].astype(str))
        parent_code = _esto_flow_code(parent_flow)
        direct = retained[
            retained["economy_key"].astype(str).eq(economy)
            & retained["esto_product"].astype(str).eq(product)
            & retained["esto_flow"].map(_esto_flow_code).str.startswith(parent_code + ".")
        ]
        direct_by_flow = direct.groupby("esto_flow", dropna=False)[list(year_cols)].sum()
        # A child that is present only as zeros is a missing projection, not a
        # protected child. A projected child which was not active for this
        # fuel in the ESTO base year must also not block a base-active sibling
        # from being reconstructed. This is important for LNG: a new
        # liquefaction series can coexist with a historical gas-blending
        # series without making the latter's carry-forward underdetermined.
        direct_flows = {
            str(flow) for flow, values in direct_by_flow.iterrows()
            if values.abs().gt(tolerance).any()
        }
        # A future-only direct 9th child must not be treated as a protected
        # historical child.  Projection merging can materialise it as an
        # explicit zero-valued ESTO row in the base year (as LNG does for USA),
        # so membership in ``child_flows`` alone is not sufficient here.
        base_active_child_flows = set(
            active.loc[
                active["base_value"].abs() > tolerance,
                "child_flow",
            ].astype(str)
        )
        direct_active_flows = direct_flows & base_active_child_flows
        produced_elsewhere = {
            flow for flow in child_flows
            if (economy, flow, product) in existing_pairs
        }
        missing = active[
            ~active["child_flow"].astype(str).isin(
                direct_active_flows | produced_elsewhere
            )
        ].copy()
        if missing.empty:
            continue

        # Remove all-zero allocated placeholders before emitting reconstructed
        # rows with the same ESTO keys.
        missing_flows = set(missing["child_flow"].astype(str))
        retained = retained.loc[~(
            retained["economy_key"].astype(str).eq(economy)
            & retained["esto_product"].astype(str).eq(product)
            & retained["esto_flow"].astype(str).isin(missing_flows)
        )].copy()

        external_direct = existing_rows[
            existing_rows["economy_key"].astype(str).eq(economy)
            & existing_rows["esto_product"].astype(str).eq(product)
            & existing_rows["esto_flow"].astype(str).isin(produced_elsewhere)
        ] if not existing_rows.empty else pd.DataFrame()
        direct_by_year = {
            year: float(
                pd.to_numeric(direct.get(year, pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()
                + pd.to_numeric(external_direct.get(year, pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()
            )
            for year in year_cols
        }
        parent_by_year = {year: float(parent_row.get(year, 0.0) or 0.0) for year in year_cols}
        parent_has_projection = any(abs(value) > tolerance for value in parent_by_year.values())
        active_total = float(active["base_value"].sum())
        protected_flows = direct_active_flows | produced_elsewhere
        protected_base_total = float(
            active.loc[active["child_flow"].astype(str).isin(protected_flows), "base_value"].sum()
        )
        missing_total = float(missing["base_value"].sum())
        has_protected_children = bool(protected_flows)
        carry_zero_net_profile = (
            not parent_has_projection
            and not has_protected_children
            and abs(active_total) <= tolerance
            and abs(missing_total) <= tolerance
        )
        cannot_allocate = (
            abs(active_total) <= tolerance
            or (has_protected_children and abs(protected_base_total) <= tolerance)
            or abs(missing_total) <= tolerance
        )
        if cannot_allocate and not carry_zero_net_profile:
            for year in year_cols:
                diagnostics.append({
                    "economy_key": economy,
                    "esto_product": product,
                    "parent_flow": parent_flow,
                    "child_flow": "",
                    "base_year_value": active_total,
                    "direct_ninth_presence": bool(direct_flows),
                    "existing_output_presence": bool(produced_elsewhere),
                    "owner_workflow": owner,
                    "diagnostic_type": "missing_ninth_sector_fill_unallocated",
                    "allocation_method": "unallocated_signed_profile_net_zero",
                    "year": int(year),
                    "parent_value": parent_by_year[year],
                    "direct_children_value": direct_by_year[year],
                    "residual_value": parent_by_year[year] - direct_by_year[year],
                    "allocation_share": pd.NA,
                    "conservation_error": parent_by_year[year] - direct_by_year[year],
                    "base_year_continuity_error": pd.NA,
                    "duplicate_output_count": 0,
                })
            continue

        if carry_zero_net_profile:
            # No future parent or base-active direct child supplies a scale,
            # but the full signed historical hand-off is known. Keep both
            # sides of that hand-off rather than dropping a net-zero pair.
            method = "base_year_constant"
        elif parent_has_projection and has_protected_children:
            method = "parent_augmented_for_protected_children"
        elif parent_has_projection:
            method = "parent_base_year_share"
        elif has_protected_children:
            method = "inferred_parent_from_protected_children"
        else:
            method = "base_year_constant"
        for _, profile_row in missing.iterrows():
            child = parent_row.to_dict()
            child_flow = str(profile_row["child_flow"])
            child["esto_flow"] = child_flow
            child["missing_ninth_fill_method"] = method
            missing_share = (
                float(profile_row["base_value"]) / missing_total
                if method != "base_year_constant"
                else pd.NA
            )
            for year in year_cols:
                direct_value = direct_by_year[year]
                inferred_parent = (
                    direct_value * active_total / protected_base_total
                    if has_protected_children else pd.NA
                )
                parent_value = parent_by_year[year]
                reconstructed_parent = parent_value
                if has_protected_children:
                    # Do not shrink a supplied parent.  When a protected child
                    # implies a larger same-sign parent, grow it instead.
                    if not parent_has_projection or (
                        float(inferred_parent) * parent_value >= 0
                        and abs(float(inferred_parent)) > abs(parent_value)
                    ):
                        reconstructed_parent = float(inferred_parent)
                residual = reconstructed_parent - direct_value
                child_value = (
                    residual * missing_share
                    if method != "base_year_constant"
                    else float(profile_row["base_value"])
                )
                child[year] = child_value
                diagnostics.append({
                    "economy_key": economy,
                    "esto_product": product,
                    "parent_flow": parent_flow,
                    "child_flow": child_flow,
                    "base_year_value": float(profile_row["base_value"]),
                    "direct_ninth_presence": child_flow in direct_active_flows,
                    "existing_output_presence": child_flow in produced_elsewhere,
                    "owner_workflow": owner,
                    "diagnostic_type": "missing_ninth_sector_fill_applied",
                    "allocation_method": method,
                    "year": int(year),
                    "parent_value": parent_by_year[year],
                    "direct_children_value": direct_by_year[year],
                    "residual_value": residual if method != "base_year_constant" else pd.NA,
                    "allocation_share": missing_share if method != "base_year_constant" else pd.NA,
                    "conservation_error": 0.0 if method != "base_year_constant" else pd.NA,
                    "base_year_continuity_error": child_value - float(profile_row["base_value"])
                    if int(year) == min(int(value) for value in year_cols)
                    else pd.NA,
                    "duplicate_output_count": 0,
                    "inferred_parent_value": inferred_parent,
                    "reconstructed_parent_value": reconstructed_parent,
                })
            generated.append(child)

    generated_frame = pd.DataFrame(generated)
    duplicate_keys = ["economy_key", "esto_flow", "esto_product"]
    if not generated_frame.empty:
        generated_counts = generated_frame.groupby(duplicate_keys, dropna=False).size()
        duplicate_generated = generated_counts[generated_counts.gt(1)]
        retained_keys = set(map(tuple, retained[duplicate_keys].astype(str).to_numpy()))
        generated_keys = set(map(tuple, generated_frame[duplicate_keys].astype(str).to_numpy()))
        collisions = retained_keys & generated_keys
        if not duplicate_generated.empty or collisions:
            duplicate_examples = list(duplicate_generated.index) + sorted(collisions)
            raise ValueError(
                "General missing-9th fill produced duplicate ESTO output pairs: "
                + "; ".join(str(key) for key in duplicate_examples[:10])
            )
    result = pd.concat([retained, generated_frame], ignore_index=True, sort=False)
    return result, pd.DataFrame(diagnostics)


def _build_parent_child_reconciliation_diagnostics(
    source_by_pair: pd.DataFrame,
    allocated_rows: pd.DataFrame,
    year_cols: Sequence[int],
    tolerance: float = 1e-6,
) -> pd.DataFrame:
    """Report protected parent/child projection mismatches.

    Coal parent rows are disaggregated into child flows while retaining the
    original 9th pair key.  Gas parent rows can be completed by direct 9th
    child rows, so the reconciliation groups the parent and gas-child sector
    family together.  Only mismatches are returned; successful checks are
    intentionally silent so the diagnostics file remains actionable.
    """
    if source_by_pair.empty or allocated_rows.empty or not year_cols:
        return pd.DataFrame()

    rows: list[dict] = []
    for _, source_row in source_by_pair.iterrows():
        economy = str(source_row["economy_key"])
        sector = str(source_row["ninth_sector"])
        fuel = str(source_row["ninth_fuel"])
        if sector == GAS_PARENT_NINTH_SECTOR:
            candidates = allocated_rows[
                allocated_rows["economy_key"].astype(str).eq(economy)
                & allocated_rows["ninth_fuel"].astype(str).eq(fuel)
                & allocated_rows["esto_flow"].astype(str).str.startswith("09.06")
            ]
            diagnostic_parent = GAS_PARENT_ESTO_FLOW
        elif sector == "09_08_coal_transformation":
            candidates = allocated_rows[
                allocated_rows["economy_key"].astype(str).eq(economy)
                & allocated_rows["ninth_sector"].astype(str).eq(sector)
                & allocated_rows["ninth_fuel"].astype(str).eq(fuel)
                & allocated_rows["esto_flow"].astype(str).str.startswith("09.08.")
            ]
            diagnostic_parent = COAL_PARENT_ESTO_FLOW
        else:
            continue

        if candidates.empty:
            continue
        for year in year_cols:
            expected = float(source_row.get(year, 0.0) or 0.0)
            allocated = float(pd.to_numeric(candidates[year], errors="coerce").fillna(0.0).sum())
            error = allocated - expected
            if abs(error) > tolerance:
                rows.append(
                    {
                        "economy_key": economy,
                        "ninth_sector": sector,
                        "ninth_fuel": fuel,
                        "parent_flow": diagnostic_parent,
                        "diagnostic_type": "parent_child_reconciliation_mismatch",
                        "year": int(year),
                        "parent_value": expected,
                        "allocated_child_value": allocated,
                        "reconciliation_error": error,
                        "child_flow_count": int(candidates["esto_flow"].nunique()),
                        "child_flows": "; ".join(sorted(candidates["esto_flow"].astype(str).unique())),
                        "esto_products": "; ".join(sorted(candidates["esto_product"].astype(str).unique()))
                        if "esto_product" in candidates.columns
                        else "",
                    }
                )
    return pd.DataFrame(rows)


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
    general_child_flow_profiles: pd.DataFrame | None = None,
    fill_missing_ninth_sectors: bool = False,
    owner_workflow: str = "",
    existing_output_pairs: pd.DataFrame | None = None,
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
    # A mapped aggregate parent may be absent after subtotal filtering while
    # its detailed child-flow profile contains the explicit economy allocation
    # evidence. Coal's projected parent is a *net* balance across products,
    # so its product weights must use the absolute signed child total, not the
    # sum of gross child magnitudes. The latter double-counts a product that is
    # output by Coke ovens and consumed by Blast furnaces, causing an artificial
    # shift of the aggregate projection into both processes.
    profile_base_abs: dict[tuple[str, str, str], float] = {}
    for profile_frame, parent_flow in (
        (child_flow_profiles, COAL_PARENT_ESTO_FLOW),
        (gas_child_flow_profiles, GAS_PARENT_ESTO_FLOW),
    ):
        if profile_frame is None or profile_frame.empty:
            continue
        profile_value_column = "base_value_abs"
        if parent_flow == COAL_PARENT_ESTO_FLOW:
            profile_frame = profile_frame.copy()
            profile_group_cols = ["economy_key", "esto_product"]
            net_profile_abs = profile_frame.groupby(
                profile_group_cols, dropna=False
            )["base_value"].transform("sum").abs()
            gross_profile_abs = profile_frame.groupby(
                profile_group_cols, dropna=False
            )["base_value_abs"].transform("sum")
            # A zero net is underdetermined: retain the established gross
            # fallback so the later sign-stable child allocator can emit the
            # positive or negative side of the profile explicitly.
            profile_frame["net_profile_abs"] = net_profile_abs.where(
                net_profile_abs.gt(0.0), gross_profile_abs
            )
            profile_value_column = "net_profile_abs"
        grouped_profile = profile_frame.groupby(
            ["economy_key", "esto_product"], dropna=False
        )[profile_value_column].first()
        for (economy_key, esto_product), value in grouped_profile.items():
            profile_base_abs[
                (str(economy_key), str(esto_product), parent_flow)
            ] = float(value)
    merged["allocation_base_value_abs"] = merged["base_value_abs"]
    parent_without_direct_base = merged["allocation_base_value_abs"].le(0.0)
    if parent_without_direct_base.any() and profile_base_abs:
        merged.loc[
            parent_without_direct_base, "allocation_base_value_abs"
        ] = merged.loc[parent_without_direct_base].apply(
            lambda row: profile_base_abs.get(
                (
                    str(row["economy_key"]),
                    str(row["esto_product"]),
                    str(row["esto_flow"]),
                ),
                0.0,
            ),
            axis=1,
        )
    merged["group_total"] = merged.groupby(
        ["economy_key", "ninth_sector", "ninth_fuel"], dropna=False
    )["allocation_base_value_abs"].transform("sum")
    merged["group_count"] = merged.groupby(
        ["economy_key", "ninth_sector", "ninth_fuel"], dropna=False
    )["esto_flow"].transform("count").astype(float)
    merged["share"] = 0.0
    merged["share_source"] = "economy"
    economy_mask = merged["group_total"] > 0
    merged.loc[economy_mask, "share"] = (
        merged.loc[economy_mask, "allocation_base_value_abs"]
        / merged.loc[economy_mask, "group_total"]
    )
    fallback_mask = ~economy_mask
    flow_family = merged["esto_flow"].map(_esto_flow_family)
    protected_flow_pair = flow_family.isin({"09.06", "09.08"}).groupby(
        [
            merged["economy_key"],
            merged["ninth_sector"],
            merged["ninth_fuel"],
        ],
        dropna=False,
    ).transform("max")
    # An explicit one-to-one relationship to a detailed protected process does
    # not need a base-year profile: there is no allocation choice to infer.
    # Parent 09.06/09.08 mappings remain protected because emitting a parent
    # without a child profile would bypass the established disaggregation rule.
    detailed_protected_target = merged["esto_flow"].astype(str).str.match(
        r"^\s*(?:09\.06|09\.08)\.\d{2}(?:\s|$)"
    )
    single_target_mask = (
        fallback_mask
        & protected_flow_pair
        & detailed_protected_target
        & merged["group_count"].eq(1.0)
    )
    merged.loc[single_target_mask, "share"] = 1.0
    merged.loc[single_target_mask, "share_source"] = (
        "single_target_no_base_year"
    )
    split_fallback_mask = fallback_mask & ~single_target_mask
    # Gas/coal transformation aggregates must not borrow another economy's
    # profile or use an arbitrary equal split. Preserve legacy APEC/equal
    # fallback behaviour for other workflow families, whose policies are
    # independently owned.
    unallocated_mask = split_fallback_mask & protected_flow_pair
    merged.loc[unallocated_mask, "share_source"] = (
        "unallocated_no_economy_base_year"
    )
    apec_mask = (
        split_fallback_mask
        & ~protected_flow_pair
        & merged["apec_group_total"].gt(0.0)
    )
    merged.loc[apec_mask, "share"] = merged.loc[apec_mask, "apec_share"]
    merged.loc[apec_mask, "share_source"] = "apec"
    equal_mask = split_fallback_mask & ~protected_flow_pair & ~apec_mask
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
    unallocated_targets = merged.loc[
        unallocated_mask,
        [
            "economy_key",
            "ninth_sector",
            "ninth_fuel",
            "esto_flow",
            "esto_product",
            "share_source",
            "group_total",
        ],
    ].drop_duplicates()
    if not unallocated_targets.empty:
        unallocated_targets = unallocated_targets.merge(
            source_by_pair,
            on=["economy_key", "ninth_sector", "ninth_fuel"],
            how="left",
        )
        nonzero_projection = (
            unallocated_targets[year_cols]
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .abs()
            .gt(1e-12)
            .any(axis=1)
        )
        unallocated_targets = unallocated_targets.loc[
            nonzero_projection
        ].copy()
        unallocated_targets["flow_family"] = unallocated_targets[
            "esto_flow"
        ].map(_esto_flow_family)
        unallocated_targets["diagnostic_type"] = (
            "unallocated_no_economy_base_year"
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

    # Do not emit zero-valued target rows for an aggregate that was deliberately
    # left unallocated. The source values remain available in diagnostics.
    merged = merged.loc[
        ~merged["share_source"].eq("unallocated_no_economy_base_year")
    ].copy()

    merged["coal_allocation_method"] = "not_applicable"
    merged, child_profile_diagnostics = _disaggregate_parent_flow_allocations(
        merged,
        child_flow_profiles,
        year_cols,
        fill_missing_ninth_sectors=(
            fill_missing_ninth_sectors
            and str(owner_workflow or "").strip() in {"", "transformation_workflow"}
        ),
    )
    merged, gas_profile_diagnostics = _allocate_gas_parent_residuals(
        merged,
        gas_child_flow_profiles,
        year_cols,
        fill_missing_ninth_sectors=(
            fill_missing_ninth_sectors
            and str(owner_workflow or "").strip() in {"", "transformation_workflow"}
        ),
    )
    general_fill_diagnostics = pd.DataFrame()
    general_parent_source_keys: set[tuple[str, str, str]] = set()
    if fill_missing_ninth_sectors:
        if general_child_flow_profiles is not None and not general_child_flow_profiles.empty:
            owned_parent_flows = set(
                general_child_flow_profiles.loc[
                    general_child_flow_profiles["owner_workflow"].astype(str).eq(
                        str(owner_workflow or "").strip()
                    ),
                    "profile_parent_flow",
                ].astype(str)
            ) & APPROVED_MISSING_NINTH_PARENT_FLOWS
            general_parent_source_keys = set(map(
                tuple,
                merged.loc[
                    merged["esto_flow"].astype(str).isin(owned_parent_flows),
                    ["economy_key", "ninth_sector", "ninth_fuel"],
                ].astype(str).to_numpy(),
            ))
        merged, general_fill_diagnostics = _fill_general_missing_ninth_children(
            merged,
            general_child_flow_profiles,
            year_cols,
            owner_workflow=owner_workflow,
            existing_output_pairs=existing_output_pairs,
        )
    parent_child_diagnostics = _build_parent_child_reconciliation_diagnostics(
        source_by_pair,
        merged,
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
    if not unallocated_targets.empty:
        diagnostics = pd.concat(
            [diagnostics, unallocated_targets],
            ignore_index=True,
            sort=False,
        )

    conservation_source = source_by_pair.loc[
        ~source_by_pair["ninth_sector"].eq(GAS_PARENT_NINTH_SECTOR)
    ].copy()
    if general_parent_source_keys and not conservation_source.empty:
        source_keys = pd.MultiIndex.from_frame(
            conservation_source[["economy_key", "ninth_sector", "ninth_fuel"]].astype(str)
        )
        conservation_source = conservation_source.loc[
            ~source_keys.isin(pd.MultiIndex.from_tuples(sorted(general_parent_source_keys)))
        ]
    conservation_diagnostics = _build_conservation_diagnostics(
        conservation_source,
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
    if not general_fill_diagnostics.empty:
        diagnostics = pd.concat(
            [diagnostics, general_fill_diagnostics],
            ignore_index=True,
            sort=False,
        )
    if not parent_child_diagnostics.empty:
        diagnostics = pd.concat(
            [diagnostics, parent_child_diagnostics],
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


def build_unallocated_projection_flow_context(
    diagnostics: pd.DataFrame,
    esto_data: pd.DataFrame,
    projection_df: pd.DataFrame,
    base_year: int,
    projection_years: Sequence[int],
) -> pd.DataFrame:
    """Return long-form unallocated values plus same-family ESTO context."""
    if diagnostics is None or diagnostics.empty:
        return pd.DataFrame()
    unallocated = diagnostics[
        diagnostics.get("diagnostic_type", pd.Series(index=diagnostics.index, dtype=str))
        .astype(str)
        .eq("unallocated_no_economy_base_year")
    ].copy()
    if unallocated.empty:
        return pd.DataFrame()

    key_columns = ["economy_key", "ninth_sector", "ninth_fuel", "flow_family"]
    for column in key_columns:
        if column not in unallocated.columns:
            unallocated[column] = ""
    contexts = (
        unallocated[["economy_key", "flow_family"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    rows: list[dict] = []

    projected_years = [
        int(year)
        for year in projection_years
        if year in unallocated.columns or str(int(year)) in unallocated.columns
    ]
    historical_source = pd.DataFrame()
    historical_year_columns: dict[int, object] = {}
    if esto_data is not None and not esto_data.empty:
        historical_source = esto_data.copy()
        historical_source["economy_key"] = historical_source["economy"].map(
            normalize_economy_key
        )
        historical_source["flow_family"] = historical_source["flows"].map(
            _esto_flow_family
        )
        historical_year_columns = {
            int(column): column
            for column in historical_source.columns
            if str(column).isdigit() and int(column) <= int(base_year)
        }
    projected_source = pd.DataFrame()
    if projection_df is not None and not projection_df.empty:
        projected_source = projection_df.copy()
        projected_source["flow_family"] = projected_source["esto_flow"].map(
            _esto_flow_family
        )

    for _, context in contexts.iterrows():
        economy_key = str(context["economy_key"])
        flow_family = str(context["flow_family"])
        context_key = f"{economy_key}|{flow_family}"
        source_rows = unallocated[
            unallocated["economy_key"].astype(str).eq(economy_key)
            & unallocated["flow_family"].astype(str).eq(flow_family)
        ]
        for _, target_row in source_rows[
            ["ninth_sector", "ninth_fuel", "esto_flow", "esto_product"]
        ].drop_duplicates().iterrows():
            rows.append(
                {
                    "diagnostic_type": "unallocated_projection_context",
                    "diagnostic_record_type": "unallocated_target_mapping",
                    "context_key": context_key,
                    "economy_key": economy_key,
                    "flow_family": flow_family,
                    "ninth_sector": target_row["ninth_sector"],
                    "ninth_fuel": target_row["ninth_fuel"],
                    "esto_flow": target_row["esto_flow"],
                    "esto_product": target_row["esto_product"],
                    "year": pd.NA,
                    "value": pd.NA,
                }
            )
        source_pairs = source_rows[
            ["ninth_sector", "ninth_fuel", *projected_years]
        ].drop_duplicates(subset=["ninth_sector", "ninth_fuel"])
        for _, source_row in source_pairs.iterrows():
            for year in projected_years:
                rows.append(
                    {
                        "diagnostic_type": "unallocated_projection_context",
                        "diagnostic_record_type": "unallocated_projection",
                        "context_key": context_key,
                        "economy_key": economy_key,
                        "flow_family": flow_family,
                        "ninth_sector": source_row["ninth_sector"],
                        "ninth_fuel": source_row["ninth_fuel"],
                        "esto_flow": "",
                        "esto_product": "",
                        "year": year,
                        "value": float(source_row.get(year, 0.0) or 0.0),
                    }
                )

        if not historical_source.empty and flow_family:
            historical = historical_source[
                historical_source["economy_key"].eq(economy_key)
                & historical_source["flow_family"].eq(flow_family)
            ].copy()
            historical_years = sorted(historical_year_columns)
            if not historical.empty and historical_years:
                source_year_columns = [
                    historical_year_columns[year] for year in historical_years
                ]
                historical = (
                    historical.groupby(
                        ["economy_key", "flows", "products"], dropna=False
                    )[source_year_columns]
                    .sum()
                    .reset_index()
                )
                for _, history_row in historical.iterrows():
                    for year in historical_years:
                        rows.append(
                            {
                                "diagnostic_type": "unallocated_projection_context",
                                "diagnostic_record_type": "historical_flow_family",
                                "context_key": context_key,
                                "economy_key": economy_key,
                                "flow_family": flow_family,
                                "ninth_sector": "",
                                "ninth_fuel": "",
                                "esto_flow": history_row["flows"],
                                "esto_product": history_row["products"],
                                "year": year,
                                "value": float(
                                    history_row.get(
                                        historical_year_columns[year],
                                        0.0,
                                    )
                                    or 0.0
                                ),
                            }
                        )

        if not projected_source.empty and flow_family:
            projected = projected_source[
                projected_source["economy_key"].astype(str).eq(economy_key)
                & projected_source["flow_family"].eq(flow_family)
            ].copy()
            available_projection_years = [
                year for year in projected_years if year in projected.columns
            ]
            for _, projected_row in projected.iterrows():
                for year in available_projection_years:
                    rows.append(
                        {
                            "diagnostic_type": "unallocated_projection_context",
                            "diagnostic_record_type": "allocated_projection_flow_family",
                            "context_key": context_key,
                            "economy_key": economy_key,
                            "flow_family": flow_family,
                            "ninth_sector": "",
                            "ninth_fuel": "",
                            "esto_flow": projected_row["esto_flow"],
                            "esto_product": projected_row["esto_product"],
                            "year": year,
                            "value": float(projected_row.get(year, 0.0) or 0.0),
                        }
                    )
    return pd.DataFrame(rows)


def carry_transformation_owned_all_zero_own_use(
    projection_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
    ninth_series: pd.DataFrame,
    base_values: pd.DataFrame,
    projection_years: Sequence[int],
    owned_loss_flows: dict[str, str],
    all_zero_carry_exceptions: dict[tuple[str, str], str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carry eligible transformation own-use energy through all-zero projections.

    ``owned_loss_flows`` is deliberately supplied by the transformation
    workflow from its process registry.  That keeps ownership in one place and
    prevents proxy-owned own-use rows (notably LNG) from being emitted twice.
    A nonzero Ninth source remains authoritative, including zero years inside
    its supplied series.
    """
    required_base = {"economy_key", "esto_flow", "esto_product", "base_value"}
    required_mapping = {"ninth_sector", "ninth_fuel", "esto_flow", "esto_product"}
    if (
        not owned_loss_flows
        or base_values.empty
        or not required_base.issubset(base_values.columns)
        or not required_mapping.issubset(mapping_df.columns)
    ):
        return projection_df, pd.DataFrame()

    exception_reasons = dict(all_zero_carry_exceptions or {})
    result = projection_df.copy()
    if result.empty:
        result = pd.DataFrame(columns=["economy_key", "esto_flow", "esto_product", *projection_years])
    for year in projection_years:
        if year not in result.columns:
            result[year] = 0.0

    mapping = mapping_df[list(required_mapping)].copy()
    for column in required_mapping:
        mapping[column] = mapping[column].fillna("").astype(str).str.strip()
    mapping = mapping[mapping["esto_flow"].isin(owned_loss_flows)].drop_duplicates()

    source = ninth_series.copy()
    if not source.empty:
        for column in ("economy_key", "ninth_sector", "ninth_fuel"):
            source[column] = source[column].fillna("").astype(str).str.strip()
        for year in projection_years:
            if year not in source.columns:
                source[year] = 0.0

    diagnostics: list[dict[str, object]] = []
    candidates = base_values.loc[
        base_values["esto_flow"].astype(str).isin(owned_loss_flows)
        & pd.to_numeric(base_values["base_value"], errors="coerce").fillna(0.0).ne(0.0)
    ].copy()
    for _, candidate in candidates.iterrows():
        economy_key = str(candidate["economy_key"]).strip()
        flow = str(candidate["esto_flow"]).strip()
        product = str(candidate["esto_product"]).strip()
        base_value = float(candidate["base_value"])
        exception_reason = exception_reasons.get((economy_key, flow))
        if exception_reason:
            diagnostics.append({
                "diagnostic_type": "transformation_own_use_ninth_projection_all_zero",
                "economy_key": economy_key,
                "esto_flow": flow,
                "esto_product": product,
                "leap_process_label": owned_loss_flows[flow],
                "signed_base_year_value": base_value,
                "ninth_projection_state": "shutdown_exception",
                "owner_workflow": "transformation_workflow",
                "owner_writes_as": "transformation_auxiliary_fuel_use",
                "process_output_nonzero_every_projection_year": False,
                "proposed_action": "skip_confirmed_shutdown",
                "provenance": "economy_flow_shutdown_exception",
                "exception_reason": exception_reason,
            })
            continue
        source_pairs = mapping.loc[
            mapping["esto_flow"].eq(flow) & mapping["esto_product"].eq(product),
            ["ninth_sector", "ninth_fuel"],
        ].drop_duplicates()
        source_rows = source.iloc[0:0].copy()
        if not source_pairs.empty and not source.empty:
            source_rows = source.merge(source_pairs, on=["ninth_sector", "ninth_fuel"], how="inner")
            source_rows = source_rows[source_rows["economy_key"].eq(economy_key)]
        ninth_state = "absent" if source_rows.empty else "all_zero"
        if not source_rows.empty:
            source_values = source_rows[list(projection_years)].apply(pd.to_numeric, errors="coerce").fillna(0.0)
            if source_values.ne(0.0).any().any():
                continue

        key_mask = (
            result["economy_key"].astype(str).eq(economy_key)
            & result["esto_flow"].astype(str).eq(flow)
            & result["esto_product"].astype(str).eq(product)
        )
        if key_mask.any():
            # A direct zero source allocated to this target already has a row.
            # Replacing all years together ensures no isolated Ninth zero is filled.
            result.loc[key_mask, list(projection_years)] = base_value
        else:
            result = pd.concat(
                [result, pd.DataFrame([{
                    "economy_key": economy_key,
                    "esto_flow": flow,
                    "esto_product": product,
                    **{year: base_value for year in projection_years},
                }])],
                ignore_index=True,
                sort=False,
            )
        diagnostics.append({
            "diagnostic_type": "transformation_own_use_ninth_projection_all_zero",
            "economy_key": economy_key,
            "esto_flow": flow,
            "esto_product": product,
            "leap_process_label": owned_loss_flows[flow],
            "signed_base_year_value": base_value,
            "ninth_projection_state": ninth_state,
            "owner_workflow": "transformation_workflow",
            "owner_writes_as": "transformation_auxiliary_fuel_use",
            # The projection allocator has no process-output denominator. The
            # sector builder is the authority for that process-specific basis.
            "process_output_nonzero_every_projection_year": pd.NA,
            "proposed_action": "carry",
            "provenance": "esto_base_year_carry_forward",
        })
    return result, pd.DataFrame(diagnostics)


def build_esto_projection_table(
    ninth_data: pd.DataFrame,
    esto_data: pd.DataFrame,
    mapping_path: str | Path | tuple[str | Path, str],
    base_year: int,
    projection_years: Sequence[int],
    scenario: str = DEFAULT_SCENARIO,
    sign_stable_flows: Iterable[str] | str | None = None,
    strict_conservation: bool = False,
    fill_missing_ninth_sectors: bool = False,
    owner_workflow: str = "",
    existing_output_pairs: pd.DataFrame | None = None,
    allocation_anchor_esto_data: pd.DataFrame | None = None,
    return_allocation_provenance: bool = False,
    transformation_owned_loss_flows: dict[str, str] | None = None,
    transformation_owned_all_zero_carry_exceptions: dict[tuple[str, str], str] | None = None,
) -> (
    tuple[pd.DataFrame, pd.DataFrame]
    | tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
):
    """Return projected ESTO values plus allocation diagnostics.

    Args:
        sign_stable_flows:
            Optional ESTO flow names to allocate with sign-stable routing.
            Use `[]` or `"off"` for pure legacy abs-share behavior.
            Use `"all"` to apply sign-stable routing to every mapped ESTO flow.
        strict_conservation:
            If True, raise ValueError when allocated totals do not match source totals.
        return_allocation_provenance:
            If True, also return one long-form row per allocated 9th source
            pair, ESTO target pair, and projection year.
        allocation_anchor_esto_data:
            Optional unfiltered ESTO rows. Only mapped 09.06/09.08 subtotal
            parents are selected from this data, solely to establish
            base-year allocation shares; they are never returned as output.
    """
    if isinstance(mapping_path, tuple):
        mapping_file, mapping_sheet = Path(mapping_path[0]), str(mapping_path[1])
    else:
        mapping_file, mapping_sheet = Path(mapping_path), None
    if not config_table_exists(mapping_file, mapping_sheet):
        empty = (pd.DataFrame(), pd.DataFrame())
        return (*empty, pd.DataFrame()) if return_allocation_provenance else empty
    mapping_df = read_config_table(
        mapping_file,
        sheet_name=mapping_sheet,
        dtype=str,
    ).fillna("")
    if mapping_df.empty:
        empty = (pd.DataFrame(), pd.DataFrame())
        return (*empty, pd.DataFrame()) if return_allocation_provenance else empty
    allocation_base_data = esto_data
    if allocation_anchor_esto_data is not None:
        anchor_rows = select_approved_parent_anchor_rows(
            allocation_anchor_esto_data,
            mapping_df,
        )
        if not anchor_rows.empty:
            allocation_base_data = pd.concat(
                [esto_data, anchor_rows],
                ignore_index=True,
                sort=False,
            )
    general_child_flow_profiles = build_general_child_flow_profiles(
        esto_data,
        mapping_df,
        base_year,
    )
    ninth_filtered = filter_ninth_projection_rows(ninth_data, scenario=scenario)
    ninth_pairs = add_ninth_pair_columns(ninth_filtered)
    # 09.06 is always retained for its established residual policy. With the
    # generalized opt-in enabled, retain other mapped subtotal parents only
    # when the current ESTO data prove they have active detailed children.
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
        eligible_parent_pairs: set[tuple[str, str]] = set()
        if fill_missing_ninth_sectors and not general_child_flow_profiles.empty:
            eligible_parent_flows = set(
                general_child_flow_profiles.loc[
                    general_child_flow_profiles["owner_workflow"].astype(str).eq(
                        str(owner_workflow or "").strip()
                    ),
                    "profile_parent_flow",
                ].astype(str)
            ) & APPROVED_MISSING_NINTH_PARENT_FLOWS
            eligible_parent_pairs = set(map(
                tuple,
                mapping_df.loc[
                    mapping_df["esto_flow"].astype(str).isin(eligible_parent_flows),
                    ["ninth_sector", "ninth_fuel"],
                ].astype(str).to_numpy(),
            ))
        parent_pair_index = pd.MultiIndex.from_frame(
            ninth_parent_pairs[["ninth_sector", "ninth_fuel"]].astype(str)
        )
        general_parent_mask = parent_pair_index.isin(
            pd.MultiIndex.from_tuples(
                sorted(eligible_parent_pairs),
                names=["ninth_sector", "ninth_fuel"],
            )
        ) if eligible_parent_pairs else pd.Series(False, index=ninth_parent_pairs.index)
        ninth_parent_pairs = ninth_parent_pairs.loc[
            subtotal_mask
            & (
                ninth_parent_pairs["ninth_sector"].eq(GAS_PARENT_NINTH_SECTOR)
                | general_parent_mask
            )
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
            duplicate_parent = normal_index.isin(subtotal_index)
            ninth_pairs = ninth_pairs.loc[~duplicate_parent]
        ninth_pairs = pd.concat([ninth_pairs, ninth_parent_pairs], ignore_index=True, sort=False)
    ninth_pairs["economy_key"] = ninth_pairs["economy"].apply(normalize_economy_key)
    ninth_series = build_ninth_projection_series(ninth_pairs, projection_years)
    base_values = build_esto_base_year_values(allocation_base_data, base_year)
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
    allocation_result = allocate_ninth_projection_to_esto(
        mapping_df,
        ninth_series,
        base_values,
        projection_years,
        sign_stable_flows=sign_stable_flows,
        strict_conservation=strict_conservation,
        child_flow_profiles=child_flow_profiles,
        gas_child_flow_profiles=gas_child_flow_profiles,
        general_child_flow_profiles=general_child_flow_profiles,
        fill_missing_ninth_sectors=fill_missing_ninth_sectors,
        owner_workflow=owner_workflow,
        existing_output_pairs=existing_output_pairs,
        return_allocation_provenance=return_allocation_provenance,
    )
    if return_allocation_provenance:
        projection_df, diagnostics, allocation_provenance = allocation_result
    else:
        projection_df, diagnostics = allocation_result
        allocation_provenance = None

    own_use_diagnostics = pd.DataFrame()
    if fill_missing_ninth_sectors and transformation_owned_loss_flows:
        projection_df, own_use_diagnostics = carry_transformation_owned_all_zero_own_use(
            projection_df,
            mapping_df,
            ninth_series,
            base_values,
            projection_years,
            transformation_owned_loss_flows,
            transformation_owned_all_zero_carry_exceptions,
        )

    context = build_unallocated_projection_flow_context(
        diagnostics,
        esto_data,
        projection_df,
        base_year,
        projection_years,
    )
    if not context.empty:
        diagnostics = pd.concat(
            [diagnostics, context],
            ignore_index=True,
            sort=False,
        )
    if not own_use_diagnostics.empty:
        diagnostics = pd.concat(
            [diagnostics, own_use_diagnostics],
            ignore_index=True,
            sort=False,
        )
    if diagnostics is not None and not diagnostics.empty:
        diagnostics["scenario"] = str(scenario)

    if return_allocation_provenance:
        return projection_df, diagnostics, allocation_provenance
    return projection_df, diagnostics


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
