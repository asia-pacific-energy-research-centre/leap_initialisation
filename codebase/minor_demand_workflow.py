#%%
"""
Minor demand workflow (draft scaffold).

This script builds LEAP import-ready minor demand branches from ESTO and 9th
projection inputs.
It is a focused scaffold for Agriculture, Fishing, and Non-specified others,
using allocated 9th projections and ESTO base-year values to populate activity
and fuel rows.

Goal:
- Pull minor demand sector data (Agriculture, Fishing, Non-specified others) from ESTO.
- Map those flows to 9th Outlook sectors (via config/ninth_pairs_to_esto_pairs.xlsx).
- Use the 9th projection totals as the Activity Level time series.
- Emit a LEAP import-ready workbook that mirrors the column schema of
  data/industry export.xlsx, but with a tiny subset of branches.

Important modeling choices (intentionally simple placeholders):
- Sector Activity Level is derived from 9th projections *allocated* to ESTO flows
  using base-year shares (same logic as codebase/ninth_projection_mapping.py).
- Fuel Activity Level defaults to energy terms
  (`FUEL_ACTIVITY_MODE="activity_as_energy_intensity_as_one"`),
  and can optionally be exported as a share fraction (`"sector_share"`).
- Final Energy Intensity is set to 1.0 for every fuel and year by default.
- If intensity is changed in the future, keep fuel activity shares enabled.

Most user-editable settings live in `codebase/workflow_config.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections.abc import Mapping, Sequence

import pandas as pd

from codebase.utilities.master_config import (
    OUTLOOK_MAPPINGS_MASTER_PATH,
    config_table_exists,
    read_config_table,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
try:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
except Exception as exc:
    print(f"Failed to add repo root to sys.path: {exc}")

from codebase.configuration.config import (
    BRANCH_DEMAND_CATEGORY,
    BRANCH_DEMAND_TECHNOLOGY,
    BASE_YEAR,
)
from codebase.functions.leap_core import (
    connect_to_leap,
    create_branches_from_export_file,
    fill_branches_from_export_file,
    is_leap_api_available,
    sanitize_leap_name,
)
from codebase.functions.analysis_input_write_dispatcher import (
    dispatch_analysis_input_write,
)
from codebase.functions.leap_excel_io import finalise_export_df, save_export_files
from codebase.functions.ninth_projection_mapping import (
    add_ninth_pair_columns,
    allocate_ninth_projection_to_esto,
    build_esto_base_year_values,
    build_ninth_projection_series,
    filter_ninth_projection_rows,
    normalize_economy_key,
)
from codebase.functions.leap_expressions import build_data_expression_from_row
from codebase.functions.leap_labels import clean_fuel_label_for_leap
from codebase.scrapbook.utilities import (
    apply_matt_subtotal_mapping,
    filter_matt_subtotals,
    load_augmented_reference_tables,
)
from codebase.utilities import workflow_common
from codebase.utilities import fuel_catalog_preflight
from codebase.configuration import workflow_config as workflow_cfg
from codebase.functions.minor_demand_utils import (
    _year_columns,
    _normalize_year_columns,
    _is_current_accounts_label,
    _normalize_fuel_activity_mode,
    _resolve_fuel_activity_units,
    _resolve_sector_activity_units,
    filter_mapping_for_minor_demand,
    build_flow_to_sectors,
    build_flow_to_fuels,
    build_sector_projection,
    build_fuel_projection,
    _base_year_column,
    build_base_year_activity_value,
    build_base_year_fuel_value,
    add_base_year_to_sector_activity,
    add_base_year_to_fuel_activity,
    print_allocation_summary,
    build_activity_series,
    build_activity_series_from_allocated,
    build_intensity_series_uniform,
    build_intensity_series_from_shares,
    build_intensity_series_from_allocated,
    build_fuel_activity_series_from_allocated,
    build_fuel_activity_series_sector_share_from_allocated,
    build_fuel_activity_series_from_shares,
    build_fuel_activity_series_sector_share_from_shares,
    _build_gdp_index_series,
    build_intensity_adjustment_series,
    build_branch_path,
    build_year_rows,
    build_data_expression,
    build_expression_export_df,
    collapse_current_accounts_years,
)

# --- File paths (adjust to taste) ---
ENERGY_SOURCE_CONFIG = workflow_cfg.get_energy_source_config()
ESTO_DATA_PATH = str(ENERGY_SOURCE_CONFIG.esto_base_table_path)
NINTH_DATA_PATH = str(ENERGY_SOURCE_CONFIG.ninth_projection_table_path)
# Use merged_file_energy_ALL_20251106.csv and merged_file_energy_00_APEC_20251106 for exact 9th edition projection matching.
NINTH_TO_ESTO_MAPPING_PATH = (OUTLOOK_MAPPINGS_MASTER_PATH, "ninth_pairs_to_esto_pairs")
ESTO_SUBTOTAL_MAPPING_PATH = "config/ESTO_subtotal_mapping.xlsx"
REFERENCE_CACHE_DIR = "data/.cache/minor_demand_reference_tables"
LEAP_TEMPLATE_PATH = "data/industry export.xlsx"


# --- Variables ---
ACTIVITY_VARIABLE = "Activity Level"
INTENSITY_VARIABLE = "Final Energy Intensity"

# --- Units ---
# Defaults used when no per-run overrides are provided.
DEFAULT_MEASURE_UNITS: dict[str, dict[str, str]] = {
    ACTIVITY_VARIABLE: {"units": "Petajoule", "scale": "", "per": ""},
    INTENSITY_VARIABLE: {"units": "Petajoule", "scale": "", "per": ""},
}

# --- Intensity configuration ---
# "uniform": every fuel gets the same constant value (DEFAULT_INTENSITY).
# "fuel_share": intensity per fuel is fuel_energy / total_energy (sums to 1).
# "custom": use FUEL_INTENSITY_OVERRIDES to set values for specific fuels.
INTENSITY_MODE = "uniform"
DEFAULT_INTENSITY = 1.0

# --- Fuel activity configuration ---
# "activity_as_energy_intensity_as_one": Activity per fuel = sector activity * fuel energy share.
#   Output meaning: energy-valued activity (e.g., PJ), and fuel activities
#   sum to sector activity by year.
#   Compatibility alias: "fuel_share" (legacy name).
#   Activity units are exported as "Unspecified Unit" on both sector and fuel branches.
# "sector_share": Activity per fuel = fuel share of sector total.
#   Output meaning: fraction 0..1 (dimensionless), not energy. In this mode
#   Final Energy Intensity is forced to 1.0 for fuel branches and fuel
#   Activity Level units are exported as "Share". Sector activity units are
#   exported as "Unspecified Unit".
# "none": do not emit fuel Activity Level rows for fuel branches.
FUEL_ACTIVITY_MODE = "activity_as_energy_intensity_as_one"

# Toggle to print a small summary of the allocation split (Ag vs Fishing etc.).
DEBUG_ALLOCATION_SUMMARY = True

# Optional overrides when INTENSITY_MODE == "custom".
# Key = (esto_flow, esto_product) OR (sector_label, fuel_label) once sanitized.
FUEL_INTENSITY_OVERRIDES: dict[tuple[str, str], float] = {}

# --- Future intensity calibration scaffold ---
# "disabled": no calibration; current workflow behavior.
# Any other value currently raises NotImplementedError through the solver hook.
INTENSITY_CALIBRATION_MODE = "disabled"
RELATIVE_INTENSITY_OVERRIDES: dict[tuple[str, str], float] = {}

# --- Intensity Adjustment user variable ---
# Variable name as it appears in LEAP (must match the LEAP user variable name exactly).
INTENSITY_ADJUSTMENT_VARIABLE = "Intensity Adjustment"
# Set True to emit an Intensity Adjustment row for every fuel branch.
# Values encode the efficiency improvement implied by the 9th projection relative to a
# flat-GDP-intensity baseline: IA[year] = (ninth_tgt[year] / gdp_derived[year]) - 1.
# At base year IA = 0 by construction; negative = efficiency gain over time.
# Requires GDP_DATA_PATH_FOR_IA to be a valid path.
INCLUDE_INTENSITY_ADJUSTMENT = False
# Path to the macro data CSV (long format: Economy, Scenario, Date, Gdp columns).
GDP_DATA_PATH_FOR_IA = "data/9th_macro_data.csv"
# Which GDP scenario to use when computing the adjustment.
GDP_SCENARIO_FOR_IA = "Reference"

# --- Minor demand sector config ---
# Keep this list explicit and obvious so future edits are easy.
MINOR_DEMAND_FLOW_CONFIG = [
    {
        "esto_flow": "16.03 Agriculture",
        "sector_label": "Agriculture",
        "expected_9th_sectors": ["16_02_agriculture_and_fishing"],
    },
    {
        "esto_flow": "16.04 Fishing",
        "sector_label": "Fishing",
        "expected_9th_sectors": ["16_02_agriculture_and_fishing"],
    },
    {
        "esto_flow": "16.05 Non-specified others",
        "sector_label": "Non-specified others",
        "expected_9th_sectors": ["16_05_nonspecified_others"],
    },
]


def _projection_years() -> list[int]:
    """Return the default projection year list."""
    start_year = int(globals().get("PROJECTION_START_YEAR", 2023))
    final_year = int(globals().get("EXPORT_FINAL_YEAR", 2060))
    return list(range(start_year, final_year + 1))


def _default_aggregate_economy_label() -> str:
    """Return configured aggregate economy label with a safe fallback."""
    return str(globals().get("AGGREGATE_ECONOMY_LABEL", "ALL_ECONOMIES"))


def _default_ninth_scenario() -> str:
    """Return configured 9th scenario with a safe fallback."""
    return str(globals().get("NINTH_SCENARIO", "reference"))


def _default_export_scenario() -> str:
    """Return configured export scenario with a safe fallback."""
    return str(globals().get("EXPORT_SCENARIO", "Reference"))


def _normalize_export_scenarios(
    scenarios: str | Sequence[str] | None,
) -> list[str]:
    """Return cleaned scenario labels for export workbook generation."""
    scenario_list = workflow_common.normalize_workflow_scenarios(scenarios, [])
    if not scenario_list:
        scenario_list = workflow_common.normalize_workflow_scenarios(
            globals().get("EXPORT_SCENARIOS"),
            [],
        )
    if not scenario_list:
        scenario_list = [_default_export_scenario()]
    return scenario_list


def _default_export_region() -> str:
    """Return configured export region with a safe fallback."""
    return str(globals().get("EXPORT_REGION", "United States"))


def _default_export_filename_template() -> str:
    """Return configured export filename template with a safe fallback."""
    return str(
        globals().get(
            "EXPORT_FILENAME_TEMPLATE",
            str(workflow_cfg.MINOR_DEMAND_EXPORT_FILENAME_TEMPLATE),
        )
    )


def _resolve_measure_units(
    measure_units: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, dict[str, str]]:
    """Return per-measure unit settings merged with defaults."""
    resolved = {
        measure: {
            "units": str(settings["units"]),
            "scale": str(settings["scale"]),
            "per": str(settings["per"]),
        }
        for measure, settings in DEFAULT_MEASURE_UNITS.items()
    }

    source = measure_units
    if source is None:
        configured_units = globals().get("MEASURE_UNITS")
        if isinstance(configured_units, Mapping):
            source = configured_units
    if not isinstance(source, Mapping):
        return resolved

    for measure, defaults in resolved.items():
        override = source.get(measure)
        if not isinstance(override, Mapping):
            continue
        for field in ("units", "scale", "per"):
            value = override.get(field, defaults[field])
            if value is None:
                value = defaults[field]
            resolved[measure][field] = str(value)
    return resolved


def validate_intensity_calibration_config() -> None:
    """Validate future calibration settings before workflow execution."""
    valid_modes = {"disabled"}
    mode = str(globals().get("INTENSITY_CALIBRATION_MODE", "disabled")).strip().lower()
    if mode not in valid_modes:
        raise ValueError(
            "Unsupported INTENSITY_CALIBRATION_MODE "
            f"'{globals().get('INTENSITY_CALIBRATION_MODE')}'. "
            "Currently supported: disabled."
        )
    overrides = globals().get("RELATIVE_INTENSITY_OVERRIDES")
    if overrides is None:
        return
    if not isinstance(overrides, Mapping):
        raise ValueError("RELATIVE_INTENSITY_OVERRIDES must be a mapping when provided.")


def plan_intensity_calibration_inputs(
    flow: str,
    economy_key: str,
    projection_years: Sequence[int],
) -> dict[str, object]:
    """Build a placeholder payload for a future calibration solver."""
    return {
        "flow": str(flow),
        "economy_key": str(economy_key),
        "projection_years": [int(year) for year in projection_years],
        "relative_intensity_overrides": dict(RELATIVE_INTENSITY_OVERRIDES),
        "mode": str(INTENSITY_CALIBRATION_MODE),
    }


def solve_activity_intensity_balance(payload: Mapping[str, object]) -> dict[str, object]:
    """
    Placeholder for future activity-intensity balancing.

    Raises until non-disabled calibration behavior is implemented.
    """
    mode = str(globals().get("INTENSITY_CALIBRATION_MODE", "disabled")).strip().lower()
    if mode == "disabled":
        return {"status": "disabled", "payload": dict(payload)}
    raise NotImplementedError(
        "Intensity calibration mode is enabled, but solver is not implemented yet. "
        "Set INTENSITY_CALIBRATION_MODE='disabled' to run current workflow behavior."
    )


def _coerce_economy_label(value, fallback: str | None = None) -> str:
    """Return a stable string economy label."""
    fallback = fallback or _default_aggregate_economy_label()
    if value is None:
        return fallback
    if isinstance(value, bool):
        return fallback
    text = str(value).strip()
    return text or fallback


def add_all_economy_total(
    df: pd.DataFrame,
    economy_label: str | None = None,
) -> pd.DataFrame:
    """Append synthetic all-economies rows to a dataset."""
    economy_label = economy_label or _default_aggregate_economy_label()
    if df is None or df.empty or "economy" not in df.columns:
        return df
    if df["economy"].astype(str).eq(economy_label).any():
        return df
    year_cols = _year_columns(df)
    if not year_cols:
        return df
    group_cols = [
        col
        for col in df.columns
        if col not in year_cols and col not in {"economy", "economy_key"}
    ]
    if group_cols:
        totals = (
            df.groupby(group_cols, dropna=False)[year_cols]
            .sum()
            .reset_index()
        )
    else:
        totals = pd.DataFrame(
            [
                {
                    year: pd.to_numeric(df[year], errors="coerce").fillna(0.0).sum()
                    for year in year_cols
                }
            ]
        )
    totals["economy"] = economy_label
    if "economy_key" in df.columns:
        totals["economy_key"] = normalize_economy_key(economy_label)
    for col in df.columns:
        if col not in totals.columns:
            totals[col] = pd.NA
    totals = totals[df.columns.tolist()]
    return pd.concat([df, totals], ignore_index=True)


def load_esto_data(path: str = ESTO_DATA_PATH) -> pd.DataFrame:
    """
    Load ESTO (Matt) data and drop subtotals.

    Why:
    - The mapping file (ninth_pairs_to_esto_pairs.xlsx) includes subtotal pairs.
    - We only want real flow/product rows for the minor demand sectors.
    """
    workflow_common.archive_config_dir_once_per_day()
    df, _ = load_augmented_reference_tables(
        esto_path=path,
        ninth_path=NINTH_DATA_PATH,
        subtotal_mapping_path=ESTO_SUBTOTAL_MAPPING_PATH,
        synthetic_rules_path="config/synthetic_reference_rows.csv",
        cache_dir=REFERENCE_CACHE_DIR,
        apply_esto_subtotal_map=True,
        filter_esto_subtotals_flag=True,
        filter_ninth_subtotals_flag=False,
    )
    df = _normalize_year_columns(df)
    df["economy_key"] = df["economy"].apply(normalize_economy_key)
    df["flows"] = df["flows"].astype(str).str.strip()
    df["products"] = df["products"].astype(str).str.strip()
    return df


def load_ninth_data(path: str = NINTH_DATA_PATH) -> pd.DataFrame:
    """
    Load 9th Outlook data and filter to the projection scenario.

    Why:
    - Activity Level is derived from 9th projections.
    - We want non-subtotal rows and a consistent scenario.
    """
    workflow_common.archive_config_dir_once_per_day()
    _, df = load_augmented_reference_tables(
        esto_path=ESTO_DATA_PATH,
        ninth_path=path,
        subtotal_mapping_path=ESTO_SUBTOTAL_MAPPING_PATH,
        synthetic_rules_path="config/synthetic_reference_rows.csv",
        cache_dir=REFERENCE_CACHE_DIR,
        apply_esto_subtotal_map=True,
        filter_esto_subtotals_flag=True,
        filter_ninth_subtotals_flag=False,
    )
    df = _normalize_year_columns(df)
    df = filter_ninth_projection_rows(df, scenario=NINTH_SCENARIO)
    df = add_ninth_pair_columns(df)
    df["economy_key"] = df["economy"].apply(normalize_economy_key)
    return df


def load_mapping(
    path: str | Path | tuple[str | Path, str] = NINTH_TO_ESTO_MAPPING_PATH,
) -> pd.DataFrame:
    """
    Load the 9th↔ESTO mapping file.

    We only keep the columns we need for minor demand mapping.
    """
    if isinstance(path, tuple):
        mapping = read_config_table(path[0], sheet_name=path[1], dtype=str).fillna("")
    else:
        mapping = read_config_table(path, dtype=str).fillna("")
    keep_cols = ["9th_sector", "9th_fuel", "esto_flow", "esto_product"]
    mapping = mapping[[col for col in keep_cols if col in mapping.columns]].copy()
    for col in ["9th_sector", "9th_fuel", "esto_flow", "esto_product"]:
        if col in mapping.columns:
            mapping[col] = mapping[col].astype(str).str.strip()
    return mapping


def build_allocated_projection_table(
    ninth_data: pd.DataFrame,
    esto_data: pd.DataFrame,
    projection_years: Sequence[int],
    scenario: str | None = None,
    mapping: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Allocate 9th projections down to ESTO flow/product pairs.

    This follows the same allocation logic used elsewhere in the repo:
    - 9th projections are split using base-year ESTO shares
    - If economy shares are missing, APEC or equal shares are used

    This is the key step that splits Agriculture vs Fishing when the 9th data
    only has a combined "16_02_agriculture_and_fishing" projection.
    """
    scenario = scenario or _default_ninth_scenario()
    mapping_df = mapping.copy() if mapping is not None else load_mapping()
    if mapping_df is None or mapping_df.empty:
        print("[WARN] No mapping rows available for allocation.")
        return pd.DataFrame()
    ninth_filtered = filter_ninth_projection_rows(ninth_data, scenario=scenario)
    ninth_pairs = add_ninth_pair_columns(ninth_filtered)
    if "economy_key" not in ninth_pairs.columns and "economy" in ninth_pairs.columns:
        ninth_pairs["economy_key"] = ninth_pairs["economy"].apply(normalize_economy_key)
    ninth_series = build_ninth_projection_series(ninth_pairs, projection_years)
    base_values = build_esto_base_year_values(esto_data, EXPORT_BASE_YEAR)
    projection_df, diagnostics = allocate_ninth_projection_to_esto(
        mapping_df,
        ninth_series,
        base_values,
        projection_years,
    )
    if projection_df is None or projection_df.empty:
        print("[WARN] No allocated projection data returned from build_esto_projection_table.")
        return pd.DataFrame()
    return projection_df


