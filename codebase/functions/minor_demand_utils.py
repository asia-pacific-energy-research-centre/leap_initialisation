"""
Pure computation helpers extracted from minor_demand_workflow.py.

These functions are stateless: they take parameters and return values, with no
file I/O and no reads of module-level configuration globals.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from codebase.functions.leap_core import sanitize_leap_name
from codebase.functions.leap_expressions import build_data_expression_from_row
from codebase.functions.ninth_projection_mapping import normalize_economy_key


def _year_columns(df: pd.DataFrame) -> list[int]:
    """Return a sorted list of year columns, coerced to int where possible."""
    year_cols = []
    for col in df.columns:
        if str(col).isdigit():
            year_cols.append(int(col))
    return sorted(set(year_cols))


def _normalize_year_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure year columns are int for consistent downstream handling."""
    rename_map = {col: int(col) for col in df.columns if str(col).isdigit()}
    return df.rename(columns=rename_map)


def _is_current_accounts_label(value: object) -> bool:
    """Return True when a scenario label is a Current Accounts variant."""
    text = str(value).strip().lower()
    return text in {"current accounts", "current account"}


def _normalize_fuel_activity_mode(mode: object) -> str:
    """Normalize fuel activity mode and preserve legacy aliases."""
    normalized = str(mode).strip().lower()
    if normalized == "fuel_share":
        return "activity_as_energy_intensity_as_one"
    return normalized


def _resolve_fuel_activity_units(
    activity_units: Mapping[str, str],
    mode: str,
) -> dict[str, str]:
    """
    Resolve fuel-branch activity units for the selected fuel activity mode.

    Sector rows keep the configured Activity Level units. This only affects fuel rows.
    """
    resolved = {
        "units": str(activity_units.get("units", "")),
        "scale": str(activity_units.get("scale", "")),
        "per": str(activity_units.get("per", "")),
    }
    if _normalize_fuel_activity_mode(mode) == "sector_share":
        resolved["units"] = "Share"
        resolved["scale"] = ""
        resolved["per"] = ""
    if _normalize_fuel_activity_mode(mode) == "activity_as_energy_intensity_as_one":
        resolved["units"] = "Unspecified Unit"
        resolved["scale"] = ""
        resolved["per"] = ""
    return resolved


def _resolve_sector_activity_units(
    activity_units: Mapping[str, str],
    mode: str,
) -> dict[str, str]:
    """Resolve sector-branch activity units for the selected fuel activity mode."""
    resolved = {
        "units": str(activity_units.get("units", "")),
        "scale": str(activity_units.get("scale", "")),
        "per": str(activity_units.get("per", "")),
    }
    normalized = _normalize_fuel_activity_mode(mode)
    if normalized in {"activity_as_energy_intensity_as_one", "sector_share"}:
        resolved["units"] = "Unspecified Unit"
        resolved["scale"] = ""
        resolved["per"] = ""
    return resolved


def filter_mapping_for_minor_demand(
    mapping: pd.DataFrame,
    esto_data: pd.DataFrame,
    flow_configs: Sequence[dict],
) -> pd.DataFrame:
    """
    Filter mapping rows to:
    - our minor demand flows
    - non-subtotal ESTO pairs (present in filtered ESTO data)
    - non-empty 9th sector/fuel labels
    """
    flow_list = [cfg["esto_flow"] for cfg in flow_configs]
    mapping = mapping[mapping["esto_flow"].isin(flow_list)].copy()
    mapping = mapping[(mapping["9th_sector"] != "") & (mapping["9th_fuel"] != "")]
    # Only keep pairs that exist in non-subtotal ESTO data.
    valid_pairs = (
        esto_data[["flows", "products"]]
        .drop_duplicates()
        .rename(columns={"flows": "esto_flow", "products": "esto_product"})
    )
    mapping = mapping.merge(valid_pairs, on=["esto_flow", "esto_product"], how="inner")
    return mapping


