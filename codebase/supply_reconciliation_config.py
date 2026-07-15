"""
supply_reconciliation_config.py — user-facing configuration for the supply reconciliation workflow.

Edit this file to change:
  - Sentinel constants (UNLIMITED, DECREASE_TO_ZERO, INCREASE_BY_PCT, etc.)
  - Capacity-unmet priority ordering, module caps, and production caps
  - Input/output directory paths and LEAP import settings
  - Timing, diagnostics, and completion-beep flags
  - Per-run scope (ECONOMIES, SCENARIOS) is set in the notebook runtime block
    at the bottom of supply_reconciliation_workflow.py, not here.

Imported by supply_reconciliation_workflow.py via `from ... import *` plus explicit
private-name imports.  Do not import from supply_reconciliation_workflow — that
would create a circular dependency.

Preset precedence: settings marked ``PRESET-CONTROLLED DEFAULT`` below are
defaults only. Both active presets in supply_reconciliation_workflow.py define
the same names, and ``globals().update(ACTIVE_PRESET)`` replaces these values
when the workflow cell runs. Edit the active preset for a run-specific value;
edit this file only to change the fallback used outside that workflow.
"""
from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.configuration import workflow_config as workflow_cfg
from codebase.functions import supply_data_pipeline
from codebase import transformation_workflow
from codebase.utilities.output_paths import BALANCE_TABLES_ROOT, INTEGRATED_LEAP_EXPORTS_ROOT
from codebase.mappings.canonical_mapping import DEFAULT_SHEET_MAP
from codebase.utilities.master_config import OUTLOOK_MAPPINGS_MASTER_PATH
from codebase.utilities.workflow_utils import _resolve
from codebase.utilities.leap_results_dashboard_balance import (
    DEFAULT_BACKUP_MAPPINGS_PATH as DEFAULT_BALANCE_BACKUP_MAPPINGS_PATH,
    DEFAULT_BASE_TABLE_PATH as DEFAULT_BALANCE_BASE_TABLE_PATH,
    DEFAULT_CODEBOOK_PATH as DEFAULT_BALANCE_CODEBOOK_PATH,
    DEFAULT_EXPLICIT_MAPPINGS_PATH as DEFAULT_BALANCE_EXPLICIT_MAPPINGS_PATH,
    DEFAULT_EXPLICIT_REASSIGNMENTS_PATH as DEFAULT_BALANCE_EXPLICIT_REASSIGNMENTS_PATH,
    DEFAULT_MAPPING_PAIRS_PATH as DEFAULT_BALANCE_MAPPING_PAIRS_PATH,
    DEFAULT_PROJECTION_TABLE_PATH as DEFAULT_BALANCE_PROJECTION_TABLE_PATH,
    DEFAULT_REF_WORKBOOK_PATH as DEFAULT_BALANCE_REF_WORKBOOK_PATH,
    DEFAULT_SHEET_MAP_PATH as DEFAULT_BALANCE_SHEET_MAP_PATH,
    DEFAULT_SYNTHETIC_REFERENCE_ROWS_PATH as DEFAULT_BALANCE_SYNTHETIC_REFERENCE_ROWS_PATH,
    DEFAULT_TGT_WORKBOOK_PATH as DEFAULT_BALANCE_TGT_WORKBOOK_PATH,
)


# ---------------------------------------------------------------------------
# Module capacity cap sentinels
# Use these in CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS instead of raw
# numbers to make intent clear and reduce the risk of stale hardcoded values.
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class _ModuleCapRule:
    kind: str       # "zero" | "base_year" | "increase_pct" | "decrease_pct" | "explicit"
    param: float = 0.0

# Cap = 0: module must not grow beyond where it is (headroom always 0).
DECREASE_TO_ZERO = _ModuleCapRule("zero")

# Cap = base-year output: no additional capacity beyond ESTO baseline.
KEEP_EXOGENOUS_CAP_SAME_AS_BASE_YEAR_ENERGY_OUTPUT = _ModuleCapRule("base_year")

def INCREASE_BY_PCT(pct: float) -> _ModuleCapRule:
    """Allow up to `pct` percent growth above the base-year output level."""
    return _ModuleCapRule("increase_pct", float(pct))

def DECREASE_BY_PCT(pct: float) -> _ModuleCapRule:
    """Reduce the effective cap to `(1 - pct/100)` of the base-year output."""
    return _ModuleCapRule("decrease_pct", float(pct))

def SET_CAP_TO(value: float) -> _ModuleCapRule:
    """Explicit numeric cap — use sparingly; prefer the other sentinels."""
    return _ModuleCapRule("explicit", float(value))


# ---------------------------------------------------------------------------
# Production cap sentinels
# Use these in CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS instead of raw numbers.
# These reuse _ModuleCapRule internally but have production-appropriate names
# so that config entries are self-documenting about which lever they govern.
# ---------------------------------------------------------------------------

# Production must not grow beyond the base-year constrained production level.
KEEP_PRODUCTION_AT_BASE_YEAR = _ModuleCapRule("base_year")

# Zero out production headroom — no new production may be allocated.
DECREASE_PRODUCTION_TO_ZERO = _ModuleCapRule("zero")

def INCREASE_PRODUCTION_BY_PCT(pct: float) -> _ModuleCapRule:
    """Allow production to grow up to `pct` percent above the base-year constrained level."""
    return _ModuleCapRule("increase_pct", float(pct))

def DECREASE_PRODUCTION_BY_PCT(pct: float) -> _ModuleCapRule:
    """Cap production at `(1 - pct/100)` of the base-year constrained production level."""
    return _ModuleCapRule("decrease_pct", float(pct))

def SET_PRODUCTION_CAP_TO(value: float) -> _ModuleCapRule:
    """Explicit production cap in the same energy units as the balance table."""
    return _ModuleCapRule("explicit", float(value))


# ---------------------------------------------------------------------------
# Shared no-cap sentinel
# Use UNLIMITED in either config dict to explicitly allow unrestricted growth.
# Equivalent to omitting the entry, but self-documents the intent.
# ---------------------------------------------------------------------------

UNLIMITED = _ModuleCapRule("unlimited")
UNLIMITED_PRODUCTION = _ModuleCapRule("unlimited")


def _resolve_module_cap_rule(
    rule: _ModuleCapRule | float | None,
    baseline_output: float,
) -> float | None:
    """Resolve a cap sentinel to a concrete float given the module's baseline output."""
    if rule is None:
        return None
    if isinstance(rule, (int, float)):
        return max(float(rule), 0.0)
    if not isinstance(rule, _ModuleCapRule):
        return None
    if rule.kind == "zero":
        return 0.0
    if rule.kind == "base_year":
        return max(float(baseline_output), 0.0)
    if rule.kind == "increase_pct":
        return max(float(baseline_output) * (1.0 + rule.param / 100.0), 0.0)
    if rule.kind == "decrease_pct":
        return max(float(baseline_output) * (1.0 - rule.param / 100.0), 0.0)
    if rule.kind == "explicit":
        return max(rule.param, 0.0)
    if rule.kind == "unlimited":
        return None  # no cap
    return None