def add_base_year_to_intensity(
    intensity_series: dict[int, float],
    esto_data: pd.DataFrame,
    flow: str,
    esto_product: str,
    economy_key: str,
    base_year: int,
) -> dict[int, float]:
    """Inject a deterministic base-year intensity for Current Accounts exports."""
    updated = {int(year): float(value) for year, value in intensity_series.items()}
    if FUEL_ACTIVITY_MODE == "sector_share":
        updated[int(base_year)] = 1.0
        return updated
    if INTENSITY_MODE == "fuel_share":
        flow_total = build_base_year_activity_value(esto_data, flow, economy_key, base_year)
        fuel_value = build_base_year_fuel_value(
            esto_data,
            flow,
            esto_product,
            economy_key,
            base_year,
        )
        updated[int(base_year)] = 0.0 if flow_total == 0.0 else fuel_value / flow_total
        return updated
    if updated:
        first_year = min(updated)
        updated[int(base_year)] = float(updated[first_year])
    else:
        updated[int(base_year)] = 0.0
    return updated


def build_intensity_series(
    flow: str,
    esto_product: str,
    projection_years: Sequence[int],
    fuel_projection: pd.DataFrame,
    sector_projection: pd.DataFrame,
    flow_to_sectors: dict[str, list[str]],
    economy_key: str,
    mapping: pd.DataFrame,
    allocated_projection: pd.DataFrame | None = None,
) -> dict[int, float]:
    """
    Dispatch to the configured intensity mode.

    Default = uniform (constant 1.0).
    """
    if FUEL_ACTIVITY_MODE == "sector_share":
        if INTENSITY_MODE != "uniform" or float(DEFAULT_INTENSITY) != 1.0 or FUEL_INTENSITY_OVERRIDES:
            print(
                "[WARN] FUEL_ACTIVITY_MODE='sector_share' forces Final Energy Intensity to 1.0; "
                "INTENSITY_MODE and intensity overrides are ignored."
            )
        return build_intensity_series_uniform(projection_years, 1.0)
    if INTENSITY_MODE == "custom":
        override = FUEL_INTENSITY_OVERRIDES.get((flow, esto_product))
        if override is not None:
            return build_intensity_series_uniform(projection_years, override)
        return build_intensity_series_uniform(projection_years, DEFAULT_INTENSITY)
    if INTENSITY_MODE == "fuel_share":
        if allocated_projection is not None and not allocated_projection.empty:
            return build_intensity_series_from_allocated(
                allocated_projection,
                flow,
                esto_product,
                economy_key,
                projection_years,
            )
        return build_intensity_series_from_shares(
            fuel_projection,
            sector_projection,
            flow_to_sectors,
            flow,
            esto_product,
            economy_key,
            projection_years,
            mapping,
        )
    # Default fallback
    return build_intensity_series_uniform(projection_years, DEFAULT_INTENSITY)