def build_flow_to_sectors(
    mapping: pd.DataFrame, flow_configs: Sequence[dict]
) -> dict[str, list[str]]:
    """
    Build mapping: ESTO flow -> list of 9th sector codes.

    We also compare against expected mappings (if provided) to flag surprises.
    """
    flow_to_sectors: dict[str, list[str]] = {}
    for cfg in flow_configs:
        flow = cfg["esto_flow"]
        sectors = sorted(
            mapping.loc[mapping["esto_flow"] == flow, "9th_sector"]
            .dropna()
            .unique()
            .tolist()
        )
        sectors = [sector for sector in sectors if sector]
        expected = cfg.get("expected_9th_sectors", [])
        if expected and set(sectors) != set(expected):
            print(
                f"[WARN] Mapping for '{flow}' differs from expectation. "
                f"Expected {expected}, got {sectors}."
            )
        flow_to_sectors[flow] = sectors
    return flow_to_sectors


def build_flow_to_fuels(
    esto_data: pd.DataFrame,
    flow_configs: Sequence[dict],
    economy_key: str | None,
) -> dict[str, list[str]]:
    """
    Build mapping: ESTO flow -> list of ESTO product (fuel) labels.

    The fuels become leaf branches in LEAP. Names are kept exactly as in ESTO,
    except we sanitize them for LEAP safety when building branch paths.
    """
    working = esto_data.copy()
    if economy_key:
        working = working[working["economy_key"] == economy_key]
    flow_to_fuels: dict[str, list[str]] = {}
    for cfg in flow_configs:
        flow = cfg["esto_flow"]
        fuels = (
            working.loc[working["flows"] == flow, "products"]
            .dropna()
            .astype(str)
            .str.strip()
            .unique()
            .tolist()
        )
        flow_to_fuels[flow] = sorted([fuel for fuel in fuels if fuel])
    return flow_to_fuels


def build_sector_projection(
    ninth_data: pd.DataFrame, projection_years: Sequence[int]
) -> pd.DataFrame:
    """
    Aggregate 9th projections by economy + sector (all fuels combined).
    """
    year_cols = [year for year in projection_years if year in ninth_data.columns]
    working = ninth_data.copy()
    for year in year_cols:
        working[year] = pd.to_numeric(working[year], errors="coerce").fillna(0.0)
    grouped = (
        working.groupby(["economy_key", "9th_sector"], dropna=False)[year_cols]
        .sum()
        .reset_index()
    )
    return grouped


def build_fuel_projection(
    ninth_data: pd.DataFrame, projection_years: Sequence[int]
) -> pd.DataFrame:
    """
    Aggregate 9th projections by economy + sector + fuel.

    This supports future fuel-share intensity logic.
    """
    year_cols = [year for year in projection_years if year in ninth_data.columns]
    working = ninth_data.copy()
    for year in year_cols:
        working[year] = pd.to_numeric(working[year], errors="coerce").fillna(0.0)
    grouped = (
        working.groupby(["economy_key", "9th_sector", "9th_fuel"], dropna=False)[year_cols]
        .sum()
        .reset_index()
    )
    return grouped


def _base_year_column(df: pd.DataFrame, base_year: int) -> int | str | None:
    """Return the matching base-year column name if present."""
    if int(base_year) in df.columns:
        return int(base_year)
    if str(base_year) in df.columns:
        return str(base_year)
    return None


def build_base_year_activity_value(
    esto_data: pd.DataFrame,
    flow: str,
    economy_key: str,
    base_year: int,
) -> float:
    """Return the ESTO base-year total for a flow."""
    year_col = _base_year_column(esto_data, base_year)
    if year_col is None:
        return 0.0
    subset = esto_data[
        (esto_data["economy_key"] == economy_key)
        & (esto_data["flows"] == flow)
    ]
    if subset.empty:
        return 0.0
    values = pd.to_numeric(subset[year_col], errors="coerce").fillna(0.0)
    return float(values.sum())


def build_base_year_fuel_value(
    esto_data: pd.DataFrame,
    flow: str,
    esto_product: str,
    economy_key: str,
    base_year: int,
) -> float:
    """Return the ESTO base-year value for one flow/product row."""
    year_col = _base_year_column(esto_data, base_year)
    if year_col is None:
        return 0.0
    subset = esto_data[
        (esto_data["economy_key"] == economy_key)
        & (esto_data["flows"] == flow)
        & (esto_data["products"] == esto_product)
    ]
    if subset.empty:
        return 0.0
    values = pd.to_numeric(subset[year_col], errors="coerce").fillna(0.0)
    return float(values.sum())