# -----------------------------------------------------------------------------
# Workflow configuration
# -----------------------------------------------------------------------------

# Scope settings that are applied from the bottom notebook runtime block.
EXPORT_DATASET_KEY = workflow_cfg.SUPPLY_EXPORT_DATASET_KEY  # "ninth" or "esto"
ENERGY_SOURCE_CONFIG = workflow_cfg.get_energy_source_config()

# Input/output locations.
RESULTS_DIR = REPO_ROOT / "outputs" / "leap_results_dashboard" / "USA"
COMPARISON_LONG_PATH = RESULTS_DIR / "comparison_long.csv"  # demand comparison input
MAPPING_STATUS_PATH = RESULTS_DIR / "mapping_status.xlsx"  # demand mapping input
# PRESET-CONTROLLED DEFAULT: both active presets replace this value. Keep the
# fallback here before output paths are derived; the workflow refreshes paths
# after its active preset selects the pass mode.
CAPACITY_UNMET_PASS_MODE = "results_update"
# Optional label for an isolated run-output tree.  The workflow's default
# ``"auto"`` value derives a concise label from pass mode, economies, and
# scenarios; a literal value overrides it.  ``None`` keeps the legacy output
# directory for callers that deliberately need it.
RUN_OUTPUT_LABEL: str | None = None
_PASS_MODE_SUBDIR = {
    "baseline_seed": "baseline_seed",
    "results_update": "results_update",
}
_PASS_MODE_ALIASES = {
    "first_clean": "baseline_seed",
    "consecutive": "results_update",
}
OUTPUT_DIR = INTEGRATED_LEAP_EXPORTS_ROOT / _PASS_MODE_SUBDIR[CAPACITY_UNMET_PASS_MODE]
RECONCILIATION_FILENAME = "results_supply_reconciliation.csv"  # core merged output
YEARLY_BALANCE_DIR = BALANCE_TABLES_ROOT / "supply_reconciliation" / "yearly_balance_tables"
CONVENTIONAL_BALANCE_DIR = (
    BALANCE_TABLES_ROOT / "supply_reconciliation" / "conventional_balance_tables"
)
EXPORT_OUTPUT_DIR = OUTPUT_DIR / "workbooks"  # supply+transformation+transfer LEAP files
EXPORT_FILENAME_TEMPLATE = supply_data_pipeline.EXPORT_FILENAME_TEMPLATE
TRANSFORMATION_EXPORT_OUTPUT_DIR = EXPORT_OUTPUT_DIR
TRANSFORMATION_EXPORT_FILENAME_TEMPLATE = transformation_workflow.core.EXPORT_FILENAME_TEMPLATE
COMBINED_EXPORT_FILENAME_TEMPLATE = "combined_st_{economy}_{scenario}.xlsx"

# LEAP results workbook discovery and refinery fallback settings.
LEAP_RESULTS_TABLES_DIR = REPO_ROOT / "data" / "leap results tables"
REFINERY_RESULTS_FILENAME_TEMPLATE = "transformation_and_supply_results_{economy}_{scenario}.xlsx"
TRANSFORMATION_RESULTS_FILENAME_TEMPLATE = "transformation_results_{economy}_{scenario}.xlsx"
REFINERY_RESULTS_SHEET_NAME = "refining output"
REFINERY_SECTOR_NAME = "Oil Refining"
REFINERY_FUEL_LABEL_ALIASES = {
    "Gas and diesel oil": "Gas/diesel oil",
}

# Demand and year controls.
DEMAND_SOURCE_PRIORITY = ("leap", "projection")
BASE_YEAR = supply_data_pipeline.EXPORT_BASE_YEAR
LEAP_IMPORT_MAX_YEAR = 2060
FINAL_YEAR = min(int(supply_data_pipeline.EXPORT_FINAL_YEAR), LEAP_IMPORT_MAX_YEAR)  # LEAP-safe horizon
BALANCE_EXPORT_YEARS = [BASE_YEAR, 2030, 2050]

# Optional external cap templates (LEAP-format workbooks). Leave empty to disable.
CONSTRAINT_TEMPLATE_PATHS: list[Path | str] = []
CONSTRAINT_TEMPLATE_SHEETS: list[str] | None = None

# Demand table shaping controls.
DROP_PARENT_DEMAND_ROWS_WHEN_CHILDREN_PRESENT = True
INCLUDE_TOP_LEVEL_DEMAND_CATEGORY_ROWS = True
DROP_DISAGGREGATED_DEMAND_SECTORS = True

# LEAP import controls.
LEAP_IMPORT_SCENARIOS: list[str] | None = None
LEAP_IMPORT_REGION = supply_data_pipeline.EXPORT_REGION
LEAP_IMPORT_CREATE_BRANCHES = True
LEAP_IMPORT_FILL_BRANCHES = True
LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS = False
LEAP_IMPORT_SUPPLY_TO_LEAP = True
LEAP_IMPORT_TRANSFORMATION_TO_LEAP = True
LEAP_IMPORT_TRANSFERS_TO_LEAP = True
LEAP_IMPORT_LOG_LEVEL = "summary"  # detailed|summary|quiet
LEAP_IMPORT_WARNING_PRINT_LIMIT = 20
# PRESET-CONTROLLED DEFAULT: both active presets replace this value.
RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT = False

# All LEAP balance exports must use at least Level 2 detail so module branch
# rows (e.g. 'Oil Refining/Oil Refining', hydrogen process rows) are visible.
# The readiness check rejects flat Level 1 exports for every economy; see
# _workbook_has_level2_detail in codebase/functions/supply_demand_mapping.py.
# Set to False only for a deliberate temporary bypass, such as working with a
# legacy flat export while diagnosing a separate workflow issue.
REQUIRE_LEVEL2_BALANCE_EXPORT_DETAIL = True

# Electricity and heat interim controls.
# When True, three simplified power transformation modules are built from ESTO
# power sector data: 'Electricity interim' (electricity plants), 'CHP interim'
# (CHP plants, dual output electricity+heat), and 'Heat plant interim' (heat
# plants).  All three are written into a single export workbook per economy.
# Set to False when the full power model is in use.
# PRESET-CONTROLLED DEFAULT: both active presets replace this value.
RUN_ELECTRICITY_HEAT_INTERIM = False

# Other loss / own-use proxy controls.
# - "auto" syncs to CAPACITY_UNMET_PASS_MODE.
# - "first" forces ESTO + 9th proxy activity for baseline-seed initialisation.
# - "second" forces LEAP-balance proxy activity for results-update initialisation.
# These values choose activity source only; they are not post-initialisation
# anchored-intensity modes.
RUN_OTHER_LOSS_OWN_USE_PROXY = True
# PRESET-CONTROLLED DEFAULT: both active presets replace this value.
OTHER_LOSS_OWN_USE_PROXY_STAGE = "auto"  # auto|first|second
OTHER_LOSS_OWN_USE_OUTPUT_FUEL_SCOPE = "economy"  # economy|all_economies
OTHER_LOSS_OWN_USE_INCLUDE_IN_LEAP_IMPORT = True
OTHER_LOSS_OWN_USE_LEAP_BALANCE_WORKBOOK_PATH = None
OTHER_LOSS_OWN_USE_LEAP_BALANCE_SCENARIO = "Target"
OTHER_LOSS_OWN_USE_LEAP_BALANCE_DATE_ID = None