def build_fuel_activity_series(
    flow: str,
    esto_product: str,
    projection_years: Sequence[int],
    fuel_projection: pd.DataFrame,
    sector_projection: pd.DataFrame,
    flow_to_sectors: dict[str, list[str]],
    economy_key: str,
    mapping: pd.DataFrame,
    sector_activity: dict[int, float],
    allocated_projection: pd.DataFrame | None = None,
) -> dict[int, float]:
    """
    Dispatch to the configured fuel activity mode.

    Mode semantics:
    - activity_as_energy_intensity_as_one: returns energy-valued activity per fuel.
    - fuel_share: legacy alias of activity_as_energy_intensity_as_one.
    - sector_share: returns fraction 0..1 per fuel.
    - none: returns zero series (caller skips fuel activity rows).
    """
    mode = _normalize_fuel_activity_mode(FUEL_ACTIVITY_MODE)
    if mode == "none":
        return {int(year): 0.0 for year in projection_years}
    if (
        mode == "activity_as_energy_intensity_as_one"
        and allocated_projection is not None
        and not allocated_projection.empty
    ):
        return build_fuel_activity_series_from_allocated(
            allocated_projection,
            sector_activity,
            flow,
            esto_product,
            economy_key,
            projection_years,
        )
    if mode == "activity_as_energy_intensity_as_one":
        return build_fuel_activity_series_from_shares(
            fuel_projection,
            sector_projection,
            flow_to_sectors,
            flow,
            esto_product,
            economy_key,
            projection_years,
            mapping,
            sector_activity,
        )
    if mode == "sector_share" and allocated_projection is not None and not allocated_projection.empty:
        return build_fuel_activity_series_sector_share_from_allocated(
            allocated_projection,
            flow,
            esto_product,
            economy_key,
            projection_years,
        )
    if mode == "sector_share":
        return build_fuel_activity_series_sector_share_from_shares(
            fuel_projection,
            sector_projection,
            flow_to_sectors,
            flow,
            esto_product,
            economy_key,
            projection_years,
            mapping,
        )
    raise ValueError(
        f"Unsupported FUEL_ACTIVITY_MODE '{FUEL_ACTIVITY_MODE}'. "
        "Valid options: activity_as_energy_intensity_as_one, sector_share, none."
    )