def add_base_year_to_sector_activity(
    activity_series: dict[int, float],
    esto_data: pd.DataFrame,
    flow: str,
    economy_key: str,
    base_year: int,
) -> dict[int, float]:
    """Inject the ESTO base-year total so Current Accounts uses actual history."""
    updated = {int(year): float(value) for year, value in activity_series.items()}
    updated[int(base_year)] = build_base_year_activity_value(
        esto_data,
        flow,
        economy_key,
        base_year,
    )
    return updated


def add_base_year_to_fuel_activity(
    fuel_activity_series: dict[int, float],
    esto_data: pd.DataFrame,
    flow: str,
    esto_product: str,
    economy_key: str,
    base_year: int,
    mode: str,
) -> dict[int, float]:
    """Inject the ESTO base-year fuel value or share."""
    updated = {int(year): float(value) for year, value in fuel_activity_series.items()}
    flow_total = build_base_year_activity_value(esto_data, flow, economy_key, base_year)
    fuel_value = build_base_year_fuel_value(
        esto_data,
        flow,
        esto_product,
        economy_key,
        base_year,
    )
    normalized_mode = _normalize_fuel_activity_mode(mode)
    if normalized_mode == "sector_share":
        updated[int(base_year)] = 0.0 if flow_total == 0.0 else fuel_value / flow_total
    elif normalized_mode == "activity_as_energy_intensity_as_one":
        updated[int(base_year)] = fuel_value
    return updated


def print_allocation_summary(
    projection_df: pd.DataFrame,
    economy_key: str,
    flow_configs: Sequence[dict],
    years_to_show: Sequence[int],
) -> None:
    """
    Print a compact summary of allocated projections for each minor-demand flow.

    This helps verify that Agriculture vs Fishing splits are non-zero and distinct.
    """
    if projection_df is None or projection_df.empty:
        print("[INFO] Allocation summary skipped (no allocated projection data).")
        return
    year_cols = [year for year in years_to_show if year in projection_df.columns]
    if not year_cols:
        print("[INFO] Allocation summary skipped (no matching year columns).")
        return
    print("\n=== Allocation summary (allocated 9th projections) ===")
    for cfg in flow_configs:
        flow = cfg["esto_flow"]
        subset = projection_df[
            (projection_df["economy_key"] == economy_key)
            & (projection_df["esto_flow"] == flow)
        ]
        if subset.empty:
            print(f"- {flow}: no allocated rows.")
            continue
        totals = subset[year_cols].sum().to_dict()
        year_str = ", ".join([f"{year}: {totals.get(year, 0.0):.2f}" for year in year_cols])
        print(f"- {flow}: {year_str}")


def build_activity_series(
    sector_projection: pd.DataFrame,
    flow_to_sectors: dict[str, list[str]],
    flow: str,
    economy_key: str,
    projection_years: Sequence[int],
) -> dict[int, float]:
    """
    Return Activity Level values for a given ESTO flow and economy.

    We sum all 9th sectors that map to this flow.
    """
    sectors = flow_to_sectors.get(flow, [])
    year_cols = [year for year in projection_years if year in sector_projection.columns]
    if not sectors:
        return {year: 0.0 for year in year_cols}
    subset = sector_projection[
        (sector_projection["economy_key"] == economy_key)
        & (sector_projection["9th_sector"].isin(sectors))
    ]
    if subset.empty:
        return {year: 0.0 for year in year_cols}
    totals = subset[year_cols].sum().to_dict()
    return {int(year): float(value) for year, value in totals.items()}


def build_activity_series_from_allocated(
    projection_df: pd.DataFrame,
    flow: str,
    economy_key: str,
    projection_years: Sequence[int],
) -> dict[int, float]:
    """
    Return Activity Level using allocated 9th projections per ESTO flow.
    """
    if projection_df is None or projection_df.empty:
        return {int(year): 0.0 for year in projection_years}
    year_cols = [year for year in projection_years if year in projection_df.columns]
    subset = projection_df[
        (projection_df["economy_key"] == economy_key)
        & (projection_df["esto_flow"] == flow)
    ]
    if subset.empty:
        return {int(year): 0.0 for year in year_cols}
    totals = subset[year_cols].sum().to_dict()
    return {int(year): float(value) for year, value in totals.items()}


def build_intensity_series_uniform(
    projection_years: Sequence[int], value: float
) -> dict[int, float]:
    """Constant intensity for every year."""
    return {int(year): float(value) for year in projection_years}


