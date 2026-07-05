#%%
# Summary: Load and prepare supply workflow datasets, mappings, and projection lookup.
import sys
from pathlib import Path
from typing import Iterable

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
    add_all_economy_total,
    build_dataset_map,
    filter_reference_scenario,
    normalize_year_columns,
)
from codebase.utilities.esto_reference_loader import (
    apply_esto_subtotal_mapping as apply_matt_subtotal_mapping,
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
SUBTOTAL_MAPPING_PATH = CONFIG_DIR / "ESTO_subtotal_mapping.xlsx"
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
# Keep supply projection splitting identical to transformation: preserve target
# signs wherever a same-sign base-year pool exists and fail on any loss of source
# energy during allocation.
PROJECTION_SIGN_STABLE_MODE = "all"
PROJECTION_STRICT_CONSERVATION = True


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
    # The subtotal-labeled debug output is intentionally disabled here to keep
    # asset preparation side effects aligned with the existing workflow.
    esto_data = filter_matt_subtotals(esto_data_with_subtotals)

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

    projection_df, projection_diagnostics = build_esto_projection_table(
        ninth_data=ninth_data,
        esto_data=esto_data,
        mapping_path=NINTH_TO_ESTO_MAPPING_PATH,
        base_year=BASE_YEAR,
        projection_years=PROJECTION_YEAR_RANGE,
        sign_stable_flows=PROJECTION_SIGN_STABLE_MODE,
        strict_conservation=PROJECTION_STRICT_CONSERVATION,
    )
    projection_lookup = build_projection_lookup(projection_df)
    global SUPPLY_PROJECTION_LOOKUP
    SUPPLY_PROJECTION_LOOKUP = projection_lookup
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
    assets = dataset_map, sector_config, code_to_name_mapping, ninth_data, esto_data
    if return_projection_lookup:
        return assets, projection_lookup
    return assets


#%%