# Results packaging controls.
RESULTS_SINGLE_FILE_NAME = "supply_recon_run.xlsx"
RESULTS_SINGLE_FILE_OUTPUT = True
RESULTS_SINGLE_FILE_ARCHIVE_MIN_HOURS = 24
RESULTS_SINGLE_FILE_ARCHIVE_EVERY_RUN = True
RESULTS_SINGLE_FILE_ARCHIVE_DIR = OUTPUT_DIR / "supporting_files" / "archive"
RESULTS_CHECKS_DIR = OUTPUT_DIR / "supporting_files" / "checks"
RESULTS_RUNTIME_DIR = OUTPUT_DIR / "supporting_files" / "runtime"
ENABLE_WORKFLOW_TIMING = True
WRITE_WORKFLOW_TIMING_CSV = True
WORKFLOW_TIMING_FILENAME = "workflow_stage_timings.csv"
RESULTS_WRITE_LEGACY_SIDECAR_FILES = False
KEEP_ALL_ZERO_SUPPLY_ROWS = True
BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES = True
SUPPLY_RECONCILIATION_FAIL_ON_SOURCE_DIAGNOSTICS = False

# Completion beep — plays when run_with_config() exits (success or error).
ENABLE_COMPLETION_BEEP = True
COMPLETION_BEEP_ON_ERROR = True
COMPLETION_BEEP_COUNT = 1
COMPLETION_BEEP_FREQUENCY_HZ = 880
COMPLETION_BEEP_DURATION_MS = 180
COMPLETION_BEEP_PAUSE_SECONDS = 0.12
RESULTS_UNMATCHED_ID_REPORT_FILENAME = "supply_reconciliation_unmatched_id_rows.csv"
RESULTS_METADATA_MISMATCH_REPORT_FILENAME = "supply_reconciliation_metadata_mismatches.csv"
RESULTS_CONFIG_MAPPING_MISMATCH_REPORT_FILENAME = "supply_reconciliation_config_mapping_mismatches.csv"
RESULTS_BALANCE_DEMAND_ISSUES_FILENAME = "supply_reconciliation_balance_demand_issues.csv"
RESULTS_BALANCE_MATCHING_DIAGNOSTICS_FILENAME = "supply_reconciliation_balance_matching_diagnostics.csv"
RESULTS_SOURCE_DIAGNOSTICS_FILENAME = "supply_reconciliation_source_diagnostics.csv"
RESULTS_DROPPED_UNMATCHED_ZERO_SUPPLY_ROWS_FILENAME = (
    "supply_reconciliation_dropped_unmatched_zero_supply_rows.csv"
)

# Optional live LEAP probe to keep fuel branch catalogs current.
RUN_LEAP_FUEL_BRANCH_PROBE_AT_START = False
LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH = (
    RESULTS_CHECKS_DIR / "transformation_supply_fuel_branch_catalog_probe.csv"
)
USE_RESULTS_VERIFICATION_EXPORT_SOURCE = True
RESULTS_VERIFICATION_EXPORT_PATH = REPO_ROOT / "data" / "full model export.xlsx"
RESULTS_VERIFICATION_EXPORT_SHEET = "Export"
AGGREGATED_DEMAND_ID_LOOKUP_PATH = REPO_ROOT / "data" / "full model export.xlsx"

# Backward-compatible aliases used by existing catalog helpers.
USE_FULL_MODEL_EXPORT_CATALOG_SOURCE = USE_RESULTS_VERIFICATION_EXPORT_SOURCE
FULL_MODEL_EXPORT_CATALOG_PATH = RESULTS_VERIFICATION_EXPORT_PATH
FULL_MODEL_EXPORT_CATALOG_SHEET = RESULTS_VERIFICATION_EXPORT_SHEET

# Transformation refresh from live LEAP Results (before reconciliation).
REFRESH_TRANSFORMATION_MEASURES_FROM_LEAP_RESULTS = False
REFRESH_TRANSFORMATION_MEASURE_SCENARIO = "Target"
REFRESH_TRANSFORMATION_MEASURE_REGION = LEAP_IMPORT_REGION

# Trade target behavior is fixed to the balanced iterative supply-link method.
# Imports are omitted from supply exports so LEAP can reveal unmet requirements
# after recalculation. Later passes use those balance results to add
# transformation capacity, primary production, or export adjustments.
ACTIVE_SUPPLY_LINK_METHOD = "capacity_unmet_iterative_balanced"
DEMAND_SECTOR_PREFIXES = ("04_", "05_", "14_", "15_", "16_")
DEMAND_NON_ACTIONABLE_FUEL_PHRASES = (
    "do not use",
)
# Fuel labels that are sector-level rollups rather than real fuels, so they
# never need their own ESTO pair (the per-fuel rows underneath them already
# carry the demand). Matched as a full, case-insensitive fuel label.
DEMAND_NON_ACTIONABLE_FUEL_EXACT_MATCHES = ("total",)

# Capacity-constrained mode knobs.
CAPACITY_CONSTRAINT_FACTOR = 1.0
CAPACITY_CONSTRAINT_UNITS = "Gigajoules/Year"
CAPACITY_CONSTRAINT_SCALE = "Million"
CAPACITY_MAX_AVAILABILITY = 100.0
CAPACITY_CREDIT = 100.0
CAPACITY_ENDOGENOUS = 0.0
CAPACITY_CLEAR_OUTPUT_TRADE_TARGETS = True

# Capacity unmet iterative mode knobs.
# CAPACITY_UNMET_PASS_MODE choices:
# - "baseline_seed": first clean pass; ignore old iterative state and write
#   baseline exports/capacity only.
# - "results_update": follow-up pass; use refreshed LEAP balance results and
#   persisted state to allocate remaining gaps.
# Backward-compatible aliases accepted by the resolver:
# - "first_clean" -> "baseline_seed"
# - "consecutive" -> "results_update"
# The iterative pass now prefers balance-table outputs for observed trade
# instead of legacy LEAP results workbooks.
SCRAPE_LEAP_RESULTS = False  # keep False unless explicitly re-enabling live LEAP scraping
CAPACITY_UNMET_STATE_PATH = RESULTS_RUNTIME_DIR / "capacity_unmet_iterative_state.json"
CAPACITY_UNMET_RESULTS_DIR = YEARLY_BALANCE_DIR
CAPACITY_UNMET_IMPORT_SHEETS: tuple[str, ...] = ("imports primary", "imports secondary")
CAPACITY_UNMET_EXPORT_SHEETS: tuple[str, ...] = ("exports primary", "exports secondary")


