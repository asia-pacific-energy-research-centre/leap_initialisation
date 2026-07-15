#%%
"""
Notebook-safe exploration for aggregated demand bridge behavior and jet-fuel allocation.

This script compares bridge-off vs bridge-on aggregated demand for 20_USA and
then inspects why Kerosene type jet fuel changes in the Reference scenario.

It does not modify any published workbook outputs. It only writes diagnostics
to outputs/scrapbook/aggregated_demand_bridge_jetfuel_test/.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd


#%%
# --- Stable configuration ---

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DATA_PATH = REPO_ROOT / "data" / "merged_file_energy_ALL_20251106.csv"
ESTO_DATA_PATH = REPO_ROOT / "data" / "00APEC_2024_low_with_subtotals.csv"
MAPPINGS_PATH = Path(r"C:\Users\Work\github\leap_mappings\config\outlook_mappings_master.xlsx")
OUTPUT_DIR = REPO_ROOT / "outputs" / "scrapbook" / "aggregated_demand_bridge_jetfuel_test"

ECONOMY = "20_USA"
SCENARIO = "Reference"
BASE_YEAR = 2022
FINAL_YEAR = 2023

ELECTRICITY_FUEL = "Electricity"
JET_FUEL = "Kerosene type jet fuel"
JET_SOURCE_FUEL = "07_x_jet_fuel"


#%%
def _build_aggregated_demand(*, apply_bridge: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build aggregated demand plus provenance for a single scenario."""
    from codebase.aggregated_demand_workflow import build_aggregated_demand

    result, provenance = build_aggregated_demand(
        economy=ECONOMY,
        scenario=SCENARIO,
        base_year=BASE_YEAR,
        final_year=FINAL_YEAR,
        data_path=DATA_PATH,
        esto_data_path=ESTO_DATA_PATH,
        fuel_mappings_path=MAPPINGS_PATH,
        apply_first_projection_year_bridge=apply_bridge,
        return_provenance=True,
    )
    return result, provenance


def _electricity_bridge_compare(off: pd.DataFrame, on: pd.DataFrame) -> pd.DataFrame:
    off_series = off[off["leap_fuel_name"].eq(ELECTRICITY_FUEL)][["year", "value"]].copy()
    on_series = on[on["leap_fuel_name"].eq(ELECTRICITY_FUEL)][["year", "value"]].copy()
    off_series = off_series.rename(columns={"value": "value_bridge_off"})
    on_series = on_series.rename(columns={"value": "value_bridge_on"})
    merged = off_series.merge(on_series, on="year", how="outer").sort_values("year")
    merged["difference"] = merged["value_bridge_on"] - merged["value_bridge_off"]
    merged["pct_change"] = (
        (merged["difference"] / merged["value_bridge_off"]) * 100.0
    )
    return merged


def _jet_fuel_provenance_summary(provenance: pd.DataFrame) -> pd.DataFrame:
    """Summarize signed and absolute jet-fuel allocations for the projection year."""
    working = provenance[
        provenance["year"].eq(FINAL_YEAR)
        & provenance["source_fuel_or_product"].eq(JET_SOURCE_FUEL)
    ].copy()
    if working.empty:
        return pd.DataFrame()

    summary = (
        working.groupby(["leap_fuel_name"], dropna=False)["allocated_value"]
        .agg(
            signed_sum="sum",
            abs_sum=lambda series: series.abs().sum(),
            row_count="count",
        )
        .reset_index()
        .sort_values("abs_sum", ascending=False)
    )
    summary["source_fuel_or_product"] = JET_SOURCE_FUEL
    return summary[
        [
            "source_fuel_or_product",
            "leap_fuel_name",
            "signed_sum",
            "abs_sum",
            "row_count",
        ]
    ]


