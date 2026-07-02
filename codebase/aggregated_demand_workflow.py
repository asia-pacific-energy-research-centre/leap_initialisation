#%%
"""
Build aggregated demand by LEAP fuel from ESTO base year and ninth projection data.

Combines demand from all relevant sectors into a single branch per fuel:
  Demand\\All demand aggregated\\{fuel_name}

Base year (2022): ESTO sectors including own-use, T&D losses, and main demand.
Projection years (2023+): ninth dataset filtered to subtotal_results=False and
specific sector/sub1/sub2 hierarchy.

All values are converted to positive (abs). Electricity is excluded from
Transmission & Distribution losses rows.

Standalone use:
    python -m codebase.aggregated_demand_workflow

Integration: import build_aggregated_demand() or build_aggregated_demand_as_dummy()
and pass results to supply_reconciliation_workflow.py when USE_AGGREGATED_DEMAND_AS_DUMMY
is enabled.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
try:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
except Exception as exc:
    print(f"Failed to add repo root to sys.path: {exc}")

from codebase.configuration import workflow_config as workflow_cfg
from codebase.functions.unified_name_lookup import load_active_mapping_sheet
from codebase.utilities.output_paths import STANDALONE_LEAP_EXPORTS_ROOT
from codebase.utilities.master_config import OUTLOOK_MAPPINGS_MASTER_PATH

# ── Data sources ──────────────────────────────────────────────────────────────
DATA_DIR = REPO_ROOT / "data"
CONFIG_DIR = REPO_ROOT / "config"
ENERGY_SOURCE_CONFIG = workflow_cfg.get_energy_source_config()
ESTO_BASE_DATA_PATH = ENERGY_SOURCE_CONFIG.esto_base_table_path
PROJECTION_DATA_PATH = ENERGY_SOURCE_CONFIG.ninth_projection_table_path
FUEL_MAPPINGS_PATH = OUTLOOK_MAPPINGS_MASTER_PATH
FUEL_ESTO_SHEET = "leap_combined_esto"
FUEL_NINTH_SHEET = "leap_combined_ninth"

# ── Year settings ─────────────────────────────────────────────────────────────
BASE_YEAR = ENERGY_SOURCE_CONFIG.esto_base_year
PROJECTION_START_YEAR = ENERGY_SOURCE_CONFIG.projection_start_year
PROJECTION_END_YEAR = 2060
if ENERGY_SOURCE_CONFIG.projection_final_year is not None:
    PROJECTION_END_YEAR = int(ENERGY_SOURCE_CONFIG.projection_final_year)

# ── LEAP branch / export settings ─────────────────────────────────────────────
DEMAND_BRANCH_ROOT = r"Demand\All demand aggregated"
VARIABLE_NAME = "Total Energy"
UNITS = "Petajoule"

# ── Intensity / activity mode ─────────────────────────────────────────────────
# When True, branches are written as Activity Level (=1) + Final Energy Intensity
# instead of a single Total Energy row.  LEAP computes total energy = intensity × activity,
# so with activity=1 the intensity value equals total energy.
USE_INTENSITY_ACTIVITY_MODE = True
INTENSITY_VARIABLE_NAME = "Final Energy Intensity"
ACTIVITY_VARIABLE_NAME = "Activity Level"
ACTIVITY_UNITS = "Unspecified Unit"
LEAP_SCENARIOS = ["Current Accounts", "Reference", "Target"]

# ── Sector-branch mode ────────────────────────────────────────────────────────
# When True, branches are written as Demand\All demand aggregated\{SectorLabel}\{fuel_name}
# instead of the flat Demand\All demand aggregated\{fuel_name}.
# Disabled by default; enable when LEAP has per-sector sub-branches set up.
USE_SECTOR_BRANCHES = False
# Maps LEAP scenario names to the 'scenarios' column values in the merged CSV
SCENARIO_CSV_MAP: dict[str, str] = {
    "Current Accounts": "reference",
    "Reference": "reference",
    "Target": "target",
}
DEFAULT_EXPORT_FILENAME_TEMPLATE = "aggregated_demand_{economy}_{scenario}.xlsx"
DEFAULT_EXPORT_REGION = getattr(workflow_cfg, "GLOBAL_REGION", "United States")

# Economy codes that mean "aggregate all member economies rather than filtering"
_AGGREGATE_ECONOMY_SENTINELS: frozenset[str] = frozenset({
    "00_apec", "00apec", "all_economies", "all",
})
# ── ESTO base-year demand sector filters ──────────────────────────────────────
# Own-use sub2sectors to include from 10_01_own_use
ESTO_OWN_USE_SUB2: frozenset[str] = frozenset({
    "10_01_01_electricity_chp_and_heat_plants",
    "10_01_03_liquefaction_regasification_plants",
    "10_01_06_coal_mines",
    "10_01_11_oil_refineries",
    "10_01_12_oil_and_gas_extraction",
    "10_01_13_pump_storage_plants",
})
# Demand sectors with no sub-sector restriction for base year
ESTO_OTHER_DEMAND_SECTORS: frozenset[str] = frozenset({
    "04_international_marine_bunkers",
    "05_international_aviation_bunkers",
    "14_industry_sector",
    "15_transport_sector",
    "16_other_sector",
    "17_nonenergy_use",
})

# ── Ninth projection demand sector filters ────────────────────────────────────
# All three levels must be satisfied simultaneously (not one at a time)
NINTH_SECTORS: frozenset[str] = frozenset({
    "10_losses_and_own_use",
    "14_industry_sector",
    "16_other_sector",
    "17_nonenergy_use",
    "15_transport_sector",
    "04_international_marine_bunkers",
    "05_international_aviation_bunkers",
})
NINTH_SUB1_SECTORS: frozenset[str] = frozenset({
    "x",
    "10_01_own_use",
    "10_02_transmission_and_distribution_losses",
    "14_01_mining_and_quarrying",
    "14_02_construction",
    "14_03_manufacturing",
    "16_01_buildings",
    "15_03_rail",
    "15_04_domestic_navigation",
    "16_02_agriculture_and_fishing",
    "16_05_nonspecified_others",
    "15_01_domestic_air_transport",
    "15_02_road",
    "15_05_pipeline_transport",
    "15_06_nonspecified_transport",
})
NINTH_SUB2_SECTORS: frozenset[str] = frozenset({
    "x",
    "10_01_01_electricity_chp_and_heat_plants",
    "10_01_03_liquefaction_regasification_plants",
    "10_01_11_oil_refineries",
    "10_01_12_oil_and_gas_extraction",
    "10_01_13_pump_storage_plants",
    "14_03_01_iron_and_steel",
    "14_03_02_chemical_incl_petrochemical",
    "14_03_03_non_ferrous_metals",
    "14_03_04_nonmetallic_mineral_products",
    "14_03_05_transportation_equipment",
    "14_03_06_machinery",
    "14_03_07_food_beverages_and_tobacco",
    "14_03_08_pulp_paper_and_printing",
    "14_03_09_wood_and_wood_products",
    "14_03_10_textiles_and_leather",
    "14_03_11_nonspecified_industry",
    "16_01_01_commercial_and_public_services",
    "16_01_02_residential",
    "16_01_03_ai_training",
    "16_01_04_traditional_data_centres",
    "16_02_03_agriculture",
    "16_02_04_fishing",
    "15_01_01_passenger",
    "15_01_02_freight",
    "15_02_01_passenger",
    "15_02_02_freight",
    "15_03_01_passenger",
    "15_03_02_freight",
    "15_04_01_passenger",
    "15_04_02_freight",
})

# Fuel to exclude from T&D losses (10_02)
TD_LOSSES_SUB1 = "10_02_transmission_and_distribution_losses"
TD_LOSSES_EXCLUDE_FUEL = "17_electricity"

# ── Demand zeroing mode ───────────────────────────────────────────────────────
# Variables that must NOT be zeroed because they are share/ratio variables that
# must remain coherent across sibling branches (LEAP enforces that shares sum to
# 100 and will error if they don't).
DEMAND_SHARE_VARIABLES: frozenset[str] = frozenset({
    "Device Share",
    "Sales Share",
    "Stock Share",
})

# Branch path prefix for the aggregated demand branches written by this workflow.
# These are excluded from zeroing so the aggregated demand values are preserved.
DEMAND_AGGREGATED_BRANCH_PREFIX = "Demand\\All demand aggregated"

# Branch path prefix for the Other loss and own use proxy branches.
# When the proxy workflow is running in the same pass these should neither be
# zeroed (they're being set by the proxy) nor included in the aggregated demand
# total (to avoid double-counting with the proxy output).
DEMAND_OTHER_LOSS_OWN_USE_BRANCH_PREFIX = "Demand\\Other loss and own use"

# ESTO sectors whose flows go to Demand\Other loss and own use in LEAP.
# When exclude_own_use_td_losses=True these are dropped from the aggregated sum.
OWN_USE_SECTORS: frozenset[str] = frozenset({"10_01_own_use"})
TD_LOSSES_SECTORS: frozenset[str] = frozenset({"10_02_transmission_and_distribution_losses"})

# Default source for zeroing: the full model export in data/
FULL_MODEL_EXPORT_PATH = DATA_DIR / "full model export.xlsx"
FULL_MODEL_EXPORT_SHEET = "Export"


# ── Helpers ───────────────────────────────────────────────────────────────────

_SECTOR_LEAP_LABELS: dict[str, str] = {
    "04_international_marine_bunkers":              "International Marine Bunkers",
    "05_international_aviation_bunkers":            "International Aviation Bunkers",
    "10_01_own_use":                               "Own Use",
    "10_02_transmission_and_distribution_losses":  "Transmission and Distribution Losses",
    "10_losses_and_own_use":                       "Losses and Own Use",
    "14_industry_sector":                          "Industry",
    "15_transport_sector":                         "Transport",
    "16_other_sector":                             "Other Sector",
    "17_nonenergy_use":                            "Non-Energy Use",
}

_SECTOR_SHORT_CODES: dict[str, str] = {
    # top-level sectors
    "04_international_marine_bunkers":          "MB",
    "05_international_aviation_bunkers":        "AB",
    "10_losses_and_own_use":                    "LOU",
    "14_industry_sector":                       "IND",
    "15_transport_sector":                      "TR",
    "16_other_sector":                          "OTH",
    "17_nonenergy_use":                         "NEU",
    # sub1sectors
    "10_01_own_use":                            "OU",
    "10_02_transmission_and_distribution_losses": "TD",
    "14_01_mining_and_quarrying":               "MQ",
    "14_02_construction":                       "CON",
    "14_03_manufacturing":                      "MFG",
    "15_01_domestic_air_transport":             "AIR",
    "15_02_road":                               "RD",
    "15_03_rail":                               "RL",
    "15_04_domestic_navigation":                "NAV",
    "15_05_pipeline_transport":                 "PP",
    "15_06_nonspecified_transport":             "NTR",
    "16_01_buildings":                          "BD",
    "16_02_agriculture_and_fishing":            "AG",
    "16_05_nonspecified_others":                "NSO",
}


def _sector_exclusion_suffix(excluded_sectors: list[str] | None) -> str:
    """
    Build a filename suffix using short codes for excluded sectors.

    Examples
    --------
    ["14_industry_sector"]                       → "_no_IND"
    ["14_industry_sector", "16_01_buildings"]    → "_no_BD_IND"
    ["15_transport_sector"]                      → "_no_TR"
    """
    if not excluded_sectors:
        return ""
    parts = []
    for code in sorted(excluded_sectors):
        short = _SECTOR_SHORT_CODES.get(code)
        if not short:
            # Fallback: strip leading digits/underscores, drop "_sector", uppercase
            short = re.sub(r"^[\d_]+", "", code).replace("_sector", "").replace("_", "").upper()[:6]
        if short:
            parts.append(short)
    # Sort so the suffix is deterministic regardless of input order
    return ("_no_" + "_".join(sorted(parts))) if parts else ""


def resolve_active_branch_excluded_sectors(
    active_branches: list[str] | None,
    sector_map: dict[str, list[str]],
    base_excluded: list[str] | None = None,
) -> list[str] | None:
    """
    Compute the effective excluded_sectors list by merging manually specified
    exclusions with ESTO sectors implied by active detailed demand branches.

    Subtraction values come from 9th Outlook / ESTO source data — not from
    detailed LEAP branch result values.  This means the aggregated placeholder
    is always reduced by the source-data amount for the given sector, regardless
    of how the detailed LEAP branch evolves in future years.

    Deduplication: if both 'Freight road' and 'Passenger road' are active,
    15_02_road is added only once because both map to the same ESTO sector.

    Parameters
    ----------
    active_branches:
        LEAP demand group names whose detailed branches have been inserted into
        LEAP.  Matched against sector_map keys.  None or [] means no active
        branches — only base_excluded (if any) is returned.
    sector_map:
        Maps LEAP demand group names → lists of ESTO sector/sub1sector codes.
        Use LEAP_DEMAND_GROUP_ESTO_SECTOR_MAP from supply_reconciliation_config.
    base_excluded:
        Manually configured exclusion codes (e.g. AGGREGATED_DEMAND_EXCLUDED_SECTORS).
        These are always included regardless of active_branches.

    Returns
    -------
    list[str] | None
        Combined, deduplicated exclusion list in insertion order, or None when
        the result is empty (so callers can test truthiness directly).
    """
    seen: set[str] = set()
    effective: list[str] = []
    for code in (base_excluded or []):
        if code not in seen:
            seen.add(code)
            effective.append(code)
    for branch in (active_branches or []):
        if branch not in sector_map:
            import warnings
            warnings.warn(
                f"resolve_active_branch_excluded_sectors: '{branch}' not found in "
                f"sector_map — no ESTO sectors excluded for this group.",
                UserWarning,
                stacklevel=2,
            )
        for code in sector_map.get(branch, []):
            if code not in seen:
                seen.add(code)
                effective.append(code)
    return effective if effective else None


def load_fuel_mapping(
    path: Path = FUEL_MAPPINGS_PATH,
    sheet: str = FUEL_NINTH_SHEET,
) -> dict[str, str]:
    """Return source fuel/product -> LEAP fuel mapping from active canonical rows."""
    df = load_active_mapping_sheet(sheet, Path(path))
    if sheet == FUEL_ESTO_SHEET:
        source_col = "esto_product"
    elif sheet == FUEL_NINTH_SHEET:
        source_col = "ninth_fuel"
    else:
        # Compatibility for older direct calls to fuel_ninth_final_proposed.
        raw = pd.read_excel(path, sheet_name=sheet).fillna("")
        raw["ninth_fuel"] = raw["ninth_fuel"].astype(str).str.strip()
        raw["leap_fuel_name"] = raw["leap_fuel_name"].astype(str).str.strip()
        raw = raw[raw["leap_fuel_name"].str.lower().ne("nan")]
        raw = raw.drop_duplicates(subset=["ninth_fuel"], keep="first")
        return dict(zip(raw["ninth_fuel"], raw["leap_fuel_name"]))
    required = [source_col, "raw_leap_fuel_name"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise KeyError(f"{sheet} is missing required columns for aggregated demand: {missing}")
    work = df[required].copy()
    for col in required:
        work[col] = work[col].fillna("").astype(str).str.strip()
    work = work[work[source_col].ne("") & work["raw_leap_fuel_name"].ne("")]
    work = work.drop_duplicates(subset=[source_col], keep="first")
    return dict(zip(work[source_col], work["raw_leap_fuel_name"]))


def _normalize_esto_economy(value: object) -> str:
    """Normalize compact ESTO economy codes such as 20USA to 20_USA or 02BD to 02_BD."""
    text = str(value or "").strip()
    if re.fullmatch(r"\d{2}[A-Za-z]{2,3}", text):
        return f"{text[:2]}_{text[2:].upper()}"
    return text


def _resolve_fuel_code(fuels: pd.Series, subfuels: pd.Series) -> pd.Series:
    """Use the deepest non-'x' fuel code: subfuel if set, otherwise parent fuel."""
    sub = subfuels.astype(str).str.strip()
    parent = fuels.astype(str).str.strip()
    use_sub = sub.str.lower().ne("x") & sub.ne("") & sub.ne("nan")
    return sub.where(use_sub, parent)




def _is_aggregate_economy(economy: str | None) -> bool:
    return not economy or str(economy).strip().lower() in _AGGREGATE_ECONOMY_SENTINELS


def _esto_flow_is_excluded(flow: object, excluded_codes: set[str]) -> bool:
    """Return True if an ESTO flow is covered by a normalized exclusion code."""
    text = str(flow or "").strip()
    if not text or not excluded_codes:
        return False
    prefix_map = {
        "04_international_marine_bunkers": "04",
        "05_international_aviation_bunkers": "05",
        "10_losses_and_own_use": "10",
        "10_01_own_use": "10.01",
        "10_02_transmission_and_distribution_losses": "10.02",
        "14_industry_sector": "14",
        "14_01_mining_and_quarrying": "14.01",
        "14_02_construction": "14.02",
        "14_03_manufacturing": "14.03",
        "15_transport_sector": "15",
        "15_01_domestic_air_transport": "15.01",
        "15_02_road": "15.02",
        "15_03_rail": "15.03",
        "15_04_domestic_navigation": "15.04",
        "15_05_pipeline_transport": "15.05",
        "15_06_nonspecified_transport": "15.06",
        "16_other_sector": "16",
        "16_01_buildings": "16.01",
        "16_02_agriculture_and_fishing": "16.02",
        "16_05_nonspecified_others": "16.05",
        "17_nonenergy_use": "17",
    }
    for code in excluded_codes:
        prefix = prefix_map.get(code, code.replace("_", "."))
        if prefix and text.startswith(prefix):
            return True
    return False


def _esto_flow_to_sector(flow: str) -> str:
    """Map an ESTO flow code (dot-notation prefix) to a top-level sector key."""
    if flow.startswith("04"):    return "04_international_marine_bunkers"
    if flow.startswith("05"):    return "05_international_aviation_bunkers"
    if flow.startswith("10.01"): return "10_01_own_use"
    if flow.startswith("10.02"): return "10_02_transmission_and_distribution_losses"
    if flow.startswith("14"):    return "14_industry_sector"
    if flow.startswith("15"):    return "15_transport_sector"
    if flow.startswith("16"):    return "16_other_sector"
    if flow.startswith("17"):    return "17_nonenergy_use"
    return "other"


def _load_demand_csv(
    path: Path = PROJECTION_DATA_PATH,
    economy: str | None = None,
    final_year: int = PROJECTION_END_YEAR,
) -> pd.DataFrame:
    """Load the merged energy CSV, keeping only columns needed for demand extraction.

    When economy is an aggregate sentinel (00_APEC, ALL_ECONOMIES, etc.) all
    member economies are loaded and summed later by the caller.
    """
    stable_cols = [
        "economy", "scenarios", "sectors", "sub1sectors", "sub2sectors",
        "fuels", "subfuels", "subtotal_results",
    ]
    year_cols = [str(y) for y in range(BASE_YEAR, final_year + 1)]
    header = pd.read_csv(path, nrows=0)
    use_cols = [c for c in [*stable_cols, *year_cols] if c in header.columns]
    df = pd.read_csv(path, usecols=use_cols, low_memory=False)
    for col in ["economy", "scenarios", "sectors", "sub1sectors", "sub2sectors", "fuels", "subfuels"]:
        df[col] = df[col].astype(str).str.strip()
    df["subtotal_results"] = (
        df["subtotal_results"].astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    )
    if economy and not _is_aggregate_economy(economy):
        economy_key = str(economy).strip()
        df = df[df["economy"] == economy_key].copy()
        if df.empty:
            raise ValueError(
                f"Economy {economy_key!r} not found in {path.name}. "
                f"Use an aggregate sentinel (e.g. '00_APEC') to sum all economies, "
                f"or check the economy code."
            )
    return df


def _load_esto_base_csv(
    path: Path = ESTO_BASE_DATA_PATH,
    economy: str | None = None,
    base_year: int = BASE_YEAR,
) -> pd.DataFrame:
    """Load configured ESTO flow/product table for base-year demand extraction."""
    stable_cols = ["economy", "flows", "products", "is_subtotal"]
    year_cols = [str(base_year)]
    header = pd.read_csv(path, nrows=0)
    use_cols = [c for c in [*stable_cols, *year_cols] if c in header.columns]
    df = pd.read_csv(path, usecols=use_cols, low_memory=False)
    for col in ["economy", "flows", "products"]:
        df[col] = df[col].astype(str).str.strip()
    df["economy"] = df["economy"].map(_normalize_esto_economy)
    if "is_subtotal" not in df.columns:
        df["is_subtotal"] = False
    df["is_subtotal"] = (
        df["is_subtotal"].astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    )
    if economy and not _is_aggregate_economy(economy):
        economy_key = str(economy).strip()
        df = df[df["economy"] == economy_key].copy()
        if df.empty:
            raise ValueError(f"Economy {economy_key!r} not found in {path.name}.")
    return df


# ── Core extraction ───────────────────────────────────────────────────────────

def _extract_base_year(
    df: pd.DataFrame,
    base_year: int = BASE_YEAR,
    exclude_own_use_td_losses: bool = False,
    excluded_sectors: list[str] | None = None,
    use_sector_branches: bool = False,
) -> pd.DataFrame:
    """
    Filter configured ESTO base-year demand rows. Returns long DataFrame:
    columns: economy, fuel_code, year, value.

    ESTO flow families included:
      - 10.01 own use subflows
      - 10.02 T&D losses, excluding electricity
      - 04, 05, 14, 15, 16, 17 demand flows

    When exclude_own_use_td_losses=True, the own-use and T&D losses rows are
    omitted so they are not double-counted with the other_loss_own_use proxy.
    """
    not_subtotal = ~df["is_subtotal"]
    flows = df["flows"].astype(str).str.strip()
    products = df["products"].astype(str).str.strip()

    own_use_mask = flows.str.startswith("10.01")
    td_mask = flows.str.startswith("10.02")
    other_mask = flows.str.startswith(("04", "05", "14", "15", "16", "17"))

    if exclude_own_use_td_losses:
        combined_mask = not_subtotal & other_mask
    else:
        combined_mask = not_subtotal & (own_use_mask | td_mask | other_mask)

    filtered = df[combined_mask].copy()

    # Remove electricity from T&D losses (only relevant when not excluding)
    if not exclude_own_use_td_losses:
        td_elec = filtered["flows"].astype(str).str.startswith("10.02") & filtered["products"].astype(str).str.startswith("17")
        filtered = filtered[~td_elec].copy()

    # Drop any explicitly excluded sector or sub1sector codes
    if excluded_sectors:
        excluded = {str(item).strip() for item in excluded_sectors if str(item).strip()}
        filtered = filtered[
            ~filtered["flows"].map(lambda flow: _esto_flow_is_excluded(flow, excluded))
        ].copy()

    base_col = str(base_year)
    if base_col not in filtered.columns:
        raise KeyError(f"Base year column '{base_year}' not found in ESTO data.")

    filtered["fuel_code"] = products.loc[filtered.index]
    filtered["year"] = int(base_year)
    filtered["value"] = pd.to_numeric(filtered[base_col], errors="coerce").abs().fillna(0.0)

    if use_sector_branches:
        filtered["sector"] = filtered["flows"].apply(_esto_flow_to_sector)
        return filtered[["economy", "sector", "fuel_code", "year", "value"]].copy()
    return filtered[["economy", "fuel_code", "year", "value"]].copy()


def _extract_projection_years(
    df: pd.DataFrame,
    csv_scenario: str,
    final_year: int = PROJECTION_END_YEAR,
    exclude_own_use_td_losses: bool = False,
    excluded_sectors: list[str] | None = None,
    use_sector_branches: bool = False,
) -> pd.DataFrame:
    """
    Filter to ninth projection rows (>=2023, subtotal_results=False).
    Applies sector + sub1sector + sub2sector filter simultaneously.
    Returns long DataFrame: economy, fuel_code, year, value.

    When exclude_own_use_td_losses=True, rows with sub1sector in OWN_USE_SECTORS
    or TD_LOSSES_SECTORS are omitted.
    """
    mask = (
        ~df["subtotal_results"] &
        df["sectors"].isin(NINTH_SECTORS) &
        df["sub1sectors"].isin(NINTH_SUB1_SECTORS) &
        df["sub2sectors"].isin(NINTH_SUB2_SECTORS) &
        (df["scenarios"] == csv_scenario)
    )
    if exclude_own_use_td_losses:
        mask = mask & ~df["sub1sectors"].isin(OWN_USE_SECTORS | TD_LOSSES_SECTORS)
    if excluded_sectors:
        excl = set(excluded_sectors)
        mask = mask & ~(df["sectors"].isin(excl) | df["sub1sectors"].isin(excl))
    filtered = df[mask].copy()

    # Remove electricity from T&D losses (only relevant when not excluding)
    if not exclude_own_use_td_losses:
        td_elec = (filtered["sub1sectors"] == TD_LOSSES_SUB1) & (filtered["fuels"] == TD_LOSSES_EXCLUDE_FUEL)
        filtered = filtered[~td_elec].copy()

    year_cols = [
        str(y) for y in range(PROJECTION_START_YEAR, final_year + 1)
        if str(y) in filtered.columns
    ]
    if not year_cols:
        return pd.DataFrame(columns=["economy", "fuel_code", "year", "value"])

    filtered["fuel_code"] = _resolve_fuel_code(filtered["fuels"], filtered["subfuels"])
    if use_sector_branches:
        filtered = filtered.copy()
        filtered["sector"] = filtered["sectors"]
        id_vars = ["economy", "sector", "fuel_code"]
        select_cols = ["economy", "sector", "fuel_code", *year_cols]
    else:
        id_vars = ["economy", "fuel_code"]
        select_cols = ["economy", "fuel_code", *year_cols]
    long = filtered[select_cols].melt(
        id_vars=id_vars,
        value_vars=year_cols,
        var_name="year",
        value_name="value",
    )
    long["year"] = pd.to_numeric(long["year"], errors="coerce").astype("Int64")
    long["value"] = pd.to_numeric(long["value"], errors="coerce").abs().fillna(0.0)
    out_cols = (["economy", "sector", "fuel_code", "year", "value"] if use_sector_branches
                else ["economy", "fuel_code", "year", "value"])
    return long[out_cols].copy()


# ── Public API ─────────────────────────────────────────────────────────────────

def build_aggregated_demand(
    economy: str,
    scenario: str = "Reference",
    base_year: int = BASE_YEAR,
    final_year: int = PROJECTION_END_YEAR,
    data_path: Path = PROJECTION_DATA_PATH,
    esto_data_path: Path = ESTO_BASE_DATA_PATH,
    fuel_mappings_path: Path = FUEL_MAPPINGS_PATH,
    exclude_own_use_td_losses: bool = False,
    excluded_sectors: list[str] | None = None,
    use_sector_branches: bool = False,
) -> pd.DataFrame:
    """
    Build aggregated demand by LEAP fuel for one economy and scenario.

    Returns DataFrame with columns:
        economy, scenario, leap_fuel_name, year, value  (value in PJ, positive)
    When use_sector_branches=True, also includes a 'sector' column with the
    top-level demand sector key (e.g. '14_industry_sector').

    ESTO base-year products and ninth projection fuels not found in the active
    canonical mapping sheets are dropped with a warning.

    When exclude_own_use_td_losses=True, own-use (10_01) and T&D losses (10_02)
    sectors are excluded from the sum — use this when the other_loss_own_use proxy
    is running in the same pass to avoid double-counting those amounts.

    excluded_sectors is a list of ninth sector/subsector codes to omit from the
    aggregation entirely (e.g. ["14_industry_sector"] or ["16_01_buildings"]).
    Matching ESTO flow prefixes are omitted from the base-year extraction.
    """
    esto_fuel_map = load_fuel_mapping(fuel_mappings_path, FUEL_ESTO_SHEET)
    ninth_fuel_map = load_fuel_mapping(fuel_mappings_path, FUEL_NINTH_SHEET)
    esto_df = _load_esto_base_csv(esto_data_path, economy=economy, base_year=base_year)
    ninth_df = _load_demand_csv(data_path, economy=economy, final_year=final_year)

    # For aggregate sentinels, collapse all member economies into one label
    economy_label = str(economy).strip()
    if _is_aggregate_economy(economy):
        esto_df = esto_df.copy()
        ninth_df = ninth_df.copy()
        esto_df["economy"] = economy_label
        ninth_df["economy"] = economy_label

    group_cols = ["economy", "sector", "fuel_code", "year"] if use_sector_branches else ["economy", "fuel_code", "year"]

    base_rows = _extract_base_year(
        esto_df,
        base_year=base_year,
        exclude_own_use_td_losses=exclude_own_use_td_losses,
        excluded_sectors=excluded_sectors,
        use_sector_branches=use_sector_branches,
    )
    base_agg = base_rows.groupby(group_cols, as_index=False)["value"].sum(min_count=1)
    base_agg["value"] = base_agg["value"].fillna(0.0)

    if scenario == "Current Accounts":
        combined = base_agg.copy()
    else:
        csv_scen = SCENARIO_CSV_MAP.get(scenario, "reference").lower()
        proj_rows = _extract_projection_years(
            ninth_df,
            csv_scenario=csv_scen,
            final_year=final_year,
            exclude_own_use_td_losses=exclude_own_use_td_losses,
            excluded_sectors=excluded_sectors,
            use_sector_branches=use_sector_branches,
        )
        proj_agg = proj_rows.groupby(group_cols, as_index=False)["value"].sum(min_count=1)
        proj_agg["value"] = proj_agg["value"].fillna(0.0)
        combined = pd.concat([base_agg, proj_agg], ignore_index=True)

    combined["year"] = combined["year"].astype(int)
    combined = combined[(combined["year"] >= base_year) & (combined["year"] <= final_year)].copy()

    # Map fuel codes → LEAP fuel names
    combined["leap_fuel_name"] = combined["fuel_code"].map(ninth_fuel_map)
    base_mask = combined["year"].eq(int(base_year))
    combined.loc[base_mask, "leap_fuel_name"] = combined.loc[base_mask, "fuel_code"].map(esto_fuel_map)
    unmapped = combined.loc[combined["leap_fuel_name"].isna(), "fuel_code"].unique()
    if len(unmapped):
        print(
            f"[WARN] {len(unmapped)} fuel/product codes have no active canonical mapping,"
            f" dropped: {sorted(unmapped)[:15]}"
        )
    combined = combined[combined["leap_fuel_name"].notna()].copy()

    # Aggregate many-to-one fuel mappings
    agg_cols = (["economy", "sector", "leap_fuel_name", "year"] if use_sector_branches
                else ["economy", "leap_fuel_name", "year"])
    result = combined.groupby(agg_cols, as_index=False)["value"].sum(min_count=1)
    result["value"] = result["value"].fillna(0.0)
    result["scenario"] = scenario

    out_cols = (["economy", "scenario", "sector", "leap_fuel_name", "year", "value"]
                if use_sector_branches
                else ["economy", "scenario", "leap_fuel_name", "year", "value"])
    return (
        result[out_cols]
        .sort_values(out_cols[:-1])
        .reset_index(drop=True)
    )


def build_aggregated_demand_all_scenarios(
    economy: str,
    scenarios: list[str] = LEAP_SCENARIOS,
    base_year: int = BASE_YEAR,
    final_year: int = PROJECTION_END_YEAR,
    data_path: Path = PROJECTION_DATA_PATH,
    esto_data_path: Path = ESTO_BASE_DATA_PATH,
    fuel_mappings_path: Path = FUEL_MAPPINGS_PATH,
    exclude_own_use_td_losses: bool = False,
    excluded_sectors: list[str] | None = None,
    use_sector_branches: bool = False,
) -> pd.DataFrame:
    """Build aggregated demand for all LEAP scenarios and return combined DataFrame."""
    parts = [
        build_aggregated_demand(
            economy=economy,
            scenario=s,
            base_year=base_year,
            final_year=final_year,
            data_path=data_path,
            esto_data_path=esto_data_path,
            fuel_mappings_path=fuel_mappings_path,
            exclude_own_use_td_losses=exclude_own_use_td_losses,
            excluded_sectors=excluded_sectors,
            use_sector_branches=use_sector_branches,
        )
        for s in scenarios
    ]
    return pd.concat(parts, ignore_index=True)


def build_aggregated_demand_as_dummy(
    economy: str,
    scenarios: list[str] | None = None,
    base_year: int = BASE_YEAR,
    final_year: int = PROJECTION_END_YEAR,
    data_path: Path = PROJECTION_DATA_PATH,
    esto_data_path: Path = ESTO_BASE_DATA_PATH,
    fuel_mappings_path: Path = FUEL_MAPPINGS_PATH,
    exclude_own_use_td_losses: bool = False,
    excluded_sectors: list[str] | None = None,
    use_sector_branches: bool = False,
) -> pd.DataFrame:
    """
    Return aggregated demand data in the format expected by load_results_demand_table
    in supply_reconciliation_workflow.py for use as dummy demand.

    Returns DataFrame with columns:
        economy, scenario, esto_product, year, demand_value, demand_source

    The output is always fuel-level totals (no sector column) because the
    reconciliation needs total demand per product regardless of whether the LEAP
    workbook uses sector-split branches.  use_sector_branches is forwarded to
    build_aggregated_demand_all_scenarios() so that excluded_sectors are applied
    consistently with how the LEAP workbook is generated.
    exclude_own_use_td_losses is forwarded as well so the internal dummy-demand
    table stays aligned with the LEAP workbook when own-use and T&D losses are
    being handled by the separate proxy workflow.

    Fuel names are mapped back to esto_product codes via fuel_product_final_proposed.
    Rows where no esto_product mapping exists are dropped.
    """
    use_scenarios = scenarios if scenarios is not None else LEAP_SCENARIOS
    long = build_aggregated_demand_all_scenarios(
        economy=economy,
        scenarios=use_scenarios,
        base_year=base_year,
        final_year=final_year,
        data_path=data_path,
        esto_data_path=esto_data_path,
        fuel_mappings_path=fuel_mappings_path,
        exclude_own_use_td_losses=exclude_own_use_td_losses,
        excluded_sectors=excluded_sectors,
        use_sector_branches=use_sector_branches,
    )
    if long.empty:
        return pd.DataFrame(
            columns=["economy", "scenario", "esto_product", "year", "demand_value", "demand_source"]
        )

    # Load reverse mapping: leap_fuel_name → esto_product from active canonical rows.
    fuel_prod = load_active_mapping_sheet(FUEL_ESTO_SHEET, Path(fuel_mappings_path))
    fuel_prod["leap_fuel_name"] = fuel_prod["raw_leap_fuel_name"].astype(str).str.strip()
    fuel_prod["esto_product"] = fuel_prod["esto_product"].astype(str).str.strip()
    # When multiple esto_products map to one leap_fuel_name, keep first (many-to-one is OK here)
    prod_map = (
        fuel_prod.drop_duplicates(subset=["leap_fuel_name"], keep="first")
        .set_index("leap_fuel_name")["esto_product"]
        .to_dict()
    )

    long["esto_product"] = long["leap_fuel_name"].map(prod_map)
    unmapped = long.loc[long["esto_product"].isna(), "leap_fuel_name"].unique()
    if len(unmapped):
        print(
            f"[WARN] {len(unmapped)} LEAP fuel names have no esto_product mapping, dropped:"
            f" {sorted(unmapped)[:10]}"
        )
    long = long[long["esto_product"].notna()].copy()

    result = long.groupby(
        ["economy", "scenario", "esto_product", "year"], as_index=False
    )["value"].sum(min_count=1)
    result["value"] = result["value"].fillna(0.0)
    result["demand_source"] = "aggregated_demand_projection"

    return (
        result.rename(columns={"value": "demand_value"})
        [["economy", "scenario", "esto_product", "year", "demand_value", "demand_source"]]
        .reset_index(drop=True)
    )


# ── Aggregated demand LEAP workbook ──────────────────────────────────────────

def _build_id_lookups(
    id_lookup_path: Path | str,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Return (branch_to_id, variable_to_id, scenario_to_id) dicts from a LEAP full export."""
    raw = pd.read_excel(Path(id_lookup_path), header=2)
    branch_to_id = (
        raw[["Branch Path", "BranchID"]].dropna(subset=["Branch Path"])
        .drop_duplicates(subset=["Branch Path"])
        .set_index("Branch Path")["BranchID"]
        .apply(lambda x: int(x) if pd.notna(x) else -1)
        .to_dict()
    )
    variable_to_id = (
        raw[["Variable", "VariableID"]].dropna(subset=["Variable"])
        .drop_duplicates(subset=["Variable"])
        .set_index("Variable")["VariableID"]
        .apply(lambda x: int(x) if pd.notna(x) else -1)
        .to_dict()
    )
    scenario_to_id = (
        raw[["Scenario", "ScenarioID"]].dropna(subset=["Scenario"])
        .drop_duplicates(subset=["Scenario"])
        .set_index("Scenario")["ScenarioID"]
        .apply(lambda x: int(x) if pd.notna(x) else -1)
        .to_dict()
    )
    return branch_to_id, variable_to_id, scenario_to_id


