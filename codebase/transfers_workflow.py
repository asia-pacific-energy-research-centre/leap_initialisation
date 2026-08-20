#%%
"""
Draft transfer analysis scaffolding.

This script converts ESTO transfer flows into LEAP transformation-style process
records and export workbooks.
It handles economy-specific transfer mappings, optional unallocated-process
fallback behavior, and import dispatch for the generated transfer workbook.

Purpose:
- Treat ESTO 08.* Transfers flows as Transformation-style processes for LEAP.
- Build process_records compatible with transformation exports.
- Keep logic isolated (no edits to existing transformation modules).

Notes:
- Inputs are negative, outputs are positive in balance tables.
- Prefer subflows (08.01/08.02/08.03) when they have nonzero data; fallback to 08 Transfers.
- Transfers are economy-specific: update TRANSFER_PROCESS_CONFIG with explicit mappings.
- Subtotals are dropped before any transfer logic runs.

Most user-editable settings live in `codebase/workflow_config.py`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
try:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
except Exception as exc:
    print(f"Failed to add repo root to sys.path: {exc}")

from codebase.functions import transformation_analysis_utils as core
from codebase.functions.conservation_policy import build_with_conservation_policy
from codebase.functions.ninth_projection_mapping import normalize_economy_key
from codebase.configuration import workflow_config as workflow_cfg
from codebase.functions import leap_api, leap_exports
from codebase.functions.analysis_input_write_dispatcher import (
    get_analysis_input_write_mode,
)
from codebase.configuration.config import (
    BRANCH_DEMAND_CATEGORY,
    BRANCH_DEMAND_TECHNOLOGY,
)
from codebase.utilities import workflow_common
from codebase.utilities import leap_export_template_resolver
from codebase.functions.transfers_utils import (
    _sum_series,
    _flow_has_nonzero,
    _combine_flow_rows,
    _resolve_transfer_io_labels,
    _template_processes_cover_all,
    _build_process_records_for_mapping,
    _sum_label_series_dict,
    _max_efficiency_ratio,
    _normalized_name_set,
    _apply_unallocated_policy,
    _infer_primary_economy,
    _sum_year_dicts,
    _sum_label_series,
    consolidate_transfer_output_rows,
    merge_transfer_rows,
    _merge_transfer_process_records,
    _consolidate_transfer_outputs,
)

# --- Configuration ---
TRANSFER_FLOW_CODES = [
    "08 Transfers",
    "08.01 Recycled products",
    "08.02 Interproduct transfers",
    "08.03 Products transferred",
    "08.99 Transfers nonspecified"
]

# Prefer subflows when they have nonzero data.
TRANSFER_SUBFLOWS = [
    "08.01 Recycled products",
    "08.02 Interproduct transfers",
    "08.03 Products transferred",
    "08.99 Transfers nonspecified"
]

# If True, filter subtotal rows immediately before transfer calculations.
DROP_SUBTOTALS_FIRST = True
DEFAULT_SCENARIOS = list(workflow_cfg.TRANSFERS_DEFAULT_SCENARIOS)
# FALLBACK ONLY — not the ID lookup. The workbook's economy resolves its own LEAP
# export template (each economy is a separate area with its own BranchIDs); this
# current USA export is used only for aggregate sentinels and economies with no
# template yet. Do not pass it as id_lookup_path to "be explicit": that is the
# `073c489` bypass, which made a routing fix a no-op in production for a day
# while its tests passed, because they pinned the template too.
EXPORT_ID_LOOKUP_PATH = leap_export_template_resolver.resolve_leap_export_template("20_USA")

# Category templates that help organize transfers when per-economy mappings are missing.
# These are broad, optional groupings based on the requested breakdowns.
TRANSFER_CATEGORY_TEMPLATES = [
    {
        "category": "Upstream liquids transfers",
        "inputs": [
            "08.01 Natural gas",
            "06.02 Natural gas liquids",
            "06.01 Crude oil",
            "06 Crude oil & NGL",
            "06.05 Other hydrocarbons",
        ],
        "outputs": [
            "07.09 LPG",
            "07.11 Ethane",
            "06.05 Other hydrocarbons",
        ],
    },
    {
        "category": "Refinery and blending transfers",
        "inputs": [
            "06.04 Additives/ oxygenates",
            "07.03 Naphtha",
            "07 Petroleum products",
            "07.17 Other products",
            "07.02 Aviation gasoline",
            "07.12 White spirit SBP",
            "07.13 Lubricants",
            "07.15 Paraffin  waxes",
            "07.08 Fuel oil",
            "07.06 Kerosene",
            "07.07 Gas/diesel oil",
            "07.14 Bitumen",
            "07.05 Kerosene type jet fuel",
            "07.09 LPG",
            "07.01 Motor gasoline",
            "07.16 Petroleum coke",
            "07.10 Refinery gas (not liquefied)",
        ],
        "outputs": [
            "07.13 Lubricants",
            "07.16 Petroleum coke",
            "07.02 Aviation gasoline",
            "07.10 Refinery gas (not liquefied)",
            "07.16 Petroleum coke",
            "07.01 Motor gasoline",
            "07.07 Gas/diesel oil",
            "07.05 Kerosene type jet fuel",
            "07.06 Kerosene",
            "07.08 Fuel oil",
            "07.14 Bitumen",
            "06.03 Refinery feedstocks",
            "07.03 Naphtha",
            "07.17 Other products",
            "07.15 Paraffin  waxes",
            "07.12 White spirit SBP",
        ],
    },
    {
        "category": "Transfers unallocated",
        "inputs": [],
        "outputs": [],
        "mode": "others",
    },
]

# Economy-specific mapping. Each entry is a list of process configs per flow.
# Replace these placeholders with real transfer groupings per economy.
# Note: When TRANSFER_CATEGORY_TEMPLATES changes, re-run
# `codebase/scrapbook/transfers_mapping_exploration.py` and paste the printed
# TRANSFER_PROCESS_CONFIG output here so categories stay aligned.
TRANSFER_PROCESS_CONFIG: dict[str, dict[str, list[dict]]] = {
    "00_APEC": {
        "transfer_flows_combined": [
            {
                "process": "Upstream liquids transfers",
                "inputs": [
                    "06.02 Natural gas liquids",
                    "06.05 Other hydrocarbons"
                ],
                "outputs": [
                    "06.01 Crude oil",
                    "07.09 LPG",
                    "07.11 Ethane"
                ]
            },
            {
                "process": "Refinery and blending transfers",
                "inputs": [
                    "06.04 Additives/ oxygenates",
                    "07.03 Naphtha",
                    "07.05 Kerosene type jet fuel",
                    "07.06 Kerosene",
                    "07.08 Fuel oil",
                    "07.12 White spirit SBP",
                    "07.14 Bitumen",
                    "07.15 Paraffin  waxes",
                    "07.17 Other products"
                ],
                "outputs": [
                    "07.01 Motor gasoline",
                    "07.02 Aviation gasoline",
                    "07.03 Naphtha",
                    "07.06 Kerosene",
                    "07.07 Gas/diesel oil",
                    "06.03 Refinery feedstocks",
                    "07.10 Refinery gas (not liquefied)",
                    "07.13 Lubricants",
                    "07.16 Petroleum coke"
                ]
            }
        ]
    },
    "01_AUS": {
        "transfer_flows_combined": [
            {
                "process": "Upstream & refinery transfers",
                "inputs": [
                    "06.02 Natural gas liquids"
                ],
                "outputs": [
                    "06.01 Crude oil",
                    "06.03 Refinery feedstocks",
                    "07.09 LPG",
                    "07.11 Ethane",
                    "07.17 Other products"
                ]
            }
        ]
    },
    "02_BD": {
        "transfer_flows_combined": [
            {
                "process": "Refinery and blending transfers",
                "inputs": [
                    "07.01 Motor gasoline",
                    "07.03 Naphtha"
                ],
                "outputs": [
                    "06.03 Refinery feedstocks",
                    "07.17 Other products"
                ]
            }
        ]
    },
    "03_CDA": {
        "transfer_flows_combined": [
            {
                "process": "Upstream liquids transfers",
                "inputs": [
                    "06.02 Natural gas liquids",
                    "06.05 Other hydrocarbons"
                ],
                "outputs": [
                    "07.09 LPG",
                    "07.11 Ethane"
                ]
            },
            {
                "process": "Refinery and blending transfers",
                "inputs": [
                    "06.04 Additives/ oxygenates",
                    "07.02 Aviation gasoline",
                    "07.03 Naphtha",
                    "07.05 Kerosene type jet fuel",
                    "07.08 Fuel oil",
                    "07.12 White spirit SBP",
                    "07.14 Bitumen",
                    "07.17 Other products"
                ],
                "outputs": [
                    "07.01 Motor gasoline",
                    "07.03 Naphtha",
                    "07.06 Kerosene",
                    "07.07 Gas/diesel oil",
                    "06.03 Refinery feedstocks",
                    "07.10 Refinery gas (not liquefied)",
                    "07.13 Lubricants",
                    "07.16 Petroleum coke"
                ]
            }
        ]
    },
    "04_CHL": {
        "transfer_flows_combined": [
            {
                "process": "Upstream & refinery transfers",
                "inputs": [
                    "06.02 Natural gas liquids",
                    "07.01 Motor gasoline",
                    "07.02 Aviation gasoline",
                    "07.03 Naphtha",
                    "07.05 Kerosene type jet fuel",
                    "07.06 Kerosene",
                    "07.07 Gas/diesel oil",
                    "07.08 Fuel oil",
                    "07.09 LPG",
                    "07.17 Other products"
                ],
                "outputs": [
                    "06.03 Refinery feedstocks"
                ]
            }
        ]
    },
    "08_JPN": {
        "transfer_flows_combined": [
            {
                "process": "Upstream & refinery transfers",
                "inputs": [
                    "06.05 Other hydrocarbons",
                    "07.05 Kerosene type jet fuel",
                    "07.06 Kerosene",
                    "07.08 Fuel oil",
                    "07.09 LPG",
                    "07.13 Lubricants",
                    "07.14 Bitumen",
                    "07.15 Paraffin  waxes",
                    "07.16 Petroleum coke"
                ],
                "outputs": [
                    "07.01 Motor gasoline",
                    "07.03 Naphtha",
                    "07.07 Gas/diesel oil",
                    "07.17 Other products"
                ]
            }
        ]
    },
    "09_ROK": {
        "transfer_flows_combined": [
            {
                "process": "Upstream & refinery transfers",
                "inputs": [
                    "06.04 Additives/ oxygenates",
                    "07.03 Naphtha",
                    "07.06 Kerosene",
                    "07.08 Fuel oil",
                    "07.12 White spirit SBP",
                    "07.13 Lubricants",
                    "07.15 Paraffin  waxes",
                    "07.17 Other products"
                ],
                "outputs": [
                    "06.03 Refinery feedstocks",
                    "07.01 Motor gasoline",
                    "07.02 Aviation gasoline",
                    "07.05 Kerosene type jet fuel",
                    "07.07 Gas/diesel oil",
                    "07.09 LPG",
                    "07.10 Refinery gas (not liquefied)",
                    "07.14 Bitumen",
                    "07.16 Petroleum coke"
                ]
            }
        ]
    },
    "11_MEX": {
        "transfer_flows_combined": [
            {
                "process": "Upstream liquids transfers",
                "inputs": [
                    "06.02 Natural gas liquids"
                ],
                "outputs": [
                    
                    "07.09 LPG",
                    "07.11 Ethane"
                ]
            },
            {
                "process": "Refinery and blending transfers",
                "inputs": [
                    "07.03 Naphtha"
                ],
                "outputs": [
                    "06.03 Refinery feedstocks",
                    "07.03 Naphtha",
                    "07.06 Kerosene"
                ]
            }
        ]
    },
    "12_NZ": {
        "transfer_flows_combined": [
            {
                "process": "Upstream liquids transfers",
                "inputs": [
                    "06.02 Natural gas liquids"
                ],
                "outputs": [
                    "07.09 LPG"
                ]
            },
            {
                "process": "Refinery and blending transfers",
                "inputs": [
                    "07.01 Motor gasoline",
                    "07.05 Kerosene type jet fuel",
                    "07.07 Gas/diesel oil",
                    "07.08 Fuel oil",
                    "07.14 Bitumen",
                    "07.17 Other products"
                ],
                "outputs": [
                    "06.03 Refinery feedstocks",
                    "07.03 Naphtha",
                    "07.06 Kerosene"
                ]
            }
        ]
    },
    "13_PNG": {
        "transfer_flows_combined": [
            {
                "process": "Upstream & refinery transfers",
                "inputs": [
                    "07.03 Naphtha",
                    "07.06 Kerosene"
                ],
                "outputs": [
                    "07.01 Motor gasoline",
                    "07.05 Kerosene type jet fuel"
                ]
            }
        ]
    },
    "14_PE": {
        "transfer_flows_combined": [
            {
                "process": "Upstream liquids transfers",
                "inputs": [
                    "06.02 Natural gas liquids"
                ],
                "outputs": [
                    "07.09 LPG"
                ]
            },
            {
                "process": "Refinery and blending transfers",
                "inputs": [
                    "07.05 Kerosene type jet fuel",
                    "07.07 Gas/diesel oil",
                    "07.08 Fuel oil"
                ],
                "outputs": [
                    "07.01 Motor gasoline",
                    "07.03 Naphtha",
                    "07.06 Kerosene",
                    "06.03 Refinery feedstocks",
                ]
            }
        ]
    },
    "18_CT": {
        "transfer_flows_combined": [
            {
                "process": "Upstream & refinery transfers",
                "inputs": [
                    "07.03 Naphtha",
                    "07.05 Kerosene type jet fuel",
                    "07.06 Kerosene",
                    "07.07 Gas/diesel oil",
                    "07.08 Fuel oil",
                    "06.03 Refinery feedstocks",
                    "07.12 White spirit SBP",
                    "07.13 Lubricants",
                    "07.09 LPG"
                ],
                "outputs": [
                    "06.04 Additives/ oxygenates",
                    "07.01 Motor gasoline",
                    "07.17 Other products"
                ]
            }
        ]
    },
    "20_USA": {
        # Previously split into "Upstream liquids transfers" and "Refinery and
        # blending transfers", but the refinery/blending category had a thin
        # input mapping (input_total ~33) against a much larger output pool,
        # producing an outlier ~25.6x efficiency ratio. Merged into a single
        # unallocated process so inputs/outputs balance against the full USA
        # transfer pool instead (~1.06x once combined).
        "transfer_flows_combined": [
            {
                "process": "Transfers unallocated",
                "inputs": [
                    "06.02 Natural gas liquids",
                    "06.04 Additives/ oxygenates",
                    "07.02 Aviation gasoline",
                    "07.06 Kerosene",
                    "07.08 Fuel oil"
                ],
                "outputs": [
                    "06.03 Refinery feedstocks",
                    "07.01 Motor gasoline",
                    "07.03 Naphtha",
                    "07.05 Kerosene type jet fuel",
                    "07.06 Kerosene",
                    "07.07 Gas/diesel oil",
                    "07.09 LPG",
                    "07.11 Ethane",
                    "07.14 Bitumen",
                    "07.17 Other products"
                ]
            }
        ],
    },
    "21_VN": {
        "transfer_flows_combined": [
            {
                "process": "Upstream & refinery transfers",
                "inputs": [
                    "06.02 Natural gas liquids"
                ],
                "outputs": [
                    "07.09 LPG"
                ]
            }
        ]
    }
}

TRANSFER_ECONOMY_CONFIG_ALIASES = {
    "ALL_ECONOMIES": "00_APEC",
}



def select_transfer_flows(
    data: pd.DataFrame, year_cols: list[int], economy: str
) -> list[str]:
    """Prefer subflows when they have data; fallback to aggregate."""
    subflow_hits = []
    for flow_code in TRANSFER_SUBFLOWS:
        rows = core.select_flow_rows(data, economy, flow_code)
        if _flow_has_nonzero(rows, year_cols):
            subflow_hits.append(flow_code)
    if subflow_hits:
        return subflow_hits
    aggregate_rows = core.select_flow_rows(data, economy, "08 Transfers")
    if _flow_has_nonzero(aggregate_rows, year_cols):
        return ["08 Transfers"]
    return []


def _route_transfer_projection_to_historical_flow(
    projection_df: pd.DataFrame,
    historical_transfer_data: pd.DataFrame,
    base_year: int,
) -> pd.DataFrame:
    """Route generic ``08 Transfers`` projections to an active ESTO subflow.

    The canonical 9th-to-ESTO crosswalk intentionally targets ``08 Transfers``.
    ESTO history, however, commonly records the same values in one of its
    transfer subflows (for USA this is ``08.99 Transfers nonspecified``).  Use
    the largest absolute base-year subflow as the destination so the existing
    transfer-process configuration continues to see one coherent time series.
    """
    if projection_df.empty or historical_transfer_data.empty:
        return projection_df
    if base_year not in historical_transfer_data.columns:
        return projection_df
    working = projection_df.copy()
    history = historical_transfer_data.copy()
    history[base_year] = pd.to_numeric(history[base_year], errors="coerce").fillna(0.0)
    history["flows"] = history["flows"].astype(str).str.strip()
    history["economy_key"] = history["economy"].apply(normalize_economy_key)
    subflow_history = history[history["flows"].isin(TRANSFER_SUBFLOWS)]
    if subflow_history.empty:
        return working
    flow_scores = (
        subflow_history.groupby(["economy_key", "flows"], dropna=False)[base_year]
        .apply(lambda values: values.abs().sum())
        .reset_index(name="base_year_abs")
    )
    preferred_flows = (
        flow_scores.sort_values(["economy_key", "base_year_abs", "flows"], ascending=[True, False, True])
        .drop_duplicates("economy_key")
    )
    preferred_lookup = dict(
        zip(preferred_flows["economy_key"], preferred_flows["flows"])
    )
    canonical_mask = working["esto_flow"].astype(str).str.strip().eq("08 Transfers")
    working.loc[canonical_mask, "esto_flow"] = working.loc[
        canonical_mask, "economy_key"
    ].map(preferred_lookup).fillna("08 Transfers")
    return working


def _build_transfer_projection_profile_history(
    historical_transfer_data: pd.DataFrame,
    base_year: int,
) -> pd.DataFrame:
    """Roll active transfer subflows up before allocating 9th fuel projections.

    The maintained 9th crosswalk targets the parent ``08 Transfers`` flow, while
    ESTO commonly stores the economy's product profile under a child such as
    ``08.99 Transfers nonspecified``.  The projection allocator must see that
    child profile at the parent flow before it allocates one 9th fuel across
    several possible ESTO products.  Otherwise it has no base-year evidence and
    falls back to equal shares.
    """
    if historical_transfer_data.empty:
        return historical_transfer_data.copy()
    year_col = (
        base_year
        if base_year in historical_transfer_data.columns
        else str(base_year)
    )
    if year_col not in historical_transfer_data.columns:
        return historical_transfer_data.copy()

    working = historical_transfer_data.copy()
    working["economy_key"] = working["economy"].apply(normalize_economy_key)
    working[year_col] = pd.to_numeric(
        working[year_col], errors="coerce"
    ).fillna(0.0)
    flow_names = working["flows"].astype(str).str.strip()
    subflow_mask = flow_names.isin(TRANSFER_SUBFLOWS)
    active_subflow_economies = set(
        working.loc[subflow_mask]
        .groupby("economy_key", dropna=False)[year_col]
        .apply(lambda values: values.abs().sum())
        .loc[lambda totals: totals > 0]
        .index
    )
    if not active_subflow_economies:
        return working.drop(columns=["economy_key"])

    active_economy_mask = working["economy_key"].isin(active_subflow_economies)
    parent_mask = flow_names.eq("08 Transfers")
    working = working.loc[~(active_economy_mask & parent_mask)].copy()
    rolled_subflow_mask = (
        working["economy_key"].isin(active_subflow_economies)
        & working["flows"].astype(str).str.strip().isin(TRANSFER_SUBFLOWS)
    )
    working.loc[rolled_subflow_mask, "flows"] = "08 Transfers"
    return working.drop(columns=["economy_key"])


def classify_transfer_projection_availability(
    historical_transfer_data: pd.DataFrame,
    ninth_transfer_data: pd.DataFrame,
    scenario: str,
    base_year: int,
    projection_years: Sequence[int],
) -> pd.DataFrame:
    """Classify raw 9th transfer coverage before missing values become zeroes."""
    columns = [
        "economy", "scenario", "esto_base_year_transfer_mass",
        "ninth_rows_present", "projection_nonzero_year_count",
        "projection_availability",
    ]
    if historical_transfer_data.empty:
        return pd.DataFrame(columns=columns)

    history = historical_transfer_data.copy()
    history["economy_key"] = history["economy"].apply(normalize_economy_key)
    base_column = base_year if base_year in history.columns else str(base_year)
    history["_base_mass"] = pd.to_numeric(
        history[base_column], errors="coerce"
    ).fillna(0.0).abs() if base_column in history.columns else 0.0
    base_mass = history.groupby("economy_key", dropna=False)["_base_mass"].sum()

    ninth = ninth_transfer_data.copy()
    if "scenarios" in ninth.columns:
        ninth = ninth.loc[
            ninth["scenarios"].astype(str).str.strip().str.lower().eq(str(scenario).strip().lower())
        ].copy()
    if "subtotal_results" in ninth.columns:
        ninth = ninth.loc[ninth["subtotal_results"].eq(False)].copy()
    ninth["economy_key"] = ninth["economy"].apply(normalize_economy_key)
    available_years = [year for year in projection_years if year in ninth.columns]
    if available_years:
        absolute_projection_mass = ninth[available_years].apply(
            pd.to_numeric, errors="coerce"
        ).fillna(0.0).abs()
        absolute_projection_mass["economy_key"] = ninth["economy_key"].to_numpy()
        nonzero_years = absolute_projection_mass.groupby(
            "economy_key", dropna=False
        )[available_years].sum().ne(0.0).sum(axis=1)
    else:
        nonzero_years = pd.Series(dtype=int)
    ninth_rows = ninth.groupby("economy_key", dropna=False).size()
    economy_labels = history.groupby("economy_key", dropna=False)["economy"].first()

    records: list[dict] = []
    for economy_key, economy in economy_labels.items():
        esto_mass = float(base_mass.get(economy_key, 0.0))
        has_ninth_rows = bool(ninth_rows.get(economy_key, 0) > 0)
        nonzero_count = int(nonzero_years.get(economy_key, 0))
        state = (
            "no_ninth_rows" if not has_ninth_rows else
            "structural_zero" if esto_mass == 0.0 else
            "projection_supplied" if nonzero_count > 0 else
            "projection_unavailable"
        )
        records.append({
            "economy": economy,
            "scenario": str(scenario),
            "esto_base_year_transfer_mass": esto_mass,
            "ninth_rows_present": has_ninth_rows,
            "projection_nonzero_year_count": nonzero_count,
            "projection_availability": state,
        })
    return pd.DataFrame(records, columns=columns)


def apply_transfer_projection_fallback(
    transfer_data: pd.DataFrame,
    availability: pd.DataFrame,
    base_year: int,
    projection_years: Sequence[int],
) -> pd.DataFrame:
    """Carry the ESTO base year forward only when transfer projection is unavailable."""
    if transfer_data.empty or availability.empty:
        return transfer_data
    unavailable = set(availability.loc[
        availability["projection_availability"].eq("projection_unavailable"), "economy"
    ].map(normalize_economy_key))
    if not unavailable:
        return transfer_data
    working = transfer_data.copy()
    base_column = base_year if base_year in working.columns else str(base_year)
    if base_column not in working.columns:
        return working
    mask = working["economy"].map(normalize_economy_key).isin(unavailable)
    for year in projection_years:
        if year in working.columns:
            working.loc[mask, year] = working.loc[mask, base_column]
    return working


def build_transfer_data_for_scenario(
    scenario: str,
    return_projection_availability: bool = False,
) -> tuple[pd.DataFrame, list[int]] | tuple[pd.DataFrame, list[int], pd.DataFrame]:
    """Build transfer-only data with ESTO history and scenario-specific 9th projections."""
    if core.esto_data_raw is None or core.ninth_data_raw is None:
        core.prepare_transformation_assets()
    historical = core.esto_data_raw.copy()
    historical["flows"] = historical["flows"].astype(str).str.strip()
    historical = historical[historical["flows"].isin(TRANSFER_FLOW_CODES)].copy()
    if historical.empty:
        return historical, []

    ninth_transfer_data = core.ninth_data_raw[
        core.ninth_data_raw["sectors"].astype(str).str.strip().eq("08_transfers")
    ].copy()
    # Transfers previously passed strict_conservation=False, i.e. it never ran the
    # conservation check at all. Unified 2026-07-16 onto the repo-wide policy
    # (warn by default). If transfers legitimately cannot conserve by
    # construction, this will warn on every projection -- say so and exempt it
    # rather than reverting the whole policy.
    projection_profile_history = _build_transfer_projection_profile_history(
        historical,
        core.BASE_YEAR,
    )
    projection_df, projection_diagnostics = build_with_conservation_policy(
        f"transfers projection (scenario={scenario!r})",
        lambda strict_conservation: core.build_esto_projection_table(
            ninth_data=ninth_transfer_data,
            esto_data=projection_profile_history,
            mapping_path=core.NINTH_TO_ESTO_MAPPING_PATH,
            base_year=core.BASE_YEAR,
            projection_years=core.PROJECTION_YEAR_RANGE,
            scenario=scenario,
            sign_stable_flows="all",
            strict_conservation=strict_conservation,
            fill_missing_ninth_sectors=workflow_cfg.FILL_IN_MISSING_9TH_SECTORS,
            owner_workflow="transfers_workflow",
        ),
    )
    if projection_diagnostics is not None and not projection_diagnostics.empty:
        diagnostic_path = (
            Path(core.EXPORT_OUTPUT_DIR)
            / f"transfer_projection_diagnostics_{str(scenario).strip().lower()}.csv"
        )
        diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
        projection_diagnostics.to_csv(diagnostic_path, index=False)
        print(f"Saved transfer projection diagnostics to {diagnostic_path}")
    projection_df = _route_transfer_projection_to_historical_flow(
        projection_df,
        historical,
        core.BASE_YEAR,
    )
    availability = classify_transfer_projection_availability(
        historical, ninth_transfer_data, scenario, core.BASE_YEAR, core.PROJECTION_YEAR_RANGE
    )
    transfer_data = core.merge_projection_into_esto(
        historical,
        projection_df,
        core.PROJECTION_YEAR_RANGE,
    )
    transfer_data = apply_transfer_projection_fallback(
        transfer_data, availability, core.BASE_YEAR, core.PROJECTION_YEAR_RANGE
    )
    year_cols = sorted(column for column in transfer_data.columns if str(column).isdigit())
    if return_projection_availability:
        return transfer_data, year_cols, availability
    return transfer_data, year_cols


def _normalize_transfer_process_name(process_config: dict, flow_code: str) -> str:
    """Return a standardized process name aligned to the three transfer categories."""
    raw = (
        process_config.get("category")
        or process_config.get("process")
        or flow_code
    )
    text = str(raw).strip()
    lowered = text.lower()
    if "upstream" in lowered and ("refinery" in lowered or "blending" in lowered):
        return TRANSFER_PROCESS_NAMES["unallocated"]
    if "upstream" in lowered:
        return TRANSFER_PROCESS_NAMES["upstream_liquids"]
    if "refinery" in lowered or "blending" in lowered:
        return TRANSFER_PROCESS_NAMES["refinery_blending"]
    return text


def balance_one_sided_transfer_flow(
    flow_rows: pd.DataFrame,
    year_cols: list[int],
    economy: str,
    flow_code: str,
    policy: dict | None = None,
) -> tuple[pd.DataFrame, dict | None]:
    """Add a nominal counterpart to a transfer flow that only has one sign.

    A transfer flow whose products all leave (or all arrive) cannot become a
    LEAP process, because a process needs both a feedstock and an output. Where
    that happens, append one row carrying ``counterpart_value`` on the empty
    side in every year that is one-sided, leaving every measured value exactly
    as ESTO records it.

    Returns ``(rows, diagnostic)``. ``diagnostic`` is ``None`` when the flow was
    already two-sided or the policy is disabled, so callers can report only the
    flows they actually changed.
    """
    policy = policy if policy is not None else ONE_SIDED_TRANSFER_BALANCE_POLICY
    if not isinstance(policy, dict) or not policy.get("enabled", False):
        return flow_rows, None
    if flow_rows is None or flow_rows.empty:
        return flow_rows, None

    present_years = [year for year in year_cols if year in flow_rows.columns]
    if not present_years:
        return flow_rows, None

    values = flow_rows[present_years].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    negative_by_year = values.clip(upper=0.0).sum(axis=0)
    positive_by_year = values.clip(lower=0.0).sum(axis=0)

    # A year needs a counterpart only when it has mass on exactly one side.
    has_negative = negative_by_year.abs() > 1e-9
    has_positive = positive_by_year.abs() > 1e-9
    needs_output = has_negative & ~has_positive
    needs_input = has_positive & ~has_negative
    if not bool(needs_output.any() or needs_input.any()):
        return flow_rows, None

    input_year_list = [year for year in present_years if needs_input.get(year, False)]
    counterpart_value = _auto_balance_value(
        positive_by_year[input_year_list] if input_year_list else None, policy
    )
    product = str(policy.get("product") or AUTO_BALANCE_PRODUCT_LABEL)

    template = flow_rows.iloc[0].copy()
    for column in present_years:
        template[column] = 0.0
    for column, value in (("products", product), ("subfuels", "x")):
        if column in flow_rows.columns:
            template[column] = value
    if "fuels" in flow_rows.columns:
        template["fuels"] = product
    for column in ("is_subtotal", "subtotal_layout", "subtotal_results"):
        if column in flow_rows.columns:
            template[column] = False

    for year in present_years:
        if bool(needs_output.get(year, False)):
            template[year] = counterpart_value
        elif bool(needs_input.get(year, False)):
            template[year] = -counterpart_value

    balanced = pd.concat(
        [flow_rows, pd.DataFrame([template], columns=flow_rows.columns)],
        ignore_index=True,
    )
    input_years = input_year_list
    max_implied_efficiency_percent = None
    if input_years and counterpart_value:
        max_implied_efficiency_percent = float(
            positive_by_year[input_years].abs().max() / abs(counterpart_value) * 100.0
        )
    diagnostic = {
        "economy": economy,
        "flow_code": flow_code,
        "counterpart_product": product,
        "counterpart_value": counterpart_value,
        "output_years_added": sorted(int(y) for y in present_years if needs_output.get(y, False)),
        "input_years_added": sorted(int(y) for y in input_years),
        "measured_side": "outflow_only" if bool(needs_output.any()) else "inflow_only",
        "max_implied_efficiency_percent": max_implied_efficiency_percent,
    }
    return balanced, diagnostic


def _report_one_sided_transfer_balance(diagnostic: dict) -> None:
    """Print a synthesized-counterpart notice, including the efficiency risk."""
    years = diagnostic["output_years_added"] or diagnostic["input_years_added"]
    span = f"{years[0]}-{years[-1]}" if years else "none"
    print(
        f"[INFO] One-sided transfer flow {diagnostic['flow_code']} for "
        f"{diagnostic['economy']} ({diagnostic['measured_side']}): added "
        f"{diagnostic['counterpart_value']:,.4g} PJ of "
        f"'{diagnostic['counterpart_product']}' for {span} so the flow can form a "
        "LEAP process. Measured values are unchanged."
    )
    # Inflow-only counterparts are sized against the efficiency ceiling rather
    # than left at the floor, so this should never exceed it. Report it anyway:
    # if it ever does, the sizing is wrong and the measured output gets clipped.
    implied_percent = diagnostic.get("max_implied_efficiency_percent")
    if implied_percent is None:
        return
    ceiling = float(
        getattr(workflow_cfg, "TRANSFORMATION_PROCESS_EFFICIENCY_MAX_PERCENT", 1000.0)
    )
    clipping_on = bool(
        getattr(workflow_cfg, "TRANSFORMATION_CLIP_PROCESS_EFFICIENCY_TO_MAX", True)
    )
    if clipping_on and implied_percent > ceiling + 1e-6:
        print(
            f"[WARN] {diagnostic['economy']} {diagnostic['flow_code']}: implied process "
            f"efficiency {implied_percent:,.0f}% still exceeds the ceiling of "
            f"{ceiling:,.0f}% after auto-sizing the counterpart. The measured output "
            "will be clipped — this indicates a sizing bug, not a data problem."
        )


def _build_template_processes(
    flow_rows: pd.DataFrame,
    year_cols: list[int],
    start_year: int,
) -> list[dict]:
    """Create process configs from category templates using nonzero products."""
    totals, _ = core.summarize_fuel_totals(
        flow_rows, year_cols, start_year, allow_all_years_fallback=True
    )
    processes: list[dict] = []
    matched_inputs: set[str] = set()
    matched_outputs: set[str] = set()
    for template in TRANSFER_CATEGORY_TEMPLATES:
        if template.get("mode") == "others":
            continue
        inputs = [
            label for label in template["inputs"] if totals.get(label, 0.0) < 0
        ]
        outputs = [
            label for label in template["outputs"] if totals.get(label, 0.0) > 0
        ]
        if not inputs or not outputs:
            continue
        matched_inputs.update(inputs)
        matched_outputs.update(outputs)
        processes.append(
            {
                "process": template["category"],
                "category": template["category"],
                "inputs": inputs,
                "outputs": outputs,
            }
        )
    others_template = next(
        (template for template in TRANSFER_CATEGORY_TEMPLATES if template.get("mode") == "others"),
        None,
    )
    if others_template is not None:
        other_inputs = [
            label
            for label, value in totals.items()
            if value < 0 and label not in matched_inputs
        ]
        other_outputs = [
            label
            for label, value in totals.items()
            if value > 0 and label not in matched_outputs
        ]
        if other_inputs and other_outputs:
            processes.append(
                {
                    "process": others_template["category"],
                    "category": others_template["category"],
                    "inputs": other_inputs,
                    "outputs": other_outputs,
                }
            )
    if not _template_processes_cover_all(totals, processes):
        return []
    return processes




def build_transfer_rows(
    economy: str,
    sector_title: str = "Transfers",
    start_year: int = core.YEAR_START_FOR_ANALYSIS,
    process_config: dict | None = None,
    use_output_targets: bool = False,
    feedstock_method: str | None = None,
    data_override: pd.DataFrame | None = None,
    year_cols_override: list[int] | None = None,
    scenario: str | None = None,
    projection_availability_out: list[pd.DataFrame] | None = None,
) -> list[dict]:
    """Return transfer rows for the given economy."""
    if data_override is not None:
        data = data_override
    elif scenario is not None:
        data, year_cols_override, availability = build_transfer_data_for_scenario(
            scenario,
            return_projection_availability=True,
        )
        if projection_availability_out is not None:
            projection_availability_out.append(availability)
    else:
        data = core.esto_data
    if DROP_SUBTOTALS_FIRST:
        data = core.filter_matt_subtotals(data)
        data = core.filter_total_energy_rows(data)
    year_cols = year_cols_override or core.esto_year_cols
    records: list[dict] = []
    flow_codes = select_transfer_flows(data, year_cols, economy)
    if not flow_codes:
        print(f"No nonzero transfer flows for {economy}.")
        return records
    config_source = process_config or TRANSFER_PROCESS_CONFIG
    economy_config = config_source.get(economy)
    if not economy_config:
        alias = TRANSFER_ECONOMY_CONFIG_ALIASES.get(economy)
        if alias:
            economy_config = config_source.get(alias, {})
    if economy_config is None:
        economy_config = {}
    unallocated_policy = economy_config.get("unallocated_policy", DEFAULT_TRANSFER_UNALLOCATED_POLICY)

    def _sector_title_for_process(process_cfg: dict, fallback_flow_code: str) -> str:
        if not SPLIT_TRANSFER_SECTORS:
            return str(sector_title)
        return _normalize_transfer_process_name(process_cfg, fallback_flow_code)
    handled_flows: set[str] = set()
    combined_processes = economy_config.get(TRANSFER_COMBINED_FLOW_KEY)
    if combined_processes:
        combined_rows = _combine_flow_rows(data, economy, flow_codes)
        # Same one-sided guard as the per-flow branch below. Economies with a
        # `transfer_flows_combined` config never reach that loop, so without
        # this they keep the silent no-process behaviour (e.g. 13_PNG).
        combined_rows, combined_one_sided = balance_one_sided_transfer_flow(
            combined_rows, year_cols, economy, TRANSFER_COMBINED_FLOW_KEY
        )
        if combined_one_sided is not None:
            _report_one_sided_transfer_balance(combined_one_sided)
        if not combined_rows.empty:
            for process_cfg in combined_processes:
                records.extend(
                    _build_process_records_for_mapping(
                        combined_rows,
                        year_cols,
                        start_year,
                        economy,
                        TRANSFER_COMBINED_FLOW_KEY,
                        process_cfg,
                        _sector_title_for_process(process_cfg, TRANSFER_COMBINED_FLOW_KEY),
                        normalize_process_name_fn=_normalize_transfer_process_name,
                        use_output_targets=use_output_targets,
                        feedstock_method=feedstock_method,
                    )
                )
            if records:
                handled_flows.update(flow_codes)
    for flow_code in flow_codes:
        if flow_code in handled_flows:
            continue
        flow_rows = core.select_flow_rows(data, economy, flow_code)
        if flow_rows.empty:
            continue
        # A one-sided flow cannot form a process; give it a nominal counterpart
        # before any process config or template sees it.
        flow_rows, one_sided_diagnostic = balance_one_sided_transfer_flow(
            flow_rows, year_cols, economy, flow_code
        )
        if one_sided_diagnostic is not None:
            _report_one_sided_transfer_balance(one_sided_diagnostic)
        flow_processes = economy_config.get(flow_code)
        if not flow_processes:
            flow_processes = _build_template_processes(flow_rows, year_cols, start_year)
        if not flow_processes:
            # Final fallback: treat all positives as outputs, all negatives as inputs.
            totals, _ = core.summarize_fuel_totals(
                flow_rows, year_cols, start_year, allow_all_years_fallback=True
            )
            negatives = [label for label, value in totals.items() if value < 0]
            positives = [label for label, value in totals.items() if value > 0]
            flow_processes = [
                {
                    "process": TRANSFER_PROCESS_NAMES["unallocated"],
                    "inputs": negatives,
                    "outputs": positives,
                }
            ]
        for process_cfg in flow_processes:
            records.extend(
                _build_process_records_for_mapping(
                    flow_rows,
                    year_cols,
                    start_year,
                    economy,
                    flow_code,
                    process_cfg,
                    _sector_title_for_process(process_cfg, flow_code),
                    normalize_process_name_fn=_normalize_transfer_process_name,
                    use_output_targets=use_output_targets,
                    feedstock_method=feedstock_method,
                )
            )
    return _apply_unallocated_policy(records, unallocated_policy)


def save_transfer_export(
    process_records: list[dict],
    scenarios: list[str] | None = None,
    output_dir: str | None = None,
    filename_template: str | None = None,
    id_lookup_path: Path | str | None = None,
) -> str | None:
    """Save a LEAP export workbook for transfer process records."""
    if not process_records:
        print("No transfer rows to export.")
        return None
    scenario_list = workflow_common.normalize_workflow_scenarios(
        scenarios,
        DEFAULT_SCENARIOS,
    )
    economy = process_records[0].get("economy", "economy")
    output_dir = output_dir or core.EXPORT_OUTPUT_DIR
    filename = (filename_template or EXPORT_FILENAME_TEMPLATE).format(
        economy=core.format_filename_segment(economy),
        scenario=core.format_filename_segment("_".join(scenario_list)),
    )
    return core.save_transformation_export(
        process_records,
        core.EXPORT_REGION,
        core.EXPORT_BASE_YEAR,
        core.EXPORT_FINAL_YEAR,
        core.code_to_name_mapping,
        output_dir,
        filename,
        core.EXPORT_MODEL_NAME,
        scenario_list,
        # None means "resolve this workbook's own economy" — same `economy` the
        # filename is built from, so the IDs and the name cannot disagree.
        id_lookup_path=(
            id_lookup_path
            if id_lookup_path is not None
            else leap_export_template_resolver.resolve_leap_export_template_or_fallback(
                economy,
                fallback=EXPORT_ID_LOOKUP_PATH,
            )
        ),
    )

def format_export_filename(
    economy_label: str,
    scenarios: Sequence[str],
    template: str | None = None,
) -> str:
    template = template or EXPORT_FILENAME_TEMPLATE
    return leap_exports.build_workbook_filename(
        economy_label=economy_label,
        scenarios=scenarios,
        template=template,
        fallback_template=EXPORT_FILENAME_TEMPLATE,
    )



def assemble_transfer_workbook(
    economies: Iterable[str] | None = None,
    scenarios: Sequence[str] | None = None,
    export_output_dir: Path | str | None = None,
    filename_template: str | None = None,
    process_config: dict | None = None,
    start_year: int = core.YEAR_START_FOR_ANALYSIS,
    include_output_series: bool = False,
    use_output_targets: bool = False,
    feedstock_method: str | None = None,
    aggregate_economy_label: str | None = None,
    id_lookup_path: Path | str | None = None,
    build_export: bool = core.BUILD_LEAP_EXPORT,
    full_branch_catalog_df: pd.DataFrame | None = None,
    in_scope_sector_titles: set[str] | None = None,
) -> list[Path]:
    """Build transfer rows and emit the LEAP workbook.

    Pass full_branch_catalog_df (+ in_scope_sector_titles) to zero-fill every
    catalog branch owned by the transfers workbook, matching what the full
    supply reconciliation run produces via save_transfer_exports_with_supply_overrides.
    """
    if not build_export:
        print("BUILD_LEAP_EXPORT is False; skipping workbook generation.")
        return []
    economy_list = workflow_common.normalize_economies(economies or core.ECONOMIES_TO_ANALYZE)
    should_aggregate, aggregate_label, _ = workflow_common.resolve_aggregate_economy(
        economy_list,
        aggregate_label=aggregate_economy_label or workflow_cfg.TRANSFERS_AGGREGATE_ECONOMY_LABEL,
    )
    data_override = None
    year_cols_override = None
    previous_import_export_data = None
    previous_import_export_years = None
    import_export_override = False
    if should_aggregate:
        data_override = core.add_all_economy_total(
            core.esto_data,
            core.esto_year_cols,
            aggregate_label,
        )
        year_cols_override = core.esto_year_cols
        economy_list = [aggregate_label]
    rows: list[dict] = []
    original_feedstock_method = core.FEEDSTOCK_METHOD
    if feedstock_method is not None:
        core.FEEDSTOCK_METHOD = core.resolve_feedstock_method(feedstock_method)
    try:
        if should_aggregate and use_output_targets:
            previous_import_export_data = core.ESTO_IMPORT_EXPORT_REFERENCE_DATA
            previous_import_export_years = core.ESTO_IMPORT_EXPORT_YEAR_COLS
            core.ESTO_IMPORT_EXPORT_REFERENCE_DATA = data_override
            core.ESTO_IMPORT_EXPORT_YEAR_COLS = year_cols_override or core.esto_year_cols
            import_export_override = True
        for economy in economy_list:
            rows.extend(
                build_transfer_rows(
                    economy,
                    start_year=start_year,
                    process_config=process_config,
                    use_output_targets=use_output_targets,
                    feedstock_method=core.FEEDSTOCK_METHOD,
                    data_override=data_override,
                    year_cols_override=year_cols_override,
                )
            )
    finally:
        if import_export_override:
            core.ESTO_IMPORT_EXPORT_REFERENCE_DATA = previous_import_export_data
            core.ESTO_IMPORT_EXPORT_YEAR_COLS = previous_import_export_years
        core.FEEDSTOCK_METHOD = original_feedstock_method
    if not rows:
        print("No transfer rows were generated; nothing to export.")
        return []
    rows = merge_transfer_rows(rows)
    consolidate_transfer_output_rows(rows, include_output_series, use_output_targets)
    scenario_list = workflow_common.normalize_workflow_scenarios(
        scenarios,
        DEFAULT_SCENARIOS,
    )
    output_dir_path = Path(export_output_dir or core.EXPORT_OUTPUT_DIR)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    economy_label = _infer_primary_economy(rows)
    export_filename = format_export_filename(economy_label, scenario_list, filename_template)
    previous_output_setting = core.INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT
    previous_output_config = dict(core.TRANSFORMATION_OUTPUT_VARIABLES)
    core.INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT = bool(include_output_series)
    core.TRANSFORMATION_OUTPUT_VARIABLES["output"] = bool(include_output_series)
    core.TRANSFORMATION_OUTPUT_VARIABLES["output_import_target"] = bool(use_output_targets)
    core.TRANSFORMATION_OUTPUT_VARIABLES["output_export_target"] = bool(use_output_targets)
    try:
        export_path = core.save_transformation_export(
            rows,
            core.EXPORT_REGION,
            core.EXPORT_BASE_YEAR,
            core.EXPORT_FINAL_YEAR,
            core.code_to_name_mapping,
            str(output_dir_path),
            export_filename,
            core.EXPORT_MODEL_NAME,
            scenario_list,
            # None means "resolve this workbook's own economy" (economy_label,
            # the same value the filename uses).
            id_lookup_path=(
                id_lookup_path
                if id_lookup_path is not None
                else leap_export_template_resolver.resolve_leap_export_template_or_fallback(
                    economy_label,
                    fallback=EXPORT_ID_LOOKUP_PATH,
                )
            ),
            full_branch_catalog_df=full_branch_catalog_df,
            in_scope_sector_titles=in_scope_sector_titles,
        )
    finally:
        core.INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT = previous_output_setting
        core.TRANSFORMATION_OUTPUT_VARIABLES = previous_output_config
    if export_path:
        try:
            workflow_common.diagnose_missing_canonical_branches(
                export_path=Path(export_path),
                sheet_name=SHEET_NAME,
                workflow_name="transfers_workflow",
            )
        except Exception as exc:
            print(f"[WARN] transfers_workflow: canonical-branch diagnostic failed: {exc}")
    return [Path(export_path)] if export_path else []


def _read_unique_column(export_path: Path, column: str) -> list[str]:
    for header in (2, 0):
        try:
            df = pd.read_excel(
                export_path, sheet_name=SHEET_NAME, header=header, usecols=[column]
            )
        except Exception:
            continue
        if column not in df.columns:
            continue
        seen: list[str] = []
        for value in df[column].dropna().astype(str):
            if value not in seen:
                seen.append(value)
        if seen:
            return seen
    return []


def list_export_scenarios(export_path: Path) -> list[str]:
    return leap_exports.list_scenarios(export_path, sheet_name=SHEET_NAME)


def validate_export_region(export_path: Path, region: str) -> None:
    return leap_exports.validate_region(export_path, region, sheet_name=SHEET_NAME)


def find_transfer_workbook(
    directory: Path | str | None = None, filename: str | None = None
) -> Path:
    directory_path = Path(directory or core.EXPORT_OUTPUT_DIR)
    return leap_exports.find_workbook(
        directory=directory_path,
        prefix=EXPORT_FILENAME_PREFIX,
        filename=filename,
    )


def import_transfer_workbook_to_leap(
    export_directory: Path | str | None = None,
    filename: str | None = None,
    scenario_to_run: str | None = None,
    region: str | None = None,
    include_current_accounts: bool = False,
    create_branches: bool = True,
    fill_branches: bool = True,
    raise_on_missing_branch: bool = False,
) -> Path:
    """Connect to LEAP, create branches, and fill data from the transfer export."""
    if (
        str(scenario_to_run or "").strip().lower() in {"current accounts", "current account"}
        and not include_current_accounts
    ):
        raise ValueError(
            "Direct transfer LEAP import for 'Current Accounts' is disabled "
            "unless include_current_accounts=True is passed explicitly."
        )
    export_path = find_transfer_workbook(export_directory, filename)
    target_region = region or core.EXPORT_REGION
    return leap_api.import_workbook(
        export_path=export_path,
        sheet_name=SHEET_NAME,
        scenario=scenario_to_run,
        region=target_region,
        create_branches=create_branches,
        fill_branches=fill_branches,
        include_current_accounts=include_current_accounts,
        default_branch_type=(
            BRANCH_DEMAND_CATEGORY,
            BRANCH_DEMAND_CATEGORY,
            BRANCH_DEMAND_TECHNOLOGY,
        ),
        raise_on_missing_branch=raise_on_missing_branch,
    )


def run_transfer_export_and_import(
    economies: Iterable[str] | None = None,
    scenarios: Sequence[str] | None = None,
    include_leap_import: bool = False,
    import_scenario: str | Sequence[str] | None = None,
    region: str | None = None,
    handle_current_accounts: bool = True,
    create_branches: bool = True,
    fill_branches: bool = True,
    aggregate_economy_label: str | None = None,
    id_lookup_path: Path | str | None = None,
    feedstock_method: str | None = None,
    **export_kwargs,
) -> list[Path]:
    """Run exports and optionally push the workbook into LEAP."""
    _print_reset_reminder_for_import(include_leap_import)
    exports = assemble_transfer_workbook(
        economies=economies,
        scenarios=scenarios,
        export_output_dir=export_kwargs.get("export_output_dir"),
        filename_template=export_kwargs.get("filename_template"),
        process_config=export_kwargs.get("process_config"),
        start_year=export_kwargs.get("start_year", core.YEAR_START_FOR_ANALYSIS),
        include_output_series=export_kwargs.get("include_output_series", False),
        use_output_targets=export_kwargs.get("use_output_targets", False),
        feedstock_method=feedstock_method,
        aggregate_economy_label=aggregate_economy_label,
        id_lookup_path=export_kwargs.get("id_lookup_path", id_lookup_path),
        build_export=export_kwargs.get("build_export", core.BUILD_LEAP_EXPORT),
    )
    if not exports or not include_leap_import:
        return exports
    scenario_list = workflow_common.normalize_workflow_scenarios(
        scenarios,
        DEFAULT_SCENARIOS,
    )
    scenario_choices = workflow_common.resolve_import_scenarios(
        scenario_list,
        import_scenario,
    )
    if get_analysis_input_write_mode() == "api" and not LEAP_API_AVAILABLE:
        print("[INFO] LEAP API unavailable in this environment; skipping branch creation/fill.")
        return exports
    for index, scenario_choice in enumerate(scenario_choices):
        import_transfer_workbook_to_leap(
            export_directory=exports[0].parent,
            filename=exports[0].name,
            scenario_to_run=scenario_choice,
            region=region or core.EXPORT_REGION,
            include_current_accounts=handle_current_accounts and index == 0,
            create_branches=create_branches and index == 0,
            fill_branches=fill_branches,
        )
    return exports


# Legacy names kept for compatibility.
def build_transfer_process_records(
    economy: str,
    sector_title: str = "Transfers",
    start_year: int = core.YEAR_START_FOR_ANALYSIS,
    process_config: dict | None = None,
    use_output_targets: bool = False,
    data_override: pd.DataFrame | None = None,
    year_cols_override: list[int] | None = None,
    scenario: str | None = None,
    projection_availability_out: list[pd.DataFrame] | None = None,
) -> list[dict]:
    return build_transfer_rows(
        economy=economy,
        sector_title=sector_title,
        start_year=start_year,
        process_config=process_config,
        use_output_targets=use_output_targets,
        data_override=data_override,
        year_cols_override=year_cols_override,
        scenario=scenario,
        projection_availability_out=projection_availability_out,
    )


def prepare_transfer_exports(
    economies: Iterable[str] | None = None,
    scenarios: Sequence[str] | None = None,
    export_output_dir: Path | str | None = None,
    filename_template: str | None = None,
    process_config: dict | None = None,
    start_year: int = core.YEAR_START_FOR_ANALYSIS,
    include_output_series: bool = False,
    use_output_targets: bool = False,
    feedstock_method: str | None = None,
    aggregate_economy_label: str | None = None,
    build_export: bool = core.BUILD_LEAP_EXPORT,
) -> list[Path]:
    return assemble_transfer_workbook(
        economies=economies,
        scenarios=scenarios,
        export_output_dir=export_output_dir,
        filename_template=filename_template,
        process_config=process_config,
        start_year=start_year,
        include_output_series=include_output_series,
        use_output_targets=use_output_targets,
        feedstock_method=feedstock_method,
        aggregate_economy_label=aggregate_economy_label,
        build_export=build_export,
    )


def run_transfer_pipeline(
    economies: Iterable[str] | None = None,
    scenarios: Sequence[str] | None = None,
    include_leap_import: bool = False,
    import_scenario: str | Sequence[str] | None = None,
    region: str | None = None,
    handle_current_accounts: bool = True,
    create_branches: bool = True,
    fill_branches: bool = True,
    aggregate_economy_label: str | None = None,
    id_lookup_path: Path | str | None = None,
    **export_kwargs,
) -> list[Path]:
    return run_transfer_export_and_import(
        economies=economies,
        scenarios=scenarios,
        include_leap_import=include_leap_import,
        import_scenario=import_scenario,
        region=region,
        handle_current_accounts=handle_current_accounts,
        create_branches=create_branches,
        fill_branches=fill_branches,
        aggregate_economy_label=aggregate_economy_label,
        id_lookup_path=id_lookup_path,
        **export_kwargs,
    )


def locate_transfer_export(
    directory: Path | str | None = None, filename: str | None = None
) -> Path:
    return find_transfer_workbook(directory=directory, filename=filename)


def get_available_scenarios(export_path: Path) -> list[str]:
    return list_export_scenarios(export_path)


def ensure_region_in_export(export_path: Path, region: str) -> None:
    return validate_export_region(export_path, region)


def run_transfer_leap_import(
    export_directory: Path | str | None = None,
    filename: str | None = None,
    scenario_to_run: str | None = None,
    region: str | None = None,
    include_current_accounts: bool = False,
    create_branches: bool = True,
    fill_branches: bool = True,
    raise_on_missing_branch: bool = False,
) -> Path:
    return import_transfer_workbook_to_leap(
        export_directory=export_directory,
        filename=filename,
        scenario_to_run=scenario_to_run,
        region=region,
        include_current_accounts=include_current_accounts,
        create_branches=create_branches,
        fill_branches=fill_branches,
        raise_on_missing_branch=raise_on_missing_branch,
    )


#%%

EXPORT_FILENAME_TEMPLATE = workflow_cfg.TRANSFERS_EXPORT_FILENAME_TEMPLATE
EXPORT_FILENAME_PREFIX = workflow_cfg.TRANSFERS_EXPORT_FILENAME_PREFIX
SHEET_NAME = workflow_cfg.TRANSFERS_SHEET_NAME
TRANSFER_COMBINED_FLOW_KEY = "transfer_flows_combined"
TRANSFER_PROCESS_NAMES = {
    "upstream_and_refinery": "Upstream & refinery transfers",
    "upstream_liquids": "Upstream liquids transfers",
    "refinery_blending": "Refinery and blending transfers",
    "unallocated": "Transfers unallocated",
}
DEFAULT_TRANSFER_UNALLOCATED_POLICY = {
    "enabled": True,
    "process_name": TRANSFER_PROCESS_NAMES["unallocated"],
    "max_efficiency_ratio": 50.0,
    "merge_all_when_triggered": True,
}

# One-sided transfer flows -------------------------------------------------
#
# Some economies record a transfer flow with products leaving and nothing
# arriving (or the reverse). `05_PRC` is the largest: 5,228 PJ of products
# transferred out in 2022 with no receiving product in the 2024/2025 ESTO
# vintages (the 2026 vintage adds it as `06.05 Other hydrocarbons`). A LEAP
# transformation process needs both an input and an output, so such a flow
# produces no process at all and the economy's transfers silently vanish.
#
# Policy: keep the measured side exactly as ESTO records it and add a nominal
# counterpart on the empty side. That is the smallest addition that makes a
# valid LEAP process while leaving the ESTO balance untouched — the imbalance
# ESTO already carries surfaces as process loss rather than being papered over
# with an invented quantity.
# The counterpart is carried on a dedicated fuel rather than a real product, so
# it is always identifiable as synthetic wherever it surfaces. `99` sits outside
# the ESTO product vocabulary (which runs 01-21), and the all-caps name makes it
# unmistakable in LEAP branch listings and balance outputs.
AUTO_BALANCE_PRODUCT_CODE = "99"
AUTO_BALANCE_PRODUCT_LABEL = "99 AUTO BALANCE"
AUTO_BALANCE_LEAP_FUEL_NAME = "AUTO BALANCE"

ONE_SIDED_TRANSFER_BALANCE_POLICY = {
    "enabled": True,
    # Floor for the counterpart, in the source's energy units (PJ). The actual
    # value is raised above this only when needed to keep the implied process
    # efficiency within the configured ceiling — see `_auto_balance_value`.
    "minimum_counterpart_value": 1.0,
    # Synthetic fuel carrying the counterpart. Deliberately not a real product:
    # attributing the balancing quantity to (say) refinery feedstocks would put
    # invented energy on a fuel that downstream balances treat as real.
    "product": AUTO_BALANCE_PRODUCT_LABEL,
}


def _auto_balance_value(measured_output_by_year, policy: dict) -> float:
    """Return the counterpart magnitude to use for a one-sided transfer flow.

    For an *inflow-only* flow the counterpart becomes the process feedstock, so
    the implied efficiency is ``measured_output / counterpart``. Sizing the
    counterpart against the configured ceiling keeps every synthesized process
    inside it by construction, instead of relying on an operator noticing a
    warning and raising the ceiling by hand.

    Outflow-only flows have the counterpart on the output side, where the
    implied efficiency is very small rather than very large, so they simply take
    the floor.
    """
    floor = float(policy.get("minimum_counterpart_value", 1.0))
    if measured_output_by_year is None or len(measured_output_by_year) == 0:
        return floor
    peak = float(abs(measured_output_by_year).max())
    if peak <= 0.0:
        return floor
    ceiling_percent = float(
        getattr(workflow_cfg, "TRANSFORMATION_PROCESS_EFFICIENCY_MAX_PERCENT", 1000.0)
    )
    if not getattr(workflow_cfg, "TRANSFORMATION_CLIP_PROCESS_EFFICIENCY_TO_MAX", True):
        return floor
    if ceiling_percent <= 0.0:
        return floor
    return max(floor, peak / (ceiling_percent / 100.0))
LEAP_API_AVAILABLE = leap_api.is_available()


def get_transfer_sector_titles() -> set[str]:
    """Return all possible LEAP sector titles that the transfers workflow can produce.

    Used by zero-fill logic to identify catalog branches that belong to transfers
    even when a specific economy had no transfer data in the current run.
    """
    titles: set[str] = set()
    # Generic fallback title (SPLIT_TRANSFER_SECTORS = False)
    titles.add("Transfers")
    # All named category/process titles (SPLIT_TRANSFER_SECTORS = True)
    titles.update(TRANSFER_PROCESS_NAMES.values())
    # Any category names declared in the templates that fall outside TRANSFER_PROCESS_NAMES
    for template in TRANSFER_CATEGORY_TEMPLATES:
        cat = template.get("category")
        if cat:
            titles.add(str(cat))
    return titles


#%%
# Simple notebook-focused configuration block.
ECONOMIES = (
    list(workflow_cfg.TRANSFERS_NOTEBOOK_ECONOMIES)
    if workflow_cfg.TRANSFERS_NOTEBOOK_ECONOMIES is not None
    else list(core.ECONOMIES_TO_ANALYZE)
)
SCENARIOS = (
    list(workflow_cfg.TRANSFERS_NOTEBOOK_SCENARIOS)
    if workflow_cfg.TRANSFERS_NOTEBOOK_SCENARIOS is not None
    else list(DEFAULT_SCENARIOS)
)
INCLUDE_LEAP_IMPORT = (
    workflow_cfg.TRANSFERS_NOTEBOOK_INCLUDE_LEAP_IMPORT
    if workflow_cfg.TRANSFERS_NOTEBOOK_INCLUDE_LEAP_IMPORT is not None
    else (LEAP_API_AVAILABLE if get_analysis_input_write_mode() == "api" else True)
)
IMPORT_SCENARIOS = [
    scenario.lower()
    for scenario in SCENARIOS
    if scenario.lower() not in {"current accounts", "current account"}
]


def _print_reset_reminder_for_import(include_leap_import: bool) -> None:
    """Remind users that standalone transfer import does not clear stale trade targets."""
    if not include_leap_import:
        return
    print(
        "[WARN] Reset reminder: standalone transfers workflow import does not perform a global "
        "supply/transformation trade reset. If you need a clean rerun, run "
        "codebase/supply_reconciliation_workflow.py with "
        "MAIN_RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT=True."
    )


CURRENT_ACCOUNTS = workflow_cfg.TRANSFERS_NOTEBOOK_CURRENT_ACCOUNTS
INCLUDE_OUTPUT_SERIES = False
USE_OUTPUT_TARGETS = True
AGGREGATE_ECONOMY_LABEL = workflow_cfg.TRANSFERS_AGGREGATE_ECONOMY_LABEL
SPLIT_TRANSFER_SECTORS = True

#%%
if __name__ == "__main__":
    exports = run_transfer_export_and_import(
        economies=ECONOMIES,
        scenarios=SCENARIOS,
        include_leap_import=INCLUDE_LEAP_IMPORT,
        import_scenario=IMPORT_SCENARIOS,
        handle_current_accounts=CURRENT_ACCOUNTS,
        include_output_series=INCLUDE_OUTPUT_SERIES,
        use_output_targets=USE_OUTPUT_TARGETS,
        aggregate_economy_label=AGGREGATE_ECONOMY_LABEL,
    )
    if exports:
        print(f"Transfer export saved to: {exports[0]}")
#%%


try:
    from codebase.utilities.workflow_common import emit_completion_beep as _emit_completion_beep
except Exception:  # pragma: no cover
    def _emit_completion_beep(*, success: bool = True) -> None:  # noqa: ARG001
        return


if __name__ == "__main__":  # pragma: no cover
    _emit_completion_beep(success=True, style="chime")