def refresh_output_paths_for_pass_mode(
    capacity_unmet_pass_mode: str,
    run_output_label: str | None = None,
) -> dict[str, Path]:
    """Refresh pass-specific output paths after a notebook preset is applied.

    A nonblank ``run_output_label`` isolates all generated workbooks, balance
    tables, caches, diagnostics, state, and timing history below ``runs/<label>``.
    """
    normalized_mode = str(capacity_unmet_pass_mode).strip().lower()
    normalized_mode = _PASS_MODE_ALIASES.get(normalized_mode, normalized_mode)
    if normalized_mode not in _PASS_MODE_SUBDIR:
        raise ValueError(
            "Invalid CAPACITY_UNMET_PASS_MODE="
            f"{capacity_unmet_pass_mode!r}. Expected 'baseline_seed' or 'results_update'."
        )

    global CAPACITY_UNMET_PASS_MODE, RUN_OUTPUT_LABEL
    global OUTPUT_DIR, EXPORT_OUTPUT_DIR, TRANSFORMATION_EXPORT_OUTPUT_DIR
    global YEARLY_BALANCE_DIR, CONVENTIONAL_BALANCE_DIR, CAPACITY_UNMET_RESULTS_DIR
    global RESULTS_SINGLE_FILE_ARCHIVE_DIR, RESULTS_CHECKS_DIR, RESULTS_RUNTIME_DIR
    global CAPACITY_UNMET_STATE_PATH, LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH

    CAPACITY_UNMET_PASS_MODE = normalized_mode
    label = str(run_output_label or "").strip()
    if label:
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_.")
        if not safe_label:
            raise ValueError("RUN_OUTPUT_LABEL must include at least one letter or number.")
        RUN_OUTPUT_LABEL = safe_label
        OUTPUT_DIR = (
            INTEGRATED_LEAP_EXPORTS_ROOT
            / _PASS_MODE_SUBDIR[normalized_mode]
            / "runs"
            / safe_label
        )
    else:
        RUN_OUTPUT_LABEL = None
        OUTPUT_DIR = INTEGRATED_LEAP_EXPORTS_ROOT / _PASS_MODE_SUBDIR[normalized_mode]
    if RUN_OUTPUT_LABEL:
        YEARLY_BALANCE_DIR = OUTPUT_DIR / "balance_tables" / "yearly_balance_tables"
        CONVENTIONAL_BALANCE_DIR = OUTPUT_DIR / "balance_tables" / "conventional_balance_tables"
    else:
        YEARLY_BALANCE_DIR = BALANCE_TABLES_ROOT / "supply_reconciliation" / "yearly_balance_tables"
        CONVENTIONAL_BALANCE_DIR = (
            BALANCE_TABLES_ROOT / "supply_reconciliation" / "conventional_balance_tables"
        )
    CAPACITY_UNMET_RESULTS_DIR = YEARLY_BALANCE_DIR
    EXPORT_OUTPUT_DIR = OUTPUT_DIR / "workbooks"
    TRANSFORMATION_EXPORT_OUTPUT_DIR = EXPORT_OUTPUT_DIR
    RESULTS_SINGLE_FILE_ARCHIVE_DIR = OUTPUT_DIR / "supporting_files" / "archive"
    RESULTS_CHECKS_DIR = OUTPUT_DIR / "supporting_files" / "checks"
    RESULTS_RUNTIME_DIR = OUTPUT_DIR / "supporting_files" / "runtime"
    CAPACITY_UNMET_STATE_PATH = RESULTS_RUNTIME_DIR / "capacity_unmet_iterative_state.json"
    LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH = (
        RESULTS_CHECKS_DIR / "transformation_supply_fuel_branch_catalog_probe.csv"
    )
    return {
        "OUTPUT_DIR": OUTPUT_DIR,
        "RUN_OUTPUT_LABEL": RUN_OUTPUT_LABEL,
        "EXPORT_OUTPUT_DIR": EXPORT_OUTPUT_DIR,
        "TRANSFORMATION_EXPORT_OUTPUT_DIR": TRANSFORMATION_EXPORT_OUTPUT_DIR,
        "YEARLY_BALANCE_DIR": YEARLY_BALANCE_DIR,
        "CONVENTIONAL_BALANCE_DIR": CONVENTIONAL_BALANCE_DIR,
        "CAPACITY_UNMET_RESULTS_DIR": CAPACITY_UNMET_RESULTS_DIR,
        "RESULTS_SINGLE_FILE_ARCHIVE_DIR": RESULTS_SINGLE_FILE_ARCHIVE_DIR,
        "RESULTS_CHECKS_DIR": RESULTS_CHECKS_DIR,
        "RESULTS_RUNTIME_DIR": RESULTS_RUNTIME_DIR,
        "CAPACITY_UNMET_STATE_PATH": CAPACITY_UNMET_STATE_PATH,
        "LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH": LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH,
    }

# ---------------------------------------------------------------------------
# Capacity-unmet iterative config — edit these dicts directly.
#
# PRIORITY_BY_PRODUCT: required for any ESTO product produced by 2+ modules.
#   First module in the list gets headroom allocated first. Products with only
#   one producer do not need an entry. The workflow raises at startup and prints
#   exactly what to add if a multi-module product is missing.
#
# MODULE_CAPACITY_UPPER_LIMITS: economy → scenario → module_name → sentinel.
#   Module names must match the 'module' column of process_catalog (case-insensitive).
#   Use the sentinel constants defined above (UNLIMITED, KEEP_EXOGENOUS_CAP_SAME_AS_BASE_YEAR_ENERGY_OUTPUT,
#   DECREASE_TO_ZERO, INCREASE_BY_PCT(x), etc.).  Omit an entry to allow unrestricted growth.
#
# PRODUCTION_UPPER_LIMITS: economy → scenario → esto_product → sentinel.
#   Keys are matched with the leading ESTO numeric prefix stripped, so
#   "08.01 Natural gas" and "Natural gas" both match.
#
# To add a new economy, copy an existing economy block and adjust the values.
# config/supply_reconciliation_config.json is now archived — it is no longer
# the primary source; edit here instead.
# ---------------------------------------------------------------------------