def save_aggregated_demand_as_leap_workbook(
    economy: str,
    output_path: Path,
    scenarios: list[str] | None = None,
    region: str = DEFAULT_EXPORT_REGION,
    base_year: int = BASE_YEAR,
    final_year: int = PROJECTION_END_YEAR,
    data_path: Path = PROJECTION_DATA_PATH,
    esto_data_path: Path = ESTO_BASE_DATA_PATH,
    fuel_mappings_path: Path = FUEL_MAPPINGS_PATH,
    model_name: str = "",
    exclude_own_use_td_losses: bool = False,
    id_lookup_path: Path | str | None = None,
    excluded_sectors: list[str] | None = None,
    use_sector_branches: bool = False,
) -> Path | None:
    """
    Build aggregated demand and save as a LEAP-importable workbook (LEAP + FOR_VIEWING sheets).

    Writes Demand\\All demand aggregated\\{fuel_name} rows with Variable=Total Energy
    and Expression as a scalar (Current Accounts) or Data(...) series (other scenarios).
    Returns the output path, or None if there was nothing to write.

    When exclude_own_use_td_losses=True, own-use and T&D losses sectors are excluded
    from the demand sum so the aggregated total does not double-count amounts that the
    other_loss_own_use proxy handles separately in Demand\\Other loss and own use.

    When id_lookup_path is provided, BranchID/VariableID/ScenarioID columns are merged
    from that file (a LEAP full export with header=2). RegionID is always set to 1.
    """
    use_scenarios = scenarios if scenarios is not None else list(LEAP_SCENARIOS)
    demand = build_aggregated_demand_all_scenarios(
        economy=economy,
        scenarios=use_scenarios,
        base_year=base_year,
        final_year=final_year,
        data_path=data_path,
        esto_data_path=esto_data_path,
        fuel_mappings_path=fuel_mappings_path,
        exclude_own_use_td_losses=exclude_own_use_td_losses,
        excluded_sectors=excluded_sectors,
        use_sector_branches=use_sector_branches,
    )
    if demand.empty:
        print("[INFO] save_aggregated_demand_as_leap_workbook: no demand data — workbook not written.")
        return None

    has_sector = use_sector_branches and "sector" in demand.columns
    group_keys = (["sector", "leap_fuel_name", "scenario"] if has_sector
                  else ["leap_fuel_name", "scenario"])

    rows = []
    for group_key, grp in demand.groupby(group_keys, sort=True):
        if has_sector:
            sector_key, fuel_name, scenario = group_key
            sector_label = _SECTOR_LEAP_LABELS.get(sector_key, sector_key)
            branch = f"{DEMAND_BRANCH_ROOT}\\{sector_label}\\{fuel_name}"
        else:
            fuel_name, scenario = group_key
            branch = f"{DEMAND_BRANCH_ROOT}\\{fuel_name}"
        grp = grp.sort_values("year")
        year_val = list(zip(grp["year"].astype(int), grp["value"].astype(float)))
        if scenario == "Current Accounts":
            base_vals = [(yr, v) for yr, v in year_val if yr == base_year]
            expr = f"{base_vals[0][1]:.6g}" if base_vals else "0"
        else:
            tokens: list[str] = []
            for yr, val in year_val:
                tokens.append(str(yr))
                tokens.append(f"{val:.6g}")
            expr = "Data(" + ", ".join(tokens) + ")"
        if USE_INTENSITY_ACTIVITY_MODE:
            rows.append({
                "Branch Path": branch,
                "Variable": ACTIVITY_VARIABLE_NAME,
                "Scenario": scenario,
                "Region": region,
                "Scale": "",
                "Units": ACTIVITY_UNITS,
                "Per...": "",
                "Expression": expr,
            })
            rows.append({
                "Branch Path": branch,
                "Variable": INTENSITY_VARIABLE_NAME,
                "Scenario": scenario,
                "Region": region,
                "Scale": "",
                "Units": UNITS,
                "Per...": ACTIVITY_UNITS,
                "Expression": "1",
            })
        else:
            rows.append({
                "Branch Path": branch,
                "Variable": VARIABLE_NAME,
                "Scenario": scenario,
                "Region": region,
                "Scale": "",
                "Units": UNITS,
                "Per...": "",
                "Expression": expr,
            })

    if not rows:
        print("[INFO] save_aggregated_demand_as_leap_workbook: no rows after grouping — workbook not written.")
        return None

    export_df = pd.DataFrame(rows)

    id_lookup_resolved = Path(id_lookup_path) if id_lookup_path is not None else None
    if id_lookup_resolved is not None and id_lookup_resolved.exists():
        branch_to_id, variable_to_id, scenario_to_id = _build_id_lookups(id_lookup_resolved)
        export_df.insert(0, "BranchID", export_df["Branch Path"].map(
            lambda x: branch_to_id.get(str(x).strip(), -1)))
        export_df.insert(1, "VariableID", export_df["Variable"].map(
            lambda x: variable_to_id.get(str(x).strip(), -1)))
        export_df.insert(2, "ScenarioID", export_df["Scenario"].map(
            lambda x: scenario_to_id.get(str(x).strip(), -1)))
        export_df.insert(3, "RegionID", 1)
        matched = int((export_df["BranchID"] != -1).sum())
        print(f"[INFO] Merged IDs: {matched}/{len(export_df)} rows matched BranchID.")
    elif id_lookup_resolved is not None:
        print(f"[WARN] id_lookup_path not found, skipping ID merge: {id_lookup_resolved}")

    max_levels = min(8, export_df["Branch Path"].str.split("\\").str.len().max())
    for i in range(1, max_levels + 1):
        export_df[f"Level {i}"] = export_df["Branch Path"].apply(
            lambda x, _i=i: x.split("\\")[_i - 1] if len(x.split("\\")) >= _i else ""
        )

    cols = list(export_df.columns)

    preamble_row = {col: "" for col in cols}
    preamble_row["Branch Path"] = "Area:"
    preamble_row["Variable"] = model_name or ""
    preamble_row["Scenario"] = "Ver:"
    preamble_row["Region"] = "2"
    empty_row = {col: pd.NA for col in cols}
    header_row_data = {col: col for col in cols}

    full_df = pd.concat(
        [
            pd.DataFrame([preamble_row]),
            pd.DataFrame([empty_row]),
            pd.DataFrame([header_row_data]),
            export_df,
        ],
        ignore_index=True,
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        full_df.to_excel(writer, sheet_name="LEAP", index=False, header=False)
        full_df.to_excel(writer, sheet_name="FOR_VIEWING", index=False, header=False)

    print(f"[INFO] Saved {len(rows)} aggregated demand rows to {output_path}")
    return output_path


# ── Demand zeroing export ─────────────────────────────────────────────────────

def build_demand_zeroing_rows(
    source_path: Path = FULL_MODEL_EXPORT_PATH,
    sheet_name: str = FULL_MODEL_EXPORT_SHEET,
    scenarios: list[str] | None = None,
    region: str = DEFAULT_EXPORT_REGION,
    exclude_branch_prefixes: list[str] | None = None,
) -> pd.DataFrame:
    """
    Build LEAP import rows to zero out all non-share demand branches.

    Reads Demand branch rows from source_path (typically data/full model export.xlsx),
    excluding:
      - Demand\\All demand aggregated\\... branches (where aggregated demand is written)
      - Share variables listed in DEMAND_SHARE_VARIABLES (Device Share, Sales Share,
        Stock Share) which must remain coherent across siblings
      - Any branch prefixes listed in exclude_branch_prefixes (e.g.
        DEMAND_OTHER_LOSS_OWN_USE_BRANCH_PREFIX when the proxy is running in the
        same pass)

    Returns a DataFrame with LEAP import columns: Branch Path, Variable, Scenario,
    Region, Scale, Units, Per..., Expression. Expression is "0" for all rows.
    """
    _LEAP_EXPORT_COLS = [
        "Branch Path", "Variable", "Scenario", "Region",
        "Scale", "Units", "Per...", "Expression",
    ]
    empty = pd.DataFrame(columns=_LEAP_EXPORT_COLS)

    path = Path(source_path)
    if not path.exists():
        print(f"[WARN] Demand zeroing source not found: {path}")
        return empty

    try:
        raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    except Exception as exc:
        print(f"[WARN] Failed reading {path} for demand zeroing: {exc}")
        return empty

    header_row = None
    for idx in range(len(raw.index)):
        row_vals = {
            str(v).strip().lower()
            for v in raw.iloc[idx].tolist()
            if str(v or "").strip()
        }
        if "branch path" in row_vals and "variable" in row_vals:
            header_row = idx
            break
    if header_row is None:
        print(f"[WARN] Could not find LEAP header row in {path}")
        return empty

    df = raw.iloc[header_row + 1:].copy()
    df.columns = raw.iloc[header_row].tolist()
    df = df.dropna(how="all").reset_index(drop=True)

    for col in ["Branch Path", "Variable", "Scenario", "Region"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    mask = (
        df["Branch Path"].str.startswith("Demand\\")
        & ~df["Branch Path"].str.startswith(DEMAND_AGGREGATED_BRANCH_PREFIX)
        & ~df["Variable"].isin(DEMAND_SHARE_VARIABLES)
    )
    if exclude_branch_prefixes:
        for prefix in exclude_branch_prefixes:
            mask = mask & ~df["Branch Path"].str.startswith(prefix)
    df = df[mask].copy()

    if scenarios:
        df = df[df["Scenario"].isin(scenarios)].copy()

    if df.empty:
        print("[INFO] No demand zeroing rows found after filtering.")
        return empty

    df = df.drop_duplicates(subset=["Branch Path", "Variable", "Scenario"], keep="first")

    result = df[["Branch Path", "Variable", "Scenario"]].copy()
    result["Region"] = region
    result["Scale"] = df["Scale"].fillna("") if "Scale" in df.columns else ""
    result["Units"] = df["Units"].fillna("") if "Units" in df.columns else ""
    result["Per..."] = df["Per..."].fillna("") if "Per..." in df.columns else ""
    result["Expression"] = "0"

    return result[_LEAP_EXPORT_COLS].reset_index(drop=True)


def save_demand_zeroing_workbook(
    output_path: Path,
    source_path: Path = FULL_MODEL_EXPORT_PATH,
    sheet_name: str = FULL_MODEL_EXPORT_SHEET,
    scenarios: list[str] | None = None,
    region: str = DEFAULT_EXPORT_REGION,
    model_name: str = "",
    exclude_branch_prefixes: list[str] | None = None,
) -> Path | None:
    """
    Save a LEAP-importable workbook that sets all non-share demand branches to 0.

    The workbook has LEAP and FOR_VIEWING sheets in the format expected by
    _merge_workbook_sheets and fill_branches_from_export_file. Rows cover every
    (Branch Path, Variable, Scenario) combination found in source_path under
    Demand\\..., except aggregated-demand branches, share variables, and any
    prefixes listed in exclude_branch_prefixes.
    """
    rows = build_demand_zeroing_rows(
        source_path=source_path,
        sheet_name=sheet_name,
        scenarios=scenarios,
        region=region,
        exclude_branch_prefixes=exclude_branch_prefixes,
    )
    if rows.empty:
        print("[INFO] No demand zeroing rows — workbook not written.")
        return None

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cols = list(rows.columns)
    preamble_row = {col: "" for col in cols}
    preamble_row["Branch Path"] = "Area:"
    preamble_row["Variable"] = model_name or ""
    preamble_row["Scenario"] = "Ver:"
    preamble_row["Region"] = "2"
    empty_row = {col: pd.NA for col in cols}
    header_row_data = {col: col for col in cols}

    full_df = pd.concat(
        [
            pd.DataFrame([preamble_row]),
            pd.DataFrame([empty_row]),
            pd.DataFrame([header_row_data]),
            rows,
        ],
        ignore_index=True,
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        full_df.to_excel(writer, sheet_name="LEAP", index=False, header=False)
        full_df.to_excel(writer, sheet_name="FOR_VIEWING", index=False, header=False)

    print(f"[INFO] Saved {len(rows)} demand zeroing rows to {output_path}")
    return output_path


# ── LEAP export writer ────────────────────────────────────────────────────────

def _data_expression(year_val_pairs: list[tuple[int, float]]) -> str:
    """Build LEAP Data(year, val, ...) expression string."""
    tokens = []
    for yr, val in year_val_pairs:
        tokens.append(str(yr))
        tokens.append(f"{val:.6g}")
    return "Data(" + ", ".join(tokens) + ")"


def save_to_leap_export(
    demand_df: pd.DataFrame,
    output_path: Path,
    region: str = DEFAULT_EXPORT_REGION,
    branch_root: str = DEMAND_BRANCH_ROOT,
    use_sector_branches: bool = False,
) -> None:
    """
    Write aggregated demand to a LEAP-importable Excel workbook.

    demand_df must have columns: economy, scenario, leap_fuel_name, year, value.
    When use_sector_branches=True, demand_df must also have a 'sector' column and
    branches are written as {branch_root}\\{SectorLabel}\\{fuel_name}.
    Produces one row per (fuel, scenario) in the LEAP export format.
    """
    if demand_df is None or demand_df.empty:
        print("[WARN] save_to_leap_export called with empty DataFrame — nothing written.")
        return

    has_sector = use_sector_branches and "sector" in demand_df.columns
    group_keys = (["sector", "leap_fuel_name", "scenario"] if has_sector
                  else ["leap_fuel_name", "scenario"])

    rows = []
    for group_key, grp in demand_df.groupby(group_keys, sort=True):
        if has_sector:
            sector_key, fuel_name, scenario = group_key
            sector_label = _SECTOR_LEAP_LABELS.get(sector_key, sector_key)
            branch = f"{branch_root}\\{sector_label}\\{fuel_name}"
        else:
            fuel_name, scenario = group_key
            branch = f"{branch_root}\\{fuel_name}"
        grp = grp.sort_values("year")
        year_val = list(zip(grp["year"].astype(int), grp["value"].astype(float)))

        if scenario == "Current Accounts":
            base_vals = [(yr, v) for yr, v in year_val if yr == BASE_YEAR]
            expr = f"{base_vals[0][1]:.6g}" if base_vals else "0"
        else:
            expr = _data_expression(year_val)
        if USE_INTENSITY_ACTIVITY_MODE:
            rows.append({
                "Branch Path": branch,
                "Variable": ACTIVITY_VARIABLE_NAME,
                "Scenario": scenario,
                "Region": region,
                "Scale": "",
                "Units": ACTIVITY_UNITS,
                "Per...": "",
                "Expression": expr,
            })
            rows.append({
                "Branch Path": branch,
                "Variable": INTENSITY_VARIABLE_NAME,
                "Scenario": scenario,
                "Region": region,
                "Scale": "",
                "Units": UNITS,
                "Per...": ACTIVITY_UNITS,
                "Expression": "1",
            })
        else:
            rows.append({
                "Branch Path": branch,
                "Variable": VARIABLE_NAME,
                "Scenario": scenario,
                "Region": region,
                "Scale": "",
                "Units": UNITS,
                "Per...": "",
                "Expression": expr,
            })

    export_df = pd.DataFrame(rows)

    max_levels = min(8, export_df["Branch Path"].str.split("\\").str.len().max())
    for i in range(1, max_levels + 1):
        export_df[f"Level {i}"] = export_df["Branch Path"].apply(
            lambda x, _i=i: x.split("\\")[_i - 1] if len(x.split("\\")) >= _i else ""
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    col_names = list(export_df.columns)
    preamble_row = {col: "" for col in col_names}
    preamble_row["Branch Path"] = "Area:"
    preamble_row["Variable"] = ""
    preamble_row["Scenario"] = "Ver:"
    preamble_row["Region"] = "2"
    header_row_data = {col: col for col in col_names}
    full_output = pd.concat(
        [
            pd.DataFrame([preamble_row]),
            pd.DataFrame([header_row_data]),
            export_df,
        ],
        ignore_index=True,
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        full_output.to_excel(writer, sheet_name="Export", index=False, header=False)

    print(f"[INFO] Saved {len(export_df)} rows to {output_path}")


# ── Standalone entry point ────────────────────────────────────────────────────

def main(
    economy: str | None = None,
    scenarios: list[str] | None = None,
    final_year: int = PROJECTION_END_YEAR,
    output_dir: Path | None = None,
    excluded_sectors: list[str] | None = None,
    use_sector_branches: bool = USE_SECTOR_BRANCHES,
) -> None:
    """
    Run the aggregated demand workflow for one economy and save to Excel.

    If economy is None, uses workflow_config.GLOBAL_ECONOMIES[0].
    If scenarios is None, uses LEAP_SCENARIOS (Current Accounts, Reference, Target).
    If excluded_sectors is provided (e.g. ["14_industry_sector", "16_01_buildings"]),
    those sector/sub1sector codes are omitted from the aggregation and the output
    filename will include a suffix such as "_no_industry_buildings".
    If use_sector_branches=True, branches are written as
    Demand\\All demand aggregated\\{SectorLabel}\\{fuel_name} instead of the flat
    per-fuel path.
    """
    if economy is None:
        economies = list(getattr(workflow_cfg, "GLOBAL_ECONOMIES", ["20_USA"]))
        economy = economies[0] if economies else "20_USA"

    use_scenarios = scenarios if scenarios is not None else list(LEAP_SCENARIOS)
    out_dir = Path(output_dir) if output_dir else STANDALONE_LEAP_EXPORTS_ROOT

    if _is_aggregate_economy(economy):
        print(f"[INFO] Economy {economy!r} is an aggregate sentinel — summing all member economies.")
    print(f"[INFO] Building aggregated demand for economy={economy!r}")
    print(f"[INFO] Scenarios: {use_scenarios}, years: {BASE_YEAR}–{final_year}")

    demand = build_aggregated_demand_all_scenarios(
        economy=economy,
        scenarios=use_scenarios,
        base_year=BASE_YEAR,
        final_year=final_year,
        data_path=PROJECTION_DATA_PATH,
        esto_data_path=ESTO_BASE_DATA_PATH,
        fuel_mappings_path=FUEL_MAPPINGS_PATH,
        excluded_sectors=excluded_sectors,
        use_sector_branches=use_sector_branches,
    )

    fuels_found = sorted(demand["leap_fuel_name"].unique())
    print(f"[INFO] {len(fuels_found)} fuels after mapping: {fuels_found}")

    if excluded_sectors:
        print(f"[INFO] Excluded sectors: {excluded_sectors}")
    if use_sector_branches:
        print(f"[INFO] Sector-branch mode: branches will include sector sub-level.")

    scenario_token = "_".join(
        "".join(c for c in s if c.isalnum()) for s in use_scenarios
    )
    econ_token = "".join(c for c in economy if c.isalnum() or c == "_")
    exclusion_suffix = _sector_exclusion_suffix(excluded_sectors)
    sector_suffix = "_by_sector" if use_sector_branches else ""
    filename = f"aggregated_demand_{econ_token}_{scenario_token}{exclusion_suffix}{sector_suffix}.xlsx"
    output_path = out_dir / filename

    save_to_leap_export(demand, output_path=output_path, use_sector_branches=use_sector_branches)
    print(f"[INFO] Done.")


if __name__ == "__main__":
    main()
#%%
