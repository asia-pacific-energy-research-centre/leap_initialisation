#%%
# Summary: Build LEAP supply import/export values by fuel using ESTO/9th datasets.
# Most user-editable settings live in `codebase/workflow_config.py`.
# How it works:
# - Loads ESTO/9th data and normalizes year columns.
# - Filters 9th data to chosen scenario only.
# - For each fuel, selects import/export rows based on flow labels.
# - Uses 2022 ESTO base-year values plus 9th projections for 2023+.
# - Prints import/export totals for each fuel and economy.
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

# Ensure the repository root is importable for scripts executed from any location.
REPO_ROOT = Path(__file__).resolve().parents[2]
try:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
except Exception as exc:
    print(f"Failed to add repo root to sys.path: {exc}")

from codebase.utilities import workflow_common
from codebase.configuration import workflow_config as workflow_cfg
from codebase.utilities.master_config import OUTLOOK_MAPPINGS_MASTER_PATH
from codebase.functions.esto_data_utils import (
    try_debug_breakpoint,
    _extract_numeric_segments,
    _match_code_prefix,
    load_csv_data,
    normalize_year_columns,
    filter_reference_scenario,
    sum_years,
    add_all_economy_total,
    build_dataset_map,
    resolve_dataset,
)
from codebase.utilities.esto_reference_loader import (
    filter_esto_subtotals as filter_matt_subtotals,
    load_augmented_reference_tables,
)
from codebase.functions.ninth_projection_mapping import (
    build_esto_projection_table,
    build_projection_lookup,
    normalize_economy_key,
)
from codebase.functions import supply_assets as supply_assets_module
from codebase.functions import supply_diagnostics as supply_diagnostics_module
from codebase.functions.supply_branch_classification import (
    ESTO_PRODUCT_CLASSIFICATION,
    SECONDARY_ESTO_PRODUCT_EXACT,
    SECONDARY_ESTO_PRODUCT_MAJOR_CODES,
    SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH,
    SUPPLY_ROOT_CLASSIFICATION_SOURCE_SHEET,
    SUPPLY_ROOT_CLASSIFICATION_STRICT,
    _classify_supply_root_for_product,
    _esto_product_major_code,
    _is_secondary_esto_product,
    _load_supply_branch_path_lookup_from_export,
    _load_supply_root_lookup_from_export,
    _normalize_supply_branch_path_for_lookup,
    _normalize_supply_lookup_fuel_name,
    _read_branch_variable_rows_from_workbook,
    _resolve_supply_root_from_export_lookup,
)
from codebase.functions.supply_export_rows import (
    _normalize_override_year_map,
    sanitize_leap_label,
)
from codebase.functions.supply_config_builder import (
    apply_code_to_name_mapping,
    build_supply_sector_config,
    find_first_existing_file,
    load_code_to_name_mapping,
    map_code_label,
)
from codebase.functions.supply_value_series import (
    OUTPUT_FLOW_KEYS,
    _get_projection_series,
    build_ninth_bucket_allocator,
    build_supply_value_by_year,
    get_flow_series_for_fuel,
    get_flow_total_for_fuel,
    get_years_from,
    is_output_flow,
    normalize_supply_flow_total,
    select_flow_rows,
    select_fuel_rows,
    select_rows,
)
from codebase.functions.supply_export_io import (
    EXPORT_FILENAME_REGEX,
    _extract_fuel_from_branch_path,
    _match_scenario_token,
    _normalize_token,
    _read_unique_column,
    ensure_region_in_export,
    ensure_supply_fuel_exists,
    ensure_supply_fuels_from_export,
    extract_export_metadata,
    get_available_scenarios,
    get_supply_fuels_from_export,
    locate_supply_export,
    _print_supply_missing_both_primary_secondary_summary,
    run_branch_fill,
    run_supply_leap_import,
)
from codebase.functions.supply_export_builder import (
    APEC_ECONOMY_REGION_MAP,
    EXPORT_BASE_YEAR,
    EXPORT_ECONOMY_REGION_OVERRIDES,
    EXPORT_FILENAME_TEMPLATE,
    EXPORT_FINAL_YEAR,
    EXPORT_MODEL_NAME,
    EXPORT_OUTPUT_DIR,
    EXPORT_REGION,
    EXPORT_SCENARIOS,
    FLOW_CODES_BY_DATASET,
    SUPPLY_MEASURES,
    build_supply_log_rows,
    format_scenario_label_for_filename,
    generate_supply_exports as _generate_supply_exports,
    get_region_for_economy,
)
#%%

