"""
Pure-computation helpers for the other-loss / own-use proxy workflow.

Extracted from other_loss_own_use_proxy_workflow.py so that functions with
no module-level-state dependencies can be imported and tested independently.
The workflow file imports everything from here; external callers that
currently reach into the workflow module still work via those re-exports.
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping, Sequence

import pandas as pd

from codebase.functions.leap_core import sanitize_leap_name
from codebase.functions.leap_labels import clean_fuel_label_for_leap
from codebase.functions.leap_expressions import build_data_expression_from_row
from codebase.functions.leap_excel_io import read_export_sheet
from codebase.utilities.workflow_utils import (
    _normalize_economy,
    _normalize_year_columns,
    _resolve,
)
from codebase.utilities.leap_balance_export_resolver import (
    build_leap_balance_activity_series,
    load_leap_balance_activity_table as _load_shared_leap_balance_activity_table,
    normalize_balance_label,
)


# ---------------------------------------------------------------------------
# Static constants (imported by the workflow file to avoid duplication)
# ---------------------------------------------------------------------------

DEMAND_ROOT_PARTS: list[str] = ["Demand", "Other loss and own use"]
ACTIVITY_VARIABLE = "Activity Level"
INTENSITY_VARIABLE = "Final Energy Intensity"
DEFAULT_MEASURE_UNITS: dict[str, dict[str, str]] = {
    ACTIVITY_VARIABLE: {"units": "Unspecified Unit", "scale": "", "per": ""},
    INTENSITY_VARIABLE: {"units": "Petajoule", "scale": "", "per": ""},
}

LEAP_BALANCE_FUEL_SETS: dict[str, list[str]] = {
    "electricity_heat_output": [
        "Electricity",
        "Heat",
    ],
    "natural_gas_lng_output": [
        "Natural gas",
        "LNG",
    ],
    "lng_only": [
        "LNG",
    ],
    "natural_gas_only": [
        "Natural gas",
    ],
    "gas_works_gas_output": [
        "Gas works gas",
    ],
    "gas_to_liquids_output": [
        "LPG",
        "Kerosene",
        "Naphtha",
        "Gas and diesel oil",
        "Fuel oil",
        "Refinery gas not liquefied",
        "Other products",
    ],
    "coal_primary_and_products": [
        "Coking coal",
        "Other bituminous coal",
        "Sub bituminous coal",
        "Anthracite",
        "Lignite",
        "Coal nonspecified",
        "Coke oven coke",
        "Gas coke",
        "Coke oven gas",
        "Blast furnace gas",
        "Other recovered gases",
        "Patent fuel",
        "Coal tar",
        "BKB and PB",
    ],
    "coke_oven_output": [
        "Coke oven coke",
        "Coke oven gas",
        "Coal tar",
    ],
    "blast_furnace_output": [
        "Blast furnace gas",
    ],
    "patent_fuel_output": [
        "Patent fuel",
    ],
    "bkb_pb_output": [
        "BKB and PB",
    ],
    "coal_to_oil_output": [
        "LPG",
        "Naphtha",
        "Gas and diesel oil",
        "Fuel oil",
        "Other products",
    ],
    "oil_refinery_output": [
        "LPG",
        "Naphtha",
        "Gas and diesel oil",
        "Fuel oil",
        "Kerosene",
        "Kerosene type jet fuel",
        "Gasoline type jet fuel",
        "Motor gasoline",
        "Aviation gasoline",
        "Bitumen",
        "Petroleum coke",
        "Lubricants",
        "Paraffin waxes",
        "White spirit SBP",
        "Refinery gas not liquefied",
        "Ethane",
        "Other products",
        "PetProd nonspecified",
    ],
    "oil_and_gas_primary_production": [
        "Crude oil",
        "Natural gas",
        "Natural gas liquids",
        "Other hydrocarbons",
    ],
    "electricity_output": [
        "Electricity",
    ],
    "nuclear_primary_production": [
        "Nuclear",
    ],
    "charcoal_output": [
        "Charcoal",
    ],
    "biogas_output": [
        "Biogas",
    ],
    "nonspecified_transformation_output": [
        "Natural gas liquids",
        "Other hydrocarbons",
        "LPG",
        "Ethane",
    ],
    "all_production_ex_total": [
        "Electricity",
        "Natural gas",
        "Kerosene",
        "LPG",
        "Crude oil",
        "Charcoal",
        "Hydro",
        "Biogasoline",
        "Wind",
        "Geothermal",
        "Nuclear",
        "Heat",
        "Hydrogen",
        "Biogas",
        "Naphtha",
        "Peat",
        "Bitumen",
        "Petroleum coke",
        "Lubricants",
        "Refinery feedstocks",
        "Biomass",
        "Bagasse",
        "LNG",
        "Ammonia",
        "Fuel oil",
        "Aviation gasoline",
        "Biodiesel",
        "Patent fuel",
        "Other bituminous coal",
        "Coking coal",
        "Coke oven gas",
        "Coal tar",
        "Blast furnace gas",
        "Coke oven coke",
        "Lignite",
        "Anthracite",
        "Additives and oxygenates",
        "BKB and PB",
        "Bio jet kerosene",
        "Black liqour",
        "Coal nonspecified",
        "Ethane",
        "Fuelwood and woodwaste",
        "Gas coke",
        "Gas and diesel oil",
        "Gasoline type jet fuel",
        "Industrial waste",
        "Kerosene type jet fuel",
        "Motor gasoline",
        "Municipal solid waste renewable",
        "Natural gas liquids",
        "Other biomass",
        "Other hydrocarbons",
        "Other liquid biofuels",
        "Other products",
        "Other recovered gases",
        "Other sources",
        "Paraffin waxes",
        "PetProd nonspecified",
        "Refinery gas not liquefied",
        "Solar nonspecified",
        "Tide wave ocean",
        "White spirit SBP",
        "of which Photovoltaics",
        "Municipal solid waste non renewable",
        "Sub bituminous coal",
    ],
    "production_with_electricity": [
        "Electricity",
        "Natural gas",
        "Kerosene",
        "LPG",
        "Crude oil",
        "Charcoal",
        "Hydro",
        "Biogasoline",
        "Wind",
        "Geothermal",
        "Nuclear",
        "Heat",
        "Hydrogen",
        "Biogas",
        "Naphtha",
        "Peat",
        "Bitumen",
        "Petroleum coke",
        "Lubricants",
        "Refinery feedstocks",
        "Biomass",
        "Bagasse",
        "LNG",
        "Ammonia",
        "Fuel oil",
        "Aviation gasoline",
        "Biodiesel",
        "Patent fuel",
        "Other bituminous coal",
        "Coking coal",
        "Coke oven gas",
        "Coal tar",
        "Blast furnace gas",
        "Coke oven coke",
        "Lignite",
        "Anthracite",
        "Additives and oxygenates",
        "BKB and PB",
        "Bio jet kerosene",
        "Black liqour",
        "Coal nonspecified",
        "Ethane",
        "Fuelwood and woodwaste",
        "Gas coke",
        "Gas and diesel oil",
        "Gasoline type jet fuel",
        "Industrial waste",
        "Kerosene type jet fuel",
        "Motor gasoline",
        "Municipal solid waste renewable",
        "Natural gas liquids",
        "Other biomass",
        "Other hydrocarbons",
        "Other liquid biofuels",
        "Other products",
        "Other recovered gases",
        "Other sources",
        "Paraffin waxes",
        "PetProd nonspecified",
        "Refinery gas not liquefied",
        "Solar nonspecified",
        "Tide wave ocean",
        "White spirit SBP",
        "of which Photovoltaics",
        "Municipal solid waste non renewable",
        "Sub bituminous coal",
    ],
    "production_ex_electricity": [
        "Natural gas",
        "Kerosene",
        "LPG",
        "Crude oil",
        "Charcoal",
        "Hydro",
        "Biogasoline",
        "Wind",
        "Geothermal",
        "Nuclear",
        "Heat",
        "Hydrogen",
        "Biogas",
        "Naphtha",
        "Peat",
        "Bitumen",
        "Petroleum coke",
        "Lubricants",
        "Refinery feedstocks",
        "Biomass",
        "Bagasse",
        "LNG",
        "Ammonia",
        "Fuel oil",
        "Aviation gasoline",
        "Biodiesel",
        "Patent fuel",
        "Other bituminous coal",
        "Coking coal",
        "Coke oven gas",
        "Coal tar",
        "Blast furnace gas",
        "Coke oven coke",
        "Lignite",
        "Anthracite",
        "Additives and oxygenates",
        "BKB and PB",
        "Bio jet kerosene",
        "Black liqour",
        "Coal nonspecified",
        "Ethane",
        "Fuelwood and woodwaste",
        "Gas coke",
        "Gas and diesel oil",
        "Gasoline type jet fuel",
        "Industrial waste",
        "Kerosene type jet fuel",
        "Motor gasoline",
        "Municipal solid waste renewable",
        "Natural gas liquids",
        "Other biomass",
        "Other hydrocarbons",
        "Other liquid biofuels",
        "Other products",
        "Other recovered gases",
        "Other sources",
        "Paraffin waxes",
        "PetProd nonspecified",
        "Refinery gas not liquefied",
        "Solar nonspecified",
        "Tide wave ocean",
        "White spirit SBP",
        "of which Photovoltaics",
        "Municipal solid waste non renewable",
        "Sub bituminous coal",
    ],
}

# Row labels for LEAP's power-generation Transformation branches. Real "full
# model output" balance exports do not break these out individually -- they
# collapse generation into the "* interim" placeholder rows instead -- so any
# activity source built from these rows needs the matching interim row as its
# next fallback.
POWER_BRANCH_INTERIM_FALLBACK_ROWS: dict[str, str] = {
    "Electricity Generation": "Electricity interim",
    "CHP plants": "CHP interim",
    "Heat plants": "Heat plant interim",
}

# Balance-export row carrying total demand-side activity. Any process whose
# LEAP-balance activity is sourced from a Demand branch other than the
# Demand/Other loss and own use target branch itself (that would be
# circular) should add a fallback tier here using
# balance_rows=[DEMAND_AGGREGATE_FALLBACK_ROW] and its own fuel_set, since
# real balance exports do not break Demand out by branch -- only this one
# aggregate row exists. No current process sources activity from a Demand
# branch, so nothing uses this yet.
DEMAND_AGGREGATE_FALLBACK_ROW = "All demand aggregated"

# Per-process ordered fallback chains for LEAP-balance activity. Values may be
# a single fallback dict or a list of dicts tried in order; the first fallback
# with a non-zero series wins.
LEAP_BALANCE_ACTIVITY_FALLBACKS: dict[str, object] = {
    "pump_storage_plants": [
        {
            "balance_rows": ["Electricity Generation"],
            "fuel_set": "electricity_output",
            "value_mode": "positive_only",
        },
        {
            "balance_rows": [POWER_BRANCH_INTERIM_FALLBACK_ROWS["Electricity Generation"]],
            "fuel_set": "electricity_output",
            "value_mode": "absolute",
        },
    ],
    "electricity_chp_and_heat_plants": [
        {
            "balance_rows": [
                POWER_BRANCH_INTERIM_FALLBACK_ROWS["Electricity Generation"],
                POWER_BRANCH_INTERIM_FALLBACK_ROWS["CHP plants"],
                POWER_BRANCH_INTERIM_FALLBACK_ROWS["Heat plants"],
            ],
            "fuel_set": "electricity_heat_output",
            "value_mode": "absolute",
        },
    ],
    "liquefaction_regasification_plants": [
        {
            "balance_rows": ["Imports", "Exports"],
            "fuel_set": "lng_only",
            "value_mode": "absolute",
        },
        {
            "balance_rows": ["Production", "Imports"],
            "fuel_set": "natural_gas_only",
            "value_mode": "absolute",
        },
    ],
}

# Per-process ordered fallback chains for first-run (esto_ninth) activity, the
# alternative-source analogue of LEAP_BALANCE_ACTIVITY_FALLBACKS. Each tier is
# a full esto+ninth activity definition tried in order when the configured
# proxy activity is zero for the selected economy; the first tier with a
# non-zero series wins. This applies to every economy: economies whose source
# tables populate the configured activity never reach the fallback.
ESTO_NINTH_ACTIVITY_FALLBACKS: dict[str, list[dict[str, object]]] = {
    # Some economies (e.g. 01_AUS) report large 10.01.03 own-use but leave the
    # 09.06.02 transformation throughput flow empty, booking LNG movements as
    # trade instead. Absolute imports+exports of LNG covers both liquefaction
    # (exports) and regasification (imports); if LNG trade is also zero, fall
    # back to natural gas production plus imports.
    "liquefaction_regasification_plants": [
        {
            "fallback_key": "lng_imports_exports_abs",
            "activity_label": "Absolute LNG imports plus exports",
            "esto": {
                "flows": ["02 Imports", "03 Exports"],
                "include_exact_products": ["08.02 LNG"],
                "value_mode": "absolute",
            },
            "ninth": {
                "sector_codes": ["02_imports", "03_exports"],
                "subfuels": ["08_02_lng"],
                "value_mode": "absolute",
            },
        },
        {
            "fallback_key": "natural_gas_production_imports_abs",
            "activity_label": "Absolute natural gas production plus imports",
            "esto": {
                "flows": ["01 Production", "02 Imports"],
                "include_exact_products": ["08.01 Natural gas"],
                "value_mode": "absolute",
            },
            "ninth": {
                "sector_codes": ["01_production", "02_imports"],
                "subfuels": ["08_01_natural_gas"],
                "value_mode": "absolute",
            },
        },
        # ESTO and the 9th can disagree on whether gas imports are booked as
        # natural gas or LNG (09_ROK/17_SGP: ESTO says 08.01 Natural gas, the
        # 9th says 08_02_lng). The single-product tiers above then fail the
        # ESTO/9th consistency rule or lose their projections; this combined
        # tier accepts either label on either leg so the same physical trade
        # is found in both datasets.
        {
            "fallback_key": "gas_trade_combined_abs",
            "activity_label": "Absolute natural gas plus LNG trade",
            "esto": {
                "flows": ["02 Imports", "03 Exports"],
                "include_exact_products": ["08.01 Natural gas", "08.02 LNG"],
                "value_mode": "absolute",
            },
            "ninth": {
                "sector_codes": ["02_imports", "03_exports"],
                "subfuels": ["08_01_natural_gas", "08_02_lng"],
                "value_mode": "absolute",
            },
        },
    ],
    "pump_storage_plants": [
        {
            "fallback_key": "hydro_electricity_output_positive",
            "activity_label": "Positive hydro electricity output",
            "esto": {
                "flows": [],
                "value_mode": "positive_only",
            },
            "ninth": {
                "sector_codes": ["09_01_05_hydro"],
                "fuels": ["17_electricity"],
                "subfuels": ["17_electricity"],
                "value_mode": "positive_only",
            },
        },
    ],
}


def _leap_balance_fallback_chain(process_key: str) -> list[Mapping[str, object]]:
    """Return the ordered LEAP-balance fallback list for one process key."""
    value = LEAP_BALANCE_ACTIVITY_FALLBACKS.get(str(process_key or "").strip())
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalize_activity_source_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"first", "first_run", "esto_ninth", "balance_tables"}:
        return "esto_ninth"
    if mode in {"second", "second_run", "leap", "leap_balance", "leap_outputs"}:
        return "leap_balance"
    raise ValueError(
        f"Invalid activity_source_mode={value!r}. "
        "Use 'esto_ninth' for first-run proxies or 'leap_balance' for LEAP-output proxies."
    )


# ---------------------------------------------------------------------------
# Private data helpers
# ---------------------------------------------------------------------------

def _year_columns(df: pd.DataFrame) -> list[int]:
    years = []
    for col in df.columns:
        if str(col).isdigit():
            years.append(int(col))
    return sorted(set(years))


def _compact_economy(value: object) -> str:
    return _normalize_economy(value).replace("_", "")


def _clean_ninth_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text == "x":
        return text
    parts = text.split("_")
    while parts and (parts[0].isdigit() or parts[0] == "x"):
        parts.pop(0)
    label = " ".join(part for part in parts if part).strip()
    return _sentence_case_fuel_label(label) if label else text


def _sentence_case_fuel_label(value: object) -> str:
    """Apply the usual LEAP fuel-label style without title-casing every word."""
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    protected = {
        "BKB",
        "BKB/PB",
        "CCS",
        "CHP",
        "LNG",
        "LPG",
        "NGL",
        "PB",
    }

    def _format_token(token: str, *, is_first: bool) -> str:
        if not token:
            return token
        if "/" in token:
            return "/".join(_format_token(part, is_first=is_first and idx == 0) for idx, part in enumerate(token.split("/")))
        if token.upper() in protected:
            return token.upper()
        lower = token.lower()
        return lower[:1].upper() + lower[1:] if is_first else lower

    return " ".join(_format_token(token, is_first=idx == 0) for idx, token in enumerate(text.split(" ")))


def _clean_product_for_branch(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "_" in text and " " not in text:
        return _clean_ninth_name(text)
    return _sentence_case_fuel_label(clean_fuel_label_for_leap(text))


def _format_fuel_branch_label(
    value: object,
    *,
    source_name: str = "",
    fuel_mapping_lookup: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    """Return the LEAP branch fuel label, using mappings before fallback cleanup."""
    text = str(value or "").strip()
    if not text:
        return ""
    mapped = ""
    if fuel_mapping_lookup and source_name:
        mapped = fuel_mapping_lookup.get(source_name, {}).get(_normalize_source_token(text), "")
    if _normalize_source_token(text) in {"17 electricity", "17_electricity"} and _normalize_balance_label(mapped) == "green electricity":
        mapped = "Electricity"
    label = mapped or _clean_product_for_branch(text)
    return sanitize_leap_name(_sentence_case_fuel_label(label))


def _source_fuel_label(value: object) -> str:
    """Normalize ESTO/9th fuel labels to comparable LEAP-style labels."""
    text = str(value or "").strip()
    if not text or text == "x":
        return ""
    if "_" in text and " " not in text:
        return sanitize_leap_name(_clean_ninth_name(text))
    return sanitize_leap_name(clean_fuel_label_for_leap(text))


def _normalize_source_token(value: object) -> str:
    return str(value or "").strip().lower()


def _normalize_balance_label(value: object) -> str:
    return normalize_balance_label(value)


def _series_from_group(group: pd.DataFrame, year_cols: Sequence[int]) -> dict[int, float]:
    if group.empty:
        return {int(year): 0.0 for year in year_cols}
    values = group[list(year_cols)].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum()
    return {int(year): float(values.get(year, 0.0)) for year in year_cols}


def _apply_value_mode(df: pd.DataFrame, year_cols: Sequence[int], value_mode: str) -> pd.DataFrame:
    """Apply source-side sign handling before summing activity values."""
    if df.empty or not year_cols:
        return df
    mode = str(value_mode or "signed_sum").strip().lower()
    out = df.copy()
    year_list = list(year_cols)
    values = out[year_list].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    if mode in {"signed", "signed_sum", ""}:
        out[year_list] = values
        return out
    if mode in {"positive", "positive_only", "outputs"}:
        out[year_list] = values.where(values > 0.0, 0.0)
        return out
    if mode in {"negative_abs", "input_abs", "inputs_abs"}:
        out[year_list] = values.where(values < 0.0, 0.0).abs()
        return out
    if mode in {"absolute", "abs"}:
        out[year_list] = values.abs()
        return out
    raise ValueError(f"Invalid activity value_mode={value_mode!r}.")


def _has_prefix(value: object, prefixes: Sequence[str]) -> bool:
    text = str(value or "").strip()
    return any(text.startswith(prefix) for prefix in prefixes)


def _matches_exact_values(value: object, allowed_values: Sequence[str]) -> bool:
    if not allowed_values:
        return False
    text = str(value or "").strip().lower()
    allowed = {str(item or "").strip().lower() for item in allowed_values if str(item or "").strip()}
    return text in allowed


def _drop_ninth_parent_fuel_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop parent fuel rows where child subfuel rows exist in the same group."""
    if df.empty or "subfuels" not in df.columns or "fuels" not in df.columns:
        return df
    group_cols = [
        col
        for col in [
            "scenarios",
            "economy",
            "sectors",
            "sub1sectors",
            "sub2sectors",
            "sub3sectors",
            "sub4sectors",
            "fuels",
        ]
        if col in df.columns
    ]
    if not group_cols:
        return df
    out_parts = []
    for _, group in df.groupby(group_cols, dropna=False):
        subfuels = group["subfuels"].fillna("").astype(str).str.strip()
        has_child = (subfuels != "x").any()
        if has_child:
            group = group[subfuels != "x"].copy()
        out_parts.append(group)
    if not out_parts:
        return df.iloc[0:0].copy()
    return pd.concat(out_parts, ignore_index=True)


