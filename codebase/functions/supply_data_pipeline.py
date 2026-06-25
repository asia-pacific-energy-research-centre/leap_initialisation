#%%
# Summary: Build LEAP supply import/export values by fuel using ESTO/9th datasets.
# Most user-editable settings live in `codebase/workflow_config.py`.
# How it works:
# - Loads ESTO/9th data and normalizes year columns.
# - Filters 9th data to chosen scenario only.
# - For each fuel, selects import/export rows based on flow labels.
# - Uses 2022 ESTO base-year values plus 9th projections for 2023+.
# - Prints import/export totals for each fuel and economy.
import os
import re
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
from codebase.utilities import fuel_catalog_preflight
from codebase.configuration import workflow_config as workflow_cfg
from codebase.functions.esto_data_utils import (
    try_debug_breakpoint,
    _extract_numeric_segments,
    _match_code_prefix,
    load_csv_data,
    normalize_year_columns,
    filter_reference_scenario,
    sum_years,
    get_economy_list,
    add_all_economy_total,
    build_dataset_map,
    resolve_dataset,
)
from codebase.functions.analysis_input_write_dispatcher import (
    dispatch_analysis_input_write,
)
from codebase.functions.leap_core import (
    connect_to_leap,
    fill_branches_from_export_file,
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
    build_projection_lookup,
    normalize_economy_key,
)
from codebase.functions.supply_branch_classification import (
    ESTO_PRODUCT_CLASSIFICATION,
    SECONDARY_ESTO_PRODUCT_EXACT,
    SECONDARY_ESTO_PRODUCT_MAJOR_CODES,
    SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH,
    SUPPLY_ROOT_CLASSIFICATION_SOURCE_SHEET,
    SUPPLY_ROOT_CLASSIFICATION_STRICT,
    _SUPPLY_BRANCH_PATH_MISS_WARNED,
    _classify_supply_root_for_product,
    _esto_product_major_code,
    _get_supply_branch_roots_for_entry,
    _is_secondary_esto_product,
    _load_supply_branch_path_lookup_from_export,
    _load_supply_root_lookup_from_export,
    _normalize_supply_branch_path_for_lookup,
    _normalize_supply_lookup_fuel_name,
    _read_branch_variable_rows_from_workbook,
    _resolve_supply_root_from_export_lookup,
    _supply_branch_exists_in_export_source,
)
from codebase.functions.supply_export_rows import (
    _normalize_override_year_map,
    _resolve_supply_override,
    build_branch_path,
    build_year_rows,
    coerce_value_by_year,
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
SUBTOTAL_MAPPING_PATH = CONFIG_DIR / "ESTO_subtotal_mapping.xlsx"
NINTH_TO_ESTO_MAPPING_PATH = CONFIG_DIR / "ninth_pairs_to_esto_pairs.xlsx"
CODE_TO_NAME_PATHS = [
    CONFIG_DIR / "sector_fuel_codes_to_names.updated.xlsx",
    CONFIG_DIR / "sector_fuel_codes_to_names.xlsx",
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

FLOW_CODES_BY_DATASET = {
    "esto": {
        "production": "01 Production",
        "imports": "02 Imports",
        "exports": "03 Exports",
        "stock_changes": "06 Stock changes",
        "tpes": "07 Total primary energy supply",
    },
    "ninth": {
        "production": "01_production",
        "imports": "02_imports",
        "exports": "03_exports",
        "stock_changes": "06_stock_changes",
        "tpes": "07_total_primary_energy_supply",
    },
}

EXCLUDED_ESTO_PREFIXES = ["19", "20", "21"]
SUPPLY_MEASURES = [
    {"name": "Imports", "flow_key": "imports", "units": "Petajoule", "per": ""},
    {"name": "Exports", "flow_key": "exports", "units": "Petajoule", "per": ""},
    {
        "name": "Unmet Requirements",
        "flow_key": None,
        "units": "Percent",
        "per": "MeetWithImports",
        "value": 0.0,
    },
]
if not getattr(workflow_cfg, "SUPPLY_INCLUDE_UNMET_REQUIREMENTS", False):
    SUPPLY_MEASURES = [
        measure for measure in SUPPLY_MEASURES if measure.get("name") != "Unmet Requirements"
    ]
EXPORT_SCENARIOS = ["Current Accounts", "Reference", "Target"]
DEFAULT_EXPORT_OUTPUT_DIR = REPO_ROOT / "outputs" / "leap_exports"
EXPORT_OUTPUT_DIR = Path(
    os.environ.get("SUPPLY_LEAP_EXPORT_DIR", str(DEFAULT_EXPORT_OUTPUT_DIR))
)
EXPORT_FILENAME_TEMPLATE = "supply_leap_imports_{economy}_{scenarios}.xlsx"
EXPORT_FILENAME_REGEX = re.compile(
    r"supply_leap_imports_(?P<economy>[^_]+)_(?P<scenarios>.+)\.xlsx",
    re.IGNORECASE,
)
EXPORT_MODEL_NAME = "USA transport supply imports"
EXPORT_REGION = "United States"
EXPORT_BASE_YEAR = BASE_YEAR
EXPORT_FINAL_YEAR = PROJECTION_END_YEAR

APEC_ECONOMY_REGION_MAP: dict[str, str] = {
    "01_AUS": "Australia",
    "02_BD": "Brunei Darussalam",
    "03_CDA": "Canada",
    "04_CHL": "Chile",
    "05_PRC": "China",
    "06_HKC": "Hong Kong, China",
    "07_INA": "Indonesia",
    "08_JPN": "Japan",
    "09_ROK": "Republic of Korea",
    "10_MAS": "Malaysia",
    "11_MEX": "Mexico",
    "12_NZ": "New Zealand",
    "13_PNG": "Papua New Guinea",
    "14_PE": "Peru",
    "15_PHL": "The Philippines",
    "16_RUS": "Russia",
    "17_SGP": "Singapore",
    "18_CT": "Chinese Taipei",
    "19_THA": "Thailand",
    "20_USA": "United States",
    "21_VN": "Viet Nam",
}

EXPORT_ECONOMY_REGION_OVERRIDES = {"20USA": EXPORT_REGION}
SAVE_PROJECTION_DIAGNOSTICS = False
PROJECTION_DIAGNOSTICS_PATH = REPO_ROOT / "outputs" / "ninth_supply_projection_fallbacks.csv"
SUPPLY_PROJECTION_LOOKUP = None
# MAJOR_SECTOR_CONFIG uses ESTO labels for filtering, but display names can be
# filled from sector_fuel_codes_to_names.xlsx (code_to_name) via mapping below.
#%%

#%%
######### FUNCTIONS #########


def ensure_repo_root():
    """Move to repo root if running from the scrapbook folder."""
    try:
        if os.getcwd().endswith("scrapbook"):
            os.chdir("../../")
    except Exception as exc:
        print(f"Failed to set repo root: {exc}")
        try_debug_breakpoint()
        raise






def print_flow_rows(df, label, year_cols):
    """Print flow rows for debugging."""
    try:
        if not PRINT_FUEL_ROWS:
            return
        if df.empty:
            print(f"{label}: no rows found")
            return
        summary = df.copy()
        summary["total_base_year"] = summary[year_cols].sum(axis=1)
        if PRINT_ONLY_NONZERO_ROWS:
            summary = summary[summary["total_base_year"] != 0]
        if summary.empty:
            print(f"{label}: no nonzero rows after filtering")
            return
        columns_to_show = [
            "scenarios",
            "economy",
            "sectors",
            "flows",
            "fuels",
            "subfuels",
            "products",
            "total_base_year",
        ]
        columns_to_show = [col for col in columns_to_show if col in summary.columns]
        print(f"{label}: rows {summary.shape[0]}")
        print(summary[columns_to_show].head(PRINT_TOP_ROWS).to_string(index=False))
    except Exception as exc:
        print(f"Failed to print flow rows: {exc}")
        try_debug_breakpoint()
        raise










def summarize_supply_for_fuel(
    data,
    year_cols,
    economy,
    fuel_config,
    flow_codes,
    base_year,
    code_to_name_mapping=None,
):
    """Print import/export totals for a fuel and economy."""
    try:
        year_cols_from_base = get_years_from(year_cols, base_year)
        display_name = fuel_config.get("fuel_name", fuel_config["fuel_label_esto"])
        fuel_rows = select_fuel_rows(
            data,
            fuel_config["fuel_code_ninth"],
            fuel_config["fuel_label_esto"],
            fuel_name=fuel_config.get("fuel_name"),
            code_to_name_mapping=code_to_name_mapping,
        )
        if fuel_rows.empty:
            print(f"{display_name}: no fuel rows found")
            return

        imports_rows = select_flow_rows(fuel_rows, economy, flow_codes["imports"])
        exports_rows = select_flow_rows(fuel_rows, economy, flow_codes["exports"])

        print_flow_rows(imports_rows, f"{economy} imports", year_cols_from_base)
        print_flow_rows(exports_rows, f"{economy} exports", year_cols_from_base)

        imports_total = sum_years(imports_rows, year_cols_from_base)
        exports_total = sum_years(exports_rows, year_cols_from_base)

        print(
            f"{economy} {display_name} (base {base_year}): "
            f"imports {imports_total:.3f}, exports {exports_total:.3f}"
        )
    except Exception as exc:
        print(f"Failed to summarize supply for {fuel_config}: {exc}")
        try_debug_breakpoint()
        raise
#%%

#%%
def list_unique_fuels_and_products(ninth_data, esto_data):
    """Print unique fuel/subfuel combos (9th) and products (ESTO)."""
    try:
        if "fuels" in ninth_data.columns and "subfuels" in ninth_data.columns:
            fuels = (
                ninth_data[["fuels", "subfuels"]]
                .dropna()
                .drop_duplicates()
                .sort_values(["fuels", "subfuels"])
            )
            fuel_pairs = list(fuels.itertuples(index=False, name=None))
            print(f"9th fuel/subfuel combos: {len(fuel_pairs)}")
            for fuel, subfuel in fuel_pairs:
                print(f"- {fuel} / {subfuel}")
        else:
            print("9th data missing fuels/subfuels columns")

        if "products" in esto_data.columns:
            products = (
                esto_data[["products"]]
                .dropna()
                .drop_duplicates()
                .sort_values(["products"])
            )
            product_list = products["products"].astype(str).tolist()
            print(f"ESTO products: {len(product_list)}")
            for product in product_list:
                print(f"- {product}")
        else:
            print("ESTO data missing products column")
    except Exception as exc:
        print(f"Failed to list unique fuels/products: {exc}")
        try_debug_breakpoint()
        raise
#%%

#%%
def get_region_for_economy(economy_code):
    """Return the LEAP region name that should be used for an economy."""
    try:
        code = str(economy_code).strip()
        if code in APEC_ECONOMY_REGION_MAP:
            return APEC_ECONOMY_REGION_MAP[code]
        return EXPORT_ECONOMY_REGION_OVERRIDES.get(code, EXPORT_REGION)
    except Exception as exc:
        print(f"Failed to resolve region for {economy_code}: {exc}")
        try_debug_breakpoint()
        raise


def format_scenario_label_for_filename(scenarios):
    """Return a filename-friendly scenario string."""
    try:
        sanitized = "_".join(
            "".join(ch for ch in scenario if ch.isalnum())
            for scenario in scenarios
        )
        return sanitized or "scenarios"
    except Exception as exc:
        print(f"Failed to build filename-safe scenario label: {exc}")
        try_debug_breakpoint()
        raise


def build_supply_log_rows(
    data,
    year_cols,
    economy,
    fuel_config,
    flow_codes,
    scenario_names,
    base_year,
    final_year,
    code_to_name_mapping=None,
    projection_lookup=None,
    projection_years=None,
    flow_value_overrides=None,
    supply_measures=None,
):
    """Build log entries for supply measures per fuel."""
    try:
        if not fuel_config:
            print("Warning: no supply fuels available for export.")
            return []
        measures = supply_measures if isinstance(supply_measures, list) and supply_measures else SUPPLY_MEASURES
        rows = []
        for fuel_key in sorted(fuel_config):
            entry = fuel_config[fuel_key]
            display_name = entry.get("fuel_name") or entry["fuel_label_esto"]
            safe_name = sanitize_leap_label(display_name)
            branch_roots = _get_supply_branch_roots_for_entry(fuel_key, entry)
            required_flow_keys = {
                str(measure.get("flow_key") or "").strip()
                for measure in measures
                if str(measure.get("flow_key") or "").strip()
            }
            default_flow_values_by_year = {}
            for flow_key in sorted(required_flow_keys):
                source_flow_key = "production" if flow_key == "max_production" else flow_key
                flow_value = flow_codes.get(source_flow_key)
                default_flow_values_by_year[flow_key] = build_supply_value_by_year(
                    data,
                    year_cols,
                    economy,
                    entry,
                    source_flow_key,
                    flow_value,
                    base_year,
                    final_year,
                    projection_lookup=projection_lookup,
                    projection_years=projection_years,
                    code_to_name_mapping=code_to_name_mapping,
                )
            for scenario in scenario_names:
                for branch_root in branch_roots:
                    branch_path = build_branch_path(branch_root + [safe_name])
                    if not _supply_branch_exists_in_export_source(branch_path):
                        miss_key = f"{economy}|{scenario}|{branch_path}"
                        if miss_key not in _SUPPLY_BRANCH_PATH_MISS_WARNED:
                            _SUPPLY_BRANCH_PATH_MISS_WARNED.add(miss_key)
                            print(
                                "[WARN] Skipping supply export row for branch not present in "
                                "canonical full-model export source: "
                                f"{branch_path} (economy={economy}, scenario={scenario}, fuel={display_name})"
                            )
                        continue
                    branch_type = str(branch_root[-1] if branch_root else "").strip().lower()
                    for measure in measures:
                        root_filter = str(measure.get("branch_root") or "").strip().lower()
                        if root_filter and root_filter not in {"all", branch_type}:
                            continue
                        flow_key = measure.get("flow_key")
                        if flow_key:
                            override_value_by_year = _resolve_supply_override(
                                flow_value_overrides,
                                scenario,
                                fuel_key,
                                entry,
                                flow_key,
                                base_year,
                                final_year,
                            )
                            value_by_year = override_value_by_year or default_flow_values_by_year.get(
                                flow_key, {year: 0.0 for year in range(base_year, final_year + 1)}
                            )
                        else:
                            value_by_year = coerce_value_by_year(
                                measure.get("value", 0.0), base_year, final_year
                            )
                        rows.extend(
                            build_year_rows(
                                branch_path,
                                measure["name"],
                                scenario,
                                value_by_year,
                                measure["units"],
                                "",
                                measure["per"],
                            )
                        )
        return rows
    except Exception as exc:
        print(f"Failed to build supply log rows for {economy}: {exc}")
        try_debug_breakpoint()
        raise

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
    """Load the supply datasets and build the required mappings."""
    ensure_repo_root()
    sector_config = build_supply_sector_config(
        CODE_TO_NAME_PATHS,
        exclude_prefixes=EXCLUDED_ESTO_PREFIXES,
    )
    code_to_name_mapping = (
        load_code_to_name_mapping(CODE_TO_NAME_PATHS) if USE_CODE_TO_NAME_MAPPING else {}
    )
    if code_to_name_mapping:
        sector_config = apply_code_to_name_mapping(
            sector_config, code_to_name_mapping
        )

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
    ninth_data_raw, ninth_year_cols = normalize_year_columns(ninth_data_raw)
    esto_data_raw, esto_year_cols = normalize_year_columns(esto_data_raw)

    ninth_data = filter_reference_scenario(ninth_data_raw, "9th data")
    if "subtotal_results" in ninth_data.columns:
        ninth_data = ninth_data[ninth_data["subtotal_results"] == False].copy()
    esto_data_with_subtotals = apply_matt_subtotal_mapping(
        esto_data_raw, SUBTOTAL_MAPPING_PATH
    )
    # if save_subtotal_labeled:
    #     save_subtotal_labeled_data(
    #         esto_data_with_subtotals,
    #         subtotal_output_path,
    #         "ESTO (Matt) data",
    #     )
    esto_data = filter_matt_subtotals(esto_data_with_subtotals)

    economy_list = workflow_common.normalize_economies(economies or ECONOMIES_TO_ANALYZE)
    should_aggregate, aggregate_label, _ = workflow_common.resolve_aggregate_economy(
        economy_list,
        aggregate_label=aggregate_economy_label or ALL_ECONOMY_LABEL,
    )
    if should_aggregate:
        ninth_data = add_all_economy_total(
            ninth_data, ninth_year_cols, aggregate_label
        )
        esto_data = add_all_economy_total(
            esto_data, esto_year_cols, aggregate_label
        )

    projection_df, projection_diagnostics = build_esto_projection_table(
        ninth_data=ninth_data,
        esto_data=esto_data,
        mapping_path=NINTH_TO_ESTO_MAPPING_PATH,
        base_year=BASE_YEAR,
        projection_years=PROJECTION_YEAR_RANGE,
    )
    global SUPPLY_PROJECTION_LOOKUP
    SUPPLY_PROJECTION_LOOKUP = build_projection_lookup(projection_df)
    if SAVE_PROJECTION_DIAGNOSTICS and projection_diagnostics is not None:
        if not projection_diagnostics.empty:
            PROJECTION_DIAGNOSTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
            projection_diagnostics.to_csv(PROJECTION_DIAGNOSTICS_PATH, index=False)
            print(f"Saved projection fallback report to {PROJECTION_DIAGNOSTICS_PATH}")

    dataset_map = build_dataset_map(
        esto_data,
        esto_year_cols,
        ninth_data,
        ninth_year_cols,
        esto_data_raw,
        esto_year_cols,
    )
    return dataset_map, sector_config, code_to_name_mapping, ninth_data, esto_data


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
    """Generate LEAP-ready supply exports for the requested economies."""
    data, year_cols = resolve_dataset(dataset_map, dataset_key)
    flow_codes = FLOW_CODES_BY_DATASET.get(dataset_key)
    if not flow_codes:
        raise KeyError(f"Unknown dataset key for flow codes: {dataset_key}")
    if projection_lookup is None:
        projection_lookup = SUPPLY_PROJECTION_LOOKUP
    target_economies = economies or get_economy_list(data, ECONOMIES_TO_ANALYZE)
    scenario_label = ", ".join(scenario_names)
    scenario_filename = format_scenario_label_for_filename(scenario_names)
    saved_exports: list[tuple[str, Path]] = []

    for economy in target_economies:
        economy_flow_overrides = None
        if isinstance(flow_value_overrides_by_economy, dict):
            economy_flow_overrides = flow_value_overrides_by_economy.get(economy)
        log_rows = build_supply_log_rows(
            data,
            year_cols,
            economy,
            fuel_config,
            flow_codes,
            scenario_names,
            base_year,
            final_year,
            code_to_name_mapping=code_to_name_mapping,
            projection_lookup=projection_lookup,
            projection_years=projection_years,
            flow_value_overrides=economy_flow_overrides,
            supply_measures=supply_measures,
        )
        if not log_rows:
            print(f"No supply rows generated for {economy}")
            continue
        log_df = pd.DataFrame(log_rows)
        region_name = get_region_for_economy(economy)
        export_df = finalise_export_df(
            log_df, scenario_label, region_name, base_year, final_year
        )
        if export_df is None:
            print(f"Skipping export for {economy} because no data survived pivot.")
            continue
        year_columns = [
            column for column in export_df.columns if isinstance(column, int)
        ]
        if year_columns and not keep_all_zero_rows:
            numeric_years = (
                export_df[year_columns]
                .apply(pd.to_numeric, errors="coerce")
                .fillna(0.0)
            )
            nonzero_mask = numeric_years.abs().sum(axis=1) > 0.0
            dropped_count = int((~nonzero_mask).sum())
            if dropped_count:
                print(
                    f"[INFO] Dropping {dropped_count} all-zero supply rows from export for {economy}."
                )
            export_df = export_df.loc[nonzero_mask].copy()
        if export_df.empty:
            print(
                f"Skipping export for {economy} because all supply rows are zero after filtering."
            )
            continue
        os.makedirs(export_output_dir, exist_ok=True)
        export_path = Path(export_output_dir) / filename_template.format(
            economy=economy, scenarios=scenario_filename
        )
        save_export_files(
            export_df,
            export_df,
            export_path,
            base_year,
            final_year,
            EXPORT_MODEL_NAME,
        )
        saved_exports.append((economy, export_path))
        print(f"Saved supply LEAP import for {economy} at {export_path}")

    return saved_exports


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


def run_branch_fill(
    L,
    export_path: Path,
    scenario: str,
    region: str,
    handle_current_accounts: bool,
    raise_on_missing_branch: bool = True,
) -> None:
    """Load data into supply branches from the export workbook."""
    try:
        outcome = fill_branches_from_export_file(
            L,
            export_path,
            sheet_name=SHEET_NAME,
            scenario=scenario,
            region=region,
            RAISE_ERROR_ON_FAILED_SET=raise_on_missing_branch,
            SET_UNITS=True,
            HANDLE_CURRENT_ACCOUNTS_TOO=handle_current_accounts,
            RUN_FUEL_CATALOG_PREFLIGHT=False,
        )
        print(f"[INFO] Supply branch fill result: {outcome}")
        _print_supply_missing_both_primary_secondary_summary(outcome)
    except Exception as exc:
        print(f"[ERROR] Supply branch fill failed: {exc}")
        try_debug_breakpoint()
        raise


def _print_supply_missing_both_primary_secondary_summary(outcome: dict | None) -> None:
    """Print fuels that failed in all attempted Resources roots during branch fill."""
    if not isinstance(outcome, dict):
        return

    def _extract_root_and_fuel(branch_path: str | None) -> tuple[str | None, str | None]:
        parts = [part.strip() for part in str(branch_path or "").split("\\") if part and str(part).strip()]
        if len(parts) < 3:
            return None, None
        if parts[0].lower() != "resources":
            return None, None
        root = parts[1].strip()
        if root.lower() not in {"primary", "secondary"}:
            return None, None
        fuel = parts[2].strip()
        if not fuel:
            return None, None
        return root.title(), fuel

    success_roots_by_fuel: dict[str, set[str]] = {}
    failed_roots_by_fuel: dict[str, set[str]] = {}

    for branch_path, variable in outcome.get("success", []) or []:
        var_name = str(variable or "").strip().lower()
        if var_name not in {"imports", "exports"}:
            continue
        root, fuel = _extract_root_and_fuel(branch_path)
        if not root or not fuel:
            continue
        success_roots_by_fuel.setdefault(fuel, set()).add(root)

    for branch_path, variable in outcome.get("failed", []) or []:
        var_name = str(variable or "").strip().lower()
        if var_name not in {"imports", "exports"}:
            continue
        root, fuel = _extract_root_and_fuel(branch_path)
        if not root or not fuel:
            continue
        failed_roots_by_fuel.setdefault(fuel, set()).add(root)

    fuels_missing_all_attempted: list[str] = []
    for fuel, failed_roots in sorted(failed_roots_by_fuel.items()):
        if success_roots_by_fuel.get(fuel):
            continue
        if failed_roots:
            fuels_missing_all_attempted.append(
                f"{fuel} (attempted: {', '.join(sorted(failed_roots))})"
            )

    if fuels_missing_all_attempted:
        print(
            "[WARN] Supply fuels not found in attempted Resources root(s) "
            f"({len(fuels_missing_all_attempted)}): {', '.join(fuels_missing_all_attempted)}"
        )
    else:
        print(
            "[INFO] Supply branch lookup summary: no fuels were missing in their "
            "attempted Resources root(s)."
        )


def run_supply_leap_import(
    export_directory: Path = EXPORT_DIR,
    filename: str | None = EXPORT_FILE_NAME,
    scenario_to_run: str = SCENARIO_TO_RUN,
    region: str = EXPORT_REGION,
    handle_current_accounts: bool = HANDLE_CURRENT_ACCOUNTS_TOO,
    fill_branches: bool = FILL_BRANCHES_FROM_EXPORT_FILE,
) -> Path:
    """Locate the supply export and optionally fill the matching LEAP branches."""
    export_path = locate_supply_export(export_directory, filename)
    declared_scenarios = extract_export_metadata(export_path)
    available_scenarios = get_available_scenarios(export_path)
    print(
        f"[INFO] Preparing supply import from '{export_path.name}', declared scenarios "
        f"{declared_scenarios}, available scenarios {available_scenarios}."
    )
    if scenario_to_run not in available_scenarios:
        raise ValueError(
            f"Desired scenario '{scenario_to_run}' not present; available: {available_scenarios}"
        )
    ensure_region_in_export(export_path, region)

    dispatch_result = dispatch_analysis_input_write(
        export_path=export_path,
        sheet_name=SHEET_NAME,
        scenario=scenario_to_run,
        region=region,
        context_label="supply_data_pipeline.run_supply_leap_import",
    )
    if dispatch_result.get("mode") == "workbook":
        return export_path

    L = connect_to_leap()
    if L is None:
        raise RuntimeError("Failed to connect to LEAP.")
    fuel_catalog_preflight.run_fuel_catalog_preflight(
        export_path=export_path,
        sheet_name=SHEET_NAME,
        scenario=scenario_to_run,
        context="supply_data_pipeline.run_supply_leap_import",
        leap_app=L,
    )

    if fill_branches:
        print(
            "[INFO] Supply branches under Resources auto-create when their fuels "
            "are first used in Transformation/Demand and can be skipped until LEAP "
            "creates them."
        )
        ensure_supply_fuels_from_export(L, export_path)
        run_branch_fill(
            L,
            export_path,
            scenario_to_run,
            region,
            handle_current_accounts,
            raise_on_missing_branch=False,
        )
    return export_path


if __name__ == "__main__":
    run_supply_pipeline()
    if RUN_SUPPLY_LEAP_IMPORT:
        run_supply_leap_import()

#%%