def _jet_fuel_sector_breakdown(provenance: pd.DataFrame, fuel_name: str) -> pd.DataFrame:
    working = provenance[
        provenance["year"].eq(FINAL_YEAR)
        & provenance["source_fuel_or_product"].eq(JET_SOURCE_FUEL)
        & provenance["leap_fuel_name"].eq(fuel_name)
    ].copy()
    if working.empty:
        return pd.DataFrame()
    summary = (
        working.groupby("source_sector_or_flow", dropna=False)["allocated_value"]
        .agg(
            signed_sum="sum",
            abs_sum=lambda series: series.abs().sum(),
            row_count="count",
        )
        .reset_index()
        .sort_values("abs_sum", ascending=False)
    )
    summary.insert(0, "leap_fuel_name", fuel_name)
    return summary


def _jet_fuel_mapping_rows() -> pd.DataFrame:
    from codebase.functions.unified_name_lookup import load_active_mapping_sheet

    mapping = load_active_mapping_sheet("ninth_pairs_to_esto_pairs", MAPPINGS_PATH)
    working = mapping[mapping["ninth_fuel"].eq(JET_SOURCE_FUEL)].copy()
    if working.empty:
        return pd.DataFrame()
    return working[["ninth_sector", "ninth_fuel", "esto_flow", "esto_product"]].drop_duplicates()


def build_diagnostics() -> dict[str, pd.DataFrame]:
    """Build all comparison tables without mutating any source workbook."""
    off, off_provenance = _build_aggregated_demand(apply_bridge=False)
    on, _ = _build_aggregated_demand(apply_bridge=True)

    electricity_compare = _electricity_bridge_compare(off, on)

    jet_summary = _jet_fuel_provenance_summary(off_provenance)
    kerosene_sector = _jet_fuel_sector_breakdown(off_provenance, JET_FUEL)
    jet_mappings = _jet_fuel_mapping_rows()

    return {
        "electricity_compare": electricity_compare,
        "jet_fuel_summary": jet_summary,
        "kerosene_sector_breakdown": kerosene_sector,
        "jet_fuel_mapping_rows": jet_mappings,
        "bridge_off_output": off,
    }


def print_summary(tables: dict[str, pd.DataFrame]) -> None:
    electricity = tables["electricity_compare"]
    kerosene = tables["bridge_off_output"][
        tables["bridge_off_output"]["leap_fuel_name"].eq(JET_FUEL)
    ].copy()
    jet_summary = tables["jet_fuel_summary"]
    sector_breakdown = tables["kerosene_sector_breakdown"]
    jet_mappings = tables["jet_fuel_mapping_rows"]

    print("Electricity bridge comparison")
    print(electricity.to_string(index=False))
    if electricity["difference"].fillna(0.0).abs().sum() == 0.0:
        print(
            "Note: the bridge hook does not change this series because it only "
            "adjusts first-year increases, not first-year drops."
        )
    print()

    print(f"{JET_FUEL} output in the bridge-off view")
    print(kerosene.to_string(index=False))
    print()

    print(f"{JET_SOURCE_FUEL} allocation summary for {JET_FUEL}")
    print(jet_summary.to_string(index=False))
    print()

    print(f"{JET_SOURCE_FUEL} sector breakdown for {JET_FUEL}")
    print(sector_breakdown.to_string(index=False))
    print()

    print(f"Mapping rows for {JET_SOURCE_FUEL}")
    print(jet_mappings.to_string(index=False))


def save_diagnostics(tables: dict[str, pd.DataFrame]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in [
        "electricity_compare",
        "jet_fuel_summary",
        "kerosene_sector_breakdown",
        "jet_fuel_mapping_rows",
    ]:
        table = tables.get(name)
        if isinstance(table, pd.DataFrame) and not table.empty:
            table.to_csv(OUTPUT_DIR / f"{name}.csv", index=False)


def main() -> None:
    tables = build_diagnostics()
    save_diagnostics(tables)
    print_summary(tables)


#%%
if __name__ == "__main__":
    main()
