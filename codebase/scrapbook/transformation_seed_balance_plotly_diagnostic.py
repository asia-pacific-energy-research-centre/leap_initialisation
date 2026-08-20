#%%
"""Reconstruct selected transformation seed balances and compare source series.

This read-only diagnostic deliberately uses the baseline seed, ESTO, and 9th
Outlook inputs.  It does not use a calculated LEAP result or balance export.
Run the controls at the bottom from a Jupyter cell after selecting an economy,
seed workbook, and process definitions.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.functions.leap_expressions import expression_to_series

#%%
######### CONSTANTS #########
BASE_YEAR = 2022
FINAL_YEAR = 2060
TOLERANCE_PJ = 0.001
OUTPUT_ROOT = REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation" / "supporting_files" / "transformation_seed_balance_plotly_diagnostics"
ESTO_PATH = REPO_ROOT / "data" / "00APEC_2024_low_with_subtotals.csv"
NINTH_PATH = REPO_ROOT / "data" / "merged_file_energy_ALL_20251106.csv"


@dataclass(frozen=True)
class ProcessSpec:
    """The three source boundaries for one LEAP transformation process.

    ``ninth_process_code`` and each own-use code must be the 9th sector code,
    such as ``09_08_01_coke_ovens``.  A blank own-use list is valid, including
    for a 09.06 child whose own use is represented elsewhere.
    """

    name: str
    seed_process_path: str
    esto_transformation_flow: str
    esto_own_use_flows: tuple[str, ...]
    ninth_process_code: str
    ninth_own_use_codes: tuple[str, ...]


COAL_PROCESS_SPECS = (
    ProcessSpec(
        name="Coke ovens",
        seed_process_path=r"Transformation\Coke ovens\Processes\Coke ovens",
        esto_transformation_flow="09.08.01 Coke ovens",
        esto_own_use_flows=("10.01.05 Coke ovens",),
        ninth_process_code="09_08_01_coke_ovens",
        ninth_own_use_codes=("10_01_05_coke_ovens",),
    ),
    ProcessSpec(
        name="Blast furnaces",
        seed_process_path=r"Transformation\Blast furnaces\Processes\Blast furnaces",
        esto_transformation_flow="09.08.02 Blast furnaces",
        esto_own_use_flows=("10.01.07 Blast furnaces",),
        ninth_process_code="09_08_02_blast_furnaces",
        ninth_own_use_codes=("10_01_07_blast_furnaces",),
    ),
)

# Example for inspecting the active 09.06 base-year child profile.  Its source
# projection is the 09.06 parent; run it on its own, rather than together with
# several gas-processing children that share that parent boundary.
GAS_PROCESSING_CHILD_EXAMPLE = (
    ProcessSpec(
        name="Gas works plants",
        seed_process_path=r"Transformation\Gas works plants\Processes\Gas works plants",
        esto_transformation_flow="09.06 Gas processing plants",
        esto_own_use_flows=("10.01.02 Gas works plants",),
        ninth_process_code="09_06_gas_processing_plants",
        ninth_own_use_codes=("10_01_02_gas_works_plants",),
    ),
)

#%%
######### FUNCTIONS #########
def resolve_seed_workbook(economy: str, explicit_path: Path | None = None) -> Path:
    """Return the newest non-archived seed workbook for an economy."""
    if explicit_path is not None:
        return Path(explicit_path)
    candidates = list((REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation" / "baseline_seed").glob(f"leap_import_baseline_seed_{economy}_*.xlsx"))
    if not candidates:
        raise FileNotFoundError(f"No baseline seed workbook found for {economy}.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _expression_value(row: pd.Series, year: int) -> float:
    values = expression_to_series(row.get("Expression"), years=[year], base_year=BASE_YEAR)
    if values is None:
        raise ValueError(f"Cannot evaluate LEAP expression: {row.get('Expression')!r}")
    return float(values.get(year, 0.0))


def _seed_rows_for_year(seed: pd.DataFrame, scenario: str, year: int) -> pd.DataFrame:
    source_scenario = "Current Accounts" if year == BASE_YEAR else scenario
    return seed.loc[seed["Scenario"].astype(str).eq(source_scenario)].copy()


def reconstruct_seed_process(
    seed: pd.DataFrame,
    process: ProcessSpec,
    scenario: str,
    years: list[int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reconstruct gross, feedstock, auxiliary and net seed energy in PJ."""
    rows: list[dict[str, object]] = []
    auxiliary_rows: list[dict[str, object]] = []
    process_prefix = process.seed_process_path + "\\"
    for year in years:
        selected = _seed_rows_for_year(seed, scenario, year)
        process_rows = selected.loc[selected["Branch Path"].astype(str).eq(process.seed_process_path)]
        production = process_rows.loc[process_rows["Variable"].astype(str).eq("Historical Production")]
        efficiency = process_rows.loc[process_rows["Variable"].astype(str).eq("Process Efficiency")]
        if len(production) != 1 or len(efficiency) != 1:
            raise ValueError(f"{process.name} / {scenario} / {year}: expected one Historical Production and Process Efficiency row.")

        gross = _expression_value(production.iloc[0], year)
        efficiency_percent = _expression_value(efficiency.iloc[0], year)
        if abs(efficiency_percent) <= 1e-12 and abs(gross) > TOLERANCE_PJ:
            raise ValueError(f"{process.name} / {scenario} / {year}: nonzero output has zero Process Efficiency.")
        feedstock = -gross / (efficiency_percent / 100.0) if abs(efficiency_percent) > 1e-12 else 0.0

        auxiliary = selected.loc[
            selected["Branch Path"].astype(str).str.startswith(process_prefix + "Auxiliary Fuels\\", na=False)
            & selected["Variable"].astype(str).eq("Auxiliary Fuel Use")
        ].copy()
        auxiliary_total = 0.0
        for _, row in auxiliary.iterrows():
            ratio = _expression_value(row, year)
            energy = -gross * ratio
            auxiliary_total += energy
            auxiliary_rows.append(
                {
                    "scenario": scenario,
                    "process": process.name,
                    "year": year,
                    "auxiliary_fuel": str(row["Branch Path"]).split("\\")[-1],
                    "auxiliary_ratio": ratio,
                    "auxiliary_energy": energy,
                }
            )
        rows.append(
            {
                "scenario": scenario,
                "process": process.name,
                "year": year,
                "gross_output": gross,
                "feedstock_energy": feedstock,
                "auxiliary_energy": auxiliary_total,
                "seed_net": gross + feedstock + auxiliary_total,
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(auxiliary_rows)


def _source_total(table: pd.DataFrame, year: int) -> float:
    column = str(year)
    if column not in table.columns:
        return np.nan
    return float(pd.to_numeric(table[column], errors="coerce").fillna(0.0).sum())


def build_esto_net(esto: pd.DataFrame, economy: str, process: ProcessSpec, years: list[int]) -> pd.DataFrame:
    """Sum the 09 process and its 10.01 own use exactly once."""
    flows = (process.esto_transformation_flow,) + process.esto_own_use_flows
    selected = esto.loc[
        esto["economy"].astype(str).eq(economy.replace("_", ""))
        & esto["flows"].astype(str).isin(flows)
        & ~esto["is_subtotal"].astype(bool)
    ]
    return pd.DataFrame({"year": years, "esto_net": [_source_total(selected, year) for year in years]})


def _ninth_code_mask(ninth: pd.DataFrame, codes: tuple[str, ...]) -> pd.Series:
    hierarchy = ["sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors"]
    return ninth[hierarchy].astype(str).isin(codes).any(axis=1)


def _drop_ninth_fuel_rollups(table: pd.DataFrame) -> pd.DataFrame:
    """Keep a fuel's ``x`` row only when it has no more-detailed subfuel row.

    The 9th table can hold both the coking-coal detail and its ``01_coal / x``
    rollup.  Both have ``subtotal_results == False``, so the conventional
    subtotal filter alone would double-count the input.
    """
    if table.empty:
        return table
    identity = ["scenarios", "economy", "sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors", "fuels"]
    has_detail = table["subfuels"].astype(str).ne("x").groupby([table[column] for column in identity], dropna=False).transform("any")
    return table.loc[~(table["subfuels"].astype(str).eq("x") & has_detail)].copy()


def build_ninth_net(ninth: pd.DataFrame, economy: str, scenario: str, process: ProcessSpec, years: list[int]) -> pd.DataFrame:
    """Use direct child projections where available; do not include any own-use twice."""
    codes = (process.ninth_process_code,) + process.ninth_own_use_codes
    selected = ninth.loc[
        ninth["economy"].astype(str).eq(economy)
        & ninth["scenarios"].astype(str).str.casefold().eq(scenario.casefold())
        & ~ninth["subtotal_results"].astype(bool)
        & _ninth_code_mask(ninth, codes)
    ]
    selected = _drop_ninth_fuel_rollups(selected)
    return pd.DataFrame({"year": years, "ninth_net": [_source_total(selected, year) for year in years]})


def build_coal_family_ninth_net(ninth: pd.DataFrame, economy: str, scenario: str, years: list[int]) -> pd.DataFrame:
    """Use the 09.08 parent plus the two own-use children for coal-family reconciliation."""
    parent = ninth.loc[
        ninth["economy"].astype(str).eq(economy)
        & ninth["scenarios"].astype(str).str.casefold().eq(scenario.casefold())
        & ninth["sub1sectors"].astype(str).eq("09_08_coal_transformation")
        & ninth["sub2sectors"].astype(str).eq("x")
        & ~ninth["subtotal_results"].astype(bool)
    ]
    own_use = ninth.loc[
        ninth["economy"].astype(str).eq(economy)
        & ninth["scenarios"].astype(str).str.casefold().eq(scenario.casefold())
        & ~ninth["subtotal_results"].astype(bool)
        & _ninth_code_mask(ninth, ("10_01_05_coke_ovens", "10_01_07_blast_furnaces"))
    ]
    parent = _drop_ninth_fuel_rollups(parent)
    own_use = _drop_ninth_fuel_rollups(own_use)
    return pd.DataFrame({"year": years, "coal_family_ninth_net": [_source_total(parent, year) + _source_total(own_use, year) for year in years]})


def build_process_figure(process_rows: pd.DataFrame, auxiliary_rows: pd.DataFrame, process_name: str, scenario: str) -> go.Figure:
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    selected = process_rows.loc[(process_rows["process"] == process_name) & (process_rows["scenario"] == scenario)]
    figure.add_bar(x=selected["year"], y=selected["gross_output"], name="Gross output")
    figure.add_bar(x=selected["year"], y=selected["feedstock_energy"], name="Feedstock")
    for fuel, values in auxiliary_rows.loc[(auxiliary_rows["process"] == process_name) & (auxiliary_rows["scenario"] == scenario)].groupby("auxiliary_fuel"):
        figure.add_bar(x=values["year"], y=values["auxiliary_energy"], name=f"Auxiliary: {fuel}")
    for column, label, dash in (("esto_net", "ESTO net", "dot"), ("seed_net", "Seed net", "solid"), ("ninth_net", "9th net", "dash")):
        figure.add_scatter(x=selected["year"], y=selected[column], mode="lines", name=label, line={"dash": dash}, secondary_y=True)
    figure.update_layout(title=f"{process_name} — {scenario}", barmode="relative", hovermode="x unified", legend_title_text="Series")
    figure.update_yaxes(title_text="Components (PJ)", secondary_y=False)
    figure.update_yaxes(title_text="Net energy (PJ)", secondary_y=True)
    figure.update_xaxes(title_text="Year")
    return figure


def build_coal_family_figure(family: pd.DataFrame, scenario: str) -> go.Figure:
    figure = go.Figure()
    figure.add_scatter(x=family["year"], y=family["coal_family_seed_net"], mode="lines", name="Seed total")
    figure.add_scatter(x=family["year"], y=family["coal_family_ninth_net"], mode="lines", name="9th parent + own use", line={"dash": "dash"})
    figure.update_layout(title=f"Coal-family reconciliation — {scenario}", hovermode="x unified", yaxis_title="Net energy (PJ)", xaxis_title="Year")
    return figure


def validate_aus_coal(result: pd.DataFrame, family: pd.DataFrame) -> None:
    """Fail loudly when the requested AUS reference values or family identity change."""
    reference = result.loc[(result["scenario"] == "Reference") & (result["year"] == BASE_YEAR)].set_index("process")
    expected = {"Coke ovens": -49.718995, "Blast furnaces": -46.891884}
    for process, value in expected.items():
        observed = float(reference.loc[process, "seed_net"])
        if not np.isclose(observed, value, atol=TOLERANCE_PJ):
            raise AssertionError(f"AUS {process} {BASE_YEAR} seed net {observed:.6f} PJ != expected {value:.6f} PJ.")
    future = family.loc[family["year"] > BASE_YEAR]
    difference = future["coal_family_seed_net"] - future["coal_family_ninth_net"]
    if not np.allclose(difference, 0.0, atol=TOLERANCE_PJ, equal_nan=False):
        raise AssertionError("AUS Target coal-family seed total does not equal 9th parent plus own-use children for every projection year.")


def run_transformation_seed_balance_diagnostic(
    economy: str,
    seed_workbook_path: Path | None,
    process_specs: tuple[ProcessSpec, ...],
    scenarios: tuple[str, ...] = ("Reference", "Target"),
    years: list[int] | None = None,
    validate_aus_coal_values: bool = False,
) -> dict[str, Path | pd.DataFrame]:
    """Write one HTML visual and narrow CSV for selected seed transformation processes."""
    years = years or list(range(BASE_YEAR, FINAL_YEAR + 1))
    seed_path = resolve_seed_workbook(economy, seed_workbook_path)
    seed = pd.read_excel(seed_path, sheet_name="LEAP", header=2)
    esto = pd.read_csv(ESTO_PATH)
    ninth = pd.read_csv(NINTH_PATH)

    all_process_rows: list[pd.DataFrame] = []
    all_auxiliary_rows: list[pd.DataFrame] = []
    for scenario in scenarios:
        for process in process_specs:
            seed_rows, auxiliary_rows = reconstruct_seed_process(seed, process, scenario, years)
            combined = seed_rows.merge(build_esto_net(esto, economy, process, years), on="year", how="left")
            combined = combined.merge(build_ninth_net(ninth, economy, scenario, process, years), on="year", how="left")
            combined.insert(0, "economy", economy)
            combined["difference"] = combined["seed_net"] - combined["ninth_net"]
            combined["difference_flag"] = combined["difference"].abs() > TOLERANCE_PJ
            all_process_rows.append(combined)
            all_auxiliary_rows.append(auxiliary_rows)
    result = pd.concat(all_process_rows, ignore_index=True)
    auxiliary = pd.concat(all_auxiliary_rows, ignore_index=True)

    family = pd.DataFrame()
    if {process.name for process in process_specs} >= {"Coke ovens", "Blast furnaces"}:
        family_seed = result.loc[result["process"].isin(["Coke ovens", "Blast furnaces"])].groupby(["scenario", "year"], as_index=False)["seed_net"].sum().rename(columns={"seed_net": "coal_family_seed_net"})
        family_ninth = pd.concat([build_coal_family_ninth_net(ninth, economy, scenario, years).assign(scenario=scenario) for scenario in scenarios], ignore_index=True)
        family = family_seed.merge(family_ninth, on=["scenario", "year"], how="left")
        family["difference"] = family["coal_family_seed_net"] - family["coal_family_ninth_net"]
        if validate_aus_coal_values:
            validate_aus_coal(result, family.loc[family["scenario"] == "Target"])

    output_dir = OUTPUT_ROOT / economy
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{economy.lower()}_transformation_seed_balance.csv"
    html_path = output_dir / f"{economy.lower()}_transformation_seed_balance.html"
    result[["economy", "scenario", "process", "year", "gross_output", "feedstock_energy", "auxiliary_energy", "seed_net", "esto_net", "ninth_net", "difference", "difference_flag"]].to_csv(csv_path, index=False)

    charts: list[str] = []
    include_plotly = "cdn"
    for scenario in scenarios:
        for process in process_specs:
            charts.append(build_process_figure(result, auxiliary, process.name, scenario).to_html(full_html=False, include_plotlyjs=include_plotly))
            include_plotly = False
        if not family.empty:
            charts.append(build_coal_family_figure(family.loc[family["scenario"] == scenario], scenario).to_html(full_html=False, include_plotlyjs=include_plotly))
            include_plotly = False
    html_path.write_text(
        "<html><head><meta charset='utf-8'><title>Transformation seed balance diagnostic</title></head><body>"
        + "\n".join(charts)
        + "</body></html>",
        encoding="utf-8",
    )
    return {"csv_path": csv_path, "html_path": html_path, "results": result, "family": family}


#%%
######### NOTEBOOK CONTROLS #########
RUN_DIAGNOSTIC = False
ECONOMY = "01_AUS"
SEED_WORKBOOK_PATH = REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation" / "baseline_seed" / "leap_import_baseline_seed_01_AUS_UNVERIFIED_20260818.xlsx"
PROCESS_SPECS = COAL_PROCESS_SPECS

if RUN_DIAGNOSTIC:
    DIAGNOSTIC_RESULTS = run_transformation_seed_balance_diagnostic(
        economy=ECONOMY,
        seed_workbook_path=SEED_WORKBOOK_PATH,
        process_specs=PROCESS_SPECS,
        validate_aus_coal_values=True,
    )
    print(DIAGNOSTIC_RESULTS["html_path"])
    print(DIAGNOSTIC_RESULTS["csv_path"])

#%%