def _load_gdp_wide_for_ia(path: str, scenario: str) -> pd.DataFrame:
    """
    Load the macro CSV (long format) and return a wide DataFrame.

    Index = economy_key, columns = int years, values = Gdp.
    Expected columns: Economy, Scenario, Date, Gdp.
    """
    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]
    required = {"Economy", "Scenario", "Date", "Gdp"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"GDP file '{path}' missing columns: {missing}")
    df = df[df["Scenario"] == scenario].copy()
    if df.empty:
        raise ValueError(f"No rows for scenario '{scenario}' in '{path}'.")
    df["economy_key"] = df["Economy"].apply(normalize_economy_key)
    df["year"] = pd.to_numeric(df["Date"], errors="coerce").astype("Int64")
    df["Gdp"] = pd.to_numeric(df["Gdp"], errors="coerce")
    df = df.dropna(subset=["year", "Gdp"])
    wide = df.pivot_table(index="economy_key", columns="year", values="Gdp", aggfunc="first")
    wide.columns = [int(c) for c in wide.columns]
    return wide


def align_to_template_schema(
    export_df: pd.DataFrame,
    template_path: str = LEAP_TEMPLATE_PATH,
    template_sheet: str = "Export",
) -> pd.DataFrame:
    """
    Force column order to match the industry export template.

    This adds missing columns (IDs, Unnamed: 12, extra Level columns) as NA,
    and drops columns that are not in the template.
    """
    template = read_config_table(template_path, sheet_name=template_sheet, header=2, nrows=1)
    template_cols = list(template.columns)
    aligned = export_df.reindex(columns=template_cols)
    return aligned