def build_intensity_series_from_shares(
    fuel_projection: pd.DataFrame,
    sector_projection: pd.DataFrame,
    flow_to_sectors: dict[str, list[str]],
    flow: str,
    esto_product: str,
    economy_key: str,
    projection_years: Sequence[int],
    mapping: pd.DataFrame,
) -> dict[int, float]:
    """
    Derive intensity values using fuel shares.

    This sets intensity = fuel_energy / total_sector_energy for each year,
    so the sum of intensities across fuels = 1.

    NOTE: This is optional; it is *not* the default.
    """
    year_cols = [year for year in projection_years if year in sector_projection.columns]
    sectors = flow_to_sectors.get(flow, [])
    if not sectors:
        return {year: 0.0 for year in year_cols}
    # Map this ESTO product to the 9th fuels it corresponds to.
    mapped_fuels = (
        mapping.loc[
            (mapping["esto_flow"] == flow) & (mapping["esto_product"] == esto_product),
            "9th_fuel",
        ]
        .dropna()
        .unique()
        .tolist()
    )
    if not mapped_fuels:
        return {year: 0.0 for year in year_cols}
    total_energy = build_activity_series(
        sector_projection, flow_to_sectors, flow, economy_key, projection_years
    )
    fuel_subset = fuel_projection[
        (fuel_projection["economy_key"] == economy_key)
        & (fuel_projection["9th_sector"].isin(sectors))
        & (fuel_projection["9th_fuel"].isin(mapped_fuels))
    ]
    if fuel_subset.empty:
        return {year: 0.0 for year in year_cols}
    fuel_energy = fuel_subset[year_cols].sum().to_dict()
    intensity = {}
    for year in year_cols:
        total = total_energy.get(int(year), 0.0)
        if total == 0:
            intensity[int(year)] = 0.0
        else:
            intensity[int(year)] = float(fuel_energy.get(year, 0.0)) / float(total)
    return intensity


def build_intensity_series_from_allocated(
    projection_df: pd.DataFrame,
    flow: str,
    esto_product: str,
    economy_key: str,
    projection_years: Sequence[int],
) -> dict[int, float]:
    """
    Derive intensity from allocated projections: fuel_energy / total_flow_energy.

    This keeps intensities consistent with the agriculture/fishing split.
    """
    if projection_df is None or projection_df.empty:
        return {int(year): 0.0 for year in projection_years}
    year_cols = [year for year in projection_years if year in projection_df.columns]
    total_subset = projection_df[
        (projection_df["economy_key"] == economy_key)
        & (projection_df["esto_flow"] == flow)
    ]
    fuel_subset = projection_df[
        (projection_df["economy_key"] == economy_key)
        & (projection_df["esto_flow"] == flow)
        & (projection_df["esto_product"] == esto_product)
    ]
    if total_subset.empty:
        return {int(year): 0.0 for year in year_cols}
    total_energy = total_subset[year_cols].sum().to_dict()
    fuel_energy = fuel_subset[year_cols].sum().to_dict() if not fuel_subset.empty else {}
    intensity = {}
    for year in year_cols:
        total = float(total_energy.get(year, 0.0))
        if total == 0.0:
            intensity[int(year)] = 0.0
        else:
            intensity[int(year)] = float(fuel_energy.get(year, 0.0)) / total
    return intensity


def build_fuel_activity_series_from_allocated(
    projection_df: pd.DataFrame,
    sector_activity: dict[int, float],
    flow: str,
    esto_product: str,
    economy_key: str,
    projection_years: Sequence[int],
) -> dict[int, float]:
    """
    Activity per fuel = sector activity * allocated fuel share.
    """
    if projection_df is None or projection_df.empty:
        return {int(year): 0.0 for year in projection_years}
    year_cols = [year for year in projection_years if year in projection_df.columns]
    total_subset = projection_df[
        (projection_df["economy_key"] == economy_key)
        & (projection_df["esto_flow"] == flow)
    ]
    fuel_subset = projection_df[
        (projection_df["economy_key"] == economy_key)
        & (projection_df["esto_flow"] == flow)
        & (projection_df["esto_product"] == esto_product)
    ]
    if total_subset.empty:
        return {int(year): 0.0 for year in year_cols}
    total_energy = total_subset[year_cols].sum().to_dict()
    fuel_energy = fuel_subset[year_cols].sum().to_dict() if not fuel_subset.empty else {}
    activity = {}
    for year in year_cols:
        total = float(total_energy.get(year, 0.0))
        if total == 0.0:
            share = 0.0
        else:
            share = float(fuel_energy.get(year, 0.0)) / total
        activity[int(year)] = float(sector_activity.get(int(year), 0.0)) * share
    return activity


