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
EXPORT_ID_LOOKUP_PATH = REPO_ROOT / "data" / "full model export.xlsx"

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


def build_transfer_data_for_scenario(scenario: str) -> tuple[pd.DataFrame, list[int]]:
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
    projection_df, _ = build_with_conservation_policy(
        f"transfers projection (scenario={scenario!r})",
        lambda strict_conservation: core.build_esto_projection_table(
            ninth_data=ninth_transfer_data,
            esto_data=historical,
            mapping_path=core.NINTH_TO_ESTO_MAPPING_PATH,
            base_year=core.BASE_YEAR,
            projection_years=core.PROJECTION_YEAR_RANGE,
            scenario=scenario,
            sign_stable_flows="all",
            strict_conservation=strict_conservation,
        ),
    )
    projection_df = _route_transfer_projection_to_historical_flow(
        projection_df,
        historical,
        core.BASE_YEAR,
    )
    transfer_data = core.merge_projection_into_esto(
        historical,
        projection_df,
        core.PROJECTION_YEAR_RANGE,
    )
    year_cols = sorted(column for column in transfer_data.columns if str(column).isdigit())
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
) -> list[dict]:
    """Return transfer rows for the given economy."""
    if data_override is not None:
        data = data_override
    elif scenario is not None:
        data, year_cols_override = build_transfer_data_for_scenario(scenario)
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
    id_lookup_path: Path | str | None = EXPORT_ID_LOOKUP_PATH,
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
        id_lookup_path=id_lookup_path,
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
    id_lookup_path: Path | str | None = EXPORT_ID_LOOKUP_PATH,
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
            id_lookup_path=id_lookup_path,
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
    id_lookup_path: Path | str | None = EXPORT_ID_LOOKUP_PATH,
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
) -> list[dict]:
    return build_transfer_rows(
        economy=economy,
        sector_title=sector_title,
        start_year=start_year,
        process_config=process_config,
        use_output_targets=use_output_targets,
        data_override=data_override,
        year_cols_override=year_cols_override,
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
    id_lookup_path: Path | str | None = EXPORT_ID_LOOKUP_PATH,
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