def build_minor_demand_rows(
    esto_data: pd.DataFrame,
    ninth_data: pd.DataFrame,
    mapping: pd.DataFrame,
    economy: str,
    flow_configs: Sequence[dict] = MINOR_DEMAND_FLOW_CONFIG,
    projection_years: Sequence[int] | None = None,
    scenario: str | None = None,
    measure_units: Mapping[str, Mapping[str, object]] | None = None,
    gdp_wide: pd.DataFrame | None = None,
) -> list[dict]:
    """
    Build log-style rows (for finalise_export_df) for minor demand sectors.
    """
    scenario = scenario or _default_export_scenario()
    normalized_fuel_activity_mode = _normalize_fuel_activity_mode(FUEL_ACTIVITY_MODE)
    if (
        normalized_fuel_activity_mode == "activity_as_energy_intensity_as_one"
        and INTENSITY_MODE == "fuel_share"
    ):
        print(
            "[WARN] FUEL_ACTIVITY_MODE='activity_as_energy_intensity_as_one' with "
            "INTENSITY_MODE='fuel_share' "
            "will apply fuel shares twice. Consider INTENSITY_MODE='uniform' unless "
            "you intend this behavior."
        )
    projection_years = projection_years or _projection_years()
    economy_key = normalize_economy_key(economy)
    resolved_units = _resolve_measure_units(measure_units)
    activity_units = resolved_units[ACTIVITY_VARIABLE]
    sector_activity_units = _resolve_sector_activity_units(
        activity_units,
        normalized_fuel_activity_mode,
    )
    fuel_activity_units = _resolve_fuel_activity_units(
        activity_units,
        normalized_fuel_activity_mode,
    )
    intensity_units = resolved_units[INTENSITY_VARIABLE]

    # 1) Map each ESTO flow to the 9th sector(s) it belongs to.
    flow_to_sectors = build_flow_to_sectors(mapping, flow_configs)

    # 2) Identify fuels for each flow using ESTO (non-subtotal) products.
    flow_to_fuels = build_flow_to_fuels(esto_data, flow_configs, economy_key)

    # 3) Aggregate 9th projection totals by sector and (optionally) by fuel.
    sector_projection = build_sector_projection(ninth_data, projection_years)
    fuel_projection = build_fuel_projection(ninth_data, projection_years)
    allocated_projection = build_allocated_projection_table(
        ninth_data=ninth_data,
        esto_data=esto_data,
        projection_years=projection_years,
        scenario=_default_ninth_scenario(),
        mapping=mapping,
    )
    # Keep only the minor demand flows (reduces noise and speeds later filters).
    flow_list = [cfg["esto_flow"] for cfg in flow_configs]
    if allocated_projection is not None and not allocated_projection.empty:
        allocated_projection = allocated_projection[
            allocated_projection["esto_flow"].isin(flow_list)
        ].copy()
    if DEBUG_ALLOCATION_SUMMARY:
        years_to_show = [2023, 2030, 2040, 2050, 2060]
        print_allocation_summary(
            allocated_projection,
            economy_key,
            flow_configs,
            years_to_show,
        )

    rows: list[dict] = []
    for cfg in flow_configs:
        flow = cfg["esto_flow"]
        sector_label = sanitize_leap_name(cfg["sector_label"])
        sector_path = build_branch_path([*DEMAND_ROOT_PARTS, sector_label])

        # Activity Level = allocated 9th projection for this ESTO flow.
        # This splits Agriculture vs Fishing based on base-year ESTO shares.
        activity_series = build_activity_series_from_allocated(
            allocated_projection,
            flow,
            economy_key,
            projection_years,
        )
        # Only fall back when there are no allocation rows at all for this flow.
        has_alloc_rows = False
        if allocated_projection is not None and not allocated_projection.empty:
            has_alloc_rows = not allocated_projection[
                (allocated_projection["economy_key"] == economy_key)
                & (allocated_projection["esto_flow"] == flow)
            ].empty
        if not has_alloc_rows:
            # Fallback to raw 9th sector totals only if allocation is missing.
            activity_series = build_activity_series(
                sector_projection,
                flow_to_sectors,
                flow,
                economy_key,
                projection_years,
            )
        activity_series = add_base_year_to_sector_activity(
            activity_series,
            esto_data,
            flow,
            economy_key,
            EXPORT_BASE_YEAR,
        )
        rows.extend(
            build_year_rows(
                sector_path,
                ACTIVITY_VARIABLE,
                scenario,
                activity_series,
                sector_activity_units["units"],
                sector_activity_units["scale"],
                sector_activity_units["per"],
            )
        )

        # Intensity Adjustment: pre-compute once per sector; applied to every fuel branch.
        # IA[year] = (ninth_tgt[year] / (gdp_index[year] * base_energy)) - 1
        # At base year = 0; negative = efficiency gain vs flat-GDP intensity baseline.
        ia_series: dict[int, float] | None = None
        if gdp_wide is not None:
            _gdp_idx = _build_gdp_index_series(
                gdp_wide, economy_key, list(projection_years), EXPORT_BASE_YEAR
            )
            _base_sector_energy = build_base_year_activity_value(
                esto_data, flow, economy_key, EXPORT_BASE_YEAR
            )
            ia_series = build_intensity_adjustment_series(
                activity_series,
                _base_sector_energy,
                _gdp_idx,
                projection_years,
                EXPORT_BASE_YEAR,
            )

        # Final Energy Intensity per fuel (uses ESTO product names).
        fuels = flow_to_fuels.get(flow, [])
        if not fuels:
            print(f"[WARN] No fuels found for flow '{flow}'. Only Activity Level will be exported.")
        for fuel in fuels:
            fuel_label = sanitize_leap_name(clean_fuel_label_for_leap(fuel))
            fuel_path = build_branch_path([*DEMAND_ROOT_PARTS, sector_label, fuel_label])
            fuel_activity_series: dict[int, float] | None = None
            if normalized_fuel_activity_mode != "none":
                fuel_activity_series = build_fuel_activity_series(
                    flow,
                    fuel,
                    projection_years,
                    fuel_projection,
                    sector_projection,
                    flow_to_sectors,
                    economy_key,
                    mapping,
                    activity_series,
                    allocated_projection,
                )
                fuel_activity_series = add_base_year_to_fuel_activity(
                    fuel_activity_series,
                    esto_data,
                    flow,
                    fuel,
                    economy_key,
                    EXPORT_BASE_YEAR,
                    normalized_fuel_activity_mode,
                )
                if not any(abs(value) > 0 for value in fuel_activity_series.values()):
                    # Skip unused fuels to reduce clutter in the export.
                    continue
                rows.extend(
                    build_year_rows(
                        fuel_path,
                        ACTIVITY_VARIABLE,
                        scenario,
                        fuel_activity_series,
                        fuel_activity_units["units"],
                        fuel_activity_units["scale"],
                        fuel_activity_units["per"],
                    )
                )
            if fuel_activity_series is None:
                # Skip unused fuels even when fuel activity rows are disabled.
                has_energy = False
                if allocated_projection is not None and not allocated_projection.empty:
                    year_cols = [year for year in projection_years if year in allocated_projection.columns]
                    fuel_subset = allocated_projection[
                        (allocated_projection["economy_key"] == economy_key)
                        & (allocated_projection["esto_flow"] == flow)
                        & (allocated_projection["esto_product"] == fuel)
                    ]
                    if not fuel_subset.empty and year_cols:
                        has_energy = float(fuel_subset[year_cols].sum().sum()) != 0.0
                if not has_energy:
                    mapped_fuels = (
                        mapping.loc[
                            (mapping["esto_flow"] == flow) & (mapping["esto_product"] == fuel),
                            "9th_fuel",
                        ]
                        .dropna()
                        .unique()
                        .tolist()
                    )
                    if mapped_fuels:
                        year_cols = [year for year in projection_years if year in fuel_projection.columns]
                        fuel_subset = fuel_projection[
                            (fuel_projection["economy_key"] == economy_key)
                            & (fuel_projection["9th_sector"].isin(flow_to_sectors.get(flow, [])))
                            & (fuel_projection["9th_fuel"].isin(mapped_fuels))
                        ]
                        if not fuel_subset.empty and year_cols:
                            has_energy = float(fuel_subset[year_cols].sum().sum()) != 0.0
                if not has_energy:
                    continue
            intensity_series = build_intensity_series(
                flow,
                fuel,
                projection_years,
                fuel_projection,
                sector_projection,
                flow_to_sectors,
                economy_key,
                mapping,
                allocated_projection,
            )
            intensity_series = add_base_year_to_intensity(
                intensity_series,
                esto_data,
                flow,
                fuel,
                economy_key,
                EXPORT_BASE_YEAR,
            )
            rows.extend(
                build_year_rows(
                    fuel_path,
                    INTENSITY_VARIABLE,
                    scenario,
                    intensity_series,
                    intensity_units["units"],
                    intensity_units["scale"],
                    intensity_units["per"],
                )
            )
            if ia_series is not None:
                rows.extend(
                    build_year_rows(
                        fuel_path,
                        INTENSITY_ADJUSTMENT_VARIABLE,
                        scenario,
                        ia_series,
                        "Unspecified Unit",
                        "",
                        "",
                    )
                )
    return rows