def build_fuel_activity_series_sector_share_from_allocated(
    projection_df: pd.DataFrame,
    flow: str,
    esto_product: str,
    economy_key: str,
    projection_years: Sequence[int],
) -> dict[int, float]:
    """
    Activity per fuel = allocated fuel share of sector total (fraction 0..1).
    """
    if projection_df is None or projection_df.empty:
        return {int(year): 0.0 for year in projection_years}
    year_cols = [year for year in projection_years if year in projection_df.columns]
    total_subset = projection_df[
        (projection_df["economy_key"] == economy_key)
        & (projection_df["esto_flow"] == flow)
    ]
    fuel_subset = projection_df[
        (projection_df["economy_key"] == economy_key)
        & (projection_df["esto_flow"] == flow)
        & (projection_df["esto_product"] == esto_product)
    ]
    if total_subset.empty:
        return {int(year): 0.0 for year in year_cols}
    total_energy = total_subset[year_cols].sum().to_dict()
    fuel_energy = fuel_subset[year_cols].sum().to_dict() if not fuel_subset.empty else {}
    shares: dict[int, float] = {}
    for year in year_cols:
        total = float(total_energy.get(year, 0.0))
        if total == 0.0:
            shares[int(year)] = 0.0
        else:
            shares[int(year)] = float(fuel_energy.get(year, 0.0)) / total
    return shares


def build_fuel_activity_series_from_shares(
    fuel_projection: pd.DataFrame,
    sector_projection: pd.DataFrame,
    flow_to_sectors: dict[str, list[str]],
    flow: str,
    esto_product: str,
    economy_key: str,
    projection_years: Sequence[int],
    mapping: pd.DataFrame,
    sector_activity: dict[int, float],
) -> dict[int, float]:
    """
    Activity per fuel = sector activity * fuel share derived from 9th fuel projections.
    """
    share_series = build_intensity_series_from_shares(
        fuel_projection,
        sector_projection,
        flow_to_sectors,
        flow,
        esto_product,
        economy_key,
        projection_years,
        mapping,
    )
    return {
        int(year): float(sector_activity.get(int(year), 0.0)) * float(share_series.get(int(year), 0.0))
        for year in projection_years
    }


def build_fuel_activity_series_sector_share_from_shares(
    fuel_projection: pd.DataFrame,
    sector_projection: pd.DataFrame,
    flow_to_sectors: dict[str, list[str]],
    flow: str,
    esto_product: str,
    economy_key: str,
    projection_years: Sequence[int],
    mapping: pd.DataFrame,
) -> dict[int, float]:
    """
    Activity per fuel = fuel share of sector total (fraction 0..1), from 9th shares.
    """
    return build_intensity_series_from_shares(
        fuel_projection,
        sector_projection,
        flow_to_sectors,
        flow,
        esto_product,
        economy_key,
        projection_years,
        mapping,
    )


def _build_gdp_index_series(
    gdp_wide: pd.DataFrame,
    economy_key: str,
    projection_years: Sequence[int],
    base_year: int,
) -> dict[int, float]:
    """Return GDP indexed to base_year = 1.0, keyed by int year."""
    if economy_key not in gdp_wide.index:
        print(f"[WARN] Economy '{economy_key}' not in GDP data; using flat index (1.0).")
        return {int(year): 1.0 for year in projection_years}
    series = gdp_wide.loc[economy_key].dropna().astype(float)
    base = float(series.get(base_year, 0.0))
    if base == 0.0:
        print(f"[WARN] GDP base-year ({base_year}) is zero for '{economy_key}'; using flat index.")
        return {int(year): 1.0 for year in projection_years}
    return {
        int(year): (float(series[year]) / base if year in series.index else float("nan"))
        for year in projection_years
    }