#%%
######### CONSTANTS (UNLIKELY TO CHANGE) #########
DATA_DIR = REPO_ROOT / "data"
ENERGY_SOURCE_CONFIG = workflow_cfg.get_energy_source_config()
ESTO_DATA_PATH = ENERGY_SOURCE_CONFIG.esto_base_table_path
# Use merged_file_energy_ALL_20251106.csv and merged_file_energy_00_APEC_20251106 for exact 9th edition projection matching.
NINTH_DATA_PATH = ENERGY_SOURCE_CONFIG.ninth_projection_table_path
# Backward-compatible aliases for older notebook imports. Prefer the names above.
MATT_DATA_PATH = ESTO_DATA_PATH
CONFIG_DIR = REPO_ROOT / "config"
NINTH_TO_ESTO_MAPPING_PATH = (OUTLOOK_MAPPINGS_MASTER_PATH, "ninth_pairs_to_esto_pairs")
CODE_TO_NAME_PATHS = [
    OUTLOOK_MAPPINGS_MASTER_PATH,
]

BASE_YEAR = ENERGY_SOURCE_CONFIG.esto_base_year
PROJECTION_START_YEAR = ENERGY_SOURCE_CONFIG.projection_start_year
PROJECTION_END_YEAR = 2060
if ENERGY_SOURCE_CONFIG.projection_final_year is not None:
    PROJECTION_END_YEAR = int(ENERGY_SOURCE_CONFIG.projection_final_year)
PROJECTION_YEAR_RANGE = list(range(PROJECTION_START_YEAR, PROJECTION_END_YEAR + 1))
REFERENCE_CACHE_DIR = DATA_DIR / ".cache" / "supply_reference_tables"
ENABLE_DEBUG_BREAKPOINTS = True
PRINT_FUEL_ROWS = True
PRINT_ONLY_NONZERO_ROWS = True
PRINT_TOP_ROWS = 10
USE_CODE_TO_NAME_MAPPING = True

EXCLUDED_ESTO_PREFIXES = ["19", "20", "21"]
SAVE_PROJECTION_DIAGNOSTICS = False
PROJECTION_DIAGNOSTICS_PATH = REPO_ROOT / "outputs" / "ninth_supply_projection_fallbacks.csv"
SUPPLY_PROJECTION_LOOKUP = None
# MAJOR_SECTOR_CONFIG uses ESTO labels for filtering, but display names can be
# filled from sector_fuel_codes_to_names.xlsx (code_to_name) via mapping below.
#%%

#%%
######### FUNCTIONS #########








def print_flow_rows(df, label, year_cols):
    """Compatibility wrapper for diagnostic flow row printing."""
    return supply_diagnostics_module.print_flow_rows(
        df,
        label,
        year_cols,
        print_fuel_rows=PRINT_FUEL_ROWS,
        print_only_nonzero_rows=PRINT_ONLY_NONZERO_ROWS,
        print_top_rows=PRINT_TOP_ROWS,
    )










def summarize_supply_for_fuel(
    data,
    year_cols,
    economy,
    fuel_config,
    flow_codes,
    base_year,
    code_to_name_mapping=None,
):
    """Compatibility wrapper for import/export fuel summaries."""
    return supply_diagnostics_module.summarize_supply_for_fuel(
        data,
        year_cols,
        economy,
        fuel_config,
        flow_codes,
        base_year,
        code_to_name_mapping=code_to_name_mapping,
        print_fuel_rows=PRINT_FUEL_ROWS,
        print_only_nonzero_rows=PRINT_ONLY_NONZERO_ROWS,
        print_top_rows=PRINT_TOP_ROWS,
    )
#%%

#%%
def list_unique_fuels_and_products(ninth_data, esto_data):
    """Compatibility wrapper for listing fuel and product labels."""
    return supply_diagnostics_module.list_unique_fuels_and_products(ninth_data, esto_data)
#%%

#%%
#%%
######### WORKFLOW CONTROLS #########
RUN_SUPPLY_ANALYSIS = workflow_cfg.SUPPLY_RUN_SUPPLY_ANALYSIS
RUN_LIST_FUELS = workflow_cfg.SUPPLY_RUN_LIST_FUELS
ALL_ECONOMY_LABEL = workflow_cfg.SUPPLY_ALL_ECONOMY_LABEL
ECONOMIES_TO_ANALYZE = list(workflow_cfg.SUPPLY_ECONOMIES_TO_ANALYZE)
SAVE_ESTO_SUBTOTAL_LABELED = workflow_cfg.SUPPLY_SAVE_ESTO_SUBTOTAL_LABELED
ESTO_SUBTOTAL_LABELED_OUTPUT_PATH = workflow_cfg.SUPPLY_ESTO_SUBTOTAL_LABELED_OUTPUT_PATH
EXPORT_DATASET_KEY = workflow_cfg.SUPPLY_EXPORT_DATASET_KEY
EXPORT_DIR = workflow_cfg.SUPPLY_EXPORT_DIR
EXPORT_FILE_NAME = workflow_cfg.SUPPLY_EXPORT_FILE_NAME
SCENARIO_TO_RUN = workflow_cfg.SUPPLY_SCENARIO_TO_RUN
FILL_BRANCHES_FROM_EXPORT_FILE = workflow_cfg.SUPPLY_FILL_BRANCHES_FROM_EXPORT_FILE
HANDLE_CURRENT_ACCOUNTS_TOO = workflow_cfg.SUPPLY_HANDLE_CURRENT_ACCOUNTS_TOO
RUN_SUPPLY_LEAP_IMPORT = workflow_cfg.SUPPLY_RUN_SUPPLY_LEAP_IMPORT
SHEET_NAME = workflow_cfg.SUPPLY_SHEET_NAME
#%%