def _resolve_export_filename(
    economy: str,
    scenarios: str | Sequence[str] | None,
    export_filename: str | None,
) -> str:
    template = export_filename or _default_export_filename_template()
    if export_filename is None or "{economy}" in template or "{scenario}" in template:
        return workflow_common.build_workflow_export_filename(
            economy,
            scenarios,
            template,
            workflow_common.format_filename_segment,
            fallback_template=_default_export_filename_template(),
        )
    return template


def assemble_minor_demand_workbook(
    economy: str,
    export_filename: str | None = None,
    include_leap_import: bool = False,
    scenario: str | Sequence[str] | None = None,
    scenarios: str | Sequence[str] | None = None,
    import_scenario: str | Sequence[str] | None = None,
    region: str | None = None,
    aggregate_economy_label: str | None = None,
    measure_units: Mapping[str, Mapping[str, object]] | None = None,
) -> Path:
    """
    End-to-end builder:
    - Load datasets
    - Build log rows
    - Convert to LEAP export format
    - Save Excel
    - Optionally create/fill LEAP branches
    """
    if scenario is not None and scenarios is not None:
        raise ValueError("Provide only one of 'scenario' or 'scenarios'.")
    scenario_list = _normalize_export_scenarios(
        scenarios if scenarios is not None else scenario
    )
    import_scenarios = workflow_common.resolve_import_scenarios(
        scenario_list,
        import_scenario,
    )
    scenario_to_import = import_scenarios[0]
    region = region or _default_export_region()
    should_aggregate, aggregate_label, _ = workflow_common.resolve_aggregate_economy(
        economy,
        aggregate_label=_coerce_economy_label(
            aggregate_economy_label,
            fallback=_default_aggregate_economy_label(),
        ),
    )
    run_economy = aggregate_label if should_aggregate else str(economy)
    validate_intensity_calibration_config()
    if str(INTENSITY_CALIBRATION_MODE).strip().lower() != "disabled":
        calibration_payload = plan_intensity_calibration_inputs(
            flow="__minor_demand__",
            economy_key=normalize_economy_key(run_economy),
            projection_years=_projection_years(),
        )
        solve_activity_intensity_balance(calibration_payload)

    # --- Load data ---
    esto_data = load_esto_data()
    ninth_data = load_ninth_data()
    if should_aggregate:
        esto_data = add_all_economy_total(esto_data, run_economy)
        ninth_data = add_all_economy_total(ninth_data, run_economy)
    mapping = load_mapping()
    mapping = filter_mapping_for_minor_demand(mapping, esto_data, MINOR_DEMAND_FLOW_CONFIG)

    # --- Load GDP for Intensity Adjustment user variable (optional) ---
    gdp_wide: pd.DataFrame | None = None
    if INCLUDE_INTENSITY_ADJUSTMENT:
        try:
            gdp_wide = _load_gdp_wide_for_ia(GDP_DATA_PATH_FOR_IA, GDP_SCENARIO_FOR_IA)
        except Exception as _exc:
            print(f"[WARN] Could not load GDP data for Intensity Adjustment: {_exc}")

    # --- Build log rows ---
    rows = build_minor_demand_rows(
        esto_data=esto_data,
        ninth_data=ninth_data,
        mapping=mapping,
        economy=run_economy,
        scenario=scenario_list[0],
        measure_units=measure_units,
        gdp_wide=gdp_wide,
    )
    if not rows:
        raise ValueError("No log rows generated; check mappings and filters.")
    if len(scenario_list) > 1:
        base_rows = rows
        rows = []
        for scenario_name in scenario_list:
            for row in base_rows:
                scenario_row = row.copy()
                scenario_row["Scenario"] = scenario_name
                rows.append(scenario_row)

    # --- Convert to LEAP export dataframes ---
    log_df = pd.DataFrame(rows)
    export_df = finalise_export_df(
        log_df,
        scenario=scenario_to_import,
        region=region,
        base_year=EXPORT_BASE_YEAR,
        final_year=EXPORT_FINAL_YEAR,
    )
    if export_df is None or export_df.empty:
        raise ValueError("Export dataframe is empty; check projection years and data.")
    export_df = collapse_current_accounts_years(
        export_df,
        base_year=EXPORT_BASE_YEAR,
    )

    # Expression-based LEAP sheet (matches industry export.xlsx style).
    expression_df = build_expression_export_df(
        export_df,
        base_year=EXPORT_BASE_YEAR,
    )
    expression_df = align_to_template_schema(expression_df)

    # --- Save workbook ---
    export_filename = _resolve_export_filename(
        run_economy,
        scenario_list,
        export_filename,
    )
    save_export_files(
        leap_export_df=expression_df,
        export_df_for_viewing=export_df,
        leap_export_filename=export_filename,
        base_year=EXPORT_BASE_YEAR,
        final_year=EXPORT_FINAL_YEAR,
        model_name=EXPORT_MODEL_NAME,
    )

    # --- Optional: push into LEAP ---
    if include_leap_import:
        dispatch_result = dispatch_analysis_input_write(
            export_path=Path(export_filename),
            sheet_name="LEAP",
            scenario=scenario_to_import,
            region=region,
            context_label="minor_demand_workflow.include_leap_import",
        )
        if dispatch_result.get("mode") == "workbook":
            return Path(export_filename)

        if not is_leap_api_available():
            print("[INFO] LEAP API unavailable; skipping LEAP import.")
            return Path(export_filename)
        L = connect_to_leap()
        fuel_catalog_preflight.run_fuel_catalog_preflight(
            export_path=export_filename,
            sheet_name="LEAP",
            scenario=scenario_to_import,
            context="minor_demand_workflow.include_leap_import",
            leap_app=L,
        )
        # Default branch types:
        # - Non-leaf branches are demand categories.
        # - Leaf branches are demand technologies (fuel-named technologies).
        create_scenario = scenario_to_import if len(import_scenarios) == 1 else None
        create_branches_from_export_file(
            L,
            export_filename,
            sheet_name="LEAP",
            scenario=create_scenario,
            region=region,
            branch_type_mapping=None,
            default_branch_type=(
                BRANCH_DEMAND_CATEGORY,
                BRANCH_DEMAND_CATEGORY,
                BRANCH_DEMAND_TECHNOLOGY,
            ),
            RAISE_ERROR_ON_FAILED_BRANCH_CREATION=True,
        )
        for index, scenario_name in enumerate(import_scenarios):
            fill_branches_from_export_file(
                L,
                export_filename,
                sheet_name="LEAP",
                scenario=scenario_name,
                region=region,
                RAISE_ERROR_ON_FAILED_SET=True,
                HANDLE_CURRENT_ACCOUNTS_TOO=index == 0,
                RUN_FUEL_CATALOG_PREFLIGHT=False,
            )

    return Path(export_filename)


