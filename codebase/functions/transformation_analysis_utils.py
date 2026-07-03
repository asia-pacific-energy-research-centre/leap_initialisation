#%%
# Summary: Compute LEAP import parameters for transformation flows (LNG, gas works,
# blending, coal subtypes, charcoal, and nonspecified) using ESTO/9th datasets.
# How it works:
# - Loads ESTO/9th data, normalizes year columns, and cleans subtotals.
# - Uses explicit transformation flow codes per sector to select rows.
# - For each flow and economy, identifies primary input/output fuels and totals.
# - Computes efficiency as output / (feedstock + losses) using loss flow codes.
# - Treats own-use/loss fuels as auxiliary fuels unless they match feedstock.
# - Prints a LEAP-style structure block for manual import into LEAP.
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd

from codebase.utilities.master_config import (
    config_table_exists,
    read_config_table,
    OUTLOOK_MAPPINGS_MASTER_PATH,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.configuration.all_products_and_flows import ESTO_SECTORS
from codebase.configuration.config import (
    BRANCH_DEMAND_CATEGORY,
    BRANCH_DEMAND_TECHNOLOGY,
    BASE_YEAR,
)
from codebase.functions.leap_core import (
    connect_to_leap,
    create_branches_from_export_file,
    fill_branches_from_export_file,
    sanitize_leap_branch_path,
)
from codebase.utilities.esto_reference_loader import (
    apply_esto_subtotal_mapping as apply_matt_subtotal_mapping,
    filter_esto_subtotals as filter_matt_subtotals,
    load_augmented_reference_tables,
    save_subtotal_labeled_data,
)
from codebase.functions.leap_excel_io import finalise_export_df, save_export_files
from codebase.functions.ninth_projection_mapping import (
    build_esto_projection_table,
    merge_projection_into_esto,
)
from codebase.configuration import workflow_config as workflow_cfg
from codebase.utilities import workflow_common
from codebase.functions.esto_data_utils import (
    try_debug_breakpoint,
    _extract_numeric_segments,
    _match_code_prefix,
    _match_code_prefix_mask,
    load_csv_data,
    normalize_year_columns,
    filter_reference_scenario,
    sum_years,
    get_economy_list,
    add_all_economy_total,
    build_dataset_map,
    resolve_dataset,
)
from codebase.functions.transformation_series_utils import (
    ensure_full_year_series,
    series_to_year_dict,
    safe_divide_series,
    to_input_only_series,
    to_output_only_series,
    build_auxiliary_ratios_by_year,
    build_auxiliary_from_losses_by_year,
    merge_loss_into_auxiliary_by_year,
    filter_loss_values_for_feedstock_by_year,
    get_loss_total_for_efficiency_by_year,
    compute_efficiency_by_year,
    compute_primary_io,
    build_total_input_series,
    build_input_share_series,
    allocate_outputs_by_share,
    allocate_loss_by_share,
    sum_loss_values_by_year,
    scale_year_dict_by_share,
    calculate_efficiency_with_losses,
)
from codebase.functions.transformation_fuel_utils import (  # noqa: F401
    get_years_from,
    get_fuel_labels,
    summarize_fuels_by_subfuel,
    summarize_fuel_totals,
    summarize_fuel_timeseries,
    get_label_timeseries,
    sum_years_by_year,
)
#%%

#%%
######### CONSTANTS (UNLIKELY TO CHANGE) #########
ENERGY_SOURCE_CONFIG = workflow_cfg.get_energy_source_config()
ESTO_DATA_PATH = ENERGY_SOURCE_CONFIG.esto_base_table_path
# Use merged_file_energy_ALL_20251106.csv and merged_file_energy_00_APEC_20251106 for exact 9th edition projection matching.
NINTH_DATA_PATH = ENERGY_SOURCE_CONFIG.ninth_projection_table_path
# Backward-compatible alias for older notebook imports. Prefer ESTO_DATA_PATH.
MATT_DATA_PATH = ESTO_DATA_PATH
CONFIG_DIR = REPO_ROOT / "config"
SUBTOTAL_MAPPING_PATH = CONFIG_DIR / "ESTO_subtotal_mapping.xlsx"
NINTH_TO_ESTO_MAPPING_PATH = CONFIG_DIR / "ninth_pairs_to_esto_pairs.xlsx"
CODE_TO_NAME_PATHS = [
    OUTLOOK_MAPPINGS_MASTER_PATH,
    CONFIG_DIR / "sector_fuel_codes_to_names.updated.xlsx",
    CONFIG_DIR / "sector_fuel_codes_to_names.xlsx",
]

BASE_YEAR = ENERGY_SOURCE_CONFIG.esto_base_year
YEAR_START_FOR_ANALYSIS = BASE_YEAR
PROJECTION_START_YEAR = ENERGY_SOURCE_CONFIG.projection_start_year
PROJECTION_END_YEAR = 2060
if ENERGY_SOURCE_CONFIG.projection_final_year is not None:
    PROJECTION_END_YEAR = int(ENERGY_SOURCE_CONFIG.projection_final_year)
PROJECTION_YEAR_RANGE = list(range(PROJECTION_START_YEAR, PROJECTION_END_YEAR + 1))
REFERENCE_CACHE_DIR = REPO_ROOT / "data" / ".cache" / "transformation_reference_tables"
# Projection split policy for transformation workflows:
# - PROJECTION_SIGN_STABLE_MODE controls allocation behavior:
#   - "all": apply sign-stable routing to every mapped ESTO flow.
#   - "selected": apply only to SIGN_STABLE_PROJECTION_FLOWS.
#   - "off": disable sign-stable routing (legacy abs-share behavior).
# - PROJECTION_STRICT_CONSERVATION raises on any source-vs-allocated mismatch.
PROJECTION_SIGN_STABLE_MODE = "all"
SIGN_STABLE_PROJECTION_FLOWS = [
    "09.08.01 Coke ovens",
    "09.08.02 Blast furnaces",
    "09.08.03 Patent fuel plants",
    "09.08.04 BKB/PB plants",
    "09.08.05 Liquefaction (coal to oil)",
    "09.08.06 Coal mines",
]
PROJECTION_STRICT_CONSERVATION = True


def resolve_projection_sign_stable_flows(mode, selected_flows):
    """Return sign_stable_flows argument for build_esto_projection_table."""
    mode_key = str(mode or "").strip().lower()
    if mode_key in {"off", "none", ""}:
        return []
    if mode_key == "selected":
        return list(selected_flows or [])
    if mode_key == "all":
        return "all"
    raise ValueError(
        f"Invalid PROJECTION_SIGN_STABLE_MODE={mode!r}. "
        "Use one of: 'all', 'selected', 'off'."
    )
LOSS_SECTOR_CODE_9TH = "10_losses_and_own_use"
# DEFAULT_SCENARIO = "Target"
DEFAULT_REGION = "United States"
DEFAULT_OUTPUT_UNITS = "Petajoule"
DEFAULT_EFFICIENCY_UNITS = "Percent"
DEFAULT_FEEDSTOCK_UNITS = "Share"
DEFAULT_FEEDSTOCK_SCALE = "%"
DEFAULT_AUXILIARY_UNITS = "Petajoule"
DEFAULT_AUXILIARY_PER = "Petajoule"
ENABLE_DEBUG_BREAKPOINTS = True
PRINT_SECTOR_ROWS = True
PRINT_TOP_FUEL_ROWS = 12
PRINT_ONLY_NONZERO_ROWS = True
USE_CODE_TO_NAME_MAPPING = True
AUXILIARY_THRESHOLD_RATIO = 0.1
INCLUDE_ALL_AUXILIARY = False
PRINT_GAS_PROCESSING_SUMMARY = False

HYDROGEN_OUTPUT_SUBFUELS = [
    "16_x_hydrogen",
    "16_x_ammonia",
    "16_x_efuel",
]
HYDROGEN_PROCESS_CONFIG = [
    {
        "process_code": "09_13_01_electrolysers",
        "source_sub2sectors": "09_13_01_electrolysers",
        "input_fuel_codes": ["17_x_green_electricity"],
        "output_subfuels": list(HYDROGEN_OUTPUT_SUBFUELS),
        "enabled": True,
    },
    {
        "process_code": "09_13_03_smr_w_ccs",
        "source_sub2sectors": "09_13_03_smr_w_ccs",
        "input_fuel_codes": ["08_01_natural_gas"],
        "output_subfuels": list(HYDROGEN_OUTPUT_SUBFUELS),
        "enabled": True,
    },
    {
        "process_code": "09_13_02_smr_wo_ccs",
        "source_sub2sectors": "09_13_02_smr_wo_ccs",
        "input_fuel_codes": ["08_01_natural_gas"],
        "output_subfuels": list(HYDROGEN_OUTPUT_SUBFUELS),
        "enabled": True,
    },
    {
        "process_code": "electrolysers_non_green",
        "source_sub2sectors": "09_13_01_electrolysers",
        "input_fuel_codes": ["17_electricity"],
        "output_subfuels": list(HYDROGEN_OUTPUT_SUBFUELS),
        "enabled": False,
    },
]

MAJOR_SECTOR_CONFIG = {
    "lng": {
        "dataset_key": "ninth",
        "title": "NG Liquefaction",
        "liquefaction_title": "NG Liquefaction",
        "regasification_title": "LNG regasification",
        "transformation_sub1": "09_06_gas_processing_plants",
        "transformation_sub2": ["09_06_02_liquefaction_regasification_plants"],
        "loss_sub2": ["10_01_03_liquefaction_regasification_plants"],
        "esto_flow_code_liquefaction": "09.06.02.01 Liquefaction",
        "esto_flow_code_regasification": "09.06.02.02 Regasification",
    },
    "gas_works": {
        "dataset_key": "esto",
        "title": "Gas works plants",
        "transformation_sub2": [
            "09_06_01_gas_works_plants",
            "09_06_03_natural_gas_blending_plants",
        ],
        "flow_code_gas_works": "09.06.01 Gas works plants",
        "flow_code_blending": "09.06.03 Natural gas blending plants",
        "product_code_natural_gas": "08.01 Natural gas",
        "product_code_gas_works_gas": "08.03 Gas works gas",
        "product_code_lignite": "01.05 Lignite",
        "transformation_flow_codes": ["09.06.01 Gas works plants"],
        "loss_flow_codes": ["10.01.02 Gas works plants"],
    },
    "gas_blending": {
        "dataset_key": "esto",
        "title": "Natural gas blending plants",
        "transformation_flow_codes": ["09.06.03 Natural gas blending plants"],
        "loss_flow_codes": [],
    },
    "coal_coke_ovens": {
        "dataset_key": "esto",
        "title": "Coke ovens",
        "transformation_flow_codes": ["09.08.01 Coke ovens"],
        "loss_flow_codes": ["10.01.05 Coke ovens"],
    },
    "coal_blast_furnaces": {
        "dataset_key": "esto",
        "title": "Blast furnaces",
        "transformation_flow_codes": ["09.08.02 Blast furnaces"],
        "loss_flow_codes": ["10.01.07 Blast furnaces"],
    },
    "coal_patent_fuel_plants": {
        "dataset_key": "esto",
        "title": "Patent fuel plants",
        "transformation_flow_codes": ["09.08.03 Patent fuel plants"],
        "loss_flow_codes": [],
    },
    "coal_bkb_pb_plants": {
        "dataset_key": "esto",
        "title": "BKB and PB plants",
        "transformation_flow_codes": ["09.08.04 BKB/PB plants"],
        "loss_flow_codes": [],
    },
    "coal_liquefaction": {
        "dataset_key": "esto",
        "title": "Liquefaction (coal to oil)",
        "transformation_flow_codes": ["09.08.05 Liquefaction (coal to oil)"],
        "loss_flow_codes": [],
    },
    "electric_boilers": {
        "dataset_key": "esto",
        "title": "Electric boilers",
        "transformation_flow_codes": ["09.04 Electric boilers"],
        "loss_flow_codes": [],
    },
    "chemical_heat_for_electricity_production": {
        "dataset_key": "esto",
        "title": "Chemical heat for electricity production",
        "transformation_flow_codes": ["09.05 Chemical heat for electricity production"],
        "loss_flow_codes": [],
    },
    "petrochemical_industry": {
        "dataset_key": "esto",
        "title": "Petrochemical industry",
        "transformation_flow_codes": ["09.09 Petrochemical industry"],
        "loss_flow_codes": [],
    },
    "gas_to_liquids_plants": {
        "dataset_key": "esto",
        "title": "Gas to liquids plants",
        "transformation_flow_codes": ["09.06.04 Gas-to-liquids plants"],
        "loss_flow_codes": [],
    },
    "biofuels_processing": {
        "dataset_key": "esto",
        "title": "Biofuels processing",
        "transformation_flow_codes": ["09.10 Biofuels processing"],
        "loss_flow_codes": [],
    },
    "coal_mines": {
        "dataset_key": "esto",
        "title": "Coal mines",
        "transformation_flow_codes": ["09.08.06 Coal mines"],
        "loss_flow_codes": ["10.01.06 Coal mines"],
    },
    "charcoal_processing": {
        "dataset_key": "esto",
        "title": "Charcoal processing",
        "transformation_flow_codes": ["09.11 Charcoal processing"],
        "loss_flow_codes": [],
    },
    "nonspecified_transformation": {
        "dataset_key": "esto",
        "title": "Non-specified transformation",
        "transformation_flow_codes": ["09.12 Non-specified transformation"],
        "loss_flow_codes": ["10.01.17 Non-specified own uses"],
    },
    "oil_refineries": {
        "dataset_key": "esto",
        "title": "Oil Refining",
        "transformation_flow_codes": ["09.07 Oil refineries"],
        "loss_flow_codes": ["10.01.11 Oil refineries"],
        "multi_output": True,
    },
    "hydrogen_transformation": {
        "dataset_key": "ninth",
        "title": "Hydrogen transformation",
        "transformation_sub1": "09_13_hydrogen_transformation",
        "output_fuels": ["16_others"],
        "output_subfuels": list(HYDROGEN_OUTPUT_SUBFUELS),
        "process_config": HYDROGEN_PROCESS_CONFIG,
    },
} 
# Module-level data globals — populated by prepare_transformation_assets().
# None/empty until that function is called.
DATASET_MAP: dict | None = None
code_to_name_mapping: dict = {}
ESTO_IMPORT_EXPORT_REFERENCE_DATA = None
ESTO_IMPORT_EXPORT_YEAR_COLS: list = []
esto_data_raw = None
ninth_data_raw = None
esto_year_cols: list = []
ninth_year_cols: list = []
esto_year_cols_raw: list = []
esto_data = None
ninth_data = None
ESTO_IMPORT_SECTOR_LABEL = next(
    (sector for sector in ESTO_SECTORS if sector.startswith("02 ")),
    "02 Imports",
)
ESTO_EXPORT_SECTOR_LABEL = next(
    (sector for sector in ESTO_SECTORS if sector.startswith("03 ")),
    "03 Exports",
)
TRANSFORMATION_OUTPUT_VARIABLES = {
    "output": True,
    "output_import_target": True,
    "output_export_target": True,
    "feedstock_share": True,
    "process_efficiency": True,
    "auxiliary_ratio": True,
    "loss_value": True,
}
FEEDSTOCK_METHOD_SINGLE_AUX = "single_feedstock_aux_others"
FEEDSTOCK_METHOD_SPLIT = "split_processes_per_feedstock"
FEEDSTOCK_METHOD_MULTI = "multi_feedstock_single_process"
FEEDSTOCK_METHOD = FEEDSTOCK_METHOD_MULTI
# When False, loss/own-use fuels always go to aux even if they match a feedstock fuel.
# When True, loss fuels that match a feedstock label are excluded from aux.
LOSS_AUX_EXCLUDE_FEEDSTOCKS = False
# When True, input fuels detected as negative in the source data are always written to the
# export even if their values sum to zero over the export year range (e.g. data only exists
# outside the export window, such as pre-2022 historical lignite for AUS BKB/PB).
# Setting False drops these zero-sum fuels — if all inputs are dropped the process is
# skipped entirely, which is correct for sectors with no export-window activity.
# Root cause of phantom rows: the all-years fallback in summarize_fuel_totals can detect
# historical fuels as "inputs" even when the sector has zero activity in 2022+.
INCLUDE_ALL_DETECTED_INPUT_FUELS = False

_dropped_input_fuel_log: list[dict] = []
# Tracks LEAP-mapped sector titles for every sector run_analysis_for_sector visits,
# even those where all economies returned no data.  Used by zero-fill to clear catalog
# branches for sectors this workflow owns but had no ESTO data for.
_analyzed_sector_titles: set[str] = set()
#%%
# Available sectors (with non zero data) in the ESTO dataset:
# 10.01 Own Use
# 10.01.01 Electricity, CHP and heat plants
# 10.01.02 Gas works plants
# 10.01.03 Liquefaction/regasification plants
# 10.01.05 Coke ovens
# 10.01.06 Coal mines
# 10.01.07 Blast furnaces
# 10.01.11 Oil refineries
# 10.01.12 Oil and gas extraction
# 10.01.13 Pump storage plants
# 10.01.17 Non-specified own uses
# 10.02 Transmission and distribution losses
#transformation sectors:
# 09.01 Main activity producer
# 09.01.01 Electricity plants
# 09.01.02 CHP plants
# 09.01.03 Heat plants
# 09.02 Autoproducers
# 09.02.01 Electricity plants
# 09.02.02 CHP plants
# 09.02.03 Heat plants
# 09.04 Electric boilers
# 09.05 Chemical heat for electricity production
# 09.06 Gas processing plants
# 09.06.01 Gas works plants
# 09.06.02 Liquefaction/regasification plants
# 09.06.03 Natural gas blending plants
# 09.06.04 Gas-to-liquids plants
# 09.07 Oil refineries
# 09.08 Coal transformation
# 09.08.01 Coke ovens
# 09.08.02 Blast furnaces
# 09.08.03 Patent fuel plants
# 09.08.04 BKB/PB plants
# 09.08.05 Liquefaction (coal to oil)
# 09.09 Petrochemical industry
# 09.11 Charcoal processing
# 09.12 Non-specified transformation
# Unused sectors (from provided 09/10 lists; keep for reference)
# UNUSED_SECTORS = [
#     "10.01 Own Use",
#     "10.01.01 Electricity, CHP and heat plants",
#     "10.01.11 Oil refineries",
#     "10.01.12 Oil and gas extraction",
#     "10.01.13 Pump storage plants",
#     "10.02 Transmission and distribution losses",
#     "09.01 Main activity producer",
#     "09.01.01 Electricity plants",
#     "09.01.02 CHP plants",
#     "09.01.03 Heat plants",
#     "09.02 Autoproducers",
#     "09.02.01 Electricity plants",
#     "09.02.02 CHP plants",
#     "09.02.03 Heat plants",
#     "09.04 Electric boilers",
#     "09.05 Chemical heat for electricity production",
#     "09.07 Oil refineries",
#     "09.09 Petrochemical industry",
# ]
# Build mapping helpers from MAJOR_SECTOR_CONFIG when needed.
#%%

#%%
######### FUNCTIONS #########
def ensure_repo_root():
    """No-op: retained for notebook backwards-compatibility. REPO_ROOT is resolved from __file__."""
    pass













@lru_cache(maxsize=None)
def _normalize_economy_value(value):
    """Normalize economy codes to a common underscore-free form.

    Memoized: pure function applied element-wise (tens of millions of calls)
    over a tiny set of distinct economy codes during workbook generation.
    """
    try:
        if value is None:
            return ""
        return str(value).replace("_", "").strip()
    except Exception as exc:
        print(f"Failed to normalize economy value {value}: {exc}")
        try_debug_breakpoint()
        raise


def select_rows(df, filters):
    """Return filtered rows based on a dict of column -> value."""
    try:
        mask = pd.Series(True, index=df.index)
        for column, value in filters.items():
            if column in df.columns:
                if column == "economy":
                    target = _normalize_economy_value(value)
                    mask &= df[column].apply(_normalize_economy_value).eq(target)
                else:
                    mask &= df[column].eq(value)
                continue

            if column in ["sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors"]:
                if "flows" in df.columns:
                    mask &= _match_code_prefix_mask(df["flows"], value)
                    continue
            if column in ["fuels", "subfuels"] and "products" in df.columns:
                mask &= _match_code_prefix_mask(df["products"], value)
                continue

            mask &= False
        return df.loc[mask]
    except Exception as exc:
        print(f"Failed to filter rows with {filters}: {exc}")
        try_debug_breakpoint()
        raise




def clean_esto_subtotals(df, year_cols):
    """Remove subtotal rows for pre/post 2022 and return a cleaned dataset."""
    try:
        required_cols = ["subtotal_2022_and_before", "subtotal_2023_and_after"]
        if not all(col in df.columns for col in required_cols):
            print("Subtotal flags missing; skipping ESTO subtotal cleanup.")
            return df
        pre_years = [col for col in year_cols if col <= 2022]
        post_years = [col for col in year_cols if col >= 2023]

        pre_non_subtotal = df[df["subtotal_2022_and_before"] == False].copy()
        post_non_subtotal = df[df["subtotal_2023_and_after"] == False].copy()

        pre_non_subtotal[post_years] = 0
        post_non_subtotal[pre_years] = 0

        key_cols = [
            col
            for col in df.columns
            if col not in year_cols
            and col not in ["subtotal_2022_and_before", "subtotal_2023_and_after"]
        ]

        combined = (
            pd.concat([pre_non_subtotal, post_non_subtotal], ignore_index=True)
            .groupby(key_cols, dropna=False)[year_cols]
            .sum()
            .reset_index()
        )
        combined["subtotal_2022_and_before"] = False
        combined["subtotal_2023_and_after"] = False
        return combined
    except Exception as exc:
        print(f"Failed to clean ESTO subtotals: {exc}")
        try_debug_breakpoint()
        raise


def normalize_esto_economy_codes(df):
    """Insert underscore in ESTO economy codes (e.g., 01AUS -> 01_AUS)."""
    try:
        if "economy" not in df.columns:
            return df
        updated = df.copy()
        updated["economy"] = (
            updated["economy"]
            .astype(str)
            .str.replace(r"^(\d{2})([A-Z].+)$", r"\1_\2", regex=True)
        )
        return updated
    except Exception as exc:
        print(f"Failed to normalize ESTO economy codes: {exc}")
        try_debug_breakpoint()
        raise


def filter_total_energy_rows(df):
    """Drop total/aggregate summary rows from fuels or products.

    Removes:
    - Named total rows (19 Total, 20 Total Renewables, 21 Modern renewables)
    - ESTO aggregate product codes that have no decimal point (e.g. '08 Gas',
      '01 Coal', '07 Petroleum products'). These are subtotals of their
      sub-product groups and should never appear as LEAP branch fuels.
    """
    try:
        import re as _re
        updated = df.copy()
        total_codes = {"19_total", "20_total_renewables", "21_modern_renewables"}
        total_labels = {
            "19 Total",
            "20 Total Renewables",
            "21 Modern renewables",
        }
        if "fuels" in updated.columns:
            updated = updated[~updated["fuels"].astype(str).isin(total_codes)]
        if "subfuels" in updated.columns:
            updated = updated[~updated["subfuels"].astype(str).isin(total_codes)]
        if "products" in updated.columns:
            # Drop named totals
            mask_named = updated["products"].astype(str).isin(total_labels)
            # Drop aggregate codes: two-digit number + space + name, no decimal
            # e.g. "08 Gas", "01 Coal", "07 Petroleum products"
            mask_aggregate = updated["products"].astype(str).str.match(
                r"^\d{2} ", na=False
            ) & ~updated["products"].astype(str).str.contains(r"\.", na=False)
            updated = updated[~(mask_named | mask_aggregate)]
        return updated
    except Exception as exc:
        print(f"Failed to filter total energy rows: {exc}")
        try_debug_breakpoint()
        raise






def print_sector_rows(df, sector_label, filters, year_cols, start_year, code_to_name_mapping=None):
    """Print rows for a sector so the user can manually inspect inputs/outputs."""
    try:
        if not PRINT_SECTOR_ROWS:
            return
        sector_rows = select_rows(df, filters)
        if sector_rows.empty:
            print(f"\n{sector_label}: no rows found")
            return
        year_cols_from_start = get_years_from(year_cols, start_year)
        summary = sector_rows.copy()
        summary["total_from_start"] = summary[year_cols_from_start].sum(axis=1)
        if PRINT_ONLY_NONZERO_ROWS:
            summary = summary[summary["total_from_start"] != 0]
        if summary.empty:
            print(f"\n{sector_label}: no nonzero rows after filtering")
            return
        columns_to_show = [
            "scenarios",
            "economy",
            "sectors",
            "sub1sectors",
            "sub2sectors",
            "sub3sectors",
            "sub4sectors",
            "fuels",
            "subfuels",
            "flows",
            "products",
            "total_from_start",
        ]
        columns_to_show = [col for col in columns_to_show if col in summary.columns]
        print(f"\n{sector_label}: rows {summary.shape[0]}")
        summary_to_show = summary[columns_to_show].copy()
        if code_to_name_mapping:
            columns_to_map = [
                "sectors",
                "sub1sectors",
                "sub2sectors",
                "sub3sectors",
                "sub4sectors",
                "fuels",
                "subfuels",
            ]
            for column in columns_to_map:
                if column in summary_to_show.columns:
                    summary_to_show[column] = summary_to_show[column].apply(
                        lambda value: map_code_label(value, code_to_name_mapping)
                    )
        print(summary_to_show.head(PRINT_TOP_FUEL_ROWS).to_string(index=False))
    except Exception as exc:
        print(f"Failed to print sector rows for {sector_label}: {exc}")
        try_debug_breakpoint()
        raise


def print_sector_rows_from_df(
    sector_rows, sector_label, year_cols, start_year, code_to_name_mapping=None
):
    """Print already-filtered rows for a sector."""
    try:
        if not PRINT_SECTOR_ROWS:
            return
        if sector_rows.empty:
            print(f"\n{sector_label}: no rows found")
            return
        year_cols_from_start = get_years_from(year_cols, start_year)
        summary = sector_rows.copy()
        summary["total_from_start"] = summary[year_cols_from_start].sum(axis=1)
        if PRINT_ONLY_NONZERO_ROWS:
            summary = summary[summary["total_from_start"] != 0]
        if summary.empty:
            print(f"\n{sector_label}: no nonzero rows after filtering")
            return
        columns_to_show = [
            "scenarios",
            "economy",
            "sectors",
            "sub1sectors",
            "sub2sectors",
            "sub3sectors",
            "sub4sectors",
            "fuels",
            "subfuels",
            "flows",
            "products",
            "total_from_start",
        ]
        columns_to_show = [col for col in columns_to_show if col in summary.columns]
        print(f"\n{sector_label}: rows {summary.shape[0]}")
        summary_to_show = summary[columns_to_show].copy()
        if code_to_name_mapping:
            columns_to_map = [
                "sectors",
                "sub1sectors",
                "sub2sectors",
                "sub3sectors",
                "sub4sectors",
                "fuels",
                "subfuels",
            ]
            for column in columns_to_map:
                if column in summary_to_show.columns:
                    summary_to_show[column] = summary_to_show[column].apply(
                        lambda value: map_code_label(value, code_to_name_mapping)
                    )
        print(summary_to_show.head(PRINT_TOP_FUEL_ROWS).to_string(index=False))
    except Exception as exc:
        print(f"Failed to print sector rows for {sector_label}: {exc}")
        try_debug_breakpoint()
        raise




def _match_est_product_label(product_value, code_value):
    """Check whether a product label shares the prefix of a target fuel code."""
    try:
        if product_value is None or (isinstance(product_value, float) and pd.isna(product_value)):
            return False
        return _match_code_prefix(str(product_value), code_value)
    except Exception as exc:
        print(f"Failed to match ESTO product label {product_value} to {code_value}: {exc}")
        try_debug_breakpoint()
        raise


def _filter_est_import_export_rows(economy, fuel_label, sector_label):
    """Return ESTO rows for a flow sector and fuel that match the economy."""
    try:
        if ESTO_IMPORT_EXPORT_REFERENCE_DATA is None or ESTO_IMPORT_EXPORT_REFERENCE_DATA.empty:
            return pd.DataFrame()
        df = ESTO_IMPORT_EXPORT_REFERENCE_DATA
        mask = pd.Series(True, index=df.index)
        if "flows" in df.columns:
            mask &= df["flows"].eq(sector_label)
        else:
            mask &= False
        if "economy" in df.columns:
            target = _normalize_economy_value(economy)
            mask &= df["economy"].apply(_normalize_economy_value).eq(target)
        else:
            mask &= False
        if "products" in df.columns:
            mask &= df["products"].apply(
                lambda value: _match_est_product_label(value, fuel_label)
            )
        else:
            mask &= False
        if not mask.any():
            return df.iloc[0:0]
        return df.loc[mask]
    except Exception as exc:
        print(f"Failed to filter import/export rows for {fuel_label}: {exc}")
        try_debug_breakpoint()
        raise


def build_est_output_target_dict(
    economy,
    fuel_label,
    sector_label,
    start_year,
    base_year,
    final_year,
    output_series=None,
    cap_to_output=False,
):
    """Build a per-year dictionary of import/export totals for a fuel."""
    try:
        if not ESTO_IMPORT_EXPORT_YEAR_COLS:
            return {}
        rows = _filter_est_import_export_rows(economy, fuel_label, sector_label)
        if rows.empty:
            return {}
        series = sum_years_by_year(rows, ESTO_IMPORT_EXPORT_YEAR_COLS, start_year)
        series = series.abs()
        if series.sum() == 0:
            return {}
        full_series = ensure_full_year_series(series, base_year, final_year)
        if output_series is not None and not output_series.empty:
            output_series = ensure_full_year_series(output_series.abs(), base_year, final_year)
            base_output = output_series.get(base_year, 0.0)
            base_export = full_series.get(base_year, 0.0)
            if base_output > 0 and base_export > 0:
                share = base_export / base_output
                max_export_year = max(series.index) if len(series.index) else base_year
                for year in range(base_year, final_year + 1):
                    if year <= max_export_year:
                        continue
                    if full_series.get(year, 0.0) == 0 and output_series.get(year, 0.0) != 0:
                        full_series[year] = output_series.get(year, 0.0) * share
            if cap_to_output:
                for year in range(base_year, final_year + 1):
                    export_value = float(full_series.get(year, 0.0))
                    output_value = max(float(output_series.get(year, 0.0)), 0.0)
                    if export_value > output_value:
                        full_series[year] = output_value
        return series_to_year_dict(full_series, base_year, final_year)
    except Exception as exc:
        print(f"Failed to build import/export target dict for {fuel_label}: {exc}")
        try_debug_breakpoint()
        raise


def gather_output_target_dicts(economy, output_labels, base_year, final_year, output_series_by_fuel=None):
    """Return dictionaries for import/export targets across output fuels."""
    try:
        import_targets = {}
        export_targets = {}
        if not output_labels:
            return import_targets, export_targets
        if (
            ESTO_IMPORT_EXPORT_REFERENCE_DATA is None
            or ESTO_IMPORT_EXPORT_REFERENCE_DATA.empty
            or not ESTO_IMPORT_EXPORT_YEAR_COLS
        ):
            return import_targets, export_targets
        for label in output_labels:
            output_series = None
            if output_series_by_fuel:
                output_series = output_series_by_fuel.get(label)
            if TRANSFORMATION_OUTPUT_VARIABLES.get("output_import_target"):
                import_dict = build_est_output_target_dict(
                    economy,
                    label,
                    ESTO_IMPORT_SECTOR_LABEL,
                    YEAR_START_FOR_ANALYSIS,
                    base_year,
                    final_year,
                    output_series=output_series,
                )
                if import_dict:
                    import_targets[label] = import_dict
            if TRANSFORMATION_OUTPUT_VARIABLES.get("output_export_target"):
                export_dict = build_est_output_target_dict(
                    economy,
                    label,
                    ESTO_EXPORT_SECTOR_LABEL,
                    YEAR_START_FOR_ANALYSIS,
                    base_year,
                    final_year,
                    output_series=output_series,
                    cap_to_output=True,
                )
                if export_dict:
                    export_targets[label] = export_dict
        return import_targets, export_targets
    except Exception as exc:
        print(f"Failed to gather output target dicts for {output_labels}: {exc}")
        try_debug_breakpoint()
        raise


def resolve_feedstock_method(method=None):
    """Return a normalized feedstock handling method."""
    try:
        raw = FEEDSTOCK_METHOD if method is None else method
        text = str(raw or "").strip().lower()
        mapping = {
            FEEDSTOCK_METHOD_SINGLE_AUX: FEEDSTOCK_METHOD_SINGLE_AUX,
            "single": FEEDSTOCK_METHOD_SINGLE_AUX,
            "single_feedstock": FEEDSTOCK_METHOD_SINGLE_AUX,
            "single_feedstock_aux": FEEDSTOCK_METHOD_SINGLE_AUX,
            "single_feedstock_aux_others": FEEDSTOCK_METHOD_SINGLE_AUX,
            FEEDSTOCK_METHOD_SPLIT: FEEDSTOCK_METHOD_SPLIT,
            "split": FEEDSTOCK_METHOD_SPLIT,
            "split_processes": FEEDSTOCK_METHOD_SPLIT,
            "split_processes_per_feedstock": FEEDSTOCK_METHOD_SPLIT,
            "per_feedstock": FEEDSTOCK_METHOD_SPLIT,
            FEEDSTOCK_METHOD_MULTI: FEEDSTOCK_METHOD_MULTI,
            "multi": FEEDSTOCK_METHOD_MULTI,
            "multi_feedstock": FEEDSTOCK_METHOD_MULTI,
            "multi_feedstock_single_process": FEEDSTOCK_METHOD_MULTI,
        }
        if text in mapping:
            return mapping[text]
        raise ValueError(
            f"Invalid feedstock method '{raw}'. "
            f"Use one of: {FEEDSTOCK_METHOD_SINGLE_AUX}, {FEEDSTOCK_METHOD_SPLIT}, {FEEDSTOCK_METHOD_MULTI}."
        )
    except Exception as exc:
        print(f"Failed to resolve feedstock method: {exc}")
        try_debug_breakpoint()
        raise


def build_input_series_map(timeseries, negative_labels, base_year, final_year):
    """Return (series_map, zero_sum_labels) for negative fuels.

    zero_sum_labels lists fuels that had no input values in the export year range.
    When INCLUDE_ALL_DETECTED_INPUT_FUELS is True those fuels are still included in
    series_map (with zero values); otherwise they are omitted.
    """
    try:
        series_map = {}
        zero_sum_labels = []
        if timeseries is None or negative_labels is None:
            return series_map, zero_sum_labels
        for label in negative_labels:
            if label not in timeseries.index:
                continue
            series = ensure_full_year_series(
                to_input_only_series(timeseries.loc[label]),
                base_year,
                final_year,
            )
            if series.sum() == 0:
                zero_sum_labels.append(label)
                if not INCLUDE_ALL_DETECTED_INPUT_FUELS:
                    continue
            series_map[label] = series
        return series_map, zero_sum_labels
    except Exception as exc:
        print(f"Failed to build input series map: {exc}")
        try_debug_breakpoint()
        raise


def log_dropped_input_fuels(economy, flow_code, zero_sum_labels, export_base_year, export_final_year):
    """Append zero-sum input fuel events to the module-level log."""
    for label in zero_sum_labels:
        included = INCLUDE_ALL_DETECTED_INPUT_FUELS
        _dropped_input_fuel_log.append(
            {
                "economy": economy,
                "flow_code": flow_code,
                "fuel_label": label,
                "export_base_year": export_base_year,
                "export_final_year": export_final_year,
                "outcome": "force_included_with_zeros" if included else "dropped",
            }
        )
        action = "force-included with zero values (INCLUDE_ALL_DETECTED_INPUT_FUELS=True)" if included else "dropped"
        print(
            f"[WARN] {flow_code} ({economy}): input fuel '{label}' has no usable values in "
            f"{export_base_year}–{export_final_year}; {action}."
        )


def get_dropped_fuel_log() -> list[dict]:
    """Return the current dropped-input-fuel log."""
    return list(_dropped_input_fuel_log)


def reset_dropped_fuel_log() -> None:
    """Clear the dropped-input-fuel log."""
    _dropped_input_fuel_log.clear()


def get_analyzed_sector_titles() -> set[str]:
    """Return the set of LEAP-mapped sector titles visited during the current run."""
    return set(_analyzed_sector_titles)


def reset_analyzed_sector_titles() -> None:
    """Clear the analyzed-sector-titles tracking set."""
    _analyzed_sector_titles.clear()


def print_dropped_fuel_summary() -> None:
    """Print a consolidated end-of-run summary of all dropped/force-included input fuels."""
    if not _dropped_input_fuel_log:
        print("[INFO] No input fuels were dropped or force-included during this run.")
        return
    dropped = [r for r in _dropped_input_fuel_log if r["outcome"] == "dropped"]
    forced = [r for r in _dropped_input_fuel_log if r["outcome"] == "force_included_with_zeros"]
    print(
        f"\n{'='*70}\n"
        f"INPUT FUEL SUMMARY ({len(_dropped_input_fuel_log)} event(s) total)\n"
        f"  Dropped (no export-range data):          {len(dropped)}\n"
        f"  Force-included with zero values:         {len(forced)}\n"
        f"{'='*70}"
    )
    if dropped:
        print("  DROPPED fuels:")
        for r in dropped:
            print(f"    [{r['economy']}] {r['flow_code']} -> {r['fuel_label']}")
    if forced:
        print("  FORCE-INCLUDED (zero values) fuels:")
        for r in forced:
            print(f"    [{r['economy']}] {r['flow_code']} -> {r['fuel_label']}")
    print(f"{'='*70}\n")


def save_dropped_fuel_report(path) -> None:
    """Save the dropped/force-included fuel log to a CSV and print summary."""
    print_dropped_fuel_summary()
    if not _dropped_input_fuel_log:
        return
    try:
        import csv as _csv
        path = str(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fieldnames = ["economy", "flow_code", "fuel_label", "export_base_year", "export_final_year", "outcome"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(_dropped_input_fuel_log)
        print(f"[INFO] Dropped/force-included fuel report saved to: {path}")
    except Exception as exc:
        print(f"[WARN] Failed to save dropped fuel report: {exc}")


def build_loss_context(
    loss_data,
    loss_year_cols,
    start_year,
    economy,
    sector_key,
    sub2_code=None,
    flow_code=None,
):
    """Return loss series, total, and value dict for a transformation code."""
    try:
        sector_config = MAJOR_SECTOR_CONFIG.get(sector_key, {})
        loss_sub2_map = sector_config.get("loss_sub2_map", {})
        loss_sub2_list = sector_config.get("loss_sub2", [])
        loss_flow_list = sector_config.get("loss_flow_codes", [])
        loss_sub2_code = None
        loss_flow_code = None
        if sub2_code and sub2_code in loss_sub2_map:
            loss_sub2_code = loss_sub2_map[sub2_code]
        elif loss_sub2_list:
            loss_sub2_code = loss_sub2_list[0]
        if loss_flow_list:
            loss_flow_code = loss_flow_list[0]
        loss_series, loss_total, loss_values_by_year = summarize_own_use_losses_by_year(
            loss_data,
            loss_year_cols,
            start_year,
            economy,
            loss_sub2_code,
            loss_flow_code,
            allow_all_years_fallback=True,
        )
        loss_values = {label: abs(value) for label, value in loss_series.items()}
        return loss_series, loss_total, loss_values, loss_values_by_year
    except Exception as exc:
        print(f"Failed to build loss context: {exc}")
        try_debug_breakpoint()
        raise


def summarize_own_use_losses(
    data,
    year_cols,
    start_year,
    economy,
    loss_sub2_code=None,
    loss_flow_code=None,
    allow_all_years_fallback=True,
):
    """Return (loss_series, loss_total) for own use/losses tied to a code.

    Source rows are negative because they belong to own-use/loss sectors, so the returned
    totals and loss_series entries are always converted to absolute (positive) values before
    reaching LEAP.
    """
    try:
        year_cols_from_start = get_years_from(year_cols, start_year)
        if loss_sub2_code:
            loss_rows = select_rows(
                data,
                {
                    "economy": economy,
                    "sectors": LOSS_SECTOR_CODE_9TH,
                    "sub2sectors": loss_sub2_code,
                },
            )
        elif loss_flow_code and "flows" in data.columns:
            loss_rows = select_rows(
                data,
                {
                    "economy": economy,
                    "flows": loss_flow_code,
                },
            )
        else:
            return pd.Series(dtype=float), 0.0
        if loss_rows.empty:
            return pd.Series(dtype=float), 0.0
        fuel_labels = get_fuel_labels(loss_rows)
        if fuel_labels is None:
            return pd.Series(dtype=float), 0.0
        totals = (
            loss_rows.assign(fuel_label=fuel_labels)
            .groupby("fuel_label")[year_cols_from_start]
            .sum()
            .sum(axis=1)
        )
        loss_series = totals[totals != 0].sort_values()
        if loss_series.empty and allow_all_years_fallback and year_cols:
            totals = (
                loss_rows.assign(fuel_label=fuel_labels)
                .groupby("fuel_label")[year_cols]
                .sum()
                .sum(axis=1)
            )
            loss_series = totals[totals != 0].sort_values()
        loss_total = loss_series.abs().sum()
        return loss_series, loss_total
    except Exception as exc:
        print(f"Failed to summarize own use losses: {exc}")
        try_debug_breakpoint()
        raise


def summarize_own_use_losses_by_year(
    data,
    year_cols,
    start_year,
    economy,
    loss_sub2_code=None,
    loss_flow_code=None,
    allow_all_years_fallback=True,
):
    """Return (loss_series_totals, loss_total, loss_values_by_year) for own use/losses."""
    try:
        year_cols_from_start = get_years_from(year_cols, start_year)
        if loss_sub2_code:
            loss_rows = select_rows(
                data,
                {
                    "economy": economy,
                    "sectors": LOSS_SECTOR_CODE_9TH,
                    "sub2sectors": loss_sub2_code,
                },
            )
        elif loss_flow_code and "flows" in data.columns:
            loss_rows = select_rows(
                data,
                {
                    "economy": economy,
                    "flows": loss_flow_code,
                },
            )
        else:
            return pd.Series(dtype=float), 0.0, {}
        if loss_rows.empty:
            return pd.Series(dtype=float), 0.0, {}
        fuel_labels = get_fuel_labels(loss_rows)
        if fuel_labels is None:
            return pd.Series(dtype=float), 0.0, {}
        timeseries = (
            loss_rows.assign(fuel_label=fuel_labels)
            .groupby("fuel_label")[year_cols_from_start]
            .sum()
        )
        if timeseries.empty and allow_all_years_fallback and year_cols:
            timeseries = (
                loss_rows.assign(fuel_label=fuel_labels)
                .groupby("fuel_label")[year_cols]
                .sum()
            )
        if timeseries.empty:
            return pd.Series(dtype=float), 0.0, {}
        timeseries = timeseries.loc[(timeseries != 0).any(axis=1)]
        loss_series = timeseries.sum(axis=1).sort_values()
        loss_total_by_year = timeseries.abs().sum(axis=0)
        loss_total = loss_total_by_year.sum()
        loss_values_by_year = {
            label: timeseries.loc[label].abs().to_dict()
            for label in timeseries.index
        }
        return loss_series, loss_total, loss_values_by_year
    except Exception as exc:
        print(f"Failed to summarize own use losses by year: {exc}")
        try_debug_breakpoint()
        raise


def get_flow_list(data, flow_codes=None):
    """Return a list of flow codes using explicit list."""
    try:
        if flow_codes:
            return list(flow_codes)
        return []
    except Exception as exc:
        print(f"Failed to build flow list: {exc}")
        try_debug_breakpoint()
        raise


def select_flow_rows(data, economy, flow_code):
    """Select rows for a single flow code."""
    try:
        if not flow_code or "flows" not in data.columns:
            return data.iloc[0:0]
        return select_rows(data, {"economy": economy, "flows": flow_code})
    except Exception as exc:
        print(f"Failed to select flow rows for {flow_code}: {exc}")
        try_debug_breakpoint()
        raise


def summarize_loss_sectors(
    data,
    year_cols,
    start_year,
    economy,
    loss_sub2_codes,
    code_to_name_mapping,
    title_prefix,
):
    """Print summaries for loss/own-use sectors."""
    try:
        print(f"\n==== {title_prefix} ({economy}) ====")
        if not has_required_columns(
            data,
            [["sub2sectors", "subfuels", "fuels"], ["flows", "products"]],
            title_prefix,
        ):
            return
        for loss_sub2 in loss_sub2_codes:
            label = map_code_label(loss_sub2, code_to_name_mapping)
            print_sector_rows(
                data,
                f"{title_prefix} rows ({label})",
                {
                    "economy": economy,
                    "sectors": LOSS_SECTOR_CODE_9TH,
                    "sub2sectors": loss_sub2,
                },
                year_cols,
                start_year,
                code_to_name_mapping,
            )
            loss_rows = select_rows(
                data,
                {
                    "economy": economy,
                    "sectors": LOSS_SECTOR_CODE_9TH,
                    "sub2sectors": loss_sub2,
                },
            )
            if loss_rows.empty:
                continue
            negatives, positives = summarize_fuels_by_subfuel(
                loss_rows, year_cols, start_year
            )
            if not negatives.empty:
                print("Loss inputs by fuel label:")
                print(map_series_index(negatives, code_to_name_mapping).to_string())
            if not positives.empty:
                print("Loss outputs by fuel label:")
                print(map_series_index(positives, code_to_name_mapping).to_string())
    except Exception as exc:
        print(f"Failed to summarize loss sectors: {exc}")
        try_debug_breakpoint()
        raise






def _build_mapping_from_leap_display_names(mapping_df: "pd.DataFrame") -> dict:
    """Build a code→name dict from the leap_display_names sheet format."""
    mapping = {}
    seen_codes: set = set()
    for _, row in mapping_df.iterrows():
        code = row.get("code")
        if code is None or (isinstance(code, float) and pd.isna(code)):
            continue
        code = str(code).strip()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        name = row.get("leap_display_name")
        if name is None or (isinstance(name, float) and pd.isna(name)) or str(name).strip() == "":
            name = row.get("auto_name")
        if name is None or (isinstance(name, float) and pd.isna(name)):
            continue
        name = str(name).strip()
        if name:
            mapping[code] = name
    return mapping


def load_code_to_name_mapping(path_candidates):
    """Load the code-to-name mapping from the first available workbook."""
    try:
        for path in path_candidates:
            path = Path(path)
            # outlook_mappings_master.xlsx uses the leap_display_names sheet format
            if path.name == "outlook_mappings_master.xlsx":
                if not path.exists():
                    continue
                try:
                    mapping_df = pd.read_excel(path, sheet_name="leap_display_names")
                except Exception as exc:
                    print(f"Failed to read leap_display_names from {path}: {exc}")
                    continue
                if not {"code", "leap_display_name"}.issubset(set(mapping_df.columns)):
                    print(f"leap_display_names in {path} missing expected columns; trying next file.")
                    continue
                mapping = _build_mapping_from_leap_display_names(mapping_df)
                if not mapping:
                    print(f"No usable mappings found in {path}; trying next file.")
                    continue
                print(f"Loaded code-to-name mapping from {path} (leap_display_names): {len(mapping)} entries")
                return mapping

            if not config_table_exists(path, sheet_name="code_to_name"):
                continue
            try:
                mapping_df = read_config_table(path, sheet_name="code_to_name")
            except Exception as exc:
                print(f"Failed to read code-to-name mapping from {path}: {exc}")
                continue
            required_cols = {"esto_label", "9th_label", "name"}
            if not required_cols.issubset(set(mapping_df.columns)):
                missing = sorted(required_cols - set(mapping_df.columns))
                print(
                    f"Missing {missing} columns in {path}; trying next file."
                )
                continue

            mapping = {}
            for _, row in mapping_df.iterrows():
                name = row.get("name")
                if name is None or (isinstance(name, float) and pd.isna(name)):
                    continue
                name = str(name).strip()
                if not name:
                    continue

                for col in ["esto_label", "9th_label"]:
                    label = row.get(col)
                    if label is None or (isinstance(label, float) and pd.isna(label)):
                        continue
                    label = str(label).strip()
                    if not label:
                        continue
                    if label in mapping and mapping[label] != name:
                        if col == "esto_label":
                            print(
                                f"Warning: overriding label {label} name "
                                f"{mapping[label]} with {name} (esto_label)."
                            )
                            mapping[label] = name
                        else:
                            print(
                                f"Warning: keeping existing name for label {label} "
                                f"({mapping[label]}); skipping {name} from {col}."
                            )
                        continue
                    mapping[label] = name

            if not mapping:
                print(f"No usable mappings found in {path}; trying next file.")
                continue

            print(f"Loaded code-to-name mapping from {path}: {len(mapping)} entries")
            return mapping

        raise ValueError("Code-to-name mapping not found in configured files.")
    except Exception as exc:
        print(f"Failed to load code-to-name mapping: {exc}")
        try_debug_breakpoint()
        raise



# ---------------------------------------------------------------------------
# Functions extracted to transformation_record_builder.py (Phase 3b).
# Re-exported here for backwards compatibility.
# ---------------------------------------------------------------------------
from codebase.functions.transformation_record_builder import (
    is_code_like_label,
    resolve_label_name,
    map_code_label,
    map_label_list,
    format_fuel_label,
    map_series_index,
    split_auxiliary_fuels,
    get_all_other_negative_fuels,
    has_required_columns,
    build_auxiliary_ratios,
    build_auxiliary_from_losses,
    merge_loss_into_auxiliary,
    filter_loss_values_for_feedstock,
    get_loss_total_for_efficiency,
    print_leap_structure_header,
    format_value,
    build_year_rows,
    build_value_by_year,
    coerce_value_by_year,
    normalize_feedstock_share_to_percent,
    resolve_scenario_year_range,
    clip_value_by_year_range,
    normalize_feedstock_shares_for_export,
    prepare_feedstock_shares_for_export,
    normalize_process_efficiency_to_percent,
    summarize_numeric_value,
    format_filename_segment,
    build_export_filename,
    compute_own_use_ratios_for_record,
    build_process_record,
    append_process_record,
    build_zero_skeleton_record,
    borrow_zero_skeleton_measures,
    select_primary_label,
    build_transformation_process_table,
    build_transformation_detail_table,
    build_branch_path,
    build_scenario_specific_rows,
    build_transformation_log_rows,
    build_data_expression,
    build_expression_export_df,
    build_export_from_log_rows,
    save_transformation_summaries,
    consolidate_transformation_output_rows,
    build_aux_fuel_zero_rows,
    save_transformation_export,
    print_leap_structure_block,
    get_scenario_export_config,
    compute_combined_year_range,
)

def calculate_efficiency(output_df, input_df, loss_df, year_cols):
    """Compute process efficiency as output / (abs(input) + abs(losses))."""
    try:
        output_total = sum_years(output_df, year_cols)
        input_total = abs(sum_years(input_df, year_cols))
        loss_total = abs(sum_years(loss_df, year_cols)) if loss_df is not None else 0.0
        if (input_total + loss_total) == 0:
            return 0.0
        return output_total / (input_total + loss_total)
    except Exception as exc:
        print(f"Failed to calculate efficiency: {exc}")
        try_debug_breakpoint()
        raise


def calculate_aux_fuel_use(aux_df, output_df, year_cols):
    """Compute auxiliary fuel use as abs(aux input) / output."""
    try:
        output_total = sum_years(output_df, year_cols)
        aux_total = abs(sum_years(aux_df, year_cols))
        if output_total == 0:
            return 0.0
        return aux_total / output_total
    except Exception as exc:
        print(f"Failed to calculate auxiliary fuel use: {exc}")
        try_debug_breakpoint()
        raise


def run_analysis_for_sector(run_flag, sector_key, analysis_callback, process_records):
    """Resolve dataset + economies and execute an analysis callback."""
    try:
        if not run_flag:
            return
        sector_config = dict(resolve_sector_config(sector_key))
        sector_config["sector_key"] = sector_key
        # Register this sector so zero-fill can clear its catalog branches even for
        # economies that had no ESTO data (no process record produced).
        sector_title = map_code_label(sector_config.get("title", ""), code_to_name_mapping)
        if sector_title:
            _analyzed_sector_titles.add(sector_title)
        data, year_cols = resolve_dataset(DATASET_MAP, sector_config["dataset_key"])
        loss_data, loss_year_cols = data, year_cols
        for economy in get_economy_list(data, ECONOMIES_TO_ANALYZE):
            analysis_callback(
                data,
                year_cols,
                economy,
                loss_data,
                loss_year_cols,
                sector_config,
                process_records,
            )
    except Exception as exc:
        print(f"Analysis runner failed for {sector_key}: {exc}")
        try_debug_breakpoint()
        raise
#%%

#%%
def resolve_sector_config(sector_key):
    """Return sector config for a sector key."""
    try:
        return MAJOR_SECTOR_CONFIG[sector_key]
    except Exception as exc:
        print(f"Failed to resolve config for {sector_key}: {exc}")
        try_debug_breakpoint()
        raise


def run_lng_analysis(
    data,
    year_cols,
    economy,
    loss_data,
    loss_year_cols,
    sector_config,
    process_records,
):
    """Run LNG analysis for a single economy."""
    analyze_lng_liquefaction_regas(
        data,
        year_cols,
        YEAR_START_FOR_ANALYSIS,
        economy,
        code_to_name_mapping,
        loss_data,
        loss_year_cols,
        sector_config,
        process_records,
        esto_reference_data=esto_data_raw,
        esto_reference_year_cols=esto_year_cols_raw,
    )


def run_gas_processing_analysis(
    data, year_cols, economy, loss_data, loss_year_cols, sector_config, process_records
):
    """Run gas processing analysis for a single economy."""
    analyze_gas_processing(
        data,
        year_cols,
        YEAR_START_FOR_ANALYSIS,
        economy,
        code_to_name_mapping,
        loss_data,
        loss_year_cols,
        sector_config,
        process_records,
    )


def run_flow_sector_analysis(
    data, year_cols, economy, loss_data, loss_year_cols, sector_config, process_records
):
    """Run a flow-based transformation analysis for a single economy."""
    summarize_transformation_flows(
        data,
        year_cols,
        YEAR_START_FOR_ANALYSIS,
        economy,
        sector_config.get("transformation_flow_codes"),
        sector_config.get("title", "Transformation"),
        code_to_name_mapping,
        loss_data,
        loss_year_cols,
        sector_config.get("sector_key", ""),
        process_records,
        multi_output=bool(sector_config.get("multi_output", False)),
    )


def run_coal_transformation_analysis(
    data, year_cols, economy, loss_data, loss_year_cols, sector_config, process_records
):
    """Run coal transformation analysis for a single economy."""
    run_flow_sector_analysis(
        data,
        year_cols,
        economy,
        loss_data,
        loss_year_cols,
        sector_config,
        process_records,
    )


def run_charcoal_processing_analysis(
    data, year_cols, economy, loss_data, loss_year_cols, sector_config, process_records
):
    """Run charcoal processing analysis for a single economy."""
    run_flow_sector_analysis(
        data,
        year_cols,
        economy,
        loss_data,
        loss_year_cols,
        sector_config,
        process_records,
    )


def run_nonspecified_transformation_analysis(
    data, year_cols, economy, loss_data, loss_year_cols, sector_config, process_records
):
    """Run nonspecified transformation analysis for a single economy."""
    run_flow_sector_analysis(
        data,
        year_cols,
        economy,
        loss_data,
        loss_year_cols,
        sector_config,
        process_records,
    )


def run_hydrogen_transformation_analysis(
    data, year_cols, economy, loss_data, loss_year_cols, sector_config, process_records
):
    """Run hydrogen transformation analysis for a single economy."""
    analyze_hydrogen_transformation(
        data,
        year_cols,
        YEAR_START_FOR_ANALYSIS,
        economy,
        code_to_name_mapping,
        loss_data,
        loss_year_cols,
        sector_config,
        process_records,
    )
#%%

#%%
######### CONSTANTS (LIKELY TO CHANGE) #########
# Editable workflow settings live in `codebase/workflow_config.py`.
RUN_LNG_ANALYSIS = workflow_cfg.TRANSFORMATION_RUN_LNG_ANALYSIS
RUN_GAS_PROCESSING_ANALYSIS = workflow_cfg.TRANSFORMATION_RUN_GAS_PROCESSING_ANALYSIS
RUN_COAL_TRANSFORMATION_ANALYSIS = workflow_cfg.TRANSFORMATION_RUN_COAL_TRANSFORMATION_ANALYSIS
RUN_OTHER_TRANSFORMATION_ANALYSIS = workflow_cfg.TRANSFORMATION_RUN_OTHER_TRANSFORMATION_ANALYSIS
RUN_CHARCOAL_PROCESSING_ANALYSIS = workflow_cfg.TRANSFORMATION_RUN_CHARCOAL_PROCESSING_ANALYSIS
RUN_NONSPECIFIED_TRANSFORMATION_ANALYSIS = (
    workflow_cfg.TRANSFORMATION_RUN_NONSPECIFIED_TRANSFORMATION_ANALYSIS
)
RUN_OIL_REFINERY_ANALYSIS = workflow_cfg.TRANSFORMATION_RUN_OIL_REFINERY_ANALYSIS
RUN_HYDROGEN_TRANSFORMATION_ANALYSIS = (
    workflow_cfg.TRANSFORMATION_RUN_HYDROGEN_TRANSFORMATION_ANALYSIS
)
ALL_ECONOMY_LABEL = workflow_cfg.TRANSFORMATION_ALL_ECONOMY_LABEL
INCLUDE_ALL_FEEDSTOCKS_AS_AUXILIARY = (
    workflow_cfg.TRANSFORMATION_INCLUDE_ALL_FEEDSTOCKS_AS_AUXILIARY
)
ECONOMIES_TO_ANALYZE = list(workflow_cfg.TRANSFORMATION_ECONOMIES_TO_ANALYZE)
SAVE_ESTO_SUBTOTAL_LABELED = workflow_cfg.TRANSFORMATION_SAVE_ESTO_SUBTOTAL_LABELED
ESTO_SUBTOTAL_LABELED_OUTPUT_PATH = (
    workflow_cfg.TRANSFORMATION_ESTO_SUBTOTAL_LABELED_OUTPUT_PATH
)
BUILD_LEAP_EXPORT = workflow_cfg.TRANSFORMATION_BUILD_LEAP_EXPORT
SAVE_LEAP_EXPORT_FILE = workflow_cfg.TRANSFORMATION_SAVE_LEAP_EXPORT_FILE
SAVE_SUMMARY_TABLES = workflow_cfg.TRANSFORMATION_SAVE_SUMMARY_TABLES
EXPORT_OUTPUT_DIR = workflow_cfg.TRANSFORMATION_EXPORT_OUTPUT_DIR
EXPORT_FILENAME_FALLBACK = workflow_cfg.TRANSFORMATION_EXPORT_FILENAME_FALLBACK
EXPORT_FILENAME_TEMPLATE = workflow_cfg.TRANSFORMATION_EXPORT_FILENAME_TEMPLATE
EXPORT_MODEL_NAME = workflow_cfg.TRANSFORMATION_EXPORT_MODEL_NAME
EXPORT_REGION = workflow_cfg.TRANSFORMATION_EXPORT_REGION
SCENARIOS_TO_EXPORT = list(workflow_cfg.TRANSFORMATION_SCENARIOS_TO_EXPORT)
EXPORT_BASE_YEAR = int(workflow_cfg.TRANSFORMATION_EXPORT_BASE_YEAR)
_config_final_year = workflow_cfg.TRANSFORMATION_EXPORT_FINAL_YEAR
EXPORT_FINAL_YEAR = (
    PROJECTION_END_YEAR if _config_final_year is None else int(_config_final_year)
)
SUMMARY_OUTPUT_DIR = workflow_cfg.TRANSFORMATION_SUMMARY_OUTPUT_DIR
PROCESS_SUMMARY_FILENAME = workflow_cfg.TRANSFORMATION_PROCESS_SUMMARY_FILENAME
DETAIL_SUMMARY_FILENAME = workflow_cfg.TRANSFORMATION_DETAIL_SUMMARY_FILENAME

# Skip emitting output series rows that LEAP does not expect.
INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT = (
    workflow_cfg.TRANSFORMATION_INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT
)

SAVE_PROJECTION_DIAGNOSTICS = workflow_cfg.TRANSFORMATION_SAVE_PROJECTION_DIAGNOSTICS
PROJECTION_DIAGNOSTICS_PATH = (
    workflow_cfg.TRANSFORMATION_PROJECTION_DIAGNOSTICS_PATH
)

SCENARIO_EXPORT_OVERRIDES = workflow_cfg.TRANSFORMATION_SCENARIO_EXPORT_OVERRIDES




def prepare_transformation_assets() -> None:
    """Load ESTO and 9th reference data and populate the module-level analysis globals.

    Must be called once before any run_*_analysis functions are invoked.
    This matches the explicit-init pattern used by supply_data_pipeline.prepare_supply_assets().
    """
    global DATASET_MAP, code_to_name_mapping, ESTO_IMPORT_EXPORT_REFERENCE_DATA, ESTO_IMPORT_EXPORT_YEAR_COLS
    global esto_data_raw, ninth_data_raw, esto_year_cols, ninth_year_cols, esto_year_cols_raw
    global esto_data, ninth_data
    if DATASET_MAP is not None:
        return
    workflow_common.archive_config_dir_once_per_day()
    esto_data_raw, ninth_data_raw = load_augmented_reference_tables(
        esto_path=ESTO_DATA_PATH,
        ninth_path=NINTH_DATA_PATH,
        subtotal_mapping_path=SUBTOTAL_MAPPING_PATH,
        synthetic_rules_path=CONFIG_DIR / "synthetic_reference_rows.csv",
        cache_dir=REFERENCE_CACHE_DIR,
        apply_esto_subtotal_map=True,
        filter_esto_subtotals_flag=False,
        filter_ninth_subtotals_flag=False,
    )
    print(
        f"Loaded ESTO data (augmented): {esto_data_raw.shape[0]} rows, {esto_data_raw.shape[1]} columns"
    )
    print(
        f"Loaded 9th data (augmented): {ninth_data_raw.shape[0]} rows, {ninth_data_raw.shape[1]} columns"
    )
     # Note: matt data lacks sub-sector columns; keep available for dataset_key="matt" only.
    
    ninth_data_raw, ninth_year_cols = normalize_year_columns(ninth_data_raw)
    esto_data_raw, esto_year_cols = normalize_year_columns(esto_data_raw)
    esto_year_cols_raw = list(esto_year_cols)
    
    ninth_data = clean_esto_subtotals(ninth_data_raw, ninth_year_cols)
    ninth_data = filter_reference_scenario(ninth_data, "9th data")
    if "subtotal_results" in ninth_data.columns:
        ninth_data = ninth_data[ninth_data["subtotal_results"] == False].copy()
    esto_data_raw = normalize_esto_economy_codes(esto_data_raw)
    esto_data_raw = filter_total_energy_rows(esto_data_raw)
    ninth_data = filter_total_energy_rows(ninth_data)
    esto_data_with_subtotals = apply_matt_subtotal_mapping(esto_data_raw, SUBTOTAL_MAPPING_PATH)
    # if SAVE_ESTO_SUBTOTAL_LABELED:
    #     save_subtotal_labeled_data(
    #         esto_data_with_subtotals,
    #         ESTO_SUBTOTAL_LABELED_OUTPUT_PATH,
    #         "ESTO (Matt) data",
    #     )
    esto_data = filter_matt_subtotals(esto_data_with_subtotals)
    _should_aggregate, _aggregate_label, _ = workflow_common.resolve_aggregate_economy(
        ECONOMIES_TO_ANALYZE,
        aggregate_label=ALL_ECONOMY_LABEL,
    )
    if _should_aggregate:
        ninth_data = add_all_economy_total(ninth_data, ninth_year_cols, _aggregate_label)
        esto_data = add_all_economy_total(esto_data, esto_year_cols, _aggregate_label)
    projection_sign_stable_flows = resolve_projection_sign_stable_flows(
        PROJECTION_SIGN_STABLE_MODE,
        SIGN_STABLE_PROJECTION_FLOWS,
    )
    projection_df, projection_diagnostics = build_esto_projection_table(
        ninth_data=ninth_data,
        esto_data=esto_data,
        mapping_path=NINTH_TO_ESTO_MAPPING_PATH,
        base_year=BASE_YEAR,
        projection_years=PROJECTION_YEAR_RANGE,
        sign_stable_flows=projection_sign_stable_flows,
        strict_conservation=PROJECTION_STRICT_CONSERVATION,
    )
    esto_data = merge_projection_into_esto(
        esto_data, projection_df, PROJECTION_YEAR_RANGE
    )
    esto_year_cols = sorted([col for col in esto_data.columns if str(col).isdigit()])
    if SAVE_PROJECTION_DIAGNOSTICS and projection_diagnostics is not None:
        if not projection_diagnostics.empty:
            os.makedirs(EXPORT_OUTPUT_DIR, exist_ok=True)
            projection_diagnostics.to_csv(PROJECTION_DIAGNOSTICS_PATH, index=False)
            print(f"Saved projection fallback report to {PROJECTION_DIAGNOSTICS_PATH}")
    code_to_name_mapping = (
        load_code_to_name_mapping(CODE_TO_NAME_PATHS) if USE_CODE_TO_NAME_MAPPING else {}
    )
    DATASET_MAP = build_dataset_map(
        esto_data,
        esto_year_cols,
        ninth_data,
        ninth_year_cols,
        esto_data_raw,
        esto_year_cols_raw,
    )
    ESTO_IMPORT_EXPORT_REFERENCE_DATA = esto_data
    ESTO_IMPORT_EXPORT_YEAR_COLS = esto_year_cols


# ---------------------------------------------------------------------------
# Functions extracted to transformation_sector_analysis.py (Phase 3e).
# Re-exported here for backwards compatibility.
# ---------------------------------------------------------------------------
from codebase.functions.transformation_sector_analysis import (  # noqa: F401, E402
    analyze_lng_liquefaction_regas,
    analyze_gas_processing,
    summarize_transformation_flows,
    analyze_hydrogen_transformation,
)