CAPACITY_UNMET_PRIORITY_BY_PRODUCT: dict[str, list[str]] = {
    # When RUN_ELECTRICITY_HEAT_INTERIM=True the three interim modules take
    # priority; they use exogenous capacity so the capacity_unmet system cannot
    # grow them — remaining gaps fall through to the import fallback.
    "17 Electricity": [
        "Electricity interim",
        "CHP interim",
        "Electricity generation",
        "Main activity producer CHP plants",
        "Autoproducer CHP plants",
        "Chemical heat for electricity production",
        "Hydrogen transformation",
    ],
    "18 Heat": [
        "CHP interim",
        "Heat plant interim",
        "Main activity producer CHP plants",
        "Autoproducer CHP plants",
        "Heat plants",
        "Electric boilers",
    ],
    "08.01 Natural gas": [
        "Natural gas blending plants",
        "LNG regasification",
    ],
    "08.03 Gas works gas": [
        "Gas works plants",
    ],
    "16.04 Biogas": [
        "Biogas production",
        "Biogas processing",
    ],
    "16 Hydrogen": [
        "Hydrogen transformation",
    ],
    "16 Efuel": [
        "Hydrogen transformation",
    ],
    "07.01 Motor gasoline": [
        "Oil Refining",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.02 Aviation gasoline": [
        "Oil Refining",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.03 Naphtha": [
        "Oil Refining",
        "NG Liquefaction",
        "LNG regasification",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.05 Kerosene type jet fuel": [
        "Oil Refining",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.06 Kerosene": [
        "Oil Refining",
        "Gas to liquids plants",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.07 Gas/diesel oil": [
        "Oil Refining",
        "Gas to liquids plants",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.08 Fuel oil": [
        "Oil Refining",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.09 LPG": [
        "Oil Refining",
        "NG Liquefaction",
        "LNG regasification",
        "Gas to liquids plants",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.10 Refinery gas (not liquefied)": [
        "Oil Refining",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.11 Ethane": [
        "Oil Refining",
        "Non specified transformation",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.13 Lubricants": [
        "Oil Refining",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.14 Bitumen": [
        "Oil Refining",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.16 Petroleum coke": [
        "Oil Refining",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.17 Other products": [
        "Oil Refining",
        "Gas to liquids plants",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.19 Additives and oxygenates": [
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "07.99 PetProd nonspecified": [
        "Oil Refining",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "06.01 Crude oil": [
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "06.02 Natural gas liquids": [
        "Upstream liquids transfers",
        "Refinery and blending transfers",
        "Transfers unallocated",
    ],
    "06.03 Refinery feedstocks": [
        "Petrochemical industry",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "06.05 Other hydrocarbons": [
        "Non specified transformation",
        "Refinery and blending transfers",
        "Upstream liquids transfers",
        "Transfers unallocated",
    ],
    "02.01 Coke oven coke": [
        "Coke ovens",
        "Blast furnaces",
    ],
    "02.03 Coke oven gas": [
        "Coke ovens",
    ],
    "02.04 Blast furnace gas": [
        "Blast furnaces",
    ],
    "02.05 Coal tar": [
        "Coke ovens",
        "Liquefaction coal to oil",
    ],
}

_LOCKED_AT_BASE_YEAR = KEEP_EXOGENOUS_CAP_SAME_AS_BASE_YEAR_ENERGY_OUTPUT

CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS: dict[str, dict[str, dict]] = {
    "20_USA": {
        "reference": {
            # Legacy / fixed-technology modules: locked at base-year output.
            "Blast furnaces":                  _LOCKED_AT_BASE_YEAR,
            "BKB and PB plants":               _LOCKED_AT_BASE_YEAR,
            "Charcoal processing":             _LOCKED_AT_BASE_YEAR,
            "Coke ovens":                      _LOCKED_AT_BASE_YEAR,
            "Gas works plants":                _LOCKED_AT_BASE_YEAR,
            "Liquefaction coal to oil":        _LOCKED_AT_BASE_YEAR,
            "Natural gas blending plants":     _LOCKED_AT_BASE_YEAR,
            "Non specified transformation":    _LOCKED_AT_BASE_YEAR,
            "Patent fuel plants":              _LOCKED_AT_BASE_YEAR,
            "Petrochemical industry":          _LOCKED_AT_BASE_YEAR,
            "Refinery and blending transfers": _LOCKED_AT_BASE_YEAR,
            "Transfers unallocated":           _LOCKED_AT_BASE_YEAR,
            "Upstream liquids transfers":      _LOCKED_AT_BASE_YEAR,
            # Modules allowed to grow freely.
            "CHP plants":                           UNLIMITED,
            "Chemical heat for electricity production": UNLIMITED,
            "Electric boilers":                     UNLIMITED,
            "Electricity Generation":               UNLIMITED,
            "Gas to liquids plants":                UNLIMITED,
            "Heat plants":                          UNLIMITED,
            "Hydrogen transformation":              UNLIMITED,
            "LNG regasification":                   UNLIMITED,
            "NG Liquefaction":                      UNLIMITED,
            "Oil Refining":                         UNLIMITED,
            "Transmission and Distribution":        UNLIMITED,
        },
        "target": {
            # Legacy / fixed-technology modules: locked at base-year output.
            "Blast furnaces":                  _LOCKED_AT_BASE_YEAR,
            "BKB and PB plants":               _LOCKED_AT_BASE_YEAR,
            "Charcoal processing":             _LOCKED_AT_BASE_YEAR,
            "Coke ovens":                      _LOCKED_AT_BASE_YEAR,
            "Gas works plants":                _LOCKED_AT_BASE_YEAR,
            "Liquefaction coal to oil":        _LOCKED_AT_BASE_YEAR,
            "Natural gas blending plants":     _LOCKED_AT_BASE_YEAR,
            "Non specified transformation":    _LOCKED_AT_BASE_YEAR,
            "Patent fuel plants":              _LOCKED_AT_BASE_YEAR,
            "Petrochemical industry":          _LOCKED_AT_BASE_YEAR,
            "Refinery and blending transfers": _LOCKED_AT_BASE_YEAR,
            "Transfers unallocated":           _LOCKED_AT_BASE_YEAR,
            "Upstream liquids transfers":      _LOCKED_AT_BASE_YEAR,
            # Modules allowed to grow freely.
            "CHP plants":                           UNLIMITED,
            "Chemical heat for electricity production": UNLIMITED,
            "Electric boilers":                     UNLIMITED,
            "Electricity Generation":               UNLIMITED,
            "Gas to liquids plants":                UNLIMITED,
            "Heat plants":                          UNLIMITED,
            "Hydrogen transformation":              UNLIMITED,
            "LNG regasification":                   UNLIMITED,
            "NG Liquefaction":                      UNLIMITED,
            "Oil Refining":                         UNLIMITED,
            "Transmission and Distribution":        UNLIMITED,
        },
    },
}

CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS: dict[str, dict[str, dict[str, object]]] = {
    "20_USA": {
        "reference": {
            "08.01 Natural gas":                    UNLIMITED_PRODUCTION,
            "06.01 Crude oil":                      UNLIMITED_PRODUCTION,
            "06.02 Natural gas liquids":            UNLIMITED_PRODUCTION,
            "01.01 Hard coal":                      UNLIMITED_PRODUCTION,
            "01.01 Coking coal":                    UNLIMITED_PRODUCTION,
            "01.02 Other bituminous coal":          UNLIMITED_PRODUCTION,
            "01.03 Sub-bituminous coal":            UNLIMITED_PRODUCTION,
            "01.04 Anthracite":                     UNLIMITED_PRODUCTION,
            "01.05 Lignite":                        UNLIMITED_PRODUCTION,
            "06.03 Refinery feedstocks":            UNLIMITED_PRODUCTION,
            "06.05 Other hydrocarbons":             UNLIMITED_PRODUCTION,
            "12 Nuclear":                           UNLIMITED_PRODUCTION,
            "13 Hydro":                             UNLIMITED_PRODUCTION,
            "15.01 Wind":                           UNLIMITED_PRODUCTION,
            "15.02 Solar":                          UNLIMITED_PRODUCTION,
            "15.05 Geothermal":                     UNLIMITED_PRODUCTION,
            "15.03 Charcoal":                       UNLIMITED_PRODUCTION,
            "15.04 Bagasse":                        UNLIMITED_PRODUCTION,
            "15.05 Fuelwood and woodwaste":         UNLIMITED_PRODUCTION,
            "15.06 Other biomass":                  UNLIMITED_PRODUCTION,
            "15.07 Municipal solid waste renewable": UNLIMITED_PRODUCTION,
            "15.08 Black liquor":                   UNLIMITED_PRODUCTION,
            "16.04 Biogas":                         UNLIMITED_PRODUCTION,
            "16.05 Biogasoline":                    UNLIMITED_PRODUCTION,
            "16.06 Biodiesel":                      UNLIMITED_PRODUCTION,
            "16.07 Other liquid biofuels":          UNLIMITED_PRODUCTION,
            "16.08 Bio jet kerosene":               UNLIMITED_PRODUCTION,
            "16 Hydrogen":                          UNLIMITED_PRODUCTION,
            "16 Efuel":                             UNLIMITED_PRODUCTION,
            "16 Ammonia":                           UNLIMITED_PRODUCTION,
            "04 Peat":                              UNLIMITED_PRODUCTION,
            "04 Peat products":                     UNLIMITED_PRODUCTION,
        },
        "target": {
            "08.01 Natural gas":                    UNLIMITED_PRODUCTION,
            "06.01 Crude oil":                      UNLIMITED_PRODUCTION,
            "06.02 Natural gas liquids":            UNLIMITED_PRODUCTION,
            "01.01 Hard coal":                      UNLIMITED_PRODUCTION,
            "01.01 Coking coal":                    UNLIMITED_PRODUCTION,
            "01.02 Other bituminous coal":          UNLIMITED_PRODUCTION,
            "01.03 Sub-bituminous coal":            UNLIMITED_PRODUCTION,
            "01.04 Anthracite":                     UNLIMITED_PRODUCTION,
            "01.05 Lignite":                        UNLIMITED_PRODUCTION,
            "06.03 Refinery feedstocks":            UNLIMITED_PRODUCTION,
            "06.05 Other hydrocarbons":             UNLIMITED_PRODUCTION,
            "12 Nuclear":                           UNLIMITED_PRODUCTION,
            "13 Hydro":                             UNLIMITED_PRODUCTION,
            "15.01 Wind":                           UNLIMITED_PRODUCTION,
            "15.02 Solar":                          UNLIMITED_PRODUCTION,
            "15.05 Geothermal":                     UNLIMITED_PRODUCTION,
            "15.03 Charcoal":                       UNLIMITED_PRODUCTION,
            "15.04 Bagasse":                        UNLIMITED_PRODUCTION,
            "15.05 Fuelwood and woodwaste":         UNLIMITED_PRODUCTION,
            "15.06 Other biomass":                  UNLIMITED_PRODUCTION,
            "15.07 Municipal solid waste renewable": UNLIMITED_PRODUCTION,
            "15.08 Black liquor":                   UNLIMITED_PRODUCTION,
            "16.04 Biogas":                         UNLIMITED_PRODUCTION,
            "16.05 Biogasoline":                    UNLIMITED_PRODUCTION,
            "16.06 Biodiesel":                      UNLIMITED_PRODUCTION,
            "16.07 Other liquid biofuels":          UNLIMITED_PRODUCTION,
            "16.08 Bio jet kerosene":               UNLIMITED_PRODUCTION,
            "16 Hydrogen":                          UNLIMITED_PRODUCTION,
            "16 Efuel":                             UNLIMITED_PRODUCTION,
            "16 Ammonia":                           UNLIMITED_PRODUCTION,
            "04 Peat":                              UNLIMITED_PRODUCTION,
            "04 Peat products":                     UNLIMITED_PRODUCTION,
        },
    },
}

CAPACITY_UNMET_ALLOW_SAME_RESULTS_REUSE = False
CAPACITY_UNMET_FIRST_CLEAN_ARCHIVE_EXISTING_STATE = True
CAPACITY_UNMET_UNRESOLVED_POSITIVE_POLICY = "imports_fallback"  # fail|imports_fallback|track_only
CAPACITY_UNMET_PIN_EXPORTS_TO_9TH_PROJECTIONS = True
CAPACITY_UNMET_UNRESOLVED_POSITIVE_ALLOWLIST: set[str] = {
    "02.02 Gas coke",
}
# Products for which only indigenous production is eligible as a domestic
# gap-closing lever.  After the production lever is exhausted any remaining
# gap goes straight to import fallback — the transformation lever is skipped.
# Use this for primary fuels where increasing a transformation module's
# capacity would be physically wrong (e.g. LNG regasification filling a
# natural-gas gap that should come from the well, not a terminal).
CAPACITY_UNMET_PRODUCTION_ONLY_PRODUCTS: set[str] = {
    "08.01 Natural gas",
}

# Optional hard reset scope filters. Use None for category defaults.
RESET_SCOPE_ECONOMIES: list[str] | None = None
RESET_SCOPE_SCENARIOS: list[str] | None = None
RESET_SCOPE_SECTOR_TITLES: list[str] | None = None
RESET_SCOPE_ESTO_PRODUCTS: list[str] | None = None
RESET_SCOPE_YEARS: list[int] | None = None


def _use_legacy_trade_split_mode() -> bool:
    """Return True when exports should use the legacy split-target behavior."""
    return False


def _use_output_share_supply_exports_mode() -> bool:
    """Return True when supply exports should carry explicit trade values and imports stay zero."""
    return False


def _use_capacity_unmet_iterative_mode() -> bool:
    """Return True when capacity is manually uplifted using iterative unmet-import passes."""
    return False


def _use_capacity_unmet_iterative_balanced_mode() -> bool:
    """Return True when iterative mode handles both positive and negative net-trade residuals."""
    return True


def _use_capacity_unmet_iterative_any_mode() -> bool:
    """Return True for any iterative unmet-capacity mode."""
    return True


def _use_capacity_constrained_mode() -> bool:
    """Return True when exports should set process capacities and clear trade targets."""
    return False


def _use_capacity_like_mode() -> bool:
    """Return True when transformation exports should write capacity variables."""
    return _use_capacity_constrained_mode() or _use_capacity_unmet_iterative_any_mode()


# ---------------------------------------------------------------------------
# Demand / reset scope configuration
# (moved from supply_reconciliation_workflow.py)
# ---------------------------------------------------------------------------
# Reset scope configuration.
# Prefer deriving reset module/fuel scope from the canonical LEAP export workbook.
RESET_SCOPE_USE_FULL_MODEL_EXPORT = True
RESET_SCOPE_REQUIRE_FULL_MODEL_EXPORT = False
# Optional manual additions on top of derived (or fallback) scope.
TRANSFORMATION_RESET_MODULES_MANUAL_OVERRIDES: dict[str, list[str]] = {}
TRANSFORMATION_RESET_FUELS_MANUAL_OVERRIDES: dict[str, list[str]] = {}

# Legacy fallback reset catalogs (used when workbook-derived scope is unavailable).
TRANSFORMATION_RESET_MODULES: dict[str, list[str]] = {
    # Legacy fallback list for transformation modules.
    "all": [
        "Upstream liquids transfers",
        "Refinery and blending transfers",
        "NG Liquefaction",
        "LNG gasification",
        "Gas works plants",
        "Natural gas blending plants",
        "Coke ovens",
        "Blast furnaces",
        "Patent fuel plants",
        "BKB and PB plants",
        "Liquefaction coal to oil",
        # "Electric boilers",
        # "Chemical heat for electricity production",
        # "Petrochemical industry",
        # "Biofuels processing",
        # "Coal mines",
        "Charcoal processing",
        "Non specified transformation",
        "Hydrogen transformation",
        "Transfers unallocated",
        
    ],
}

TRANSFORMATION_RESET_FUELS = {'all': ['Coal',
        'Coking coal',
        'Other bituminous coal',
        'Sub bituminous coal',
        'Anthracite',
        'Lignite',
        'Coal nonspecified',
        'Coal products',
        'Coke oven coke',
        'Gas coke',
        'Coke oven gas',
        'Blast furnace gas',
        'Other recovered gases',
        'Patent fuel',
        'Coal tar',
        'BKB and PB',
        'Peat',
        'Peat products',
        'Oil shale and oil sands',
        'Crude oil and NGL',
        'Crude oil',
        'Natural gas liquids',
        'Refinery feedstocks',
        'Additives and oxygenates',
        'Other hydrocarbons',
        'Petroleum products',
        'Motor gasoline',
        'Aviation gasoline',
        'Naphtha',
        'Gasoline type jet fuel',
        'Kerosene type jet fuel',
        'Kerosene',
        'Gas and diesel oil',
        'Fuel oil',
        'LPG',
        'Refinery gas not liquefied',
        'Ethane',
        'White spirit SBP',
        'Lubricants',
        'Bitumen',
        'Paraffin waxes',
        'Petroleum coke',
        'Other products',
        'PetProd nonspecified',
        'Gas',
        'Natural gas',
        'LNG',
        'Gas works gas',
        'Gas nonspecified',
        'Nuclear',
        'Hydro',
        'Geothermal',
        'Solar',
        'of which Photovoltaics',
        'Solar nonspecified',
        'Tide wave ocean',
        'Wind',
        'Solid biomass',
        'Fuelwood and woodwaste',
        'Bagasse',
        'Charcoal',
        'Black liqour',
        'Other biomass',
        'Others',
        'Biogas',
        'Industrial waste',
        'Municipal solid waste renewable',
        'Municipal solid waste non renewable',
        'Biogasoline',
        'Biodiesel',
        'Bio jet kerosene',
        'Other liquid biofuels',
        'Other sources',
        'Electricity',]}

_RESET_SCOPE_FROM_EXPORT_CACHE: dict[str, object] | None = None

# Demand source strategy.
# Runtime toggles are set in the bottom "Notebook Runtime Variables" block.

# Demand mapping/reference inputs.
DIRECT_DEMAND_SHEET_MAP_PATH = DEFAULT_SHEET_MAP
DIRECT_DEMAND_MAPPING_WORKBOOK = OUTLOOK_MAPPINGS_MASTER_PATH
DIRECT_DEMAND_ESTO_MAPPING_SHEET = "leap_combined_esto"
DIRECT_DEMAND_NINTH_MAPPING_SHEET = "leap_combined_ninth"
DIRECT_DEMAND_BASE_TABLE_PATH = ENERGY_SOURCE_CONFIG.esto_base_table_path
DIRECT_DEMAND_PROJECTION_TABLE_PATH = ENERGY_SOURCE_CONFIG.ninth_projection_table_path
DIRECT_DEMAND_REFERENCE_CACHE_DIR = REPO_ROOT / "data/.cache/supply_reconciliation_reference_tables"
DIRECT_DEMAND_BASE_YEAR = ENERGY_SOURCE_CONFIG.esto_base_year
DIRECT_DEMAND_PROJECTION_YEARS: tuple[int, ...] = tuple(
    range(
        ENERGY_SOURCE_CONFIG.projection_start_year,
        (ENERGY_SOURCE_CONFIG.projection_final_year or FINAL_YEAR) + 1,
    )
)
DIRECT_DEMAND_BASE_ECONOMY = "20USA"
DIRECT_DEMAND_PROJECTION_ECONOMY = "20_USA"
DIRECT_DEMAND_SCENARIO_MAP = {"reference": "reference", "target": "target"}
DIRECT_DEMAND_USE_ESTO_AGG_ONLY = False
DIRECT_DEMAND_SIBLING_COMPARATOR_MODE = "aggregate_to_parent"
DIRECT_DEMAND_INCLUDE_SIBLING_PARENT_TOTALS = True

# Aggregated demand as dummy: when True, load_results_demand_table() returns ESTO/ninth
# aggregated demand (from aggregated_demand_workflow) instead of LEAP balance exports.
# Useful for a first baseline_seed pass on new economies with no balance exports yet.
# Supports both single and multi-economy runs; each economy is built independently.
# PRESET-CONTROLLED DEFAULT: both active presets replace this value.
USE_AGGREGATED_DEMAND_AS_DUMMY = True

# When True (requires USE_AGGREGATED_DEMAND_AS_DUMMY), also write a LEAP import
# workbook containing the Demand\All demand aggregated\{fuel} branches so LEAP
# has the correct demand values after import.  Without this the aggregated-demand
# branches are used internally for reconciliation but are never written to LEAP.
# PRESET-CONTROLLED DEFAULT: both active presets replace this value.
WRITE_AGGREGATED_DEMAND_WORKBOOK = True

# Controls whether the aggregated-demand workbook is automatically imported into
# LEAP via the API.  When False the file is still written for manual import.
# PRESET-CONTROLLED DEFAULT: both active presets replace this value.
AGGREGATED_DEMAND_INCLUDE_IN_LEAP_IMPORT = True

# When True (and WRITE_AGGREGATED_DEMAND_WORKBOOK is True), own-use (10_01) and
# T&D losses (10_02) sectors are excluded from the Demand\All demand aggregated
# sum.  Use this when RUN_OTHER_LOSS_OWN_USE_PROXY=True so the proxy handles
# those amounts and they are not double-counted in the aggregated total.
AGGREGATED_DEMAND_EXCLUDE_OWN_USE_TD_LOSSES = True

# Optional list of 9th-edition sector or sub1sector codes to omit from the
# aggregated demand sum.  None means no extra exclusions.
# Top-level sectors (sectors col):
#   04_international_marine_bunkers  05_international_aviation_bunkers
#   10_losses_and_own_use            14_industry_sector
#   15_transport_sector              16_other_sector   17_nonenergy_use
# Sub1sectors (sub1sectors col — finer grain, use these to exclude just a slice):
#   10_01_own_use                    10_02_transmission_and_distribution_losses
#   14_01_mining_and_quarrying       14_02_construction    14_03_manufacturing
#   15_01_domestic_air_transport     15_02_road            15_03_rail
#   15_04_domestic_navigation        15_05_pipeline_transport
#   15_06_nonspecified_transport     16_01_buildings
#   16_02_agriculture_and_fishing    16_05_nonspecified_others
# Example: ["15_transport_sector"]  or  ["15_02_road", "15_03_rail"]
# PRESET-CONTROLLED DEFAULT: both active presets replace this value.
AGGREGATED_DEMAND_EXCLUDED_SECTORS: list[str] | None = None
# When True, aggregated demand branches are written as
# Demand\All demand aggregated\{SectorLabel}\{fuel} instead of the flat
# Demand\All demand aggregated\{fuel} path. Enable when LEAP has per-sector
# sub-branches configured under the aggregated demand node.
# PRESET-CONTROLLED DEFAULT: both active presets replace this value.
AGGREGATED_DEMAND_USE_SECTOR_BRANCHES: bool = False

# Maps LEAP demand branch group names to the ESTO sector/sub1sector codes they
# represent in the 9th Outlook / ESTO source data.  When a group is listed in
# DETAILED_DEMAND_BRANCHES_ACTIVE the corresponding ESTO sectors are excluded from
# the aggregated demand placeholder to prevent double-counting.
#
# Subtraction source: 9th Outlook / ESTO source data — NOT detailed LEAP branch
# result values.  This keeps the placeholder independent of how the detailed LEAP
# branch evolves in future years relative to the 9th projection baseline.
#
# Road deduplication: Freight road and Passenger road both map to 15_02_road.
# resolve_active_branch_excluded_sectors() deduplicates automatically, so the road
# sector is excluded only once even when both LEAP branches are active.
#
# Buildings note: 16_01_buildings covers all buildings sub2sectors (16.01.01
# Commercial and public services, 16.01.02 Residential, etc.).
# Other sector note: ESTO does not separate agriculture (16.02.03) and fishing
# (16.02.04) at sub1sector level — both fall under 16_02_agriculture_and_fishing.
LEAP_DEMAND_GROUP_ESTO_SECTOR_MAP: dict[str, list[str]] = {
    "Freight road":       ["15_02_road"],
    "Passenger road":     ["15_02_road"],
    "Transport non-road": [
        "15_01_domestic_air_transport",
        "15_03_rail",
        "15_04_domestic_navigation",
        "15_05_pipeline_transport",
        "15_06_nonspecified_transport",
        "04_international_marine_bunkers",
        "05_international_aviation_bunkers",
    ],
    "Industry":           ["14_industry_sector"],
    "Other sector":       ["16_02_agriculture_and_fishing", "16_05_nonspecified_others"],
    "Buildings":          ["16_01_buildings"],
}

# LEAP demand group names whose detailed branches are currently active in LEAP.
# The ESTO sectors from LEAP_DEMAND_GROUP_ESTO_SECTOR_MAP for each active group
# are excluded from the aggregated demand placeholder so the 9th Outlook source-
# data amounts for those sectors are not double-counted alongside the detailed
# LEAP branches.  Set to None or [] when no detailed branches have been inserted.
# Example: ["Industry", "Buildings"]
DETAILED_DEMAND_BRANCHES_ACTIVE: list[str] | None = None

# Optional per-scenario demand multipliers applied after aggregation.
# Structure: {scenario_name: {esto_product: multiplier}} where "_all" applies
# to every product in that scenario. Case-insensitive scenario matching.
# Example: {"Target": {"07.07 Gas/diesel oil": 1.15, "_all": 1.0}}
AGGREGATED_DEMAND_SCENARIO_MULTIPLIERS: dict[str, dict[str, float]] = {}

# Maximum number of economies to export in parallel using ThreadPoolExecutor.
# 0 or 1 = sequential (safe default). Set to 5 to run 5 economies at once.
# Each economy writes independent files so partial cancellation loses only
# in-flight economies; completed ones are already on disk.
PARALLEL_ECONOMY_WORKERS: int = 0

# When True (and ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT is True), the
# Demand\Other loss and own use branches are excluded from zeroing because they
# are already being populated by the other_loss_own_use proxy in the same pass.
ZERO_OTHER_DEMAND_EXCLUDE_OWN_USE_PROXY_BRANCHES = True

# When True (and USE_AGGREGATED_DEMAND_AS_DUMMY is True), generate a LEAP import
# workbook that zeros every non-share Demand branch from the full model export,
# so those branches produce no energy use.  Share variables (Device Share, Sales
# Share, Stock Share) are left untouched to avoid "shares don't sum to 100" errors.
# PRESET-CONTROLLED DEFAULT: both active presets replace this value.
ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT = False

# Controls whether the demand-zeroing workbook is automatically imported into LEAP
# via the API.  When False the workbook is still written for manual LEAP import.
# PRESET-CONTROLLED DEFAULT: both active presets replace this value.
ZERO_OTHER_DEMAND_INCLUDE_IN_LEAP_IMPORT = True

BALANCE_DEMAND_REF_WORKBOOK_PATH = DEFAULT_BALANCE_REF_WORKBOOK_PATH
BALANCE_DEMAND_TGT_WORKBOOK_PATH = DEFAULT_BALANCE_TGT_WORKBOOK_PATH
BALANCE_DEMAND_EXPORTS_ROOT = REPO_ROOT / "data" / "leap balances exports"
BALANCE_DEMAND_REF_BALANCE_EXPORT_DATE_ID = None
BALANCE_DEMAND_TGT_BALANCE_EXPORT_DATE_ID = None
BALANCE_DEMAND_LEAP_TO_ESTO_MAPPING_WORKBOOK = DIRECT_DEMAND_MAPPING_WORKBOOK
BALANCE_DEMAND_NINTH_TO_ESTO_MAPPING = DEFAULT_BALANCE_MAPPING_PAIRS_PATH
BALANCE_DEMAND_CODEBOOK_PATH = _resolve(DEFAULT_BALANCE_CODEBOOK_PATH)
BALANCE_DEMAND_SHEET_MAP_PATH = _resolve(DEFAULT_BALANCE_SHEET_MAP_PATH)
BALANCE_DEMAND_BACKUP_MAPPINGS_PATH = _resolve(DEFAULT_BALANCE_BACKUP_MAPPINGS_PATH)
BALANCE_DEMAND_EXPLICIT_MAPPINGS_PATH = _resolve(DEFAULT_BALANCE_EXPLICIT_MAPPINGS_PATH)
BALANCE_DEMAND_EXPLICIT_REASSIGNMENTS_PATH = _resolve(DEFAULT_BALANCE_EXPLICIT_REASSIGNMENTS_PATH)
BALANCE_DEMAND_SYNTHETIC_REFERENCE_ROWS_PATH = _resolve(DEFAULT_BALANCE_SYNTHETIC_REFERENCE_ROWS_PATH)
BALANCE_DEMAND_BASE_TABLE_PATH = DIRECT_DEMAND_BASE_TABLE_PATH
BALANCE_DEMAND_PROJECTION_TABLE_PATH = DIRECT_DEMAND_PROJECTION_TABLE_PATH
BALANCE_DEMAND_CHART_NAVIGATION_GUIDE_PATH = REPO_ROOT / "config" / "leap_comparison_dashboard_template_v2.json"
BALANCE_DEMAND_KNOWN_ISSUES_CONFIG_PATH = REPO_ROOT / "config" / "leap_results_balance_known_issues.json"
BALANCE_DEMAND_TEMPLATE_SHEET = "EBal|2060"