# Legacy names kept for compatibility.
def build_minor_demand_log_rows(
    esto_data: pd.DataFrame,
    ninth_data: pd.DataFrame,
    mapping: pd.DataFrame,
    economy: str,
    flow_configs: Sequence[dict] = MINOR_DEMAND_FLOW_CONFIG,
    projection_years: Sequence[int] | None = None,
    scenario: str | Sequence[str] | None = None,
    measure_units: Mapping[str, Mapping[str, object]] | None = None,
) -> list[dict]:
    scenario_list = _normalize_export_scenarios(scenario)
    rows = build_minor_demand_rows(
        esto_data=esto_data,
        ninth_data=ninth_data,
        mapping=mapping,
        economy=economy,
        flow_configs=flow_configs,
        projection_years=projection_years,
        scenario=scenario_list[0],
        measure_units=measure_units,
    )
    if len(scenario_list) == 1:
        return rows
    expanded_rows: list[dict] = []
    for scenario_name in scenario_list:
        for row in rows:
            scenario_row = row.copy()
            scenario_row["Scenario"] = scenario_name
            expanded_rows.append(scenario_row)
    return expanded_rows


def build_minor_demand_export(
    economy: str,
    export_filename: str | None = None,
    include_leap_import: bool = False,
    scenario: str | Sequence[str] | None = None,
    scenarios: str | Sequence[str] | None = None,
    import_scenario: str | Sequence[str] | None = None,
    region: str | None = None,
    aggregate_economy_label: str | None = None,
    measure_units: Mapping[str, Mapping[str, object]] | None = None,
) -> Path:
    return assemble_minor_demand_workbook(
        economy=economy,
        export_filename=export_filename,
        include_leap_import=include_leap_import,
        scenario=scenario,
        scenarios=scenarios,
        import_scenario=import_scenario,
        region=region,
        aggregate_economy_label=aggregate_economy_label,
        measure_units=measure_units,
    )