def build_intensity_adjustment_series(
    ninth_sector_activity: dict[int, float],
    base_sector_energy: float,
    gdp_index: dict[int, float],
    projection_years: Sequence[int],
    base_year: int,
) -> dict[int, float]:
    """
    IA[year] = (ninth_tgt[year] / (gdp_index[year] * base_sector_energy)) - 1

    At base_year = 0.0 by construction (ninth = base_energy, gdp_index = 1.0).
    Negative values mean the 9th projects efficiency gains relative to flat-GDP intensity.
    Applied per fuel branch but computed at sector level (same value for all fuels in sector).
    """
    result: dict[int, float] = {}
    for year in projection_years:
        ninth_val = float(ninth_sector_activity.get(int(year), 0.0))
        gdp_idx = float(gdp_index.get(int(year), 1.0))
        if pd.isna(gdp_idx):
            gdp_idx = 1.0
        gdp_derived = gdp_idx * base_sector_energy
        result[int(year)] = 0.0 if gdp_derived == 0.0 else (ninth_val / gdp_derived) - 1.0
    result[int(base_year)] = 0.0
    return result


def build_branch_path(parts: Sequence[str]) -> str:
    """Join branch path segments after sanitizing each name."""
    cleaned = [sanitize_leap_name(part) for part in parts if part]
    cleaned = [segment for segment in cleaned if segment]
    return "\\".join(cleaned)


def build_year_rows(
    branch_path: str,
    measure: str,
    scenario: str,
    value_by_year: dict[int, float],
    units: str,
    scale: str,
    per_value: str,
) -> list[dict]:
    """Return log-style rows for LEAP export (one row per year)."""
    rows = []
    for year, value in sorted(value_by_year.items()):
        rows.append(
            {
                "Branch_Path": branch_path,
                "Scenario": scenario,
                "Measure": measure,
                "Units": units,
                "Scale": scale,
                "Per...": per_value,
                "Date": int(year),
                "Value": float(value),
            }
        )
    return rows


def build_data_expression(
    row: pd.Series,
    year_cols: Sequence[int],
    base_year: int | None = None,
) -> str:
    """Return a LEAP Data(...) expression from year columns."""
    if base_year is not None and _is_current_accounts_label(row.get("Scenario", "")):
        ordered_years = sorted(int(year) for year in year_cols)
        base_year_value = None
        if int(base_year) in set(ordered_years):
            base_year_value = pd.to_numeric(row.get(int(base_year)), errors="coerce")
        if pd.isna(base_year_value):
            for year in ordered_years:
                candidate = pd.to_numeric(row.get(int(year)), errors="coerce")
                if pd.isna(candidate):
                    continue
                base_year_value = float(candidate)
                break
        if pd.isna(base_year_value):
            base_year_value = 0.0
        return f"Data({int(base_year)}, {float(base_year_value)})"
    return build_data_expression_from_row(row, year_cols)


def build_expression_export_df(
    export_df: pd.DataFrame,
    base_year: int | None = None,
) -> pd.DataFrame:
    """
    Convert a year-column export DF into an Expression-based DF.
    Mirrors the LEAP-style "Export" template (no year columns).
    """
    year_cols = sorted([col for col in export_df.columns if str(col).isdigit()])
    expression_df = export_df.copy()
    expression_df["Expression"] = expression_df.apply(
        lambda row: build_data_expression(row, year_cols, base_year=base_year),
        axis=1,
    )
    expression_df = expression_df.drop(columns=year_cols)
    base_cols = ["Branch Path", "Variable", "Scenario", "Region", "Scale", "Units", "Per...", "Expression"]
    level_cols = [col for col in expression_df.columns if col.startswith("Level ")]
    expression_df = expression_df[base_cols + level_cols]
    return expression_df


def collapse_current_accounts_years(
    export_df: pd.DataFrame,
    base_year: int,
) -> pd.DataFrame:
    """
    Keep only base-year values for Current Accounts rows.

    If the base-year column is absent, anchor from the earliest available year.
    """
    working = export_df.copy()
    year_cols = sorted(int(col) for col in working.columns if str(col).isdigit())
    if not year_cols or "Scenario" not in working.columns:
        return working

    current_mask = working["Scenario"].apply(_is_current_accounts_label)
    if not current_mask.any():
        return working

    keep_year = int(base_year) if int(base_year) in set(year_cols) else min(year_cols)
    for year in year_cols:
        if int(year) == keep_year:
            continue
        working.loc[current_mask, int(year)] = pd.NA
    return working
