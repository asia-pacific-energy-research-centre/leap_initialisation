# Centralized workflow configuration for interactive runs and notebooks.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codebase.utilities.output_paths import (
    COMBINED_LEAP_EXPORTS_ROOT,
    LEAP_EXPORTS_ROOT,
    STANDALONE_LEAP_EXPORTS_ROOT,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

###############################
# CORE SETTINGS (LIKELY TO EDIT)
###############################
# These drive most workflows. Set these first.

# Accepts a string or list. Use "00_APEC" (or "ALL_ECONOMIES") to trigger aggregation.
def _normalize_economies(value) -> list[str]:
    """Return a normalized economy list from a string/iterable input."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return [str(item).strip() for item in value if str(item).strip()]


def _resolve_global_aggregate(economies: list[str]) -> str:
    """Infer the aggregate economy label from a normalized economy list."""
    if len(economies) == 1 and economies[0] in {"00_APEC", "ALL_ECONOMIES", "ALL"}:
        return economies[0]
    return "ALL_ECONOMIES"

# Default to individual APEC member economies so workbook producers emit
# reusable per-economy files. Use an explicit aggregate sentinel when a
# 00_APEC / ALL_ECONOMIES run is wanted.
GLOBAL_ECONOMIES = _normalize_economies(
    [
        "01_AUS",
        "02_BD",
        "03_CDA",
        "04_CHL",
        "05_PRC",
        "06_HKC",
        "07_INA",
        "08_JPN",
        "09_ROK",
        "10_MAS",
        "11_MEX",
        "12_NZ",
        "13_PNG",
        "14_PE",
        "15_PHL",
        "16_RUS",
        "17_SGP",
        "18_CT",
        "19_THA",
        "20_USA",
        "21_VN",
    ]
)
# Multiple economies -> per-economy runs (no aggregation unless a sentinel is used).
GLOBAL_SCENARIOS = ["Reference", "Target", "Current Accounts"]
GLOBAL_BASE_YEAR = 2022
# None means: fall back to the workflow/module default final year.
GLOBAL_FINAL_YEAR = None
GLOBAL_REGION = "United States"
GLOBAL_EXPORT_OUTPUT_DIR = STANDALONE_LEAP_EXPORTS_ROOT
GLOBAL_AGGREGATE_ECONOMY_LABEL = _resolve_global_aggregate(GLOBAL_ECONOMIES)

# Final baseline-seed validation coverage. These are deliberately independent
# of projection-only producer windows: final imports must explicitly cover the
# complete configured model horizon for every represented scenario.
BASELINE_SEED_VALIDATION_BASE_YEAR = 2022
BASELINE_SEED_VALIDATION_FINAL_YEAR = 2060
# Set back to True (2026-07-10) at the user's explicit instruction: current
# blocking findings are not considered significant enough to hold up a run.
# This contradicts the confirmed INIT-005 design decision (deferring failure
# must not turn a blocking finding into a warning) -- see
# docs/special_rules_and_design_decisions.md (INIT-005 History) for the prior
# 2026-07-07/2026-07-10 back-and-forth on this flag. It also re-fails 3 tests
# in tests/test_baseline_seed_writer_validation.py that assert blocking
# findings raise BaselineSeedValidationError
# (test_final_writer_writes_diagnostics_before_conflict_blocks,
# test_writer_accumulates_economy_failures_and_writes_no_final_workbook,
# test_default_reference_validation_window_requires_2023_through_2060).
# Revert to False to restore the INIT-005 guarantee once reviewed.
BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS = True

# Retained modelling decision: refining Exogenous Capacity follows Historical
# Production, using the existing unit conversion metadata in refining_workflow.
REFINING_USE_HISTORICAL_PRODUCTION_CAPACITY_HEURISTIC = True

# LEAP sometimes exports a "full model output all years ... REF.xlsx" workbook
# whose internal "Scenario: X, Year: Y, Units: Z" sheet subtitles say "Target"
# (a LEAP-side export mistake, not a data error). When True, the filename's
# REF/TGT token is trusted and the workbook is used for that scenario anyway;
# when False, a mismatch between the filename and the internal Scenario label
# raises instead. Disable this if mislabeled exports start masking real
# Reference/Target mix-ups.
BALANCE_EXPORT_TRUST_FILENAME_SCENARIO = True


def get_baseline_seed_validation_years(
    scenarios,
    *,
    base_year: int | None = None,
    final_year: int | None = None,
) -> dict[str, list[int]]:
    """Return Current Accounts base-year and projection scenario windows."""
    resolved_base = int(
        BASELINE_SEED_VALIDATION_BASE_YEAR if base_year is None else base_year
    )
    resolved_final = int(
        BASELINE_SEED_VALIDATION_FINAL_YEAR if final_year is None else final_year
    )
    if resolved_final < resolved_base:
        raise ValueError(
            f"Baseline-seed final year {resolved_final} precedes base year {resolved_base}."
        )
    result: dict[str, list[int]] = {}
    for scenario in scenarios:
        name = str(scenario).strip()
        if not name:
            continue
        if name.lower() in {"current account", "current accounts"}:
            result[name] = [resolved_base]
        else:
            result[name] = list(range(resolved_base + 1, resolved_final + 1))
    return result


@dataclass(frozen=True)
class EnergySourceConfig:
    """Resolved ESTO observed/base-year table and ninth projection table config."""

    esto_base_table_path: Path
    esto_base_year: int
    ninth_projection_table_path: Path
    projection_start_year: int
    projection_final_year: int | None = None


def _resolve_repo_path(path_value: str | Path) -> Path:
    """Resolve relative config paths against the repository root."""
    path = Path(str(path_value).replace("\\", "/"))
    return path if path.is_absolute() else REPO_ROOT / path


# Shared ESTO/ninth source pairing for active reconciliation workflows.
# Update these together when changing ESTO vintage; do not infer the base year
# from the filename because future source files may not be year-stamped cleanly.
ENERGY_SOURCE_ESTO_BASE_TABLE_PATH = "data/00APEC_2024_low_with_subtotals.csv"
ENERGY_SOURCE_ESTO_BASE_YEAR = GLOBAL_BASE_YEAR
ENERGY_SOURCE_NINTH_PROJECTION_TABLE_PATH = "data/merged_file_energy_ALL_20251106.csv"
ENERGY_SOURCE_PROJECTION_START_YEAR = ENERGY_SOURCE_ESTO_BASE_YEAR + 1
# None means each workflow keeps its existing final-year default.
ENERGY_SOURCE_PROJECTION_FINAL_YEAR = GLOBAL_FINAL_YEAR


def get_energy_source_config() -> EnergySourceConfig:
    """Return the resolved shared ESTO/ninth source configuration."""
    return EnergySourceConfig(
        esto_base_table_path=_resolve_repo_path(ENERGY_SOURCE_ESTO_BASE_TABLE_PATH),
        esto_base_year=int(ENERGY_SOURCE_ESTO_BASE_YEAR),
        ninth_projection_table_path=_resolve_repo_path(ENERGY_SOURCE_NINTH_PROJECTION_TABLE_PATH),
        projection_start_year=int(ENERGY_SOURCE_PROJECTION_START_YEAR),
        projection_final_year=(
            None
            if ENERGY_SOURCE_PROJECTION_FINAL_YEAR is None
            else int(ENERGY_SOURCE_PROJECTION_FINAL_YEAR)
        ),
    )

# Global Analysis-view input write mode:
# - "api" keeps current behavior (write directly via LEAP API)
# - "workbook" disables Analysis-view API writes and keeps workbook/manual import only
ANALYSIS_INPUT_WRITE_MODE = "workbook"
ANALYSIS_INPUT_FIELD_MAPPING_PATH = REPO_ROOT / "config" / "leap_export_workbook_mappings.xlsx"
ANALYSIS_INPUT_FIELD_MAPPING_SHEET = "field_mappings"
ANALYSIS_INPUT_CANONICAL_TEMPLATE_PATHS = [
    REPO_ROOT / "data" / "full model export.xlsx",
    LEAP_EXPORTS_ROOT,
]

#########################
# HELPER FUNCTIONS (RARE)
#########################
# Only needed if you want to customize file naming behavior.

def _format_scenario_token(scenarios: list[str]) -> str:
    """Return a filename-friendly scenario string."""
    sanitized = "_".join(
        "".join(ch for ch in str(scenario) if ch.isalnum()) for scenario in scenarios
    )
    return sanitized or "scenarios"


def _default_supply_export_filename(
    economies: list[str], scenarios: list[str]
) -> str:
    """Return a default supply export filename aligned to current globals."""
    economy_label = economies[0] if economies else "ALL"
    scenario_token = _format_scenario_token(scenarios)
    return f"supply_leap_imports_{economy_label}_{scenario_token}.xlsx"

###############################
# WORKFLOW SETTINGS (LESS USED)
###############################
# Everything below can be left alone unless a workflow needs a special override.

###############################
# TRANSFORMATION ANALYSIS
###############################
TRANSFORMATION_RUN_LNG_ANALYSIS = True
TRANSFORMATION_RUN_GAS_PROCESSING_ANALYSIS = True
TRANSFORMATION_RUN_COAL_TRANSFORMATION_ANALYSIS = True
TRANSFORMATION_RUN_OTHER_TRANSFORMATION_ANALYSIS = True
TRANSFORMATION_RUN_CHARCOAL_PROCESSING_ANALYSIS = True
TRANSFORMATION_RUN_NONSPECIFIED_TRANSFORMATION_ANALYSIS = True
TRANSFORMATION_RUN_OIL_REFINERY_ANALYSIS = True
TRANSFORMATION_RUN_HYDROGEN_TRANSFORMATION_ANALYSIS = True
TRANSFORMATION_ALL_ECONOMY_LABEL = GLOBAL_AGGREGATE_ECONOMY_LABEL
TRANSFORMATION_INCLUDE_ALL_FEEDSTOCKS_AS_AUXILIARY = True
TRANSFORMATION_ECONOMIES_TO_ANALYZE = list(GLOBAL_ECONOMIES)
TRANSFORMATION_SAVE_ESTO_SUBTOTAL_LABELED = True
TRANSFORMATION_ESTO_SUBTOTAL_LABELED_OUTPUT_PATH = (
    ENERGY_SOURCE_ESTO_BASE_TABLE_PATH
)
TRANSFORMATION_BUILD_LEAP_EXPORT = True
TRANSFORMATION_SAVE_LEAP_EXPORT_FILE = True
TRANSFORMATION_SAVE_SUMMARY_TABLES = True
TRANSFORMATION_EXPORT_OUTPUT_DIR = GLOBAL_EXPORT_OUTPUT_DIR
TRANSFORMATION_EXPORT_FILENAME_FALLBACK = "transformation_leap_imports.xlsx"
TRANSFORMATION_EXPORT_FILENAME_TEMPLATE = (
    "transformation_leap_imports_{economy}_{scenario}.xlsx"
)
TRANSFORMATION_EXPORT_MODEL_NAME = "LEAP Transformation Imports"
TRANSFORMATION_EXPORT_REGION = GLOBAL_REGION
TRANSFORMATION_SCENARIOS_TO_EXPORT = list(GLOBAL_SCENARIOS)
TRANSFORMATION_EXPORT_BASE_YEAR = ENERGY_SOURCE_ESTO_BASE_YEAR
# None means: fall back to PROJECTION_END_YEAR in transformation_analysis_utils.
TRANSFORMATION_EXPORT_FINAL_YEAR = GLOBAL_FINAL_YEAR
TRANSFORMATION_SUMMARY_OUTPUT_DIR = (
    Path(TRANSFORMATION_EXPORT_OUTPUT_DIR) / "supporting_files" / "transformation"
)
TRANSFORMATION_PROCESS_SUMMARY_FILENAME = "transformation_process_summary.csv"
TRANSFORMATION_DETAIL_SUMMARY_FILENAME = "transformation_detail_summary.csv"
TRANSFORMATION_INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT = False
TRANSFORMATION_SAVE_PROJECTION_DIAGNOSTICS = False
TRANSFORMATION_PROJECTION_DIAGNOSTICS_PATH = (
    Path(TRANSFORMATION_SUMMARY_OUTPUT_DIR) / "ninth_projection_allocation_fallbacks.csv"
)
TRANSFORMATION_CLIP_PROCESS_EFFICIENCY_TO_MAX = True
TRANSFORMATION_PROCESS_EFFICIENCY_MAX_PERCENT = 1000.0
TRANSFORMATION_SCENARIO_EXPORT_OVERRIDES = {
    "Current Accounts": {
        "include_current_account_rows": True,
    },
    "Current Account": {
        "include_current_account_rows": True,
    },
}

###############################
# TRANSFORMATION WORKFLOW (WRAPPER)
###############################
TRANSFORMATION_WORKFLOW_SHEET_NAME = "LEAP"
TRANSFORMATION_WORKFLOW_EXPORT_FILENAME_PREFIX = "transformation_leap_imports_"
TRANSFORMATION_WORKFLOW_DEFAULT_SCENARIOS = list(GLOBAL_SCENARIOS)

###############################
# HYDROGEN TRANSFORMATION
###############################
HYDROGEN_SHEET_NAME = "LEAP"
HYDROGEN_EXPORT_FILENAME_PREFIX = "hydrogen_transformation_leap_imports_"
HYDROGEN_EXPORT_FILENAME_TEMPLATE = (
    "hydrogen_transformation_leap_imports_{economy}_{scenario}.xlsx"
)
HYDROGEN_EXPORT_FILENAME_FALLBACK = "hydrogen_transformation_leap_imports.xlsx"
HYDROGEN_PROCESS_SUMMARY_FILENAME = "hydrogen_transformation_process_summary.csv"
HYDROGEN_DETAIL_SUMMARY_FILENAME = "hydrogen_transformation_detail_summary.csv"
HYDROGEN_DEFAULT_SCENARIOS = list(GLOBAL_SCENARIOS)

###############################
# SUPPLY DATA PIPELINE
###############################
SUPPLY_RUN_SUPPLY_ANALYSIS = True
SUPPLY_RUN_LIST_FUELS = True
SUPPLY_ALL_ECONOMY_LABEL = GLOBAL_AGGREGATE_ECONOMY_LABEL
SUPPLY_ECONOMIES_TO_ANALYZE = list(GLOBAL_ECONOMIES)
SUPPLY_SAVE_ESTO_SUBTOTAL_LABELED = False
SUPPLY_ESTO_SUBTOTAL_LABELED_OUTPUT_PATH = ENERGY_SOURCE_ESTO_BASE_TABLE_PATH
SUPPLY_EXPORT_DATASET_KEY = "ninth"
SUPPLY_EXPORT_DIR = GLOBAL_EXPORT_OUTPUT_DIR
SUPPLY_EXPORT_FILE_NAME = _default_supply_export_filename(
    GLOBAL_ECONOMIES,
    GLOBAL_SCENARIOS,
)
SUPPLY_SCENARIO_TO_RUN = "Target"
SUPPLY_FILL_BRANCHES_FROM_EXPORT_FILE = True
SUPPLY_HANDLE_CURRENT_ACCOUNTS_TOO = True
SUPPLY_RUN_SUPPLY_LEAP_IMPORT = False
SUPPLY_SHEET_NAME = "LEAP"
# When False, the supply export will not write the "Unmet Requirements" measure,
# leaving it for manual setup in LEAP.
SUPPLY_INCLUDE_UNMET_REQUIREMENTS = False
# Workbook-driven supply root classification (Resources\Primary vs Resources\Secondary).
# Source of truth for export branch-root selection when generating supply workbooks.
SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH = REPO_ROOT / "data" / "full model export.xlsx"
SUPPLY_ROOT_CLASSIFICATION_SOURCE_SHEET = "Export"
# The refreshed full-model export is the authority for whether a fuel belongs
# under Resources\Primary or Resources\Secondary.  Missing classifications
# remain warnings so baseline-seed and reconciliation workflows can continue;
# the legacy ESTO-based rule is used only for those missing fuels.
SUPPLY_ROOT_CLASSIFICATION_STRICT = False

# LEAP's explicit unlimited-production expression is written to the import
# sheet, while the human-facing FOR_VIEWING sheet carries the numeric value
# LEAP uses for the same setting.
SUPPLY_UNLIMITED_PRODUCTION_YEAR_VALUE = 1e15
SUPPLY_UNLIMITED_PRODUCTION_ESTO_PRODUCTS = frozenset(
    {
        "09 Nuclear",
        "10 Hydro",
        "11 Geothermal",
        "12.01 of which: Photovoltaics",
        "12.99 Solar nonspecified",
        "13 Tide, wave, ocean",
        "14 Wind",
    }
)

###############################
# SUPPLY WORKFLOW (WRAPPER)
###############################
SUPPLY_WORKFLOW_DEFAULT_ECONOMIES = list(GLOBAL_ECONOMIES)
SUPPLY_WORKFLOW_DEFAULT_SCENARIOS = list(GLOBAL_SCENARIOS)
SUPPLY_NOTEBOOK_ECONOMIES = list(GLOBAL_ECONOMIES)
SUPPLY_NOTEBOOK_INCLUDE_LEAP_IMPORT = True
SUPPLY_NOTEBOOK_SCENARIOS = list(GLOBAL_SCENARIOS)

###############################
# TRANSFERS WORKFLOW
###############################
TRANSFERS_EXPORT_FILENAME_TEMPLATE = "transfer_leap_imports_{economy}_{scenario}.xlsx"
TRANSFERS_EXPORT_FILENAME_PREFIX = "transfer_leap_imports_"
TRANSFERS_SHEET_NAME = "LEAP"
TRANSFERS_DEFAULT_SCENARIOS = list(GLOBAL_SCENARIOS)
TRANSFERS_AGGREGATE_ECONOMY_LABEL = GLOBAL_AGGREGATE_ECONOMY_LABEL
# None means: fall back to core.ECONOMIES_TO_ANALYZE or DEFAULT_SCENARIOS.
TRANSFERS_NOTEBOOK_ECONOMIES = None
TRANSFERS_NOTEBOOK_SCENARIOS = None
# None means: fall back to leap_api availability in transfers_workflow.
TRANSFERS_NOTEBOOK_INCLUDE_LEAP_IMPORT = None
TRANSFERS_NOTEBOOK_CURRENT_ACCOUNTS = True

###############################
# MINOR DEMAND WORKFLOW
###############################
MINOR_DEMAND_EXPORT_FILENAME_TEMPLATE = (
    str(STANDALONE_LEAP_EXPORTS_ROOT / "minor_demand_export_{economy}_{scenario}.xlsx")
)
MINOR_DEMAND_EXPORT_MODEL_NAME = "Minor demand import"
MINOR_DEMAND_EXPORT_REGION = GLOBAL_REGION
MINOR_DEMAND_EXPORT_SCENARIOS = list(GLOBAL_SCENARIOS)
MINOR_DEMAND_NINTH_SCENARIO = "reference"
MINOR_DEMAND_MEASURE_UNITS = {
    "Activity Level": {"units": "Petajoule", "scale": "", "per": ""},
    "Final Energy Intensity": {"units": "Petajoule", "scale": "", "per": ""},
}
# Fuel-activity behavior for codebase/archive/minor_demand_workflow.py:
# - "activity_as_energy_intensity_as_one" (default): fuel Activity Level is in
#   energy units and equals sector_activity * fuel_share, so fuel activities
#   sum back to sector activity.
#   Compatibility alias: "fuel_share" (legacy name for the same behavior).
#   Activity Level units are written as "Unspecified Unit" for both sector and
#   fuel branches.
# - "sector_share": fuel Activity Level is a dimensionless fraction (0..1) of
#   sector total energy for each year. In this mode, minor_demand_workflow
#   forces Final Energy Intensity to 1.0 for fuel branches and writes fuel
#   Activity Level units as "Share". Sector Activity Level units are written
#   as "Unspecified Unit".
# - "none": skip fuel Activity Level rows (still writes fuel intensity rows
#   where applicable).
MINOR_DEMAND_FUEL_ACTIVITY_MODE = "sector_share"
MINOR_DEMAND_INTENSITY_CALIBRATION_MODE = "disabled"
MINOR_DEMAND_RELATIVE_INTENSITY_OVERRIDES = {}
MINOR_DEMAND_AGGREGATE_ECONOMY_LABEL = GLOBAL_AGGREGATE_ECONOMY_LABEL
MINOR_DEMAND_DEMAND_ROOT_PARTS = ["Demand", "Other sector"]
# None means: fall back to the shared ESTO/ninth source config.
MINOR_DEMAND_EXPORT_BASE_YEAR = None
MINOR_DEMAND_PROJECTION_START_YEAR = ENERGY_SOURCE_PROJECTION_START_YEAR
MINOR_DEMAND_EXPORT_FINAL_YEAR = 2060

###############################
# FULL MODEL WORKFLOW NOTEBOOK
###############################
FULL_MODEL_RUN_TRANSFORMATION_WORKFLOW = True
FULL_MODEL_RUN_HYDROGEN_TRANSFORMATION_WORKFLOW = True
FULL_MODEL_RUN_SUPPLY_WORKFLOW = True
FULL_MODEL_RUN_TRANSFERS_WORKFLOW = True
FULL_MODEL_RUN_MINOR_DEMAND_WORKFLOW = True
FULL_MODEL_RUN_INDUSTRY_MAPPING_WORKFLOW = True

# Feedstock method for transformation + hydrogen + transfers (None keeps module default).
FULL_MODEL_FEEDSTOCK_METHOD = "multi_feedstock_single_process"

# Transformation workflow config
FULL_MODEL_TRANSFORMATION_ECONOMIES = list(GLOBAL_ECONOMIES)
FULL_MODEL_TRANSFORMATION_SCENARIOS = list(GLOBAL_SCENARIOS)
# None means: fall back to LEAP API availability in full_model_workflow_notebook.
FULL_MODEL_TRANSFORMATION_INCLUDE_LEAP_IMPORT = None
FULL_MODEL_TRANSFORMATION_AGGREGATE_ECONOMY_LABEL = GLOBAL_AGGREGATE_ECONOMY_LABEL
FULL_MODEL_TRANSFORMATION_EXPORT_DIR = None
FULL_MODEL_TRANSFORMATION_FILENAME_TEMPLATE = None

# Hydrogen transformation workflow config
FULL_MODEL_HYDROGEN_TRANSFORMATION_ECONOMIES = list(GLOBAL_ECONOMIES)
FULL_MODEL_HYDROGEN_TRANSFORMATION_SCENARIOS = list(GLOBAL_SCENARIOS)
FULL_MODEL_HYDROGEN_TRANSFORMATION_INCLUDE_LEAP_IMPORT = None
FULL_MODEL_HYDROGEN_TRANSFORMATION_HANDLE_CURRENT_ACCOUNTS = True
FULL_MODEL_HYDROGEN_TRANSFORMATION_AGGREGATE_ECONOMY_LABEL = GLOBAL_AGGREGATE_ECONOMY_LABEL
FULL_MODEL_HYDROGEN_TRANSFORMATION_EXPORT_DIR = None
FULL_MODEL_HYDROGEN_TRANSFORMATION_FILENAME_TEMPLATE = None

# Supply workflow config
FULL_MODEL_SUPPLY_ECONOMIES = list(GLOBAL_ECONOMIES)
FULL_MODEL_SUPPLY_SCENARIOS = list(GLOBAL_SCENARIOS)
FULL_MODEL_SUPPLY_INCLUDE_LEAP_IMPORT = None
FULL_MODEL_SUPPLY_EXPORT_DATASET_KEY = "ninth"

# Transfers workflow config
FULL_MODEL_TRANSFERS_ECONOMIES = list(GLOBAL_ECONOMIES)
FULL_MODEL_TRANSFERS_SCENARIOS = list(GLOBAL_SCENARIOS)
FULL_MODEL_TRANSFERS_INCLUDE_LEAP_IMPORT = None
FULL_MODEL_TRANSFERS_HANDLE_CURRENT_ACCOUNTS = True
FULL_MODEL_TRANSFERS_INCLUDE_OUTPUT_SERIES = False
FULL_MODEL_TRANSFERS_USE_OUTPUT_TARGETS = True
FULL_MODEL_TRANSFERS_AGGREGATE_ECONOMY_LABEL = GLOBAL_AGGREGATE_ECONOMY_LABEL

# Minor demand workflow config
FULL_MODEL_MINOR_DEMAND_ECONOMIES = list(GLOBAL_ECONOMIES)
FULL_MODEL_MINOR_DEMAND_SCENARIOS = list(GLOBAL_SCENARIOS)
FULL_MODEL_MINOR_DEMAND_REGION = GLOBAL_REGION
FULL_MODEL_MINOR_DEMAND_INCLUDE_LEAP_IMPORT = None
FULL_MODEL_MINOR_DEMAND_AGGREGATE_ECONOMY_LABEL = GLOBAL_AGGREGATE_ECONOMY_LABEL
FULL_MODEL_MINOR_DEMAND_EXPORT_FILENAME = None

# Industry mapping workflow config
FULL_MODEL_INDUSTRY_EXPORT_PATH = REPO_ROOT / "data" / "industry export.xlsx"
FULL_MODEL_INDUSTRY_SHEET_NAME = "Export"
FULL_MODEL_INDUSTRY_ECONOMY = "20_USA"
FULL_MODEL_INDUSTRY_BASE_YEAR = GLOBAL_BASE_YEAR
FULL_MODEL_INDUSTRY_SCENARIO = "Target"
FULL_MODEL_INDUSTRY_REGION = GLOBAL_REGION
# Industry base-year handling:
# - ensure_base_year_from_current_accounts=True tries to copy base-year points
#   from Current Accounts into projected scenarios when missing.
# - enforce_base_year_presence=False means warn-only when projected series still
#   lack base-year points after anchoring (no hard failure).
FULL_MODEL_INDUSTRY_ENSURE_BASE_YEAR_FROM_CURRENT_ACCOUNTS = True
FULL_MODEL_INDUSTRY_ENFORCE_BASE_YEAR_PRESENCE = False
