#%%
"""Dashboard-style Plotly review of the intended transfer seed outputs.

This is a read-only, notebook-safe diagnostic.  It calls the current transfer
builder, so projected lines include the agreed scenario-aware carry-forward
where the raw 9th transfer projection is unavailable.  It does not use LEAP
results or balance-export files.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase import transfers_workflow as transfers

#%%
######### CONSTANTS #########
BASE_YEAR = 2022
FINAL_YEAR = 2060
SCENARIOS = ("Reference", "Target")
OUTPUT_ROOT = REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation" / "supporting_files" / "transfer_intended_outputs_dashboard"

# These are the economies with current baseline seeds.  Change this list in a
# notebook cell when reviewing a smaller set.
DEFAULT_ECONOMIES = ("01_AUS", "02_BD", "05_PRC", "10_MAS", "11_MEX", "12_NZ", "13_PNG", "15_PHL", "19_THA", "20_USA", "21_VN")

_COLORS = {
    ("seed", "reference"): "#1f77b4",
    ("seed", "target"): "#17becf",
    ("source", "reference"): "#2ca02c",
    ("source", "target"): "#bcbd22",
    ("historical", "reference"): "#d62728",
    ("historical", "target"): "#e377c2",
}

#%%
######### FUNCTIONS #########
def _series_value(values: dict | None, year: int) -> float:
    if not values:
        return 0.0
    return float(values.get(year, values.get(str(year), 0.0)) or 0.0)


def _sum_record_values(records: list[dict], key: str, year: int) -> float:
    return sum(
        _series_value(values, year)
        for record in records
        for values in (record.get(key) or {}).values()
    )


def _sum_auxiliary_energy(records: list[dict], year: int) -> float:
    """Evaluate transfer auxiliary ratios on the same gross-output basis as LEAP."""
    total = 0.0
    for record in records:
        gross_output = sum(_series_value(values, year) for values in (record.get("output_values") or {}).values())
        ratio = sum(_series_value(values, year) for values in (record.get("auxiliary_ratios") or {}).values())
        total -= gross_output * ratio
    return total


def _record_process_names(records: list[dict]) -> str:
    names = sorted({str(record.get("process_name") or "Transfers") for record in records})
    return "; ".join(names)


def _build_intended_rows(
    economy: str,
    scenario: str,
    transfer_data: pd.DataFrame,
    year_cols: list[int],
    availability: pd.DataFrame,
) -> pd.DataFrame:
    records = transfers.build_transfer_rows(
        economy=economy,
        data_override=transfer_data,
        year_cols_override=year_cols,
    )
    if not records:
        return pd.DataFrame()
    state = availability.loc[availability["economy"].astype(str).eq(economy), "projection_availability"]
    state_value = state.iloc[0] if not state.empty else "not_classified"
    rows = []
    for year in range(BASE_YEAR, FINAL_YEAR + 1):
        gross_output = _sum_record_values(records, "output_values", year)
        feedstock_energy = -_sum_record_values(records, "feedstock_values", year)
        auxiliary_energy = _sum_auxiliary_energy(records, year)
        rows.append(
            {
                "economy": economy,
                "scenario": scenario,
                "year": year,
                "processes": _record_process_names(records),
                "projection_availability": state_value,
                "gross_output": gross_output,
                "feedstock_energy": feedstock_energy,
                "auxiliary_energy": auxiliary_energy,
                "seed_net": gross_output + feedstock_energy + auxiliary_energy,
            }
        )
    return pd.DataFrame(rows)


def _dashboard_figure(economy_rows: pd.DataFrame, economy: str) -> go.Figure:
    """Match the dashboard's line/marker, palette, legend, and white layout."""
    figure = go.Figure()
    for scenario in SCENARIOS:
        selected = economy_rows.loc[economy_rows["scenario"].eq(scenario)].sort_values("year")
        if selected.empty:
            continue
        key = scenario.lower()
        figure.add_trace(go.Scatter(
            x=selected["year"], y=selected["gross_output"], mode="lines+markers",
            name=f"Intended transfer outputs {'REF' if key == 'reference' else 'TGT'}",
            line={"color": _COLORS[("seed", key)], "dash": "solid"},
            marker={"color": _COLORS[("seed", key)], "symbol": "circle"},
        ))
        figure.add_trace(go.Scatter(
            x=selected["year"], y=-selected["feedstock_energy"], mode="lines+markers",
            name=f"Intended transfer inputs {'REF' if key == 'reference' else 'TGT'}",
            line={"color": _COLORS[("source", key)], "dash": "solid"},
            marker={"color": _COLORS[("source", key)], "symbol": "square"},
        ))
    state = ", ".join(sorted(economy_rows["projection_availability"].dropna().astype(str).unique()))
    processes = economy_rows["processes"].dropna().iloc[0] if not economy_rows.empty else "Transfers"
    figure.update_layout(
        title=f"{economy} — {processes}<br><sup>Projection state: {state}</sup>",
        template="plotly_white",
        xaxis_title="Year",
        yaxis_title="Energy (PJ)",
        hovermode="x unified",
        margin={"l": 64, "r": 28, "t": 72, "b": 56},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
    )
    return figure


