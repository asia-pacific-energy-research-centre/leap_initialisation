"""Export construction helpers for supply LEAP import workbooks."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from codebase.configuration import workflow_config as workflow_cfg
from codebase.functions.esto_data_utils import get_economy_list, try_debug_breakpoint
from codebase.functions.leap_excel_io import finalise_export_df, save_export_files
from codebase.functions.supply_branch_classification import (
    _SUPPLY_BRANCH_PATH_MISS_WARNED,
    _get_supply_branch_roots_for_entry,
    _resolve_supply_branch_label_from_export,
    _supply_branch_exists_in_export_source,
)
from codebase.functions.supply_export_rows import (
    _resolve_supply_override,
    build_branch_path,
    build_year_rows,
    coerce_value_by_year,
    sanitize_leap_label,
)
from codebase.functions.supply_value_series import (
    build_supply_value_by_year,
    select_fuel_rows,
)
from codebase.utilities import workflow_common

REPO_ROOT = Path(__file__).resolve().parents[2]
ENERGY_SOURCE_CONFIG = workflow_cfg.get_energy_source_config()
BASE_YEAR = ENERGY_SOURCE_CONFIG.esto_base_year
PROJECTION_END_YEAR = 2060
if ENERGY_SOURCE_CONFIG.projection_final_year is not None:
    PROJECTION_END_YEAR = int(ENERGY_SOURCE_CONFIG.projection_final_year)

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

SUPPLY_MEASURES = [
    {"name": "Imports", "flow_key": "imports", "units": "Petajoule", "per": ""},
    {"name": "Exports", "flow_key": "exports", "units": "Petajoule", "per": ""},
    {
        "name": "Maximum Production",
        "flow_key": "max_production",
        "units": "Petajoule",
        "per": "",
        # Branch classification decides whether this belongs in Primary or
        # Secondary resources for the current LEAP template.
        "branch_root": "all",
    },
    {
        "name": "Unmet Requirements",
        "flow_key": None,
        "units": "Percent",
        "per": "MeetWithImports",
        "value": 0.0,
    },
]

# Explicit exceptions to the source-fuel matching validation. A matched fuel
# with zero production is valid; an unmatched fuel should be reviewed after
# the complete workflow has run.
SUPPLY_FUEL_MATCH_EXCEPTIONS = {
    "biomass",
    "green electricity",
}
_SUPPLY_FUEL_MATCH_ERRORS_REPORTED: set[tuple[str, str]] = set()

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


def _is_unlimited_production_entry(fuel_entry):
    """Return whether an ESTO product uses LEAP's explicit Unlimited expression."""
    product = str((fuel_entry or {}).get("fuel_label_esto") or "").strip()
    return product in workflow_cfg.SUPPLY_UNLIMITED_PRODUCTION_ESTO_PRODUCTS


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
            fuel_match_candidates = {
                str(value or "").strip().casefold().replace("_", " ")
                for value in (
                    fuel_key,
                    entry.get("fuel_name"),
                    entry.get("fuel_label_esto"),
                )
                if str(value or "").strip()
            }
            is_match_exception = any(
                exception in candidate
                for candidate in fuel_match_candidates
                for exception in SUPPLY_FUEL_MATCH_EXCEPTIONS
            )
            if not is_match_exception:
                matched_fuel_rows = select_fuel_rows(
                    data,
                    entry.get("fuel_code_ninth"),
                    entry.get("fuel_label_esto"),
                    fuel_name=entry.get("fuel_name"),
                    code_to_name_mapping=code_to_name_mapping,
                )
                if matched_fuel_rows.empty:
                    error_key = (str(economy).strip(), str(display_name).strip())
                    if error_key not in _SUPPLY_FUEL_MATCH_ERRORS_REPORTED:
                        _SUPPLY_FUEL_MATCH_ERRORS_REPORTED.add(error_key)
                        workflow_common.defer_or_raise(
                            ValueError(
                                "Configured supply fuel did not match any source row: "
                                f"economy={economy}, fuel_key={fuel_key}, "
                                f"fuel_name={display_name}, "
                                f"fuel_label_esto={entry.get('fuel_label_esto')}, "
                                f"fuel_code_ninth={entry.get('fuel_code_ninth')}"
                            ),
                            context=f"supply_fuel_match:{economy}:{display_name}",
                        )
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
                if flow_key == "max_production" and _is_unlimited_production_entry(entry):
                    default_flow_values_by_year[flow_key] = {
                        year: float(workflow_cfg.SUPPLY_UNLIMITED_PRODUCTION_YEAR_VALUE)
                        for year in range(base_year, final_year + 1)
                    }
            for scenario in scenario_names:
                for branch_root in branch_roots:
                    branch_type = str(branch_root[-1] if branch_root else "").strip().lower()
                    template_label = _resolve_supply_branch_label_from_export(
                        branch_type,
                        display_name,
                        entry.get("fuel_label_esto"),
                        fuel_key,
                    )
                    safe_name = sanitize_leap_label(template_label or display_name)
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
                    for measure in measures:
                        root_filter = str(measure.get("branch_root") or "").strip().lower()
                        if root_filter and root_filter not in {"all", branch_type}:
                            continue
                        flow_key = measure.get("flow_key")
                        if flow_key:
                            if flow_key == "max_production" and _is_unlimited_production_entry(entry):
                                value_by_year = default_flow_values_by_year.get(
                                    flow_key,
                                    {
                                        year: float(workflow_cfg.SUPPLY_UNLIMITED_PRODUCTION_YEAR_VALUE)
                                        for year in range(base_year, final_year + 1)
                                    },
                                )
                            else:
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


def generate_supply_exports(
    dataset_map,
    fuel_config,
    code_to_name_mapping,
    projection_lookup=None,
    projection_years=None,
    dataset_key: str = workflow_cfg.SUPPLY_EXPORT_DATASET_KEY,
    economies: list[str] | None = None,
    scenario_names=EXPORT_SCENARIOS,
    base_year=EXPORT_BASE_YEAR,
    final_year=EXPORT_FINAL_YEAR,
    export_output_dir: Path | str = EXPORT_OUTPUT_DIR,
    filename_template: str = EXPORT_FILENAME_TEMPLATE,
    flow_value_overrides_by_economy: dict | None = None,
    supply_measures: list[dict] | None = None,
    keep_all_zero_rows: bool = False,
    projection_lookup_default=None,
    economies_to_analyze: list[str] | None = None,
    resolve_dataset_func=None,
):
    """Generate LEAP-ready supply exports for the requested economies."""
    if resolve_dataset_func is None:
        from codebase.functions.esto_data_utils import resolve_dataset as resolve_dataset_func

    data, year_cols = resolve_dataset_func(dataset_map, dataset_key)
    flow_codes = FLOW_CODES_BY_DATASET.get(dataset_key)
    if not flow_codes:
        raise KeyError(f"Unknown dataset key for flow codes: {dataset_key}")
    if projection_lookup is None:
        projection_lookup = projection_lookup_default
    default_economies = (
        economies_to_analyze
        if economies_to_analyze is not None
        else list(workflow_cfg.SUPPLY_ECONOMIES_TO_ANALYZE)
    )
    target_economies = economies or get_economy_list(data, default_economies)
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
