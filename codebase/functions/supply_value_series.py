"""Supply flow selection and year-series construction helpers."""
from __future__ import annotations

import pandas as pd

from codebase.functions.esto_data_utils import (
    _match_code_prefix,
    sum_years,
    try_debug_breakpoint,
)
from codebase.functions.ninth_projection_mapping import normalize_economy_key
from codebase.functions.supply_config_builder import map_code_label

OUTPUT_FLOW_KEYS = {"exports"}


def is_output_flow(flow_key):
    """Return True when a flow key represents an output that should be positive in LEAP."""
    if not flow_key:
        return False
    return str(flow_key).strip().lower() in OUTPUT_FLOW_KEYS


def normalize_supply_flow_total(flow_key, total_value):
    """Normalize the sign of a supply flow total based on its LEAP meaning."""
    try:
        if is_output_flow(flow_key):
            return abs(total_value)
        return total_value
    except Exception as exc:
        print(f"Failed to normalize flow total for {flow_key}: {exc}")
        try_debug_breakpoint()
        raise


def get_years_from(year_cols, base_year):
    """Return a list with the base year column when available."""
    try:
        if base_year in year_cols:
            return [base_year]
        return []
    except Exception as exc:
        print(f"Failed to filter year columns from {base_year}: {exc}")
        try_debug_breakpoint()
        raise


def select_rows(df, filters):
    """Return filtered rows based on a dict of column -> value."""
    try:
        mask = pd.Series(True, index=df.index)
        for column, value in filters.items():
            if column in df.columns:
                mask &= df[column].eq(value)
                continue
            mask &= False
        return df.loc[mask]
    except Exception as exc:
        print(f"Failed to filter rows with {filters}: {exc}")
        try_debug_breakpoint()
        raise


def select_flow_rows(df, economy, flow_value):
    """Select rows for a flow value using flows or sectors column."""
    try:
        if "flows" in df.columns:
            return select_rows(df, {"economy": economy, "flows": flow_value})
        if "sectors" in df.columns:
            return select_rows(df, {"economy": economy, "sectors": flow_value})
        return df.iloc[0:0]
    except Exception as exc:
        print(f"Failed to select flow rows for {flow_value}: {exc}")
        try_debug_breakpoint()
        raise


def select_fuel_rows(
    df,
    fuel_code_ninth,
    fuel_label_esto,
    fuel_name=None,
    code_to_name_mapping=None,
):
    """Select rows for a fuel using products or fuels/subfuels."""
    try:
        if "products" in df.columns:
            if code_to_name_mapping and fuel_name:
                mapped_products = df["products"].apply(
                    lambda value: map_code_label(value, code_to_name_mapping)
                )
                matched = df[mapped_products.eq(fuel_name)]
                if not matched.empty:
                    return matched
            return df[df["products"].apply(lambda value: _match_code_prefix(value, fuel_label_esto))]
        if "subfuels" in df.columns:
            matched_subfuels = df[
                df["subfuels"].apply(lambda value: _match_code_prefix(value, fuel_code_ninth))
            ]
            if not matched_subfuels.empty:
                return matched_subfuels
            # Some 9th rows carry the canonical fuel code in `fuels` with `subfuels=x`
            # (for example electricity exports). Fall back to fuels in that case.
            if "fuels" in df.columns:
                matched_fuels = df[
                    df["fuels"].apply(lambda value: _match_code_prefix(value, fuel_code_ninth))
                ]
                if not matched_fuels.empty:
                    return matched_fuels
            return matched_subfuels
        if "fuels" in df.columns:
            return df[df["fuels"].apply(lambda value: _match_code_prefix(value, fuel_code_ninth))]
        return df.iloc[0:0]
    except Exception as exc:
        print(f"Failed to select fuel rows: {exc}")
        try_debug_breakpoint()
        raise