#%%
# --- Export / LEAP settings ---
EXPORT_FILENAME_TEMPLATE = workflow_cfg.MINOR_DEMAND_EXPORT_FILENAME_TEMPLATE
EXPORT_FILENAME = EXPORT_FILENAME_TEMPLATE
EXPORT_MODEL_NAME = workflow_cfg.MINOR_DEMAND_EXPORT_MODEL_NAME
EXPORT_REGION = workflow_cfg.MINOR_DEMAND_EXPORT_REGION
EXPORT_SCENARIOS = list(workflow_cfg.MINOR_DEMAND_EXPORT_SCENARIOS)
EXPORT_SCENARIO = EXPORT_SCENARIOS[0] if EXPORT_SCENARIOS else "Reference"
EXPORT_IMPORT_SCENARIOS = [
    scenario.lower()
    for scenario in EXPORT_SCENARIOS
    if scenario.lower() not in {"current accounts", "current account"}
]
NINTH_SCENARIO = workflow_cfg.MINOR_DEMAND_NINTH_SCENARIO
# Change saved LEAP units here, or pass `measure_units=...` to function calls.
MEASURE_UNITS = dict(workflow_cfg.MINOR_DEMAND_MEASURE_UNITS)
FUEL_ACTIVITY_MODE = str(workflow_cfg.MINOR_DEMAND_FUEL_ACTIVITY_MODE)
INTENSITY_CALIBRATION_MODE = str(workflow_cfg.MINOR_DEMAND_INTENSITY_CALIBRATION_MODE)
RELATIVE_INTENSITY_OVERRIDES = dict(workflow_cfg.MINOR_DEMAND_RELATIVE_INTENSITY_OVERRIDES)
AGGREGATE_ECONOMY_LABEL = workflow_cfg.MINOR_DEMAND_AGGREGATE_ECONOMY_LABEL

# Branch root in the LEAP demand tree. Adjust to your LEAP model if needed.
# Use a list so each segment is sanitized separately.
DEMAND_ROOT_PARTS = list(workflow_cfg.MINOR_DEMAND_DEMAND_ROOT_PARTS)

# --- Years ---
# We use the same base year as the rest of the repo (2022).
_config_base_year = workflow_cfg.MINOR_DEMAND_EXPORT_BASE_YEAR
EXPORT_BASE_YEAR = ENERGY_SOURCE_CONFIG.esto_base_year if _config_base_year is None else int(_config_base_year)
PROJECTION_START_YEAR = int(getattr(workflow_cfg, "MINOR_DEMAND_PROJECTION_START_YEAR", ENERGY_SOURCE_CONFIG.projection_start_year))
EXPORT_FINAL_YEAR = int(workflow_cfg.MINOR_DEMAND_EXPORT_FINAL_YEAR)
if ENERGY_SOURCE_CONFIG.projection_final_year is not None:
    EXPORT_FINAL_YEAR = int(ENERGY_SOURCE_CONFIG.projection_final_year)


if __name__ == "__main__":
    # Example run:
    # - economy label is 9th-style (e.g., "20_USA").
    # - keep include_leap_import=False unless running with LEAP API access.
    # - use economy="00_APEC" (or "ALL_ECONOMIES") to run an aggregate economy.
    assemble_minor_demand_workbook(
        economy="20_USA",
        export_filename=None,
        include_leap_import=True,
        scenarios=EXPORT_SCENARIOS,
        import_scenario=EXPORT_IMPORT_SCENARIOS,
        region=EXPORT_REGION,
        aggregate_economy_label=AGGREGATE_ECONOMY_LABEL,
    )
#%%


try:
    from codebase.utilities.workflow_common import emit_completion_beep as _emit_completion_beep
except Exception:  # pragma: no cover
    def _emit_completion_beep(*, success: bool = True) -> None:  # noqa: ARG001
        return


if __name__ == "__main__":  # pragma: no cover
    _emit_completion_beep(success=True, style="chime")