def _empty_dashboard_figure(economy: str) -> go.Figure:
    """Keep an economy visible when the current transfer builder emits no process."""
    figure = go.Figure()
    figure.add_annotation(
        text="No transfer process is emitted by the current configuration.",
        x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
        font={"size": 16, "color": "#111827"},
    )
    figure.update_layout(
        title=f"{economy} — Transfers",
        template="plotly_white",
        xaxis={"visible": False}, yaxis={"visible": False},
        margin={"l": 64, "r": 28, "t": 72, "b": 56},
    )
    return figure


def _write_dashboard_html(figures: list[go.Figure], output_path: Path) -> None:
    sections = []
    include_plotly = "cdn"
    for figure in figures:
        sections.append(pio.to_html(figure, include_plotlyjs=include_plotly, full_html=False, config={"responsive": True}))
        include_plotly = False
    output_path.write_text(
        """<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Transfer intended outputs</title><style>
body { margin: 0; background: #ffffff; color: #111827; font-family: \"Segoe UI\", Arial, sans-serif; }
.chart { width: min(1200px, calc(100% - 32px)); margin: 20px auto 34px; }
.plotly-graph-div { width: 100% !important; }
</style></head><body>"""
        + "\n".join(f"<section class=\"chart\">{section}</section>" for section in sections)
        + "</body></html>",
        encoding="utf-8",
    )


def run_transfer_intended_outputs_dashboard(economies: tuple[str, ...] = DEFAULT_ECONOMIES) -> dict[str, Path | pd.DataFrame]:
    """Generate dashboard-style intended transfer output charts by economy.

    The current transfer builder is called once per scenario, then reused for
    every economy.  This avoids deriving projected values from an old seed.
    """
    intended_parts: list[pd.DataFrame] = []
    for scenario in SCENARIOS:
        transfer_data, year_cols = transfers.build_transfer_data_for_scenario(scenario)
        historical = transfers.core.esto_data_raw.copy()
        historical = historical.loc[historical["flows"].astype(str).isin(transfers.TRANSFER_FLOW_CODES)].copy()
        raw_ninth = transfers.core.ninth_data_raw.loc[
            transfers.core.ninth_data_raw["sectors"].astype(str).eq("08_transfers")
        ].copy()
        availability = transfers.classify_transfer_projection_availability(
            historical, raw_ninth, scenario, transfers.core.BASE_YEAR, transfers.core.PROJECTION_YEAR_RANGE
        )
        for economy in economies:
            intended = _build_intended_rows(economy, scenario, transfer_data, year_cols, availability)
            if not intended.empty:
                intended_parts.append(intended)
    if not intended_parts:
        raise ValueError("No transfer records were built for the selected economies.")
    intended_outputs = pd.concat(intended_parts, ignore_index=True)
    figures = []
    for economy in economies:
        economy_rows = intended_outputs.loc[intended_outputs["economy"].eq(economy)]
        figures.append(_dashboard_figure(economy_rows, economy) if not economy_rows.empty else _empty_dashboard_figure(economy))
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    html_path = OUTPUT_ROOT / "transfer_intended_outputs_by_economy.html"
    _write_dashboard_html(figures, html_path)
    return {"html_path": html_path, "intended_outputs": intended_outputs}


#%%
######### NOTEBOOK CONTROLS #########
RUN_DASHBOARD = False
ECONOMIES = DEFAULT_ECONOMIES

if RUN_DASHBOARD:
    TRANSFER_DASHBOARD_RESULTS = run_transfer_intended_outputs_dashboard(ECONOMIES)
    print(TRANSFER_DASHBOARD_RESULTS["html_path"])

#%%