def get_flow_total_for_fuel(
    data,
    year_cols,
    base_year,
    economy,
    fuel_config,
    flow_key,
    flow_value,
    code_to_name_mapping=None,
):
    """Sum the base-year value for a flow/fuel/economy combination and normalize the sign."""
    try:
        if flow_value is None:
            return 0.0
        if base_year not in year_cols:
            print(f"Warning: base year {base_year} missing for economy {economy}")
            return 0.0
        fuel_rows = select_fuel_rows(
            data,
            fuel_config.get("fuel_code_ninth"),
            fuel_config["fuel_label_esto"],
            fuel_name=fuel_config.get("fuel_name"),
            code_to_name_mapping=code_to_name_mapping,
        )
        flow_rows = select_flow_rows(fuel_rows, economy, flow_value)
        total = sum_years(flow_rows, [base_year])
        return normalize_supply_flow_total(flow_key, total)
    except Exception as exc:
        print(f"Failed to sum flow {flow_key} for fuel {fuel_config}: {exc}")
        try_debug_breakpoint()
        raise


def get_flow_series_for_fuel(
    data,
    year_cols,
    economy,
    fuel_config,
    flow_key,
    flow_value,
    base_year,
    final_year,
    code_to_name_mapping=None,
):
    """Return year->value from source rows for one flow/fuel/economy."""
    try:
        if flow_value is None:
            return {year: 0.0 for year in range(base_year, final_year + 1)}
        fuel_rows = select_fuel_rows(
            data,
            fuel_config.get("fuel_code_ninth"),
            fuel_config["fuel_label_esto"],
            fuel_name=fuel_config.get("fuel_name"),
            code_to_name_mapping=code_to_name_mapping,
        )
        flow_rows = select_flow_rows(fuel_rows, economy, flow_value)
        out = {year: 0.0 for year in range(base_year, final_year + 1)}
        if flow_rows.empty:
            return out
        for year in range(base_year, final_year + 1):
            if year not in year_cols:
                continue
            value = pd.to_numeric(flow_rows[year], errors="coerce").fillna(0.0).sum()
            out[year] = normalize_supply_flow_total(flow_key, float(value))
        return out
    except Exception as exc:
        print(
            f"Failed to build flow series for {economy}, {fuel_config}, {flow_key}: {exc}"
        )
        try_debug_breakpoint()
        raise


def _get_projection_series(
    projection_lookup,
    economy,
    flow_value,
    product_value,
    projection_years,
):
    """Return a projection series for an ESTO flow/product pair."""
    if projection_lookup is None or not projection_years:
        return {year: 0.0 for year in projection_years}
    econ_key = normalize_economy_key(economy)
    key = (econ_key, str(flow_value).strip(), str(product_value).strip())
    if key not in projection_lookup.index:
        return {year: 0.0 for year in projection_years}
    row = projection_lookup.loc[key]
    if isinstance(row, pd.DataFrame):
        row = row.sum()
    return {year: float(row.get(year, 0.0)) for year in projection_years}


def build_supply_value_by_year(
    data,
    year_cols,
    economy,
    fuel_config,
    flow_key,
    flow_value,
    base_year,
    final_year,
    projection_lookup=None,
    projection_years=None,
    code_to_name_mapping=None,
):
    """Return a full year mapping for one economy/fuel/flow.

    - For 9th-style datasets (sector-coded), read all years directly from source rows.
    - For ESTO-style datasets, use base-year source plus projected years from lookup.
    """
    dataset_is_ninth_style = "sectors" in data.columns and "flows" not in data.columns
    if dataset_is_ninth_style:
        return get_flow_series_for_fuel(
            data,
            year_cols,
            economy,
            fuel_config,
            flow_key,
            flow_value,
            base_year,
            final_year,
            code_to_name_mapping=code_to_name_mapping,
        )

    projection_years = [
        year for year in (projection_years or []) if year <= final_year
    ]
    base_value = get_flow_total_for_fuel(
        data,
        year_cols,
        base_year,
        economy,
        fuel_config,
        flow_key,
        flow_value,
        code_to_name_mapping=code_to_name_mapping,
    )
    projected = _get_projection_series(
        projection_lookup,
        economy,
        flow_value,
        fuel_config["fuel_label_esto"],
        projection_years,
    )
    if is_output_flow(flow_key):
        projected = {year: abs(value) for year, value in projected.items()}
    value_by_year = {year: 0.0 for year in range(base_year, final_year + 1)}
    value_by_year[base_year] = base_value
    for year, value in projected.items():
        value_by_year[int(year)] = float(value)
    if is_output_flow(flow_key):
        value_by_year = {
            year: abs(value) if value is not None else 0.0
            for year, value in value_by_year.items()
        }
    return value_by_year
