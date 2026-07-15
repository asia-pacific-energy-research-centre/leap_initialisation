"""Supply flow selection and year-series construction helpers."""
from __future__ import annotations

import hashlib

import pandas as pd

from codebase.functions.esto_data_utils import (
    _match_code_prefix,
    _match_code_prefix_mask,
    sum_years,
    try_debug_breakpoint,
)
from codebase.functions.ninth_projection_mapping import (
    build_esto_base_year_values,
    compute_esto_base_year_shares,
    normalize_economy_key,
)
from codebase.functions.supply_config_builder import map_code_label

OUTPUT_FLOW_KEYS = {"exports"}

# ESTO flow labels keyed by supply flow key, used to look up base-year ESTO
# values when splitting a shared 9th bucket across its ESTO products.
ESTO_FLOW_LABELS_BY_KEY = {
    "production": "01 Production",
    "imports": "02 Imports",
    "exports": "03 Exports",
    "stock_changes": "06 Stock changes",
    "tpes": "07 Total primary energy supply",
}


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
            selected = select_rows(df, {"economy": economy, "flows": flow_value})
            if not selected.empty:
                return selected
            # ESTO source tables use compact economy codes (for example
            # ``20USA``), while reconciliation uses underscore-normalized
            # codes (``20_USA``).  Keep the exact match first so native 9th
            # rows are untouched, then bridge only that representation gap.
            normalized_economy = normalize_economy_key(economy)
            normalized_rows = df["economy"].map(normalize_economy_key).eq(normalized_economy)
            return df.loc[normalized_rows & df["flows"].eq(flow_value)]
        if "sectors" in df.columns:
            selected = select_rows(df, {"economy": economy, "sectors": flow_value})
            if not selected.empty:
                return selected
            normalized_economy = normalize_economy_key(economy)
            normalized_rows = df["economy"].map(normalize_economy_key).eq(normalized_economy)
            return df.loc[normalized_rows & df["sectors"].eq(flow_value)]
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
            return df[_match_code_prefix_mask(df["products"], fuel_label_esto)]
        if "subfuels" in df.columns:
            # A single ESTO product can correspond to multiple 9th fuel codes,
            # or to a code that is ambiguous across mapping contexts.  In that
            # case the canonical display-name mapping is the safer selector:
            # e.g. 14_wind -> Wind and Solar's two nonspecified subfuels ->
            # Solar nonspecified.  Do this before code-prefix matching so a
            # missing/ambiguous fuel_code_ninth does not silently become zero.
            if code_to_name_mapping and fuel_name:
                mapped_subfuels = df["subfuels"].map(
                    lambda value: map_code_label(value, code_to_name_mapping)
                )
                matched_by_name = df[mapped_subfuels.eq(fuel_name)]
                if not matched_by_name.empty:
                    return matched_by_name
            # Exact code equality must precede prefix matching: codes such as
            # 01_x_thermal_coal collapse to the bare ('01',) numeric prefix
            # (segment extraction stops at "x"), so prefix matching alone would
            # also grab 01_01_coking_coal, 01_05_lignite, and every other
            # sibling subfuel in the family.
            code_text = str(fuel_code_ninth or "").strip()
            if code_text:
                exact_subfuels = df[df["subfuels"].astype(str).str.strip().eq(code_text)]
                if not exact_subfuels.empty:
                    return exact_subfuels
            matched_subfuels = df[_match_code_prefix_mask(df["subfuels"], fuel_code_ninth)]
            if not matched_subfuels.empty:
                return matched_subfuels
            # Some 9th rows carry the canonical fuel code in `fuels` with `subfuels=x`
            # (for example electricity exports). Fall back to fuels in that case.
            if "fuels" in df.columns:
                if code_to_name_mapping and fuel_name:
                    mapped_fuels = df["fuels"].map(
                        lambda value: map_code_label(value, code_to_name_mapping)
                    )
                    matched_fuels_by_name = df[mapped_fuels.eq(fuel_name)]
                    if not matched_fuels_by_name.empty:
                        return matched_fuels_by_name
                if code_text:
                    exact_fuels = df[df["fuels"].astype(str).str.strip().eq(code_text)]
                    if not exact_fuels.empty:
                        return exact_fuels
                matched_fuels = df[_match_code_prefix_mask(df["fuels"], fuel_code_ninth)]
                if not matched_fuels.empty:
                    return matched_fuels
            return matched_subfuels
        if "fuels" in df.columns:
            if code_to_name_mapping and fuel_name:
                mapped_fuels = df["fuels"].map(
                    lambda value: map_code_label(value, code_to_name_mapping)
                )
                matched_by_name = df[mapped_fuels.eq(fuel_name)]
                if not matched_by_name.empty:
                    return matched_by_name
            code_text = str(fuel_code_ninth or "").strip()
            if code_text:
                exact_fuels = df[df["fuels"].astype(str).str.strip().eq(code_text)]
                if not exact_fuels.empty:
                    return exact_fuels
            return df[_match_code_prefix_mask(df["fuels"], fuel_code_ninth)]
        return df.iloc[0:0]
    except Exception as exc:
        print(f"Failed to select fuel rows: {exc}")
        try_debug_breakpoint()
        raise