def prepare_supply_assets(
    economies: Iterable[str] | None = None,
    aggregate_economy_label: str | None = None,
    save_subtotal_labeled: bool = SAVE_ESTO_SUBTOTAL_LABELED,
    subtotal_output_path: str = ESTO_SUBTOTAL_LABELED_OUTPUT_PATH,
):
    """Compatibility wrapper for loading supply datasets and mappings."""
    supply_assets_module.ESTO_DATA_PATH = ESTO_DATA_PATH
    supply_assets_module.NINTH_DATA_PATH = NINTH_DATA_PATH
    supply_assets_module.NINTH_TO_ESTO_MAPPING_PATH = NINTH_TO_ESTO_MAPPING_PATH
    supply_assets_module.CODE_TO_NAME_PATHS = CODE_TO_NAME_PATHS
    supply_assets_module.BASE_YEAR = BASE_YEAR
    supply_assets_module.PROJECTION_YEAR_RANGE = PROJECTION_YEAR_RANGE
    supply_assets_module.REFERENCE_CACHE_DIR = REFERENCE_CACHE_DIR
    supply_assets_module.USE_CODE_TO_NAME_MAPPING = USE_CODE_TO_NAME_MAPPING
    supply_assets_module.EXCLUDED_ESTO_PREFIXES = EXCLUDED_ESTO_PREFIXES
    supply_assets_module.SAVE_PROJECTION_DIAGNOSTICS = SAVE_PROJECTION_DIAGNOSTICS
    supply_assets_module.PROJECTION_DIAGNOSTICS_PATH = PROJECTION_DIAGNOSTICS_PATH

    assets, projection_lookup = supply_assets_module.prepare_supply_assets(
        economies=economies,
        aggregate_economy_label=aggregate_economy_label,
        save_subtotal_labeled=save_subtotal_labeled,
        subtotal_output_path=subtotal_output_path,
        return_projection_lookup=True,
    )
    global SUPPLY_PROJECTION_LOOKUP
    SUPPLY_PROJECTION_LOOKUP = projection_lookup
    return assets


def generate_supply_exports(
    dataset_map,
    fuel_config,
    code_to_name_mapping,
    projection_lookup=None,
    projection_years=None,
    dataset_key: str = EXPORT_DATASET_KEY,
    economies: list[str] | None = None,
    scenario_names=EXPORT_SCENARIOS,
    base_year=EXPORT_BASE_YEAR,
    final_year=EXPORT_FINAL_YEAR,
    export_output_dir: Path | str = EXPORT_OUTPUT_DIR,
    filename_template: str = EXPORT_FILENAME_TEMPLATE,
    flow_value_overrides_by_economy: dict | None = None,
    supply_measures: list[dict] | None = None,
    keep_all_zero_rows: bool = False,
):
    """Compatibility wrapper around the extracted supply export builder."""
    return _generate_supply_exports(
        dataset_map,
        fuel_config,
        code_to_name_mapping,
        projection_lookup=projection_lookup,
        projection_years=projection_years,
        dataset_key=dataset_key,
        economies=economies,
        scenario_names=scenario_names,
        base_year=base_year,
        final_year=final_year,
        export_output_dir=export_output_dir,
        filename_template=filename_template,
        flow_value_overrides_by_economy=flow_value_overrides_by_economy,
        supply_measures=supply_measures,
        keep_all_zero_rows=keep_all_zero_rows,
        projection_lookup_default=SUPPLY_PROJECTION_LOOKUP,
        economies_to_analyze=ECONOMIES_TO_ANALYZE,
        resolve_dataset_func=resolve_dataset,
    )


def run_supply_pipeline(
    run_list_fuels: bool = RUN_LIST_FUELS,
    run_supply_analysis: bool = RUN_SUPPLY_ANALYSIS,
    dataset_key: str = EXPORT_DATASET_KEY,
    economies: list[str] | None = None,
):
    """Orchestrate the supply export analysis workflow."""
    assets = None
    if run_list_fuels or run_supply_analysis:
        assets = prepare_supply_assets(economies=economies)
    if run_list_fuels and assets:
        _, _, _, ninth_data, esto_data = assets
        list_unique_fuels_and_products(ninth_data, esto_data)

    export_paths: list[Path] = []
    if run_supply_analysis and assets:
        dataset_map, sector_config, code_to_name_mapping, _, _ = assets
        exports = generate_supply_exports(
            dataset_map,
            sector_config,
            code_to_name_mapping,
            projection_years=PROJECTION_YEAR_RANGE,
            dataset_key=dataset_key,
            economies=economies,
        )
        export_paths = [path for _, path in exports]
    return export_paths


if __name__ == "__main__":
    run_supply_pipeline()
    if RUN_SUPPLY_LEAP_IMPORT:
        run_supply_leap_import()

#%%
