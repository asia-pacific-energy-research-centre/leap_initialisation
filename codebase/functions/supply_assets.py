#%%
# Summary: Load and prepare supply workflow datasets, mappings, and projection lookup.
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
from codebase.functions.conservation_policy import build_with_conservation_policy
from codebase.utilities.master_config import OUTLOOK_MAPPINGS_MASTER_PATH
from codebase.functions.esto_data_utils import (
    add_all_economy_total,
    build_dataset_map,
    normalize_year_columns,
)
from codebase.utilities.esto_reference_loader import (
    filter_esto_subtotals as filter_matt_subtotals,
    load_augmented_reference_tables,
)
from codebase.functions.ninth_projection_mapping import (
    build_esto_projection_table,
    build_projection_lookup,
)
from codebase.functions.supply_config_builder import (
    apply_code_to_name_mapping,
    build_supply_sector_config,
    load_code_to_name_mapping,
)


#%%
######### CONSTANTS (UNLIKELY TO CHANGE) #########
DATA_DIR = REPO_ROOT / "data"
ENERGY_SOURCE_CONFIG = workflow_cfg.get_energy_source_config()
ESTO_DATA_PATH = ENERGY_SOURCE_CONFIG.esto_base_table_path
NINTH_DATA_PATH = ENERGY_SOURCE_CONFIG.ninth_projection_table_path
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
USE_CODE_TO_NAME_MAPPING = True

EXCLUDED_ESTO_PREFIXES = ["19", "20", "21"]
SAVE_PROJECTION_DIAGNOSTICS = False
PROJECTION_DIAGNOSTICS_PATH = REPO_ROOT / "outputs" / "ninth_supply_projection_fallbacks.csv"
SUPPLY_PROJECTION_LOOKUP = None
SUPPLY_PROJECTION_LOOKUPS_BY_SCENARIO: dict[str, object] = {}
# Keep supply projection splitting identical to transformation: preserve target
# signs wherever a same-sign base-year pool exists.
# Conservation severity is no longer a local flag: it is owned repo-wide by
# functions/conservation_policy.py (warn by default; set
# CONSERVATION_FAILURES_ARE_ERRORS=True to raise). This used to be a second copy
# of PROJECTION_STRICT_CONSERVATION kept in manual sync with
# transformation_analysis_utils.
PROJECTION_SIGN_STABLE_MODE = "all"


#%%
######### FUNCTIONS #########
def prepare_supply_assets(
    economies: Iterable[str] | None = None,
    aggregate_economy_label: str | None = None,
    save_subtotal_labeled: bool = workflow_cfg.SUPPLY_SAVE_ESTO_SUBTOTAL_LABELED,
    subtotal_output_path: str = workflow_cfg.SUPPLY_ESTO_SUBTOTAL_LABELED_OUTPUT_PATH,
    return_projection_lookup: bool = False,
):
    """Load the supply datasets and build the required mappings."""
    del save_subtotal_labeled, subtotal_output_path

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

    # Keep both projection scenarios. Each is allocated independently onto the
    # ESTO flow/product shape below; filtering to Reference here previously
    # caused Reference values to be reused for Target throughout reconciliation.
    ninth_data = ninth_data_raw.copy()
    if "subtotal_results" in ninth_data.columns:
        ninth_data = ninth_data[ninth_data["subtotal_results"] == False].copy()
    esto_data = filter_matt_subtotals(esto_data_raw)

    economy_list = workflow_common.normalize_economies(
        economies or workflow_cfg.SUPPLY_ECONOMIES_TO_ANALYZE
    )
    should_aggregate, aggregate_label, _ = workflow_common.resolve_aggregate_economy(
        economy_list,
        aggregate_label=aggregate_economy_label or workflow_cfg.SUPPLY_ALL_ECONOMY_LABEL,
    )
    if should_aggregate:
        ninth_data = add_all_economy_total(
            ninth_data, ninth_year_cols, aggregate_label
        )
        esto_data = add_all_economy_total(
            esto_data, esto_year_cols, aggregate_label
        )

    available_projection_scenarios = []
    if "scenarios" in ninth_data.columns:
        available = {
            str(value).strip().lower()
            for value in ninth_data["scenarios"].dropna().tolist()
        }
        available_projection_scenarios = [
            scenario
            for scenario in ("Reference", "Target")
            if scenario.lower() in available
        ]
    if not available_projection_scenarios:
        available_projection_scenarios = ["Reference"]

    projection_lookups_by_scenario: dict[str, object] = {}
    projection_diagnostic_frames: list = []
    for scenario in available_projection_scenarios:
        projection_df, projection_diagnostics = build_with_conservation_policy(
            f"supply projection ({scenario})",
            lambda strict_conservation, scenario=scenario: build_esto_projection_table(
                ninth_data=ninth_data,
                esto_data=esto_data,
                mapping_path=NINTH_TO_ESTO_MAPPING_PATH,
                base_year=BASE_YEAR,
                projection_years=PROJECTION_YEAR_RANGE,
                scenario=scenario,
                sign_stable_flows=PROJECTION_SIGN_STABLE_MODE,
                strict_conservation=strict_conservation,
                fill_missing_ninth_sectors=workflow_cfg.FILL_IN_MISSING_9TH_SECTORS,
                owner_workflow="supply_workflow",
            ),
        )
        projection_lookups_by_scenario[scenario] = build_projection_lookup(projection_df)
        if projection_diagnostics is not None and not projection_diagnostics.empty:
            projection_diagnostic_frames.append(projection_diagnostics)

    global SUPPLY_PROJECTION_LOOKUP, SUPPLY_PROJECTION_LOOKUPS_BY_SCENARIO
    SUPPLY_PROJECTION_LOOKUPS_BY_SCENARIO = projection_lookups_by_scenario
    SUPPLY_PROJECTION_LOOKUP = projection_lookups_by_scenario.get("Reference")
    if (
        SAVE_PROJECTION_DIAGNOSTICS or workflow_cfg.FILL_IN_MISSING_9TH_SECTORS
    ) and projection_diagnostic_frames:
        projection_diagnostics = pd.concat(
            projection_diagnostic_frames,
            ignore_index=True,
            sort=False,
        )
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
    assets = dataset_map, sector_config, code_to_name_mapping, ninth_data, esto_data
    if return_projection_lookup:
        return assets, projection_lookups_by_scenario
    return assets


#%%