class NinthBucketAllocator:
    """Split shared 9th-edition fuel buckets across their ESTO products.

    Several ESTO products can map to the same coarse 9th fuel code (for
    example 02.01 Coke oven coke through 02.08 BKB/PB all map to
    02_coal_products). A direct per-product row match then hands every
    product the full bucket total, overcounting the bucket N times. This
    allocator groups the configured products that match an identical 9th
    row set and returns each product's base-year ESTO share of that bucket,
    so the bucket series can be scaled into per-product series that sum back
    to the bucket total — the same base-year-share method
    allocate_ninth_projection_to_esto uses for projection years.
    """

    def __init__(self, siblings_by_product, esto_base_values):
        self._siblings_by_product = siblings_by_product
        self._esto_base_values = esto_base_values
        self._share_cache: dict[tuple, dict[str, float]] = {}

    def share(self, economy, flow_key, fuel_label_esto):
        """Return the product's share of its bucket for one economy/flow."""
        product = str(fuel_label_esto or "").strip()
        siblings = self._siblings_by_product.get(product)
        if not siblings:
            return 1.0
        economy_key = normalize_economy_key(economy)
        esto_flow = ESTO_FLOW_LABELS_BY_KEY.get(str(flow_key or "").strip().lower(), "")
        cache_key = (economy_key, esto_flow, siblings)
        shares = self._share_cache.get(cache_key)
        if shares is None:
            shares = compute_esto_base_year_shares(
                self._esto_base_values,
                economy_key,
                esto_flow,
                list(siblings),
            )
            self._share_cache[cache_key] = shares
        return float(shares.get(product, 1.0))


def build_ninth_bucket_allocator(
    data,
    fuel_config,
    code_to_name_mapping,
    esto_data,
    base_year,
):
    """Return a NinthBucketAllocator for ninth-style data, or None.

    Products are grouped by the exact row set they select in ``data`` — this
    covers both products sharing a coarse ``fuel_code_ninth`` and products
    whose display-name match resolves to the same bucket rows.
    """
    try:
        dataset_is_ninth_style = (
            data is not None
            and "sectors" in data.columns
            and "flows" not in data.columns
        )
        if not dataset_is_ninth_style or not fuel_config:
            return None
        if esto_data is None or esto_data.empty:
            return None
        products_by_signature: dict[str, list[str]] = {}
        for fuel_key in sorted(fuel_config):
            entry = fuel_config[fuel_key]
            product = str(entry.get("fuel_label_esto") or fuel_key).strip()
            matched = select_fuel_rows(
                data,
                entry.get("fuel_code_ninth"),
                entry.get("fuel_label_esto"),
                fuel_name=entry.get("fuel_name"),
                code_to_name_mapping=code_to_name_mapping,
            )
            if matched.empty:
                continue
            signature = hashlib.md5(matched.index.values.tobytes()).hexdigest()
            products_by_signature.setdefault(signature, []).append(product)
        siblings_by_product = {
            product: tuple(products)
            for products in products_by_signature.values()
            if len(products) > 1
            for product in products
        }
        if not siblings_by_product:
            return None
        esto_base_values = build_esto_base_year_values(esto_data, base_year)
        shared_groups = sorted({products for products in siblings_by_product.values()})
        print(
            "[INFO] Supply 9th-bucket allocation active for "
            f"{len(shared_groups)} shared bucket group(s): "
            + "; ".join(" + ".join(group) for group in shared_groups)
        )
        return NinthBucketAllocator(siblings_by_product, esto_base_values)
    except Exception as exc:
        print(f"Failed to build ninth bucket allocator: {exc}")
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
    bucket_allocator=None,
):
    """Return a full year mapping for one economy/fuel/flow.

    - For 9th-style datasets (sector-coded), read all years directly from source rows.
      When ``bucket_allocator`` is given, a product that shares its 9th bucket with
      sibling products receives its base-year ESTO share of the bucket series.
    - For ESTO-style datasets, use base-year source plus projected years from lookup.
    """
    dataset_is_ninth_style = "sectors" in data.columns and "flows" not in data.columns
    if dataset_is_ninth_style:
        series = get_flow_series_for_fuel(
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
        if bucket_allocator is not None:
            share = bucket_allocator.share(
                economy, flow_key, fuel_config.get("fuel_label_esto")
            )
            if share != 1.0:
                series = {year: value * share for year, value in series.items()}
        return series

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
