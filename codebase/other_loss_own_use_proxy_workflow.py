#%%
"""
Build proxy activity and intensity inputs for other loss / own-use demand branches.

The workflow creates LEAP demand-branch first estimates for balance-table
losses and own-use flows that do not fit cleanly in transformation modules.
For each configured process it:
- builds one proxy activity series, for example coal production for coal mines;
- pulls the target loss/own-use series by fuel;
- calculates fuel intensity as abs(target energy) / proxy activity;
- writes audit CSV files and a LEAP import workbook.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from collections.abc import Mapping, Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
try:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
except Exception as exc:
    print(f"Failed to add repo root to sys.path: {exc}")

from codebase.configuration import workflow_config as workflow_cfg
from codebase.configuration.config import BASE_YEAR
from codebase.functions.analysis_input_write_dispatcher import dispatch_analysis_input_write
from codebase.functions.leap_core import (
    create_branches_from_export_file,
    fill_branches_from_export_file,
    is_leap_api_available,
    sanitize_leap_name,
)
from codebase.functions.leap_excel_io import finalise_export_df, save_export_files
from codebase.functions.leap_labels import clean_fuel_label_for_leap
from codebase.functions.leap_expressions import build_data_expression_from_row
from codebase.scrapbook.utilities import apply_matt_subtotal_mapping, filter_matt_subtotals
from codebase.utilities import fuel_catalog_preflight, workflow_common
from codebase.utilities.workflow_utils import (
    _normalize_economy,
    _normalize_year_columns,
    _resolve,
)
from codebase.utilities.leap_balance_export_resolver import (
    build_leap_balance_activity_series,
    load_leap_balance_activity_table as _load_shared_leap_balance_activity_table,
    normalize_balance_label,
    resolve_balance_export_workbook,
)
from codebase.functions.other_loss_own_use_proxy_utils import (
    DEMAND_ROOT_PARTS,
    ACTIVITY_VARIABLE,
    INTENSITY_VARIABLE,
    DEFAULT_MEASURE_UNITS,
    LEAP_BALANCE_FUEL_SETS,
    LEAP_BALANCE_ACTIVITY_FALLBACKS,
    _normalize_activity_source_mode,
    _normalize_balance_label,
    _normalize_source_token,
    _year_columns,
    _compact_economy,
    _clean_ninth_name,
    _sentence_case_fuel_label,
    _clean_product_for_branch,
    _format_fuel_branch_label,
    _source_fuel_label,
    _series_from_group,
    _apply_value_mode,
    _has_prefix,
    _matches_exact_values,
    _drop_ninth_parent_fuel_rows,
    _drop_ninth_subtotals,
    _select_ninth_sector,
    _next_parent_ninth_sector_codes,
    _sum_ninth_proxy_activity_series,
    _series_has_nonzero_value,
    _target_fuel_label_from_ninth,
    load_leap_balance_activity_table,
    build_leap_balance_proxy_activity_series,
    build_esto_proxy_activity_series,
    build_ninth_proxy_activity_series,
    build_ninth_proxy_activity_series_with_fallback,
    build_proxy_activity_series,
    build_activity_series_for_mode,
    build_activity_source_gap_warnings,
    build_activity_source_fallback_report,
    build_target_energy_long,
    _nonzero_fuels_from_esto_activity,
    _nonzero_fuels_from_ninth_activity,
    _mapped_expected_fuels,
    build_proxy_fuel_set_verification,
    filter_detail_to_validated_output_fuels,
    build_branch_path,
    build_year_rows,
    build_proxy_log_rows,
    build_expression_export_df,
    load_export_key_table,
    merge_export_ids,
    _zero_data_expression_for_scenario,
    add_zero_rows_for_unset_values,
    _add_leap_header_rows,
    add_export_id_sheet,
    _write_csv_with_locked_file_fallback,
)


# --- Stable paths ---
ENERGY_SOURCE_CONFIG = workflow_cfg.get_energy_source_config()
ESTO_DATA_PATH = ENERGY_SOURCE_CONFIG.esto_base_table_path
NINTH_DATA_PATH = ENERGY_SOURCE_CONFIG.ninth_projection_table_path
ESTO_SUBTOTAL_MAPPING_PATH = REPO_ROOT / "config" / "ESTO_subtotal_mapping.xlsx"
LEAP_MAPPINGS_PATH = REPO_ROOT / "config" / "leap_mappings.xlsx"
OUTPUT_FUEL_VALIDATION_ESTO_PATHS = [
    REPO_ROOT / "data" / "00APEC_2025_low_with_subtotals.csv",
    REPO_ROOT / "data" / "00APEC_2024_low_with_subtotals.csv",
]


# --- LEAP export settings ---
# ACTIVITY_VARIABLE, INTENSITY_VARIABLE imported from other_loss_own_use_proxy_utils
EXPORT_MODEL_NAME = "Other loss and own use proxy import"

# LEAP region written into the export workbook.
EXPORT_REGION = workflow_cfg.GLOBAL_REGION

# Scenarios written to the workbook. Common values are "Target", "Reference",
# and "Current Accounts". Keep "Current Accounts" if you want base-year
# expressions for Current Accounts.
EXPORT_SCENARIOS = list(workflow_cfg.GLOBAL_SCENARIOS)

BASE_YEAR = ENERGY_SOURCE_CONFIG.esto_base_year
EXPORT_BASE_YEAR = BASE_YEAR
EXPORT_FINAL_YEAR = 2060 if ENERGY_SOURCE_CONFIG.projection_final_year is None else int(ENERGY_SOURCE_CONFIG.projection_final_year)

# 9th Edition scenario used for first-run projections.
NINTH_SCENARIO = "target"

# Supporting CSV output location and main LEAP import workbook filename pattern.
OUTPUT_ROOT = Path(workflow_cfg.GLOBAL_EXPORT_OUTPUT_DIR) / "supporting_files" / "other_loss_own_use_proxy"
EXPORT_FILENAME_TEMPLATE = str(
    Path(workflow_cfg.GLOBAL_EXPORT_OUTPUT_DIR) / "other_loss_own_use_proxy_{economy}_{scenario}.xlsx"
)

# Existing LEAP export workbook used to attach BranchID, VariableID,
# ScenarioID, and RegionID to generated rows. Rows that don't match are
# dropped with a [WARN] (branch not yet in LEAP / export key is stale).
# Refresh data/full model export.xlsx from LEAP to include new branches.
EXPORT_KEY_WORKBOOK_PATH = REPO_ROOT / "data" / "full model export.xlsx"
EXPORT_KEY_WORKBOOK_SHEET = "Export"

# DEMAND_ROOT_PARTS imported from other_loss_own_use_proxy_utils

# Activity source mode:
# - "esto_ninth": first-run method. Activity uses ESTO base years and 9th
#   Edition projection years.
# - "leap_balance": second-run method. Activity uses a LEAP balance export
#   workbook, such as data/leap balances exports/20_USA/...xlsx.
PROXY_ACTIVITY_SOURCE_MODE = "esto_ninth"

# LEAP balance workbook controls used when PROXY_ACTIVITY_SOURCE_MODE is
# "leap_balance".
# - Set LEAP_BALANCE_WORKBOOK_PATH to a specific .xlsx path to use exactly
#   that file.
# - Leave it as None to auto-resolve from the selected economy,
#   LEAP_BALANCE_SCENARIO, and LEAP_BALANCE_DATE_ID.
LEAP_BALANCE_EXPORTS_ROOT = REPO_ROOT / "data" / "leap balances exports"

# Scenario/date filters for auto-resolving a LEAP balance workbook when the
# explicit workbook path is None. Scenario examples: "Target", "Reference".
# Date ID examples depend on export filenames; None means use the resolver's
# latest/best match.
LEAP_BALANCE_SCENARIO = "Target"
LEAP_BALANCE_DATE_ID = None
LEAP_BALANCE_WORKBOOK_PATH = None

# Output fuel scope:
# - "economy": normal input-data mode. Keep only fuels that are non-zero for
#   the selected economy in the final year of both ESTO validation snapshots.
# - "all_economies": model-structure mode. Keep fuels that are non-zero in at
#   least one economy in both ESTO validation snapshots.
OUTPUT_FUEL_VALIDATION_SCOPE = "economy"

# DEFAULT_MEASURE_UNITS, LEAP_BALANCE_FUEL_SETS, LEAP_BALANCE_ACTIVITY_FALLBACKS
# imported from other_loss_own_use_proxy_utils

def make_proxy_config(
    *,
    process_key: str,
    process_label: str,
    esto_target_flows: Sequence[str],
    ninth_target_sectors: Sequence[str],
    activity_label: str = "TODO: define proxy activity",
    enabled: bool = False,
    leap_process_label: str | None = None,
    esto_activity_flows: Sequence[str] | None = None,
    esto_activity_product_prefixes: Sequence[str] | None = None,
    esto_activity_exact_products: Sequence[str] | None = None,
    esto_activity_exclude_products: Sequence[str] | None = None,
    esto_target_exclude_products: Sequence[str] | None = None,
    ninth_activity_sectors: Sequence[str] | None = None,
    ninth_activity_fuels: Sequence[str] | None = None,
    ninth_activity_subfuels: Sequence[str] | None = None,
    ninth_activity_exclude_fuels: Sequence[str] | None = None,
    ninth_activity_exclude_subfuels: Sequence[str] | None = None,
    ninth_target_exclude_fuels: Sequence[str] | None = None,
    ninth_target_exclude_subfuels: Sequence[str] | None = None,
    leap_balance_rows: Sequence[str] | None = None,
    leap_balance_fuel_set: str = "",
    activity_value_mode: str = "signed_sum",
    notes: str = "",
) -> dict[str, object]:
    """Return one editable proxy config entry."""
    return {
        "enabled": bool(enabled),
        "process_key": process_key,
        "process_label": process_label,
        "leap_process_label": leap_process_label or process_label,
        "activity_label": activity_label,
        "activity_sources": {
            "esto": {
                "flows": list(esto_activity_flows or []),
                "product_prefixes": list(esto_activity_product_prefixes or []),
                "include_exact_products": list(esto_activity_exact_products or []),
                "exclude_products": list(esto_activity_exclude_products or []),
                "value_mode": activity_value_mode,
            },
            "ninth": {
                "sector_codes": list(ninth_activity_sectors or []),
                "fuels": list(ninth_activity_fuels or []),
                "subfuels": list(ninth_activity_subfuels or []),
                "exclude_fuels": list(ninth_activity_exclude_fuels or []),
                "exclude_subfuels": list(ninth_activity_exclude_subfuels or []),
                "value_mode": activity_value_mode,
            },
            "leap_balance": {
                "balance_rows": list(leap_balance_rows or []),
                "fuel_set": leap_balance_fuel_set,
                "value_mode": activity_value_mode,
            },
        },
        "target_sources": {
            "esto": {
                "flows": list(esto_target_flows),
                "exclude_products": list(esto_target_exclude_products or []),
            },
            "ninth": {
                "sector_codes": list(ninth_target_sectors),
                "exclude_fuels": list(ninth_target_exclude_fuels or []),
                "exclude_subfuels": list(ninth_target_exclude_subfuels or []),
            },
        },
        "notes": notes,
    }


# Extracted own-use/loss children from the 9th and ESTO source tables. Keep
# disabled scaffold entries in this list so proxies can be filled in one by one
# without changing the builder functions.
PROXY_CONFIG = [
    make_proxy_config(
        enabled=True,#coal mines own-use/losses cannot be easily handled by auxiliary branch in leap since they are a supply related flow rather than a transformation flow, so keeping enabled for now
        process_key="coal_mines",
        process_label="Coal mines",
        activity_label="Primary coal and coal-products production",
        esto_activity_flows=["01 Production"],
        esto_activity_product_prefixes=["01.", "02."],
        ninth_activity_sectors=["01_production"],
        ninth_activity_fuels=["01_coal", "02_coal_products"],
        ninth_activity_subfuels=[
            "01_01_coking_coal",
            "01_05_lignite",
            "01_coal_unallocated",
            "01_x_thermal_coal",
            "02_coal_products",
        ],
        leap_balance_rows=["Production"],
        leap_balance_fuel_set="coal_primary_and_products",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.06 Coal mines"],
        ninth_target_sectors=["10_01_06_coal_mines"],
        notes=(
            "Proxy activity is the sum of primary production of subfuels under "
            "01 Coal and 02 Coal products. Fuel intensity is abs(10.01.06 Coal "
            "mines own-use/loss fuel) divided by that activity."
        ),
    ),
    make_proxy_config(
        enabled=True,#cannot be easily handled by auxiliary branch in leap since it includes both electricity and heat output, so keeping enabled for now
        process_key="electricity_chp_and_heat_plants",
        process_label="Electricity, CHP and heat plants",
        activity_label="Electricity and heat output from electricity, CHP, and heat plants",
        esto_activity_flows=[
            "09.01.01 Electricity plants",
            "09.01.02 CHP plants",
            "09.01.03 Heat plants",
            "09.02.01 Electricity plants",
            "09.02.02 CHP plants",
            "09.02.03 Heat plants",
        ],
        esto_activity_exact_products=["17 Electricity", "18 Heat"],
        ninth_activity_sectors=[
            "09_01_electricity_plants",
            "09_02_chp_plants",
            "09_x_heat_plants",
        ],
        ninth_activity_fuels=["17_electricity", "18_heat"],
        ninth_activity_subfuels=["17_electricity", "18_heat"],
        leap_balance_rows=["Electricity Generation", "CHP plants", "Heat plants"],
        leap_balance_fuel_set="electricity_heat_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.01 Electricity, CHP and heat plants"],
        ninth_target_sectors=["10_01_01_electricity_chp_and_heat_plants"],
        notes="Starter proxy: total electricity plus heat output from main/autoproducer electricity, CHP, and heat plants.",
    ),
    make_proxy_config(
        enabled=False,#can be handled by auxiliary branch in leap so keeping disabled for now
        process_key="gas_works_plants",
        process_label="Gas works plants",
        activity_label="Gas works gas output",
        esto_activity_flows=["09.06.01 Gas works plants"],
        ninth_activity_sectors=["09_06_01_gas_works_plants"],
        leap_balance_rows=["Gas works plants"],
        leap_balance_fuel_set="gas_works_gas_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.02 Gas works plants"],
        ninth_target_sectors=["10_01_02_gas_works_plants"],
        notes="Starter proxy: positive gas works gas output. If a LEAP balance export has no Gas works gas column, LEAP-balance mode returns zero for this proxy instead of failing.",
    ),
    make_proxy_config(
        enabled=True,#cannot be easily handled by auxiliary branch in leap since it includes both liquefaction and regasification, so keeping enabled
        process_key="liquefaction_regasification_plants",
        process_label="Liquefaction/regasification plants",
        activity_label="Natural gas and LNG throughput/output",
        esto_activity_flows=["09.06.02 Liquefaction/regasification plants"],
        esto_activity_exact_products=["08.01 Natural gas", "08.02 LNG"],
        ninth_activity_sectors=["09_06_02_liquefaction_regasification_plants"],
        ninth_activity_fuels=["08_gas"],
        ninth_activity_subfuels=["08_01_natural_gas", "08_02_lng"],
        leap_balance_rows=["NG Liquefaction", "LNG regasification"],
        leap_balance_fuel_set="natural_gas_lng_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.03 Liquefaction/regasification plants"],
        ninth_target_sectors=["10_01_03_liquefaction_regasification_plants"],
        notes="Starter proxy: positive output of natural gas and LNG from liquefaction/regasification.",
    ),
    make_proxy_config(
        enabled=False,#can be handled by auxiliary branch in leap so keeping disabled for now
        process_key="gas_to_liquids_plants",
        process_label="Gas-to-liquids plants",
        activity_label="Gas-to-liquids petroleum-product output",
        esto_activity_flows=["09.06.04 Gas-to-liquids plants"],
        esto_activity_product_prefixes=["07."],
        ninth_activity_sectors=["09_06_04_gastoliquids_plants"],
        ninth_activity_fuels=["07_petroleum_products"],
        ninth_activity_subfuels=[
            "07_06_kerosene",
            "07_07_gas_diesel_oil",
            "07_09_lpg",
            "07_10_refinery_gas_not_liquefied",
            "07_x_other_petroleum_products",
        ],
        leap_balance_rows=["Gas to liquids plants"],
        leap_balance_fuel_set="gas_to_liquids_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.04 Gas-to-liquids plants"],
        ninth_target_sectors=["10_01_04_gastoliquids_plants"],
        notes="Starter proxy: positive petroleum-product output from gas-to-liquids plants.",
    ),
    make_proxy_config(
        enabled=False,#can be handled by auxiliary branch in leap so keeping disabled for now
        process_key="coke_ovens",
        process_label="Coke ovens",
        activity_label="Coke oven coal-product output",
        esto_activity_flows=["09.08.01 Coke ovens"],
        ninth_activity_sectors=["09_08_01_coke_ovens"],
        ninth_activity_subfuels=["02_01_coke_oven_coke", "02_03_coke_oven_gas", "02_07_coal_tar"],
        leap_balance_rows=["Coke ovens"],
        leap_balance_fuel_set="coke_oven_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.05 Coke ovens"],
        ninth_target_sectors=["10_01_05_coke_ovens"],
        notes="Starter proxy: positive coke oven coke, coke oven gas, and coal tar output. If this detailed 9th proxy is zero while ESTO activity exists, the workflow falls back to broader parent 9th activity.",
    ),
    make_proxy_config(
        enabled=False,#can be handled by auxiliary branch in leap so keeping disabled for now
        process_key="blast_furnaces",
        process_label="Blast furnaces",
        activity_label="Blast furnace gas output",
        esto_activity_flows=["09.08.02 Blast furnaces"],
        ninth_activity_sectors=["09_08_02_blast_furnaces"],
        ninth_activity_subfuels=["02_04_blast_furnace_gas"],
        leap_balance_rows=["Blast furnaces"],
        leap_balance_fuel_set="blast_furnace_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.07 Blast furnaces"],
        ninth_target_sectors=["10_01_07_blast_furnaces"],
        notes="Starter proxy: positive blast furnace gas output. If this detailed 9th proxy is zero while ESTO activity exists, the workflow falls back to broader parent 9th activity.",
    ),
    make_proxy_config(
        enabled=False,#can be handled by auxiliary branch in leap so keeping disabled for now
        process_key="patent_fuel_plants",
        process_label="Patent fuel plants",
        activity_label="Patent fuel output",
        esto_activity_flows=["09.08.03 Patent fuel plants"],
        ninth_activity_sectors=["09_08_03_patent_fuel_plants"],
        ninth_activity_subfuels=["02_06_patent_fuel"],
        leap_balance_rows=["Patent fuel plants"],
        leap_balance_fuel_set="patent_fuel_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.08 Patent fuel plants"],
        ninth_target_sectors=["10_01_08_patent_fuel_plants"],
        notes="Starter proxy: positive patent fuel output. If this detailed 9th proxy is zero while ESTO activity exists, the workflow falls back to broader parent 9th activity.",
    ),
    make_proxy_config(
        enabled=False,#can be handled by auxiliary branch in leap so keeping disabled for now, but enabling here to have the data in the export workbook for now since it is an esto own-use/loss flow in the 2024 dataset
        process_key="bkb_pb_plants",
        process_label="BKB/PB plants",
        activity_label="BKB/PB output",
        esto_activity_flows=["09.08.04 BKB/PB plants"],
        ninth_activity_sectors=["09_08_04_bkb_pb_plants"],
        ninth_activity_subfuels=["02_08_bkb_pb"],
        leap_balance_rows=["BKB and PB plants"],
        leap_balance_fuel_set="bkb_pb_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.09 BKB/PB plants"],
        ninth_target_sectors=["10_01_09_bkb_pb_plants"],
        notes="Starter proxy: positive BKB/PB output. If this detailed 9th proxy is zero while ESTO activity exists, the workflow falls back to broader parent 9th activity.",
    ),
    make_proxy_config(
        enabled=False,#can be handled by auxiliary branch in leap so keeping disabled for now
        process_key="liquefaction_plants_coal_to_oil",
        process_label="Liquefaction plants (Coal to Oil)",
        activity_label="Coal-to-oil petroleum-product output",
        esto_activity_flows=["09.08.05 Liquefaction (coal to oil)"],
        esto_activity_product_prefixes=["07."],
        ninth_activity_sectors=["09_08_05_liquefaction_coal_to_oil"],
        ninth_activity_fuels=["07_petroleum_products"],
        ninth_activity_subfuels=["07_09_lpg", "07_03_naphtha", "07_07_gas_diesel_oil", "07_08_fuel_oil", "07_x_other_petroleum_products"],
        leap_balance_rows=["Liquefaction coal to oil"],
        leap_balance_fuel_set="coal_to_oil_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.10 Liquefaction plants (Coal to Oil)"],
        ninth_target_sectors=["10_01_10_liquefaction_plants_coal_to_oil"],
        notes="Starter proxy: positive petroleum-product output from coal-to-oil liquefaction. If this detailed 9th proxy is zero while ESTO activity exists, the workflow falls back to broader parent 9th activity.",
    ),
    make_proxy_config(
        enabled=False,#Can be handled by auxiliary branch in leap so keeping disabled for now
        process_key="oil_refineries",
        process_label="Oil Refining",
        activity_label="Oil refinery petroleum-product output",
        esto_activity_flows=["09.07 Oil refineries"],
        esto_activity_product_prefixes=["07."],
        ninth_activity_sectors=["09_07_oil_refineries"],
        ninth_activity_fuels=["07_petroleum_products"],
        ninth_activity_subfuels=[
            "07_01_motor_gasoline",
            "07_02_aviation_gasoline",
            "07_03_naphtha",
            "07_06_kerosene",
            "07_07_gas_diesel_oil",
            "07_08_fuel_oil",
            "07_09_lpg",
            "07_10_refinery_gas_not_liquefied",
            "07_11_ethane",
            "07_16_petroleum_coke",
            "07_petroleum_products_unallocated",
            "07_x_jet_fuel",
            "07_x_other_petroleum_products",
        ],
        leap_balance_rows=["Oil Refining"],
        leap_balance_fuel_set="oil_refinery_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.11 Oil refineries"],
        ninth_target_sectors=["10_01_11_oil_refineries"],
        notes="Starter proxy: positive petroleum-product output from oil refineries.",
    ),
    make_proxy_config(
        enabled=True,#cannot be easily handled by auxiliary branch in leap since it includes both production and processing own-use/losses, so keeping enabled
        process_key="oil_and_gas_extraction",
        process_label="Oil and gas extraction",
        activity_label="Primary oil and gas production",
        esto_activity_flows=["01 Production"],
        esto_activity_exact_products=[
            "06.01 Crude oil",
            "06.02 Natural gas liquids",
            "06.05 Other hydrocarbons",
            "08.01 Natural gas",
            "08.02 LNG",
            "08.03 Gas works gas",
            "08.99 Gas nonspecified",
        ],
        ninth_activity_sectors=["01_production"],
        ninth_activity_fuels=["06_crude_oil_and_ngl", "08_gas"],
        ninth_activity_subfuels=[
            "06_01_crude_oil",
            "06_02_natural_gas_liquids",
            "06_crude_oil_and_ngl_unallocated",
            "06_x_other_hydrocarbons",
            "08_01_natural_gas",
            "08_02_lng",
            "08_03_gas_works_gas",
            "08_gas_unallocated",
        ],
        leap_balance_rows=["Production"],
        leap_balance_fuel_set="oil_and_gas_primary_production",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.12 Oil and gas extraction"],
        ninth_target_sectors=["10_01_12_oil_and_gas_extraction"],
        notes="Starter proxy: primary production of crude oil/NGL/other hydrocarbons and gas products.",
    ),
    make_proxy_config(
        enabled=True,#cannot be easily handled by auxiliary branch in leap since it includes both pumping and generation, so keeping enabled
        process_key="pump_storage_plants",
        process_label="Pump storage plants",
        activity_label="Pump storage electricity output",
        ninth_activity_sectors=["09_01_05_03_pump"],
        ninth_activity_fuels=["17_electricity"],
        ninth_activity_subfuels=["17_electricity"],
        leap_balance_rows=["Pumped hydro"],
        leap_balance_fuel_set="electricity_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.13 Pump storage plants"],
        ninth_target_sectors=["10_01_13_pump_storage_plants"],
        notes="Starter proxy: 9th pump-storage electricity output. ESTO and simple LEAP balance exports do not isolate pump storage, so LEAP balance mode falls back to total electricity production unless refined later.",
    ),
    make_proxy_config(
        enabled=True,#cannot be easily handled by auxiliary branch in leap since it includes both pumping and generation, so keeping enabled
        process_key="nuclear_industry",
        process_label="Nuclear industry",
        activity_label="Primary nuclear production",
        esto_activity_flows=["01 Production"],
        esto_activity_exact_products=["09 Nuclear"],
        ninth_activity_sectors=["01_production"],
        ninth_activity_fuels=["09_nuclear"],
        ninth_activity_subfuels=["09_nuclear"],
        leap_balance_rows=["Production"],
        leap_balance_fuel_set="nuclear_primary_production",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.14 Nuclear industry"],
        ninth_target_sectors=["10_01_14_nuclear_industry"],
        notes="Starter proxy: primary nuclear production.",
    ),
    make_proxy_config(
        enabled=False,#can be handled by auxiliary branch in leap so keeping disabled for now
        process_key="charcoal_production_plants",
        process_label="Charcoal production plants",
        activity_label="Charcoal output",
        esto_activity_flows=["09.11 Charcoal processing"],
        ninth_activity_sectors=["09_11_charcoal_processing"],
        leap_balance_rows=["Charcoal processing"],
        leap_balance_fuel_set="charcoal_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.15 Charcoal production plants"],
        ninth_target_sectors=["10_01_15_charcoal_production_plants"],
        notes="Starter proxy: positive charcoal output from charcoal processing.",
    ),
    make_proxy_config(
        enabled=True,#not a transformation module in LEAP, so cannot be handled by auxiliary branch. 
        process_key="gasification_plants_for_biogases",
        process_label="Gasification plants for biogases",
        activity_label="Biogas production",
        esto_activity_flows=["01 Production"],
        esto_activity_exact_products=["16.01 Biogas"],
        ninth_activity_sectors=["01_production"],
        ninth_activity_fuels=["16_others"],
        ninth_activity_subfuels=["16_01_biogas"],
        leap_balance_rows=["Production"],
        leap_balance_fuel_set="biogas_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.16 Gasification plants for biogases"],
        ninth_target_sectors=["10_01_16_gasification_plants_for_biogases"],
        notes="Starter proxy: biogas production. There is no direct ESTO 09 gasification activity row, so this uses primary biogas production.",
    ),
    make_proxy_config(
        enabled=False,#can be handled by auxiliary branch in leap so keeping disabled for now
        process_key="nonspecified_own_uses",
        process_label="Non-specified own uses",
        activity_label="Non-specified transformation positive output",
        esto_activity_flows=["09.12 Non-specified transformation"],
        ninth_activity_sectors=["09_12_nonspecified_transformation"],
        leap_balance_rows=["Non specified transformation"],
        leap_balance_fuel_set="nonspecified_transformation_output",
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.17 Non-specified own uses"],
        ninth_target_sectors=["10_01_17_nonspecified_own_uses"],
        notes="Starter proxy: positive output from non-specified transformation. Fuel set is based on nonzero ESTO/9th activity fuels across all economies.",
    ),
    make_proxy_config(
        enabled=True,#besides electricity own-use/losses, transmission and distribution losses for other fuels cannot be easily isolated in LEAP balances or auxiliary branches, so keeping enabled for now
        process_key="transmission_and_distribution_losses",
        process_label="Transmission and distribution losses",
        leap_process_label="Transmission and distribution loss",
        activity_label="Total production excluding electricity",
        esto_activity_flows=["01 Production"],
        esto_activity_exclude_products=["17 Electricity"],
        ninth_activity_sectors=["01_production"],
        ninth_activity_exclude_fuels=["17_electricity"],
        ninth_activity_exclude_subfuels=["17_electricity"],
        leap_balance_rows=["Production"],
        leap_balance_fuel_set="production_ex_electricity",
        activity_value_mode="positive_only",
        esto_target_flows=["10.02 Transmission and distribution losses"],
        esto_target_exclude_products=["17 Electricity"],
        ninth_target_sectors=["10_02_transmission_and_distribution_losses"],
        ninth_target_exclude_fuels=["17_electricity"],
        ninth_target_exclude_subfuels=["17_electricity"],
        notes="Starter proxy: total positive production excluding electricity, so LEAP-balance activity is not driven by produced electricity.",
    ),
    make_proxy_config(
        enabled=False,#CCS own-use/losses are not clearly isolated in either ESTO or 9th, so keeping disabled for now
        process_key="ccs",
        process_label="CCS",
        esto_target_flows=[],
        ninth_target_sectors=["10_01_18_ccs"],
        notes="9th has 10_01_18_ccs, but ESTO 00APEC_2024_low.csv has no matching 10.01.18 flow.",
    ),
]


def load_esto_data(path: Path | str = ESTO_DATA_PATH) -> pd.DataFrame:
    df = pd.read_csv(_resolve(path), low_memory=False)
    df = _normalize_year_columns(df)
    df["economy_key"] = df["economy"].apply(_normalize_economy)
    try:
        labeled = apply_matt_subtotal_mapping(df, _resolve(ESTO_SUBTOTAL_MAPPING_PATH))
        df = filter_matt_subtotals(labeled)
    except Exception as exc:
        print(f"[WARN] ESTO subtotal filtering skipped: {exc}")
    total_products = {"19 Total", "20 Total Renewables", "21 Modern renewables"}
    if "products" in df.columns:
        df = df[~df["products"].astype(str).isin(total_products)].copy()
    return df


def load_ninth_data(path: Path | str = NINTH_DATA_PATH) -> pd.DataFrame:
    df = pd.read_csv(_resolve(path), low_memory=False)
    df = _normalize_year_columns(df)
    if "economy" in df.columns:
        df["economy_key"] = df["economy"].apply(_normalize_economy)
    if "scenarios" in df.columns:
        df = df[df["scenarios"].astype(str).str.lower() == NINTH_SCENARIO].copy()
    return _drop_ninth_subtotals(df)


def load_output_fuel_validation_esto_tables(
    paths: Sequence[Path | str] = OUTPUT_FUEL_VALIDATION_ESTO_PATHS,
) -> list[tuple[str, pd.DataFrame]]:
    """Load ESTO snapshot tables used to validate output branch fuel coverage."""
    tables: list[tuple[str, pd.DataFrame]] = []
    for path_value in paths:
        path = _resolve(path_value)
        df = pd.read_csv(path, low_memory=False)
        df = _normalize_year_columns(df)
        tables.append((path.name, df))
    return tables


def load_fuel_mapping_lookup(mapping_path: Path | str = LEAP_MAPPINGS_PATH) -> dict[str, dict[str, str]]:
    """Load ESTO/9th fuel -> LEAP fuel lookups from config/leap_mappings.xlsx."""
    path = _resolve(mapping_path)
    lookups = {"esto": {}, "ninth": {}}
    if not path.exists():
        return lookups
    try:
        esto = pd.read_excel(path, sheet_name="fuel_product_final_proposed", dtype=str).fillna("")
    except Exception:
        esto = pd.DataFrame()
    for _, row in esto.iterrows():
        source = str(row.get("esto_product", "") or "").strip()
        leap = str(row.get("leap_fuel_name", "") or "").strip()
        if source and leap:
            lookups["esto"][_normalize_source_token(source)] = sanitize_leap_name(leap)
    try:
        ninth = pd.read_excel(path, sheet_name="fuel_ninth_final_proposed", dtype=str).fillna("")
    except Exception:
        ninth = pd.DataFrame()
    for _, row in ninth.iterrows():
        source = str(row.get("ninth_fuel", "") or "").strip()
        leap = str(row.get("leap_fuel_name", "") or "").strip()
        if source and leap:
            lookups["ninth"][_normalize_source_token(source)] = sanitize_leap_name(leap)
    return lookups


def resolve_leap_balance_workbook_path(
    *,
    economy: str,
    scenario: str = LEAP_BALANCE_SCENARIO,
    date_id: str | None = LEAP_BALANCE_DATE_ID,
    workbook_path: Path | str | None = LEAP_BALANCE_WORKBOOK_PATH,
) -> Path:
    """Resolve the LEAP balance workbook used for second-run proxy activity."""
    if workbook_path:
        return _resolve(workbook_path)
    return resolve_balance_export_workbook(
        economy=_normalize_economy(economy),
        scenario=scenario,
        date_id=date_id,
        exports_root=_resolve(LEAP_BALANCE_EXPORTS_ROOT),
    )


def build_proxy_detail_table(
    *,
    esto_data: pd.DataFrame,
    ninth_data: pd.DataFrame,
    economy: str,
    configs: Sequence[Mapping[str, object]],
    leap_balance_activity: pd.DataFrame | None = None,
    activity_source_mode: str = PROXY_ACTIVITY_SOURCE_MODE,
    base_year: int = EXPORT_BASE_YEAR,
    final_year: int = EXPORT_FINAL_YEAR,
) -> pd.DataFrame:
    detail_frames = []
    fuel_mapping_lookup = load_fuel_mapping_lookup()
    for config in configs:
        if not bool(config.get("enabled", True)):
            continue
        activity = build_activity_series_for_mode(
            esto_data=esto_data,
            ninth_data=ninth_data,
            leap_balance_activity=leap_balance_activity,
            economy=economy,
            config=config,
            base_year=base_year,
            final_year=final_year,
            activity_source_mode=activity_source_mode,
        )
        target = build_target_energy_long(
            esto_data=esto_data,
            ninth_data=ninth_data,
            economy=economy,
            config=config,
            base_year=base_year,
            final_year=final_year,
            fuel_mapping_lookup=fuel_mapping_lookup,
        )
        if target.empty:
            continue
        target["proxy_activity"] = target["year"].map(activity).fillna(0.0)
        target["intensity"] = target.apply(
            lambda row: 0.0 if float(row["proxy_activity"]) == 0.0 else float(row["target_energy"]) / float(row["proxy_activity"]),
            axis=1,
        )
        target["activity_label"] = str(config.get("activity_label", ""))
        target["activity_source_mode"] = str(activity_source_mode)
        target["notes"] = str(config.get("notes", ""))
        detail_frames.append(target)
    if not detail_frames:
        return pd.DataFrame(
            columns=[
                "source_dataset",
                "economy",
                "process_key",
                "process_label",
                "leap_process_label",
                "fuel_label",
                "fuel_branch_label",
                "year",
                "proxy_activity",
                "target_energy",
                "target_energy_signed",
                "intensity",
                "activity_label",
                "activity_source_mode",
                "notes",
            ]
        )
    out = pd.concat(detail_frames, ignore_index=True)
    ordered = [
        "source_dataset",
        "economy",
        "process_key",
        "process_label",
        "leap_process_label",
        "fuel_label",
        "fuel_branch_label",
        "year",
        "proxy_activity",
        "target_energy",
        "target_energy_signed",
        "intensity",
        "activity_label",
        "activity_source_mode",
        "notes",
    ]
    return out[ordered].sort_values(["process_label", "fuel_branch_label", "year"], kind="mergesort")


def build_output_fuel_esto_validation(
    *,
    esto_data: pd.DataFrame,
    detail_df: pd.DataFrame,
    configs: Sequence[Mapping[str, object]],
    economy: str | None = None,
    base_year: int = EXPORT_BASE_YEAR,
    fuel_mapping_lookup: Mapping[str, Mapping[str, str]] | None = None,
    validation_esto_tables: Sequence[tuple[str, pd.DataFrame]] | None = None,
    output_fuel_scope: str = "all_economies",
) -> pd.DataFrame:
    """Check each output fuel branch is non-zero in each ESTO validation snapshot."""
    mapping_lookup = fuel_mapping_lookup or load_fuel_mapping_lookup()
    validation_tables = list(validation_esto_tables or [("esto_data", esto_data)])
    scope = _normalize_output_fuel_scope(output_fuel_scope)
    economy_key = _normalize_economy(economy) if economy else ""
    compact_economy = economy_key.replace("_", "")
    rows: list[dict[str, object]] = []
    if detail_df.empty:
        return pd.DataFrame(
            columns=[
                "process_key",
                "process_label",
                "fuel_branch_label",
                "target_esto_flows",
                "validation_files_checked",
                "validation_years_checked",
                "matched_validation_products",
                "missing_validation_files",
                "output_fuel_scope",
                "validation_economy",
                "status",
            ]
        )
    validation_products_by_flow: dict[str, dict[str, dict[str, object]]] = {}
    for table_name, table in validation_tables:
        year_cols = _year_columns(table)
        final_year = max(year_cols) if year_cols else None
        if final_year is None or table.empty:
            continue
        source = table.copy()
        if scope == "economy":
            if not economy_key:
                raise ValueError("economy is required when output_fuel_scope='economy'.")
            if "economy_key" in source.columns:
                source = source[source["economy_key"].apply(_normalize_economy).eq(economy_key)].copy()
            elif "economy" in source.columns:
                source = source[
                    source["economy"].astype(str).str.upper().isin({economy_key, compact_economy})
                    | source["economy"].apply(_normalize_economy).eq(economy_key)
                ].copy()
        if "is_subtotal" in source.columns:
            subtotal_text = source["is_subtotal"].fillna(False).astype(str).str.strip().str.lower()
            source = source[~subtotal_text.isin({"true", "1", "yes"})].copy()
        values = pd.to_numeric(source[final_year], errors="coerce").fillna(0.0).abs()
        source = source[values > 0.0].copy()
        for flow, flow_group in source.groupby("flows", dropna=False):
            flow_text = str(flow)
            flow_map = validation_products_by_flow.setdefault(flow_text, {})
            for product in flow_group["products"].dropna().unique():
                branch_label = _format_fuel_branch_label(
                    product,
                    source_name="esto",
                    fuel_mapping_lookup=mapping_lookup,
                )
                fuel_key = _normalize_balance_label(branch_label)
                if not fuel_key:
                    continue
                item = flow_map.setdefault(fuel_key, {"products_by_file": {}, "years_by_file": {}})
                item["products_by_file"].setdefault(table_name, set()).add(str(product))
                item["years_by_file"][table_name] = int(final_year)

    for config in configs:
        if not bool(config.get("enabled", True)):
            continue
        process_key = str(config.get("process_key", ""))
        process_label = str(config.get("process_label", ""))
        target_flows = list(config.get("target_sources", {}).get("esto", {}).get("flows", []))
        output_fuels = sorted(
            {
                str(value).strip()
                for value in detail_df.loc[
                    detail_df["process_key"].astype(str).eq(process_key),
                    "fuel_branch_label",
                ].dropna()
                if str(value).strip()
            }
        )
        if not output_fuels:
            continue

        for fuel_label in output_fuels:
            fuel_key = _normalize_balance_label(fuel_label)
            products_by_file: dict[str, set[str]] = {}
            years_by_file: dict[str, int] = {}
            for flow in target_flows:
                match_info = validation_products_by_flow.get(str(flow), {}).get(fuel_key, {})
                for file_name, products in match_info.get("products_by_file", {}).items():
                    products_by_file.setdefault(file_name, set()).update(products)
                for file_name, year in match_info.get("years_by_file", {}).items():
                    years_by_file[file_name] = int(year)
            expected_files = [name for name, _ in validation_tables]
            missing_files = [file_name for file_name in expected_files if not products_by_file.get(file_name)]
            matched_parts = [
                f"{file_name}: {', '.join(sorted(products))}"
                for file_name, products in sorted(products_by_file.items())
            ]
            year_parts = [
                f"{file_name}: {years_by_file[file_name]}"
                for file_name in expected_files
                if file_name in years_by_file
            ]
            rows.append(
                {
                    "process_key": process_key,
                    "process_label": process_label,
                    "fuel_branch_label": fuel_label,
                    "target_esto_flows": "; ".join(str(flow) for flow in target_flows),
                    "validation_files_checked": "; ".join(expected_files),
                    "validation_years_checked": "; ".join(year_parts),
                    "matched_validation_products": " | ".join(matched_parts),
                    "missing_validation_files": "; ".join(missing_files),
                    "output_fuel_scope": scope,
                    "validation_economy": economy_key if scope == "economy" else "all_economies",
                    "status": "matched_all_validation_files" if not missing_files else "missing_from_validation_file",
                }
            )
    columns = [
        "process_key",
        "process_label",
        "fuel_branch_label",
        "target_esto_flows",
        "validation_files_checked",
        "validation_years_checked",
        "matched_validation_products",
        "missing_validation_files",
        "output_fuel_scope",
        "validation_economy",
        "status",
    ]
    return pd.DataFrame(rows, columns=columns).sort_values(["process_label", "fuel_branch_label"], kind="mergesort")


def _normalize_scenarios(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return list(EXPORT_SCENARIOS)
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _normalize_output_fuel_scope(value: str | None) -> str:
    text = str(value or "economy").strip().lower()
    if text in {"economy", "selected_economy", "individual_economy", "current_economy"}:
        return "economy"
    if text in {"all", "all_economies", "global", "model_structure", "structure"}:
        return "all_economies"
    raise ValueError(
        f"Invalid output_fuel_scope={value!r}. Use 'economy' for economy-specific data "
        "or 'all_economies' for model-structure branch scaffolding."
    )


def _resolve_export_filename(economy: str, scenarios: Sequence[str], export_filename: str | None) -> str:
    template = export_filename or EXPORT_FILENAME_TEMPLATE
    return workflow_common.build_workflow_export_filename(
        economy,
        scenarios,
        template,
        workflow_common.format_filename_segment,
        fallback_template="other_loss_own_use_proxy.xlsx",
    )


def assemble_proxy_workbook(
    *,
    economy: str = "20_USA",
    scenarios: str | Sequence[str] | None = None,
    import_scenario: str | Sequence[str] | None = None,
    region: str | None = None,
    export_filename: str | None = None,
    include_leap_import: bool = False,
    configs: Sequence[Mapping[str, object]] = PROXY_CONFIG,
    activity_source_mode: str = PROXY_ACTIVITY_SOURCE_MODE,
    leap_balance_workbook_path: Path | str | None = LEAP_BALANCE_WORKBOOK_PATH,
    leap_balance_scenario: str = LEAP_BALANCE_SCENARIO,
    leap_balance_date_id: str | None = LEAP_BALANCE_DATE_ID,
    output_fuel_scope: str = OUTPUT_FUEL_VALIDATION_SCOPE,
    export_key_workbook_path: Path | str = EXPORT_KEY_WORKBOOK_PATH,
    export_key_sheet: str = EXPORT_KEY_WORKBOOK_SHEET,
    measure_units: Mapping[str, Mapping[str, object]] | None = None,
) -> Path:
    scenario_list = _normalize_scenarios(scenarios)
    output_scope = _normalize_output_fuel_scope(output_fuel_scope)
    region = region or EXPORT_REGION
    esto_data = load_esto_data()
    ninth_data = load_ninth_data()
    leap_balance_activity = pd.DataFrame()
    if str(activity_source_mode or "").strip().lower() in {"second", "second_run", "leap", "leap_balance", "leap_outputs"}:
        balance_path = resolve_leap_balance_workbook_path(
            economy=economy,
            scenario=leap_balance_scenario,
            date_id=leap_balance_date_id,
            workbook_path=leap_balance_workbook_path,
        )
        requested_rows: set[str] = set()
        requested_fuels: set[str] = set()
        for config in configs:
            if not bool(config.get("enabled", True)):
                continue
            leap_cfg = config.get("activity_sources", {}).get("leap_balance", {})
            requested_rows.update(str(row) for row in leap_cfg.get("balance_rows", []) if str(row).strip())
            fuel_set_name = str(leap_cfg.get("fuel_set", "")).strip()
            requested_fuels.update(LEAP_BALANCE_FUEL_SETS.get(fuel_set_name, []))
        leap_balance_activity = load_leap_balance_activity_table(
            balance_path,
            balance_rows=sorted(requested_rows),
            fuels=sorted(requested_fuels),
        )
    detail_df = build_proxy_detail_table(
        esto_data=esto_data,
        ninth_data=ninth_data,
        economy=economy,
        configs=configs,
        leap_balance_activity=leap_balance_activity,
        activity_source_mode=activity_source_mode,
        base_year=EXPORT_BASE_YEAR,
        final_year=EXPORT_FINAL_YEAR,
    )
    if detail_df.empty:
        raise ValueError("No proxy detail rows were generated; check config and source data.")

    output_dir = _resolve(OUTPUT_ROOT) / _normalize_economy(economy)
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / "proxy_activity_intensity_detail.csv"
    summary_path = output_dir / "proxy_activity_summary.csv"
    leap_activity_path = output_dir / "leap_balance_activity_source.csv"
    fuel_set_verification_path = output_dir / "proxy_fuel_set_verification.csv"
    output_fuel_validation_path = output_dir / "proxy_output_fuel_esto_validation.csv"
    output_fuel_candidate_validation_path = output_dir / "proxy_output_fuel_esto_validation_all_candidates.csv"
    activity_source_warnings_path = output_dir / "proxy_activity_source_warnings.csv"
    activity_source_fallback_path = output_dir / "proxy_activity_source_fallbacks.csv"
    if not leap_balance_activity.empty:
        leap_balance_activity.to_csv(leap_activity_path, index=False)
    fuel_mapping_lookup = load_fuel_mapping_lookup()
    validation_esto_tables = load_output_fuel_validation_esto_tables()
    output_fuel_candidate_validation = build_output_fuel_esto_validation(
        esto_data=esto_data,
        detail_df=detail_df,
        configs=configs,
        economy=economy,
        base_year=EXPORT_BASE_YEAR,
        fuel_mapping_lookup=fuel_mapping_lookup,
        validation_esto_tables=validation_esto_tables,
        output_fuel_scope=output_scope,
    )
    output_fuel_candidate_validation.to_csv(output_fuel_candidate_validation_path, index=False)
    detail_df = filter_detail_to_validated_output_fuels(detail_df, output_fuel_candidate_validation)
    if detail_df.empty:
        raise ValueError(
            "No proxy detail rows remained after output fuel validation. "
            f"See {output_fuel_candidate_validation_path}."
        )
    detail_df.to_csv(detail_path, index=False)
    output_fuel_validation = build_output_fuel_esto_validation(
        esto_data=esto_data,
        detail_df=detail_df,
        configs=configs,
        economy=economy,
        base_year=EXPORT_BASE_YEAR,
        fuel_mapping_lookup=fuel_mapping_lookup,
        validation_esto_tables=validation_esto_tables,
        output_fuel_scope=output_scope,
    )
    output_fuel_validation.to_csv(output_fuel_validation_path, index=False)
    invalid_output_fuels = output_fuel_validation[
        output_fuel_validation["status"].eq("missing_from_validation_file")
    ]
    if not invalid_output_fuels.empty:
        preview = invalid_output_fuels[
            ["process_key", "fuel_branch_label", "missing_validation_files"]
        ].head(20).to_dict("records")
        raise ValueError(
            "Output contains fuel branches that are not non-zero in every ESTO validation snapshot for the matching target flow. "
            f"See {output_fuel_validation_path}. First rows: {preview}"
        )
    activity_source_warnings = pd.DataFrame()
    activity_source_fallbacks = pd.DataFrame()
    if _normalize_activity_source_mode(activity_source_mode) == "esto_ninth":
        activity_source_fallbacks = build_activity_source_fallback_report(
            esto_data=esto_data,
            ninth_data=ninth_data,
            economy=economy,
            configs=configs,
            base_year=EXPORT_BASE_YEAR,
            final_year=EXPORT_FINAL_YEAR,
        )
        activity_source_warnings = build_activity_source_gap_warnings(
            esto_data=esto_data,
            ninth_data=ninth_data,
            economy=economy,
            configs=configs,
            base_year=EXPORT_BASE_YEAR,
            final_year=EXPORT_FINAL_YEAR,
        )
    _write_csv_with_locked_file_fallback(activity_source_fallbacks, activity_source_fallback_path)
    if not activity_source_fallbacks.empty:
        print(
            "\n[INFO] Used broader 9th parent-sector activity for other loss/own-use proxy gaps."
        )
        print(
            f"[INFO] Activity source fallbacks: {len(activity_source_fallbacks)} "
            f"(details saved to {activity_source_fallback_path})"
        )
        for _, row in activity_source_fallbacks.head(20).iterrows():
            print(
                "  - {process}: '{original}' -> '{fallback}'".format(
                    process=str(row.get("process_label") or "").strip(),
                    original=str(row.get("original_ninth_activity_sectors") or "").strip(),
                    fallback=str(row.get("fallback_ninth_activity_sectors") or "").strip(),
                )
            )
        if len(activity_source_fallbacks) > 20:
            print(f"  ... plus {len(activity_source_fallbacks) - 20} more activity source fallback(s)")
    _write_csv_with_locked_file_fallback(activity_source_warnings, activity_source_warnings_path)
    if not activity_source_warnings.empty:
        print(
            "\n[WARN] Found other loss/own-use proxy activity gaps where ESTO activity "
            "is non-zero but all 9th projection activity is zero."
        )
        print(
            f"[WARN] Activity source warnings: {len(activity_source_warnings)} "
            f"(details saved to {activity_source_warnings_path})"
        )
        for _, row in activity_source_warnings.head(20).iterrows():
            print(
                "  - {process}: ESTO total={esto_total:.3f}; 9th sectors='{sectors}'".format(
                    process=str(row.get("process_label") or "").strip(),
                    esto_total=float(row.get("esto_activity_total") or 0.0),
                    sectors=str(row.get("ninth_activity_sectors") or "").strip(),
                )
            )
        if len(activity_source_warnings) > 20:
            print(f"  ... plus {len(activity_source_warnings) - 20} more activity source warning(s)")
    fuel_set_verification = build_proxy_fuel_set_verification(
        esto_data=esto_data,
        ninth_data=ninth_data,
        configs=configs,
        fuel_mapping_lookup=fuel_mapping_lookup,
    )
    _write_csv_with_locked_file_fallback(fuel_set_verification, fuel_set_verification_path)
    (
        detail_df.groupby(["process_key", "process_label", "year"], as_index=False)["proxy_activity"]
        .max()
        .to_csv(summary_path, index=False)
    )

    base_rows = build_proxy_log_rows(
        detail_df,
        scenario=scenario_list[0],
        measure_units=measure_units,
    )
    rows = []
    for scenario_name in scenario_list:
        for row in base_rows:
            copied = row.copy()
            copied["Scenario"] = scenario_name
            rows.append(copied)
    log_df = pd.DataFrame(rows)
    import_scenarios = workflow_common.resolve_import_scenarios(scenario_list, import_scenario)
    scenario_to_import = import_scenarios[0]
    export_df = finalise_export_df(
        log_df,
        scenario=scenario_to_import,
        region=region,
        base_year=EXPORT_BASE_YEAR,
        final_year=EXPORT_FINAL_YEAR,
    )
    if export_df is None or export_df.empty:
        raise ValueError("Export dataframe is empty.")
    expression_df = build_expression_export_df(export_df, base_year=EXPORT_BASE_YEAR)
    output_path = Path(_resolve_export_filename(_normalize_economy(economy), scenario_list, export_filename))
    save_export_files(
        leap_export_df=expression_df,
        export_df_for_viewing=export_df,
        leap_export_filename=output_path,
        base_year=EXPORT_BASE_YEAR,
        final_year=EXPORT_FINAL_YEAR,
        model_name=EXPORT_MODEL_NAME,
    )
    add_export_id_sheet(
        output_path,
        expression_df,
        export_key_workbook_path=export_key_workbook_path,
        export_key_sheet=export_key_sheet,
        output_sheet_name="LEAP_WITH_IDS",
        model_name=EXPORT_MODEL_NAME,
        include_zero_rows_for_unset_values=True,
        base_year=EXPORT_BASE_YEAR,
        final_year=EXPORT_FINAL_YEAR,

    )

    if include_leap_import:
        dispatch_result = dispatch_analysis_input_write(
            export_path=output_path,
            sheet_name="LEAP",
            scenario=scenario_to_import,
            region=region,
            context_label="other_loss_own_use_proxy.include_leap_import",
        )
        if dispatch_result.get("mode") != "workbook":
            if not is_leap_api_available():
                print("[INFO] LEAP API unavailable; skipping LEAP import.")
                return output_path
            from codebase.functions.leap_core import connect_to_leap

            L = connect_to_leap()
            fuel_catalog_preflight.run_fuel_catalog_preflight(
                export_path=output_path,
                sheet_name="LEAP",
                scenario=scenario_to_import,
                context="other_loss_own_use_proxy.include_leap_import",
                leap_app=L,
            )
            create_branches_from_export_file(
                L,
                output_path,
                sheet_name="LEAP",
                scenario=None,
                region=region,
                default_branch_type=None,
                RAISE_ERROR_ON_FAILED_BRANCH_CREATION=True,
            )
            for index, scenario_name in enumerate(import_scenarios):
                fill_branches_from_export_file(
                    L,
                    output_path,
                    sheet_name="LEAP",
                    scenario=scenario_name,
                    region=region,
                    RAISE_ERROR_ON_FAILED_SET=True,
                    HANDLE_CURRENT_ACCOUNTS_TOO=index == 0,
                    RUN_FUEL_CATALOG_PREFLIGHT=False,
                )
    return output_path


#%%
# Notebook-focused settings.
NOTEBOOK_ECONOMY = "20_USA"
NOTEBOOK_SCENARIOS = EXPORT_SCENARIOS
NOTEBOOK_IMPORT_SCENARIOS = [
    scenario.lower()
    for scenario in NOTEBOOK_SCENARIOS
    if scenario.lower() not in {"current accounts", "current account"}
]
NOTEBOOK_INCLUDE_LEAP_IMPORT = False
NOTEBOOK_ACTIVITY_SOURCE_MODE = PROXY_ACTIVITY_SOURCE_MODE
NOTEBOOK_LEAP_BALANCE_WORKBOOK_PATH = LEAP_BALANCE_WORKBOOK_PATH
NOTEBOOK_LEAP_BALANCE_SCENARIO = LEAP_BALANCE_SCENARIO
NOTEBOOK_LEAP_BALANCE_DATE_ID = LEAP_BALANCE_DATE_ID
NOTEBOOK_OUTPUT_FUEL_SCOPE = OUTPUT_FUEL_VALIDATION_SCOPE


def run_with_notebook_config() -> Path:
    return assemble_proxy_workbook(
        economy=NOTEBOOK_ECONOMY,
        scenarios=NOTEBOOK_SCENARIOS,
        import_scenario=NOTEBOOK_IMPORT_SCENARIOS,
        include_leap_import=NOTEBOOK_INCLUDE_LEAP_IMPORT,
        activity_source_mode=NOTEBOOK_ACTIVITY_SOURCE_MODE,
        leap_balance_workbook_path=NOTEBOOK_LEAP_BALANCE_WORKBOOK_PATH,
        leap_balance_scenario=NOTEBOOK_LEAP_BALANCE_SCENARIO,
        leap_balance_date_id=NOTEBOOK_LEAP_BALANCE_DATE_ID,
        output_fuel_scope=NOTEBOOK_OUTPUT_FUEL_SCOPE,
    )


if __name__ == "__main__":
    run_with_notebook_config()
#%%


try:
    from codebase.utilities.workflow_common import emit_completion_beep as _emit_completion_beep
except Exception:  # pragma: no cover
    def _emit_completion_beep(*, success: bool = True) -> None:  # noqa: ARG001
        return


if __name__ == "__main__":  # pragma: no cover
    _emit_completion_beep(success=True, style="chime")
#%%