def _drop_ninth_subtotals(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "subtotal_results" in out.columns:
        out = out[out["subtotal_results"] == False].copy()
    total_codes = {"19_total", "20_total_renewables", "21_modern_renewables"}
    if "fuels" in out.columns:
        out = out[~out["fuels"].astype(str).isin(total_codes)].copy()
    if "subfuels" in out.columns:
        out = out[~out["subfuels"].astype(str).isin(total_codes)].copy()
    return out


def _select_ninth_sector(df: pd.DataFrame, sector_codes: Sequence[str]) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    hierarchy_cols = ["sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors"]
    mask = pd.Series(False, index=df.index)
    wanted = {str(code).strip().lower() for code in sector_codes}
    for col in hierarchy_cols:
        if col in df.columns:
            mask = mask | df[col].fillna("").astype(str).str.strip().str.lower().isin(wanted)
    return df[mask].copy()


def _next_parent_ninth_sector_codes(
    ninth_data: pd.DataFrame,
    sector_codes: Sequence[str],
) -> list[str]:
    """Return immediate parent sector codes for configured 9th hierarchy codes."""
    if ninth_data.empty or not sector_codes:
        return []
    hierarchy_cols = [
        col
        for col in ["sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors"]
        if col in ninth_data.columns
    ]
    wanted = {str(code).strip().lower() for code in sector_codes if str(code).strip()}
    if not hierarchy_cols or not wanted:
        return []
    parents: list[str] = []
    seen: set[str] = set()
    for _, row in ninth_data.iterrows():
        values = [str(row.get(col) or "").strip() for col in hierarchy_cols]
        lowered = [value.lower() for value in values]
        matching_indexes = [idx for idx, value in enumerate(lowered) if value in wanted]
        if not matching_indexes:
            continue
        match_idx = max(matching_indexes)
        for parent_idx in range(match_idx - 1, -1, -1):
            parent = values[parent_idx]
            parent_key = parent.lower()
            if not parent or parent_key == "x" or parent_key in wanted:
                continue
            if parent_key not in seen:
                seen.add(parent_key)
                parents.append(parent)
            break
    return parents


def _sum_ninth_proxy_activity_series(
    *,
    ninth_data: pd.DataFrame,
    economy_key: str,
    ninth_cfg: Mapping[str, object],
    sector_codes: Sequence[str],
    projection_years: Sequence[int],
    ignore_fuel_filters: bool = False,
) -> dict[int, float]:
    """Sum 9th activity for one candidate sector set."""
    ninth_subset = ninth_data[ninth_data["economy_key"] == economy_key].copy()
    ninth_subset = _select_ninth_sector(ninth_subset, sector_codes)
    fuel_values = [] if ignore_fuel_filters else list(ninth_cfg.get("fuels", []))
    subfuel_values = [] if ignore_fuel_filters else list(ninth_cfg.get("subfuels", []))
    if fuel_values or subfuel_values:
        ninth_subset = _drop_ninth_parent_fuel_rows(ninth_subset)
        fuel_mask = (
            ninth_subset["fuels"]
            .apply(lambda value: _matches_exact_values(value, fuel_values))
            .fillna(False)
            .astype(bool)
        )
        subfuel_mask = (
            ninth_subset["subfuels"]
            .apply(lambda value: _matches_exact_values(value, subfuel_values))
            .fillna(False)
            .astype(bool)
        )
        ninth_subset = ninth_subset[fuel_mask | subfuel_mask].copy()
    exclude_fuels = {str(value).strip().lower() for value in ninth_cfg.get("exclude_fuels", [])}
    exclude_subfuels = {str(value).strip().lower() for value in ninth_cfg.get("exclude_subfuels", [])}
    if exclude_fuels:
        ninth_subset = ninth_subset[
            ~ninth_subset["fuels"].fillna("").astype(str).str.strip().str.lower().isin(exclude_fuels)
        ].copy()
    if exclude_subfuels:
        ninth_subset = ninth_subset[
            ~ninth_subset["subfuels"].fillna("").astype(str).str.strip().str.lower().isin(exclude_subfuels)
        ].copy()
    ninth_subset = _apply_value_mode(ninth_subset, projection_years, str(ninth_cfg.get("value_mode", "signed_sum")))
    return _series_from_group(ninth_subset, projection_years)


def _series_has_nonzero_value(series: Mapping[int, float]) -> bool:
    return any(abs(float(value)) > 0.0 for value in series.values())


def _target_fuel_label_from_ninth(row: pd.Series) -> str:
    subfuel = str(row.get("subfuels", "") or "").strip()
    if subfuel and subfuel != "x":
        return subfuel
    return str(row.get("fuels", "") or "").strip()


# ---------------------------------------------------------------------------
# LEAP balance helpers
# ---------------------------------------------------------------------------

def load_leap_balance_activity_table(
    workbook_path: Path | str,
    *,
    balance_rows: Sequence[str],
    fuels: Sequence[str],
) -> pd.DataFrame:
    """Return long LEAP balance values for selected row labels and fuel columns."""
    return _load_shared_leap_balance_activity_table(
        _resolve(workbook_path),
        balance_rows=balance_rows,
        fuels=fuels,
    )


def build_leap_balance_proxy_activity_series(
    *,
    leap_balance_activity: pd.DataFrame,
    config: Mapping[str, object],
    base_year: int,
    final_year: int,
) -> dict[int, float]:
    """Sum configured LEAP balance fuels/rows into one proxy activity series.

    Tries the primary rows, then each configured fallback tier, and keeps
    whichever candidate covers the most projection years (ties keep the
    earliest candidate, i.e. primary over fallback). A primary tier that is
    only nonzero in the base year must not shadow a fallback tier that
    covers the whole run -- mirrors the coverage scoring in
    build_proxy_activity_series_with_fallback for ESTO/9th activity.
    """
    leap_cfg = config["activity_sources"].get("leap_balance", {})
    fuel_set_name = str(leap_cfg.get("fuel_set", "")).strip()
    fuels = LEAP_BALANCE_FUEL_SETS.get(fuel_set_name, [])
    primary_rows = [str(item) for item in leap_cfg.get("balance_rows", []) if str(item).strip()]
    primary_series = build_leap_balance_activity_series(
        leap_balance_activity,
        balance_rows=primary_rows,
        fuels=fuels,
        value_mode=str(leap_cfg.get("value_mode", "signed_sum") or "signed_sum"),
        base_year=base_year,
        final_year=final_year,
    )

    process_key = str(config.get("process_key", "")).strip()
    candidates: list[tuple[dict[int, float], list[str], str]] = [(primary_series, primary_rows, fuel_set_name)]
    for fallback_cfg in _leap_balance_fallback_chain(process_key):
        fallback_rows = [str(item) for item in fallback_cfg.get("balance_rows", []) if str(item).strip()]
        fallback_fuel_set = str(fallback_cfg.get("fuel_set", "")).strip()
        fallback_fuels = LEAP_BALANCE_FUEL_SETS.get(fallback_fuel_set, [])
        if not fallback_rows or not fallback_fuels:
            continue

        fallback_series = build_leap_balance_activity_series(
            leap_balance_activity,
            balance_rows=fallback_rows,
            fuels=fallback_fuels,
            value_mode=str(fallback_cfg.get("value_mode", leap_cfg.get("value_mode", "signed_sum")) or "signed_sum"),
            base_year=base_year,
            final_year=final_year,
        )
        if _series_has_nonzero_value(fallback_series):
            candidates.append((fallback_series, fallback_rows, fallback_fuel_set))

    nonzero_candidates = [item for item in candidates if _series_has_nonzero_value(item[0])]
    if not nonzero_candidates:
        return primary_series

    def _projection_coverage(series_values: dict[int, float]) -> int:
        return sum(
            1
            for year, value in series_values.items()
            if int(year) > int(base_year) and abs(float(value)) > 0.0
        )

    best_score = max(_projection_coverage(item[0]) for item in nonzero_candidates)
    chosen_series, chosen_rows, chosen_fuel_set = next(
        item for item in nonzero_candidates if _projection_coverage(item[0]) == best_score
    )
    if chosen_rows != primary_rows:
        print(
            "[INFO] LEAP-balance proxy activity fallback applied for "
            f"{process_key}: rows={chosen_rows}, fuel_set={chosen_fuel_set}."
        )
    return chosen_series


# ---------------------------------------------------------------------------
# Activity series builders
# ---------------------------------------------------------------------------

def build_esto_proxy_activity_series(
    *,
    esto_data: pd.DataFrame,
    economy: str,
    config: Mapping[str, object],
    base_year: int,
) -> dict[int, float]:
    economy_key = _normalize_economy(economy)
    compact_economy = _compact_economy(economy)
    activity_sources = config["activity_sources"]

    esto_cfg = activity_sources["esto"]
    esto_years = [year for year in _year_columns(esto_data) if int(year) <= int(base_year)]
    esto_subset = esto_data[
        (esto_data["economy"].astype(str).str.upper().isin([compact_economy, economy_key.replace("_", "")]))
        | (esto_data["economy_key"] == economy_key)
    ].copy()
    esto_subset = esto_subset[esto_subset["flows"].isin(esto_cfg.get("flows", []))].copy()
    product_prefixes = list(esto_cfg.get("product_prefixes", []))
    exact_products = set(esto_cfg.get("include_exact_products", []))
    if product_prefixes or exact_products:
        product_mask = (
            esto_subset["products"]
            .apply(lambda value: _has_prefix(value, product_prefixes) or str(value) in exact_products)
            .fillna(False)
            .astype(bool)
        )
        esto_subset = esto_subset[product_mask].copy()
    exclude_products = {str(value).strip().lower() for value in esto_cfg.get("exclude_products", [])}
    if exclude_products:
        esto_subset = esto_subset[
            ~esto_subset["products"].fillna("").astype(str).str.strip().str.lower().isin(exclude_products)
        ].copy()
    esto_subset = _apply_value_mode(esto_subset, esto_years, str(esto_cfg.get("value_mode", "signed_sum")))
    return _series_from_group(esto_subset, esto_years)


def build_ninth_proxy_activity_series(
    *,
    ninth_data: pd.DataFrame,
    economy: str,
    config: Mapping[str, object],
    base_year: int,
    final_year: int,
) -> dict[int, float]:
    series, _ = build_ninth_proxy_activity_series_with_fallback(
        ninth_data=ninth_data,
        economy=economy,
        config=config,
        base_year=base_year,
        final_year=final_year,
    )
    return series


def build_ninth_proxy_activity_series_with_fallback(
    *,
    ninth_data: pd.DataFrame,
    economy: str,
    config: Mapping[str, object],
    base_year: int,
    final_year: int,
) -> tuple[dict[int, float], dict[str, object] | None]:
    """Build 9th activity, climbing to broader parent sectors if the configured proxy is zero."""
    economy_key = _normalize_economy(economy)
    activity_sources = config["activity_sources"]
    ninth_cfg = activity_sources["ninth"]
    projection_years = [year for year in range(int(base_year) + 1, int(final_year) + 1) if year in ninth_data.columns]
    original_sector_codes = [str(code) for code in ninth_cfg.get("sector_codes", []) if str(code).strip()]
    series = _sum_ninth_proxy_activity_series(
        ninth_data=ninth_data,
        economy_key=economy_key,
        ninth_cfg=ninth_cfg,
        sector_codes=original_sector_codes,
        projection_years=projection_years,
    )
    if _series_has_nonzero_value(series):
        return series, None

    tried = {str(code).strip().lower() for code in original_sector_codes if str(code).strip()}
    candidate_sector_codes = original_sector_codes
    fallback_level = 0
    while candidate_sector_codes:
        parent_sector_codes = _next_parent_ninth_sector_codes(ninth_data, candidate_sector_codes)
        parent_sector_codes = [
            code
            for code in parent_sector_codes
            if str(code).strip().lower() not in tried
        ]
        if not parent_sector_codes:
            break
        fallback_level += 1
        tried.update(str(code).strip().lower() for code in parent_sector_codes if str(code).strip())
        parent_series = _sum_ninth_proxy_activity_series(
            ninth_data=ninth_data,
            economy_key=economy_key,
            ninth_cfg=ninth_cfg,
            sector_codes=parent_sector_codes,
            projection_years=projection_years,
            ignore_fuel_filters=True,
        )
        if _series_has_nonzero_value(parent_series):
            return parent_series, {
                "economy": economy_key,
                "process_key": str(config.get("process_key", "")),
                "process_label": str(config.get("process_label", "")),
                "activity_label": str(config.get("activity_label", "")),
                "original_ninth_activity_sectors": "; ".join(original_sector_codes),
                "fallback_ninth_activity_sectors": "; ".join(parent_sector_codes),
                "fallback_level": fallback_level,
                "fallback_reason": "configured_9th_activity_all_zero",
                "fallback_uses_broad_parent_activity": True,
                "fallback_activity_total": sum(abs(float(value)) for value in parent_series.values()),
            }
        candidate_sector_codes = parent_sector_codes

    return series, None


def build_proxy_activity_series(
    *,
    esto_data: pd.DataFrame,
    ninth_data: pd.DataFrame,
    economy: str,
    config: Mapping[str, object],
    base_year: int,
    final_year: int,
) -> dict[int, float]:
    esto_activity = build_esto_proxy_activity_series(
        esto_data=esto_data,
        economy=economy,
        config=config,
        base_year=base_year,
    )
    ninth_activity = build_ninth_proxy_activity_series(
        ninth_data=ninth_data,
        economy=economy,
        config=config,
        base_year=base_year,
        final_year=final_year,
    )
    esto_cfg = config["activity_sources"]["esto"]
    has_esto_activity_definition = bool(esto_cfg.get("flows", []))
    has_esto_activity = any(abs(float(value)) > 0.0 for value in esto_activity.values())
    if has_esto_activity_definition and not has_esto_activity:
        ninth_activity = {year: 0.0 for year in ninth_activity}
    activity = dict(esto_activity)
    activity.update(ninth_activity)
    wanted_years = sorted(set(esto_activity) | set(ninth_activity) | {int(base_year)})
    return {int(year): activity.get(int(year), 0.0) for year in wanted_years}


def _activity_fallback_config(
    config: Mapping[str, object],
    fallback_cfg: Mapping[str, object],
) -> dict[str, object]:
    """Build a synthetic proxy config whose activity comes from one fallback tier."""
    esto_cfg = dict(fallback_cfg.get("esto", {}) or {})
    ninth_cfg = dict(fallback_cfg.get("ninth", {}) or {})
    return {
        "enabled": True,
        "process_key": str(config.get("process_key", "")),
        "process_label": str(config.get("process_label", "")),
        "activity_sources": {
            "esto": {
                "flows": list(esto_cfg.get("flows", [])),
                "product_prefixes": list(esto_cfg.get("product_prefixes", [])),
                "include_exact_products": list(esto_cfg.get("include_exact_products", [])),
                "exclude_products": list(esto_cfg.get("exclude_products", [])),
                "value_mode": str(esto_cfg.get("value_mode", "absolute")),
            },
            "ninth": {
                "sector_codes": list(ninth_cfg.get("sector_codes", [])),
                "fuels": list(ninth_cfg.get("fuels", [])),
                "subfuels": list(ninth_cfg.get("subfuels", [])),
                "exclude_fuels": list(ninth_cfg.get("exclude_fuels", [])),
                "exclude_subfuels": list(ninth_cfg.get("exclude_subfuels", [])),
                "value_mode": str(ninth_cfg.get("value_mode", "absolute")),
            },
        },
    }


def build_proxy_activity_series_with_fallback(
    *,
    esto_data: pd.DataFrame,
    ninth_data: pd.DataFrame,
    economy: str,
    config: Mapping[str, object],
    base_year: int,
    final_year: int,
) -> tuple[dict[int, float], dict[str, object] | None]:
    """Build first-run activity, trying alternative-source tiers when the configured proxy is zero.

    Tiers come from ESTO_NINTH_ACTIVITY_FALLBACKS and are evaluated with the
    same ESTO/9th consistency rules as the configured activity (an all-zero
    ESTO series zeroes the 9th projection too), so a fallback only wins when
    it produces usable base-year data.
    """
    series = build_proxy_activity_series(
        esto_data=esto_data,
        ninth_data=ninth_data,
        economy=economy,
        config=config,
        base_year=base_year,
        final_year=final_year,
    )
    if _series_has_nonzero_value(series):
        return series, None

    process_key = str(config.get("process_key", "")).strip()
    activity_sources = config.get("activity_sources", {})
    original_esto_flows = [str(item) for item in activity_sources.get("esto", {}).get("flows", [])]
    original_ninth_sectors = [str(item) for item in activity_sources.get("ninth", {}).get("sector_codes", [])]
    candidates: list[tuple[int, Mapping[str, object], dict[str, object], dict[int, float]]] = []
    for level, fallback_cfg in enumerate(ESTO_NINTH_ACTIVITY_FALLBACKS.get(process_key, []), start=1):
        candidate_config = _activity_fallback_config(config, fallback_cfg)
        candidate = build_proxy_activity_series(
            esto_data=esto_data,
            ninth_data=ninth_data,
            economy=economy,
            config=candidate_config,
            base_year=base_year,
            final_year=final_year,
        )
        if not _series_has_nonzero_value(candidate):
            continue
        candidates.append((level, fallback_cfg, candidate_config, candidate))

    # A tier that only covers part of the horizon (e.g. nonzero history but
    # zero or truncated projections, as when ESTO and the 9th label the same
    # gas trade differently) must not shadow a later tier that covers the
    # whole run. Rank by how many projection years are nonzero (those reach
    # the LEAP import), then by having any history (report-only; the
    # base-year backfill can borrow), then keep the earliest tier on ties.
    def _coverage_score(series_values: dict[int, float]) -> tuple[int, int]:
        nonzero_projection_years = sum(
            1
            for year, value in series_values.items()
            if int(year) > int(base_year) and abs(float(value)) > 0.0
        )
        has_history = any(
            abs(float(value)) > 0.0
            for year, value in series_values.items()
            if int(year) <= int(base_year)
        )
        return nonzero_projection_years, int(has_history)

    chosen = None
    if candidates:
        best_score = max(_coverage_score(item[3]) for item in candidates)
        chosen = next(item for item in candidates if _coverage_score(item[3]) == best_score)
    if chosen is not None:
        level, fallback_cfg, candidate_config, candidate = chosen
        fallback_esto = candidate_config["activity_sources"]["esto"]
        fallback_ninth = candidate_config["activity_sources"]["ninth"]
        return candidate, {
            "economy": _normalize_economy(economy),
            "process_key": process_key,
            "process_label": str(config.get("process_label", "")),
            "activity_label": str(fallback_cfg.get("activity_label", config.get("activity_label", ""))),
            "original_ninth_activity_sectors": "; ".join(original_ninth_sectors),
            "fallback_ninth_activity_sectors": "; ".join(fallback_ninth.get("sector_codes", [])),
            "fallback_level": level,
            "fallback_reason": "configured_activity_all_zero_used_alternative_source",
            "fallback_uses_broad_parent_activity": False,
            "fallback_activity_total": sum(abs(float(value)) for value in candidate.values()),
            "fallback_key": str(fallback_cfg.get("fallback_key", "")),
            "original_esto_activity_flows": "; ".join(original_esto_flows),
            "fallback_esto_activity_flows": "; ".join(str(item) for item in fallback_esto.get("flows", [])),
        }

    return series, None


def _backfill_base_year_activity_from_projection(
    series: Mapping[int, float],
    *,
    base_year: int,
) -> tuple[dict[int, float], int | None]:
    """Copy the first nonzero projection-year activity into a zero base year.

    Processes such as pump storage have no historical activity source (no ESTO
    activity leg, and the 9th leg only covers projection years), which leaves
    base-year activity at zero while base-year target energy is positive.
    Only the base year is backfilled because only base-year-and-later rows
    reach the LEAP import; earlier years are left untouched so they remain
    visible in the consistency report. Returns the (possibly updated) series
    and the donor year, or ``None`` when no backfill was needed or possible.
    """
    base = int(base_year)
    if abs(float(series.get(base, 0.0) or 0.0)) > 0.0:
        return dict(series), None
    for year in sorted(int(y) for y in series if int(y) > base):
        value = float(series.get(year, 0.0) or 0.0)
        if abs(value) > 0.0:
            out = dict(series)
            out[base] = value
            return out, year
    return dict(series), None


def build_activity_series_for_mode(
    *,
    esto_data: pd.DataFrame,
    ninth_data: pd.DataFrame,
    leap_balance_activity: pd.DataFrame | None,
    economy: str,
    config: Mapping[str, object],
    base_year: int,
    final_year: int,
    activity_source_mode: str,
) -> dict[int, float]:
    """Dispatch activity construction for first-run or LEAP-output second-run proxies."""
    mode = _normalize_activity_source_mode(activity_source_mode)
    if mode == "esto_ninth":
        series, _ = build_proxy_activity_series_with_fallback(
            esto_data=esto_data,
            ninth_data=ninth_data,
            economy=economy,
            config=config,
            base_year=base_year,
            final_year=final_year,
        )
        series, borrowed_year = _backfill_base_year_activity_from_projection(
            series, base_year=base_year
        )
        if borrowed_year is not None:
            print(
                "[INFO] Base-year proxy activity backfilled from first nonzero "
                f"projection year for {config.get('process_key', '')}: "
                f"{base_year} <- {borrowed_year}. Target-matching intensity absorbs "
                "the borrowed scale; pre-base years stay report-only."
            )
        return series
    if mode == "leap_balance":
        if leap_balance_activity is None:
            raise ValueError("leap_balance_activity is required when activity_source_mode='leap_balance'.")
        return build_leap_balance_proxy_activity_series(
            leap_balance_activity=leap_balance_activity,
            config=config,
            base_year=base_year,
            final_year=final_year,
        )
    raise AssertionError(f"Unexpected normalized activity source mode: {mode}")


def build_activity_source_gap_warnings(
    *,
    esto_data: pd.DataFrame,
    ninth_data: pd.DataFrame,
    economy: str,
    configs: Sequence[Mapping[str, object]],
    base_year: int,
    final_year: int,
) -> pd.DataFrame:
    """Identify proxies where ESTO activity exists but 9th projection activity is zero."""
    rows: list[dict[str, object]] = []
    for config in configs:
        if not bool(config.get("enabled", True)):
            continue
        esto_activity = build_esto_proxy_activity_series(
            esto_data=esto_data,
            economy=economy,
            config=config,
            base_year=base_year,
        )
        ninth_activity, fallback_info = build_ninth_proxy_activity_series_with_fallback(
            ninth_data=ninth_data,
            economy=economy,
            config=config,
            base_year=base_year,
            final_year=final_year,
        )
        esto_nonzero = {
            int(year): float(value)
            for year, value in esto_activity.items()
            if abs(float(value)) > 0.0
        }
        if not esto_nonzero:
            continue
        projection_years = [
            int(year)
            for year in range(int(base_year) + 1, int(final_year) + 1)
            if int(year) in ninth_activity
        ]
        if not projection_years:
            continue
        ninth_values = {year: float(ninth_activity.get(year, 0.0)) for year in projection_years}
        zero_years = [year for year, value in ninth_values.items() if abs(float(value)) <= 0.0]
        if len(zero_years) != len(projection_years):
            continue
        if fallback_info is not None:
            continue
        ninth_cfg = config["activity_sources"].get("ninth", {})
        esto_cfg = config["activity_sources"].get("esto", {})
        rows.append(
            {
                "economy": _normalize_economy(economy),
                "process_key": str(config.get("process_key", "")),
                "process_label": str(config.get("process_label", "")),
                "leap_process_label": str(config.get("leap_process_label", config.get("process_label", ""))),
                "activity_label": str(config.get("activity_label", "")),
                "warning_type": "esto_activity_nonzero_ninth_activity_all_zero",
                "esto_activity_years": "; ".join(str(year) for year in sorted(esto_nonzero)),
                "esto_activity_total": sum(abs(value) for value in esto_nonzero.values()),
                "ninth_projection_years": "; ".join(str(year) for year in projection_years),
                "ninth_activity_total": sum(abs(value) for value in ninth_values.values()),
                "esto_activity_flows": "; ".join(str(item) for item in esto_cfg.get("flows", [])),
                "ninth_activity_sectors": "; ".join(str(item) for item in ninth_cfg.get("sector_codes", [])),
                "ninth_activity_fuels": "; ".join(str(item) for item in ninth_cfg.get("fuels", [])),
                "ninth_activity_subfuels": "; ".join(str(item) for item in ninth_cfg.get("subfuels", [])),
                "notes": str(config.get("notes", "")),
            }
        )
    columns = [
        "economy",
        "process_key",
        "process_label",
        "leap_process_label",
        "activity_label",
        "warning_type",
        "esto_activity_years",
        "esto_activity_total",
        "ninth_projection_years",
        "ninth_activity_total",
        "esto_activity_flows",
        "ninth_activity_sectors",
        "ninth_activity_fuels",
        "ninth_activity_subfuels",
        "notes",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(["process_label", "warning_type"], kind="mergesort")


def build_activity_source_fallback_report(
    *,
    esto_data: pd.DataFrame,
    ninth_data: pd.DataFrame,
    economy: str,
    configs: Sequence[Mapping[str, object]],
    base_year: int,
    final_year: int,
) -> pd.DataFrame:
    """Report proxies that used a parent-sector or alternative-source activity fallback."""
    rows: list[dict[str, object]] = []
    for config in configs:
        if not bool(config.get("enabled", True)):
            continue
        esto_activity = build_esto_proxy_activity_series(
            esto_data=esto_data,
            economy=economy,
            config=config,
            base_year=base_year,
        )
        has_esto_activity = any(abs(float(value)) > 0.0 for value in esto_activity.values())
        if has_esto_activity:
            _, fallback_info = build_ninth_proxy_activity_series_with_fallback(
                ninth_data=ninth_data,
                economy=economy,
                config=config,
                base_year=base_year,
                final_year=final_year,
            )
            if fallback_info is not None:
                rows.append(fallback_info)
            continue
        _, alternative_info = build_proxy_activity_series_with_fallback(
            esto_data=esto_data,
            ninth_data=ninth_data,
            economy=economy,
            config=config,
            base_year=base_year,
            final_year=final_year,
        )
        if alternative_info is not None:
            rows.append(alternative_info)
    columns = [
        "economy",
        "process_key",
        "process_label",
        "activity_label",
        "original_ninth_activity_sectors",
        "fallback_ninth_activity_sectors",
        "fallback_level",
        "fallback_reason",
        "fallback_uses_broad_parent_activity",
        "fallback_activity_total",
        "fallback_key",
        "original_esto_activity_flows",
        "fallback_esto_activity_flows",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(["process_label", "fallback_level"], kind="mergesort")


# ---------------------------------------------------------------------------
# Target energy builders
# ---------------------------------------------------------------------------

def build_target_energy_long(
    *,
    esto_data: pd.DataFrame,
    ninth_data: pd.DataFrame,
    economy: str,
    config: Mapping[str, object],
    base_year: int,
    final_year: int,
    fuel_mapping_lookup: Mapping[str, Mapping[str, str]] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    mapping_lookup: Mapping[str, Mapping[str, str]] = fuel_mapping_lookup or {}
    economy_key = _normalize_economy(economy)
    compact_economy = _compact_economy(economy)
    target_sources = config["target_sources"]

    esto_cfg = target_sources["esto"]
    esto_years = [year for year in _year_columns(esto_data) if int(year) <= int(base_year)]
    esto_subset = esto_data[
        (
            (esto_data["economy"].astype(str).str.upper().isin([compact_economy, economy_key.replace("_", "")]))
            | (esto_data["economy_key"] == economy_key)
        )
        & (esto_data["flows"].isin(esto_cfg.get("flows", [])))
    ].copy()
    esto_target_all_economies = esto_data[esto_data["flows"].isin(esto_cfg.get("flows", []))].copy()
    target_exclude_products = {str(value).strip().lower() for value in esto_cfg.get("exclude_products", [])}
    if target_exclude_products:
        esto_subset = esto_subset[
            ~esto_subset["products"].fillna("").astype(str).str.strip().str.lower().isin(target_exclude_products)
        ].copy()
        esto_target_all_economies = esto_target_all_economies[
            ~esto_target_all_economies["products"].fillna("").astype(str).str.strip().str.lower().isin(target_exclude_products)
        ].copy()
    allowed_esto_fuel_keys: set[str] = set()

    if not esto_target_all_economies.empty and esto_years:
        esto_values = esto_target_all_economies[list(esto_years)].apply(pd.to_numeric, errors="coerce").fillna(0.0).abs()
        nonzero_esto_subset = esto_target_all_economies[esto_values.sum(axis=1) > 0.0].copy()
        for product in nonzero_esto_subset["products"].dropna().unique():
            branch_label = _format_fuel_branch_label(
                product,
                source_name="esto",
                fuel_mapping_lookup=mapping_lookup,
            )
            if branch_label:
                allowed_esto_fuel_keys.add(_normalize_balance_label(branch_label))
    for product, group in esto_subset.groupby("products", dropna=False):
        fuel_branch_label = _format_fuel_branch_label(
            product,
            source_name="esto",
            fuel_mapping_lookup=mapping_lookup,
        )
        if _normalize_balance_label(fuel_branch_label) not in allowed_esto_fuel_keys:
            continue
        series = _series_from_group(group, esto_years)
        for year, value in series.items():
            rows.append(
                {
                    "source_dataset": "esto",
                    "economy": economy_key,
                    "process_key": config["process_key"],
                    "process_label": config["process_label"],
                    "leap_process_label": config.get("leap_process_label", config["process_label"]),
                    "fuel_label": str(product),
                    "fuel_branch_label": fuel_branch_label,
                    "year": int(year),
                    "target_energy": float(abs(value)),
                    "target_energy_signed": float(value),
                }
            )

    ninth_cfg = target_sources["ninth"]
    projection_years = [year for year in range(int(base_year) + 1, int(final_year) + 1) if year in ninth_data.columns]
    ninth_subset = ninth_data[ninth_data["economy_key"] == economy_key].copy()
    ninth_subset = _select_ninth_sector(ninth_subset, ninth_cfg.get("sector_codes", []))
    if not ninth_subset.empty:
        ninth_subset = ninth_subset.copy()
        ninth_subset = _drop_ninth_parent_fuel_rows(ninth_subset)
        exclude_fuels = {str(value).strip().lower() for value in ninth_cfg.get("exclude_fuels", [])}
        exclude_subfuels = {str(value).strip().lower() for value in ninth_cfg.get("exclude_subfuels", [])}
        if exclude_fuels:
            ninth_subset = ninth_subset[
                ~ninth_subset["fuels"].fillna("").astype(str).str.strip().str.lower().isin(exclude_fuels)
            ].copy()
        if exclude_subfuels:
            ninth_subset = ninth_subset[
                ~ninth_subset["subfuels"].fillna("").astype(str).str.strip().str.lower().isin(exclude_subfuels)
            ].copy()
        ninth_subset["fuel_label_for_grouping"] = ninth_subset.apply(_target_fuel_label_from_ninth, axis=1)
        ninth_subset["fuel_branch_label_for_grouping"] = ninth_subset["fuel_label_for_grouping"].apply(
            lambda value: _format_fuel_branch_label(
                value,
                source_name="ninth",
                fuel_mapping_lookup=mapping_lookup,
            )
        )
        if allowed_esto_fuel_keys:
            ninth_subset = ninth_subset[
                ninth_subset["fuel_branch_label_for_grouping"].map(_normalize_balance_label).isin(allowed_esto_fuel_keys)
            ].copy()
        else:
            ninth_subset = ninth_subset.iloc[0:0].copy()
        for fuel_branch_label, group in ninth_subset.groupby("fuel_branch_label_for_grouping", dropna=False):
            source_fuels = sorted({str(value) for value in group["fuel_label_for_grouping"].dropna().unique() if str(value).strip()})
            source_fuel_label = "; ".join(source_fuels) if source_fuels else str(fuel_branch_label)
            series = _series_from_group(group, projection_years)
            for year, value in series.items():
                rows.append(
                    {
                        "source_dataset": "ninth",
                        "economy": economy_key,
                        "process_key": config["process_key"],
                        "process_label": config["process_label"],
                        "leap_process_label": config.get("leap_process_label", config["process_label"]),
                        "fuel_label": source_fuel_label,
                        "fuel_branch_label": str(fuel_branch_label),
                        "year": int(year),
                        "target_energy": float(abs(value)),
                        "target_energy_signed": float(value),
                    }
                )
    return pd.DataFrame(rows)


def _nonzero_fuels_from_esto_activity(
    esto_data: pd.DataFrame,
    config: Mapping[str, object],
) -> dict[str, str]:
    esto_cfg = config.get("activity_sources", {}).get("esto", {})
    flows = list(esto_cfg.get("flows", []))
    if not flows or esto_data.empty:
        return {}
    year_cols = _year_columns(esto_data)
    subset = esto_data[esto_data["flows"].isin(flows)].copy()
    product_prefixes = list(esto_cfg.get("product_prefixes", []))
    exact_products = set(esto_cfg.get("include_exact_products", []))
    if product_prefixes or exact_products:
        product_mask = subset["products"].apply(
            lambda value: _has_prefix(value, product_prefixes) or str(value) in exact_products
        )
        subset = subset[product_mask].copy()
    exclude_products = {str(value).strip().lower() for value in esto_cfg.get("exclude_products", [])}
    if exclude_products:
        subset = subset[
            ~subset["products"].fillna("").astype(str).str.strip().str.lower().isin(exclude_products)
        ].copy()
    subset = _apply_value_mode(subset, year_cols, str(esto_cfg.get("value_mode", "signed_sum")))
    if subset.empty or not year_cols:
        return {}
    values = subset[year_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    nonzero = subset.loc[values.abs().gt(0.0).any(axis=1), "products"].dropna().astype(str)
    return {
        str(value).strip(): _source_fuel_label(value)
        for value in nonzero
        if _source_fuel_label(value)
    }


def _nonzero_fuels_from_ninth_activity(
    ninth_data: pd.DataFrame,
    config: Mapping[str, object],
) -> dict[str, str]:
    ninth_cfg = config.get("activity_sources", {}).get("ninth", {})
    sector_codes = list(ninth_cfg.get("sector_codes", []))
    if not sector_codes or ninth_data.empty:
        return {}
    year_cols = _year_columns(ninth_data)
    subset = _select_ninth_sector(ninth_data, sector_codes)
    fuel_values = list(ninth_cfg.get("fuels", []))
    subfuel_values = list(ninth_cfg.get("subfuels", []))
    if fuel_values or subfuel_values:
        subset = _drop_ninth_parent_fuel_rows(subset)
        fuel_mask = subset["fuels"].apply(lambda value: _matches_exact_values(value, fuel_values))
        subfuel_mask = subset["subfuels"].apply(lambda value: _matches_exact_values(value, subfuel_values))
        subset = subset[fuel_mask | subfuel_mask].copy()
    exclude_fuels = {str(value).strip().lower() for value in ninth_cfg.get("exclude_fuels", [])}
    exclude_subfuels = {str(value).strip().lower() for value in ninth_cfg.get("exclude_subfuels", [])}
    if exclude_fuels:
        subset = subset[
            ~subset["fuels"].fillna("").astype(str).str.strip().str.lower().isin(exclude_fuels)
        ].copy()
    if exclude_subfuels:
        subset = subset[
            ~subset["subfuels"].fillna("").astype(str).str.strip().str.lower().isin(exclude_subfuels)
        ].copy()
    subset = _apply_value_mode(subset, year_cols, str(ninth_cfg.get("value_mode", "signed_sum")))
    if subset.empty or not year_cols:
        return {}
    values = subset[year_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    subset = subset.loc[values.abs().gt(0.0).any(axis=1)].copy()
    if subset.empty:
        return {}
    labels = []
    for row in subset.itertuples(index=False):
        subfuel = str(getattr(row, "subfuels", "") or "").strip()
        fuel = str(getattr(row, "fuels", "") or "").strip()
        labels.append(subfuel if subfuel and subfuel != "x" else fuel)
    return {
        str(value).strip(): _source_fuel_label(value)
        for value in labels
        if _source_fuel_label(value)
    }


def _mapped_expected_fuels(
    raw_to_default_label: Mapping[str, str],
    *,
    source_name: str,
    fuel_mapping_lookup: Mapping[str, Mapping[str, str]],
) -> dict[str, dict[str, str]]:
    lookup = fuel_mapping_lookup.get(source_name, {})
    mapped: dict[str, dict[str, str]] = {}
    for raw_label, default_label in raw_to_default_label.items():
        mapped_label = lookup.get(_normalize_source_token(raw_label), default_label)
        if _normalize_balance_label(mapped_label) == "green electricity" and _normalize_balance_label(default_label) == "electricity":
            mapped_label = default_label
        mapped[raw_label] = {
            "source_raw_fuel": raw_label,
            "default_label": default_label,
            "mapped_leap_fuel": mapped_label,
            "mapping_status": "mapped_by_leap_mappings" if mapped_label != default_label else "fallback_label",
        }
    return mapped


def _row_sector_code(row: pd.Series) -> str:
    """Return the deepest non-placeholder 9th sector code for a row."""
    for column in ["sub4sectors", "sub3sectors", "sub2sectors", "sub1sectors", "sectors"]:
        value = str(row.get(column, "") or "").strip()
        if value and value.lower() != "x":
            return value
    return ""


def _row_fuel_code(row: pd.Series) -> str:
    """Return the most specific 9th fuel code for a row."""
    subfuel = str(row.get("subfuels", "") or "").strip()
    if subfuel and subfuel.lower() != "x":
        return subfuel
    fuel = str(row.get("fuels", "") or "").strip()
    if fuel and fuel.lower() != "x":
        return fuel
    return ""


def build_proxy_source_coverage_gaps(
    *,
    esto_data: pd.DataFrame,
    ninth_data: pd.DataFrame,
    configs: Sequence[Mapping[str, object]],
    economy: str,
    base_year: int,
    final_year: int,
) -> pd.DataFrame:
    """Find nonzero ESTO/9th rows that are not covered by any proxy config.

    The scan is intentionally narrow: it only considers 10.x ESTO flows and
    10_x ninth sectors, because those are the other-loss / own-use branches
    this workflow is meant to cover.
    """
    rows: list[dict[str, object]] = []
    economy_key = _normalize_economy(economy)
    compact_economy = economy_key.replace("_", "")

    esto_data = esto_data.copy()
    if "economy_key" in esto_data.columns:
        esto_data = esto_data[
            esto_data["economy_key"].map(_normalize_economy).eq(economy_key)
        ].copy()
    elif "economy" in esto_data.columns:
        esto_data = esto_data[
            esto_data["economy"].map(_normalize_economy).eq(economy_key)
            | esto_data["economy"].astype(str).str.upper().eq(compact_economy)
        ].copy()

    ninth_data = ninth_data.copy()
    if "economy_key" in ninth_data.columns:
        ninth_data = ninth_data[
            ninth_data["economy_key"].map(_normalize_economy).eq(economy_key)
        ].copy()
    elif "economy" in ninth_data.columns:
        ninth_data = ninth_data[
            ninth_data["economy"].map(_normalize_economy).eq(economy_key)
        ].copy()

    def _sorted_join(values: Sequence[str]) -> str:
        cleaned = sorted({str(value).strip() for value in values if str(value).strip()})
        return "; ".join(cleaned)

    def _match_esto_config(row_flow: str, row_product: str, config: Mapping[str, object]) -> tuple[bool, bool]:
        target_esto = config.get("target_sources", {}).get("esto", {})
        target_flows = {
            str(flow).strip()
            for flow in target_esto.get("flows", config.get("esto_target_flows", []))
            if str(flow).strip()
        }
        if row_flow not in target_flows:
            return False, False
        prefixes = list(target_esto.get("product_prefixes", []))
        exact_products = {str(item).strip() for item in target_esto.get("include_exact_products", []) if str(item).strip()}
        exclude_products = {str(item).strip().lower() for item in target_esto.get("exclude_products", []) if str(item).strip()}
        if row_product and row_product.lower() in exclude_products:
            return True, False
        if prefixes or exact_products:
            if _has_prefix(row_product, prefixes) or row_product in exact_products:
                return True, True
            return True, False
        return True, True

    def _match_ninth_config(row_sector: str, row_fuel: str, config: Mapping[str, object]) -> tuple[bool, bool]:
        target_ninth = config.get("target_sources", {}).get("ninth", {})
        target_sectors = {
            str(sector).strip()
            for sector in target_ninth.get("sector_codes", config.get("ninth_target_sectors", []))
            if str(sector).strip()
        }
        if row_sector not in target_sectors:
            return False, False
        fuels = {str(item).strip().lower() for item in target_ninth.get("fuels", []) if str(item).strip()}
        subfuels = {str(item).strip().lower() for item in target_ninth.get("subfuels", []) if str(item).strip()}
        exclude_fuels = {str(item).strip().lower() for item in target_ninth.get("exclude_fuels", []) if str(item).strip()}
        exclude_subfuels = {str(item).strip().lower() for item in target_ninth.get("exclude_subfuels", []) if str(item).strip()}
        if row_fuel and row_fuel.lower() in exclude_fuels.union(exclude_subfuels):
            return True, False
        if fuels or subfuels:
            if row_fuel.lower() in fuels or row_fuel.lower() in subfuels:
                return True, True
            return True, False
        return True, True

    esto_years = [year for year in _year_columns(esto_data) if int(year) <= int(base_year)]
    if esto_years and not esto_data.empty and "flows" in esto_data.columns:
        esto_subset = esto_data[esto_data["flows"].astype(str).str.startswith("10.")].copy()
        if "is_subtotal" in esto_subset.columns:
            subtotal_text = esto_subset["is_subtotal"].fillna(False).astype(str).str.strip().str.lower()
            esto_subset = esto_subset[~subtotal_text.isin({"true", "1", "yes"})].copy()
        for _, row in esto_subset.iterrows():
            flow_text = str(row.get("flows", "") or "").strip()
            if not flow_text:
                continue
            values = pd.to_numeric(row[esto_years], errors="coerce").fillna(0.0)
            nonzero_years = [year for year in esto_years if float(values.get(year, 0.0)) != 0.0]
            if not nonzero_years:
                continue
            product_text = str(row.get("products", "") or "").strip()
            matching_processes: list[str] = []
            covered = False
            matched_flow = False
            for config in configs:
                flow_match, config_covers_row = _match_esto_config(flow_text, product_text, config)
                if flow_match:
                    matched_flow = True
                    matching_processes.append(str(config.get("process_key", "")).strip())
                    if config_covers_row:
                        covered = True
            if covered:
                continue
            rows.append(
                {
                    "source_dataset": "esto",
                    "source_code": flow_text,
                    "fuel_code": product_text,
                    "nonzero_years": _sorted_join(str(year) for year in nonzero_years),
                    "first_nonzero_year": min(nonzero_years),
                    "last_nonzero_year": max(nonzero_years),
                    "total_abs_value": float(values.abs().sum()),
                    "matching_process_keys": _sorted_join(matching_processes),
                    "gap_type": "missing_fuel_from_proxy_config" if matched_flow else "missing_sector_from_proxy_config",
                }
            )

    projection_years = [year for year in range(int(base_year) + 1, int(final_year) + 1) if year in ninth_data.columns]
    if projection_years and not ninth_data.empty:
        ninth_subset = ninth_data.copy()
        if "scenarios" in ninth_subset.columns:
            ninth_subset = ninth_subset[ninth_subset["scenarios"].astype(str).str.lower() == "target"].copy()
        ninth_subset = _drop_ninth_subtotals(ninth_subset)
        for _, row in ninth_subset.iterrows():
            sector_code = _row_sector_code(row)
            if not sector_code or not sector_code.startswith("10_"):
                continue
            values = pd.to_numeric(row[projection_years], errors="coerce").fillna(0.0)
            nonzero_years = [year for year in projection_years if float(values.get(year, 0.0)) != 0.0]
            if not nonzero_years:
                continue
            fuel_code = _row_fuel_code(row)
            matching_processes: list[str] = []
            covered = False
            matched_sector = False
            for config in configs:
                sector_match, config_covers_row = _match_ninth_config(sector_code, fuel_code, config)
                if sector_match:
                    matched_sector = True
                    matching_processes.append(str(config.get("process_key", "")).strip())
                    if config_covers_row:
                        covered = True
            if covered:
                continue
            rows.append(
                {
                    "source_dataset": "ninth",
                    "source_code": sector_code,
                    "fuel_code": fuel_code,
                    "nonzero_years": _sorted_join(str(year) for year in nonzero_years),
                    "first_nonzero_year": min(nonzero_years),
                    "last_nonzero_year": max(nonzero_years),
                    "total_abs_value": float(values.abs().sum()),
                    "matching_process_keys": _sorted_join(matching_processes),
                    "gap_type": "missing_fuel_from_proxy_config" if matched_sector else "missing_sector_from_proxy_config",
                }
            )

    columns = [
        "source_dataset",
        "source_code",
        "fuel_code",
        "nonzero_years",
        "first_nonzero_year",
        "last_nonzero_year",
        "total_abs_value",
        "matching_process_keys",
        "gap_type",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["source_dataset", "source_code", "fuel_code"],
        kind="mergesort",
    )


def build_proxy_fuel_set_verification(
    *,
    esto_data: pd.DataFrame,
    ninth_data: pd.DataFrame,
    configs: Sequence[Mapping[str, object]],
    fuel_mapping_lookup: Mapping[str, Mapping[str, str]] | None = None,
) -> pd.DataFrame:
    """Compare configured LEAP fuel sets with nonzero ESTO/9th activity fuels."""
    rows: list[dict[str, object]] = []
    for config in configs:
        process_key = str(config.get("process_key", ""))
        process_label = str(config.get("process_label", ""))
        leap_cfg = config.get("activity_sources", {}).get("leap_balance", {})
        fuel_set_name = str(leap_cfg.get("fuel_set", "") or "").strip()
        configured_display = {
            _normalize_balance_label(sanitize_leap_name(str(fuel))): sanitize_leap_name(str(fuel))
            for fuel in LEAP_BALANCE_FUEL_SETS.get(fuel_set_name, [])
            if str(fuel).strip()
        }
        source_sets = {
            "esto": _mapped_expected_fuels(
                _nonzero_fuels_from_esto_activity(esto_data, config),
                source_name="esto",
                fuel_mapping_lookup=fuel_mapping_lookup or {},
            ),
            "ninth": _mapped_expected_fuels(
                _nonzero_fuels_from_ninth_activity(ninth_data, config),
                source_name="ninth",
                fuel_mapping_lookup=fuel_mapping_lookup or {},
            ),
        }
        for source_name, expected in source_sets.items():
            source_role = "source_of_truth" if source_name == "esto" else "supporting"
            expected_display = {
                _normalize_balance_label(info["mapped_leap_fuel"]): info
                for info in expected.values()
                if str(info.get("mapped_leap_fuel", "")).strip()
            }
            expected_keys = set(expected_display)
            configured_keys = set(configured_display)
            for fuel_key in sorted(expected_keys - configured_keys):
                status = (
                    "missing_from_leap_fuel_set"
                    if source_role == "source_of_truth"
                    else "supporting_missing_from_leap_fuel_set"
                )
                rows.append(
                    {
                        "process_key": process_key,
                        "process_label": process_label,
                        "enabled": bool(config.get("enabled", True)),
                        "source": source_name,
                        "source_role": source_role,
                        "fuel_set": fuel_set_name,
                        "fuel_label": expected_display[fuel_key]["mapped_leap_fuel"],
                        "source_raw_fuel": expected_display[fuel_key]["source_raw_fuel"],
                        "default_label": expected_display[fuel_key]["default_label"],
                        "mapping_status": expected_display[fuel_key]["mapping_status"],
                        "status": status,
                    }
                )
            for fuel_key in sorted(configured_keys - expected_keys):
                rows.append(
                    {
                        "process_key": process_key,
                        "process_label": process_label,
                        "enabled": bool(config.get("enabled", True)),
                        "source": source_name,
                        "source_role": source_role,
                        "fuel_set": fuel_set_name,
                        "fuel_label": configured_display[fuel_key],
                        "source_raw_fuel": "",
                        "default_label": "",
                        "mapping_status": "configured_only",
                        "status": "configured_not_seen_in_source_activity",
                    }
                )
            for fuel_key in sorted(expected_keys & configured_keys):
                rows.append(
                    {
                        "process_key": process_key,
                        "process_label": process_label,
                        "enabled": bool(config.get("enabled", True)),
                        "source": source_name,
                        "source_role": source_role,
                        "fuel_set": fuel_set_name,
                        "fuel_label": configured_display[fuel_key],
                        "source_raw_fuel": expected_display[fuel_key]["source_raw_fuel"],
                        "default_label": expected_display[fuel_key]["default_label"],
                        "mapping_status": expected_display[fuel_key]["mapping_status"],
                        "status": "matched",
                    }
                )
    columns = [
        "process_key",
        "process_label",
        "enabled",
        "source",
        "source_role",
        "fuel_set",
        "fuel_label",
        "source_raw_fuel",
        "default_label",
        "mapping_status",
        "status",
    ]
    return pd.DataFrame(rows, columns=columns)


def filter_detail_to_validated_output_fuels(
    detail_df: pd.DataFrame,
    validation_df: pd.DataFrame,
) -> pd.DataFrame:
    """Keep only process/fuel output rows that pass output fuel validation."""
    if detail_df.empty or validation_df.empty:
        return detail_df.copy()
    valid_pairs = validation_df[
        validation_df["status"].eq("matched_all_validation_files")
    ][["process_key", "fuel_branch_label"]].drop_duplicates()
    if valid_pairs.empty:
        return detail_df.iloc[0:0].copy()
    working = detail_df.copy()
    working["_process_key_norm"] = working["process_key"].astype(str)
    working["_fuel_branch_label_norm"] = working["fuel_branch_label"].astype(str)
    valid_pairs = valid_pairs.copy()
    valid_pairs["_process_key_norm"] = valid_pairs["process_key"].astype(str)
    valid_pairs["_fuel_branch_label_norm"] = valid_pairs["fuel_branch_label"].astype(str)
    filtered = working.merge(
        valid_pairs[["_process_key_norm", "_fuel_branch_label_norm"]],
        on=["_process_key_norm", "_fuel_branch_label_norm"],
        how="inner",
    )
    return filtered.drop(columns=["_process_key_norm", "_fuel_branch_label_norm"])


# ---------------------------------------------------------------------------
# LEAP export builders
# ---------------------------------------------------------------------------

def build_branch_path(parts: Sequence[str]) -> str:
    return "\\".join(sanitize_leap_name(part) for part in parts if str(part or "").strip())


def build_year_rows(
    branch_path: str,
    variable: str,
    scenario: str,
    value_by_year: Mapping[int, float],
    units: str,
    scale: str,
    per_value: str,
) -> list[dict[str, object]]:
    rows = []
    for year, value in sorted(value_by_year.items()):
        rows.append(
            {
                "Branch_Path": branch_path,
                "Scenario": scenario,
                "Measure": variable,
                "Units": units,
                "Scale": scale,
                "Per...": per_value,
                "Date": int(year),
                "Value": float(value),
            }
        )
    return rows


def build_proxy_log_rows(
    detail_df: pd.DataFrame,
    *,
    scenario: str,
    measure_units: Mapping[str, Mapping[str, object]] | None = None,
    include_zero_target_fuel_branches: bool = True,
) -> list[dict[str, object]]:
    if detail_df.empty:
        return []
    units = {key: dict(value) for key, value in DEFAULT_MEASURE_UNITS.items()}
    if measure_units:
        for key, value in measure_units.items():
            units.setdefault(key, {}).update(dict(value))

    rows: list[dict[str, object]] = []
    child_process_labels: list[str] = []
    process_group_col = "leap_process_label" if "leap_process_label" in detail_df.columns else "process_label"
    for process_label, process_group in detail_df.groupby(process_group_col, dropna=False):
        child_process_labels.append(str(process_label))
        for fuel_label, fuel_group in process_group.groupby("fuel_branch_label", dropna=False):
            if not str(fuel_label or "").strip():
                continue
            if not include_zero_target_fuel_branches and not (fuel_group["target_energy"].abs() > 0).any():
                continue
            fuel_path = build_branch_path([*DEMAND_ROOT_PARTS, str(process_label), str(fuel_label)])
            activity_by_year = fuel_group.set_index("year")["proxy_activity"].to_dict()
            rows.extend(
                build_year_rows(
                    fuel_path,
                    ACTIVITY_VARIABLE,
                    scenario,
                    activity_by_year,
                    str(units[ACTIVITY_VARIABLE].get("units", "")),
                    str(units[ACTIVITY_VARIABLE].get("scale", "")),
                    str(units[ACTIVITY_VARIABLE].get("per", "")),
                )
            )
            intensity_by_year = fuel_group.set_index("year")["intensity"].to_dict()
            rows.extend(
                build_year_rows(
                    fuel_path,
                    INTENSITY_VARIABLE,
                    scenario,
                    intensity_by_year,
                    str(units[INTENSITY_VARIABLE].get("units", "")),
                    str(units[INTENSITY_VARIABLE].get("scale", "")),
                    str(units[INTENSITY_VARIABLE].get("per", "")),
                )
            )

    # Root and process Activity Level rows with value=0 explicitly clear stale
    # LEAP template values without cascading parent×child multiplication.
    all_years = sorted({int(y) for y in detail_df["year"].dropna().unique()}) if not detail_df.empty else []
    zero_by_year = {y: 0.0 for y in all_years}
    parent_paths = [build_branch_path(DEMAND_ROOT_PARTS)] + [
        build_branch_path([*DEMAND_ROOT_PARTS, label]) for label in child_process_labels
    ]
    parent_rows: list[dict[str, object]] = []
    for path in parent_paths:
        parent_rows.extend(
            build_year_rows(path, ACTIVITY_VARIABLE, scenario, zero_by_year, "No data", "", "")
        )
    return parent_rows + rows


def build_expression_export_df(export_df: pd.DataFrame, *, base_year: int) -> pd.DataFrame:
    year_cols = sorted([int(col) for col in export_df.columns if str(col).isdigit()])
    out = export_df.copy()
    out["Expression"] = out.apply(
        lambda row: build_data_expression_from_row(row, year_cols),
        axis=1,
    )
    current_mask = out["Scenario"].fillna("").astype(str).str.strip().str.lower().isin({"current accounts", "current account"})
    if current_mask.any():
        out.loc[current_mask, "Expression"] = out.loc[current_mask].apply(
            lambda row: f"Data({int(base_year)},{float(pd.to_numeric(row.get(base_year), errors='coerce') if pd.notna(pd.to_numeric(row.get(base_year), errors='coerce')) else 0.0)})",
            axis=1,
        )
    out = out.drop(columns=year_cols)
    base_cols = ["Branch Path", "Variable", "Scenario", "Region", "Scale", "Units", "Per...", "Expression"]
    level_cols = [col for col in out.columns if str(col).startswith("Level ")]
    return out[base_cols + level_cols]


def load_export_key_table(
    path: Path | str,
    *,
    sheet_name: str = "Export",
) -> pd.DataFrame:
    """Load LEAP export rows that provide Branch/Variable/Scenario/Region IDs."""
    resolved = _resolve(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Missing export key workbook: {resolved}")
    _, df, _ = read_export_sheet(resolved, sheet_name=sheet_name)
    df = df.rename(columns={col: str(col).strip() for col in df.columns})
    required_cols = [
        "BranchID",
        "VariableID",
        "ScenarioID",
        "RegionID",
        "Branch Path",
        "Variable",
        "Scenario",
        "Region",
    ]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Export key workbook {resolved} sheet {sheet_name!r} is missing required columns: {missing_cols}"
        )
    df = df[required_cols].copy()
    for col in ["Branch Path", "Variable", "Scenario", "Region"]:
        df[col] = df[col].fillna("").astype(str).str.strip()
    df = df[df["Branch Path"].ne("") & df["Variable"].ne("") & df["Scenario"].ne("") & df["Region"].ne("")].copy()

    # Scope to managed branches before duplicate validation; full-model exports
    # can have duplicate keys in unrelated tree sections.
    managed_root = build_branch_path(DEMAND_ROOT_PARTS)
    managed_variables = {ACTIVITY_VARIABLE, INTENSITY_VARIABLE}
    df = df[
        df["Branch Path"].astype(str).str.startswith(managed_root)
        & df["Variable"].isin(managed_variables)
    ].copy()

    duplicate_mask = df.duplicated(["Branch Path", "Variable", "Scenario", "Region"], keep=False)
    if duplicate_mask.any():
        duplicates = df.loc[duplicate_mask, ["Branch Path", "Variable", "Scenario", "Region"]].head(20)
        raise ValueError(
            "Export key workbook has duplicate Branch Path + Variable + Scenario + Region rows. "
            f"First duplicates:\n{duplicates.to_string(index=False)}"
        )
    return df


def merge_export_ids(
    export_df: pd.DataFrame,
    *,
    export_key_table: pd.DataFrame,
) -> pd.DataFrame:
    """Attach LEAP ID columns to generated rows. RegionID is always 1."""
    join_cols = ["Branch Path", "Variable", "Scenario"]
    id_cols = ["BranchID", "VariableID", "ScenarioID"]
    all_id_cols = [*id_cols, "RegionID"]
    check_cols = [*join_cols, "Region"]
    missing_export_cols = [col for col in check_cols if col not in export_df.columns]
    if missing_export_cols:
        raise ValueError(f"Generated export data is missing merge columns: {missing_export_cols}")
    missing_key_cols = [col for col in [*id_cols, "RegionID", *check_cols] if col not in export_key_table.columns]
    if missing_key_cols:
        raise ValueError(f"Export key table is missing required columns: {missing_key_cols}")
    generated_regions = set(export_df["Region"].fillna("").astype(str).str.strip().unique()) - {""}
    key_regions = set(export_key_table["Region"].fillna("").astype(str).str.strip().unique()) - {""}
    if generated_regions and key_regions and not generated_regions.issubset(key_regions):
        print(
            f"[WARN] Region name mismatch: generated rows use {sorted(generated_regions)} but the "
            f"export key workbook has {sorted(key_regions)}. RegionID will be set to 1. "
            "Update the export key workbook Region column to match GLOBAL_REGION if this is unexpected."
        )
    generated = export_df.copy()
    for col in join_cols:
        generated[col] = generated[col].fillna("").astype(str).str.strip()
    key_table = export_key_table[[*join_cols, *id_cols]].copy()
    for col in join_cols:
        key_table[col] = key_table[col].fillna("").astype(str).str.strip()
    merged = generated.merge(
        key_table,
        how="left",
        on=join_cols,
        indicator=True,
    )
    missing = merged[merged["_merge"].ne("both")].copy()
    if not missing.empty:
        preview = missing[join_cols].head(30)
        print(
            f"[WARN] {len(missing)} generated row(s) could not be matched to BranchID/VariableID/"
            "ScenarioID from the export key workbook — these branches are not yet in "
            "data/full model export.xlsx and will be dropped from the proxy output. "
            "Refresh the full model export from LEAP to include them.\n"
            f"{preview.to_string(index=False)}"
        )
        merged = merged[merged["_merge"].eq("both")].copy()
    merged = merged.drop(columns=["_merge"])
    for col in id_cols:
        merged[col] = pd.to_numeric(merged[col], errors="coerce").astype("Int64")
        if merged[col].isna().any():
            missing_ids = merged[merged[col].isna()][join_cols].head(30)
            raise ValueError(
                f"Generated rows matched the key workbook but have missing {col} values:\n"
                f"{missing_ids.to_string(index=False)}"
            )
    merged["RegionID"] = pd.array([1] * len(merged), dtype="Int64")
    return merged[[*all_id_cols, *[col for col in merged.columns if col not in all_id_cols]]]


def _zero_data_expression_for_scenario(
    scenario: object,
    *,
    base_year: int,
    final_year: int,
) -> str:
    scenario_text = str(scenario or "").strip().lower()
    if scenario_text in {"current accounts", "current account"}:
        return f"Data({int(base_year)},0.0)"
    parts: list[str] = []
    for year in range(int(base_year), int(final_year) + 1):
        parts.extend([str(year), "0.0"])
    return f"Data({', '.join(parts)})"


def add_zero_rows_for_unset_values(
    export_df: pd.DataFrame,
    *,
    export_key_table: pd.DataFrame,
    variables: Sequence[str] = (ACTIVITY_VARIABLE, INTENSITY_VARIABLE),
    demand_root_parts: Sequence[str] = DEMAND_ROOT_PARTS,
    base_year: int,
    final_year: int,
) -> pd.DataFrame:
    """Add zero expressions for managed rows in the key workbook not otherwise set."""
    join_cols = ["Branch Path", "Variable", "Scenario"]
    key_cols = [*join_cols, "Region"]
    if export_df.empty:
        return export_df.copy()
    out = export_df.copy()
    for col in key_cols:
        out[col] = out[col].fillna("").astype(str).str.strip()
    scenarios = sorted({str(value).strip() for value in out["Scenario"].dropna().unique() if str(value).strip()})
    output_region = next(
        (str(v).strip() for v in out["Region"].dropna().unique() if str(v).strip()), ""
    )
    root_path = build_branch_path(demand_root_parts)
    key_table = export_key_table.copy()
    for col in join_cols:
        key_table[col] = key_table[col].fillna("").astype(str).str.strip()
    managed = key_table[
        key_table["Branch Path"].astype(str).str.startswith(root_path)
        & key_table["Variable"].isin(list(variables))
        & key_table["Scenario"].isin(scenarios)
    ][join_cols].drop_duplicates()
    already_set = out[join_cols].drop_duplicates()
    missing = managed.merge(already_set, on=join_cols, how="left", indicator=True)
    missing = missing[missing["_merge"].eq("left_only")].drop(columns=["_merge"])
    if missing.empty:
        return out
    template_cols = [col for col in out.columns if col not in key_cols]
    zero_rows = []
    for row in missing.itertuples(index=False):
        item = {
            "Branch Path": row[0],
            "Variable": row[1],
            "Scenario": row[2],
            "Region": output_region,
        }
        for col in template_cols:
            item[col] = pd.NA
        item["Expression"] = _zero_data_expression_for_scenario(
            item["Scenario"],
            base_year=base_year,
            final_year=final_year,
        )
        zero_rows.append(item)
    combined = pd.concat([out, pd.DataFrame(zero_rows)], ignore_index=True, sort=False)
    level_cols = [col for col in combined.columns if str(col).startswith("Level ")]
    if level_cols:
        level_values = combined["Branch Path"].apply(lambda value: str(value).split("\\"))
        for idx, col in enumerate(level_cols):
            combined[col] = combined[col].fillna(level_values.apply(lambda parts: parts[idx] if idx < len(parts) else pd.NA))
    return combined[out.columns]


def _add_leap_header_rows(
    df: pd.DataFrame,
    *,
    model_name: str = "Other loss and own use proxy import",
) -> pd.DataFrame:
    """Return df with the three LEAP-style header rows used by import workbooks."""
    header_data = {col: "" for col in df.columns}
    first_label_col = "Branch Path" if "Branch Path" in df.columns else df.columns[0]
    second_label_col = "Variable" if "Variable" in df.columns else df.columns[min(1, len(df.columns) - 1)]
    third_label_col = "Scenario" if "Scenario" in df.columns else df.columns[min(2, len(df.columns) - 1)]
    fourth_label_col = "Region" if "Region" in df.columns else df.columns[min(3, len(df.columns) - 1)]
    header_data[first_label_col] = "Area:"
    header_data[second_label_col] = model_name
    header_data[third_label_col] = "Ver:"
    header_data[fourth_label_col] = "2"
    header_row_0 = pd.DataFrame([header_data])
    empty_row = pd.DataFrame([{col: pd.NA for col in df.columns}])
    header_row_2 = pd.DataFrame([df.columns], columns=df.columns)
    return pd.concat([header_row_0, empty_row, header_row_2, df], ignore_index=True)


def add_export_id_sheet(
    workbook_path: Path | str,
    export_df: pd.DataFrame,
    *,
    export_key_workbook_path: Path | str,
    export_key_sheet: str = "Export",
    output_sheet_name: str = "LEAP_WITH_IDS",
    model_name: str = "Other loss and own use proxy import",
    keep_only_id_sheet: bool = False,
    include_zero_rows_for_unset_values: bool = True,
    base_year: int | None = None,
    final_year: int | None = None,
    export_key_table: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Add a workbook sheet containing generated rows merged to LEAP ID columns."""
    key_table = (
        export_key_table
        if export_key_table is not None
        else load_export_key_table(export_key_workbook_path, sheet_name=export_key_sheet)
    )
    if include_zero_rows_for_unset_values:
        if base_year is None or final_year is None:
            raise ValueError("base_year and final_year are required when include_zero_rows_for_unset_values=True.")
        export_df = add_zero_rows_for_unset_values(
            export_df,
            export_key_table=key_table,
            base_year=base_year,
            final_year=final_year,
        )
    merged = merge_export_ids(export_df, export_key_table=key_table)
    sheet_df = _add_leap_header_rows(merged, model_name=model_name)
    mode = "w" if keep_only_id_sheet else "a"
    writer_kwargs: dict[str, object] = {"engine": "openpyxl", "mode": mode}
    if not keep_only_id_sheet:
        writer_kwargs["if_sheet_exists"] = "replace"
    with pd.ExcelWriter(_resolve(workbook_path), **writer_kwargs) as writer:
        sheet_df.to_excel(writer, sheet_name=output_sheet_name, index=False, header=False)
    return merged


def _write_csv_with_locked_file_fallback(df: pd.DataFrame, path: Path) -> Path:
    """Write CSV, falling back to *_new.csv when Windows locks an open file."""
    try:
        df.to_csv(path, index=False)
        return path
    except PermissionError:
        fallback = path.with_name(f"{path.stem}_new{path.suffix}")
        df.to_csv(fallback, index=False)
        print(f"[WARN] Could not overwrite locked file {path}; wrote {fallback} instead.")
        return fallback
