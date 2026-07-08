#%%
"""
Read-only review: flag Transfers-sector processes with outlier efficiency ratios.

This does NOT modify transfers_workflow.py or TRANSFER_PROCESS_CONFIG. It builds
transfer process records exactly as the real workflow would (same functions,
same config), computes each process's max output/input efficiency ratio, and
flags ratios above OUTLIER_RATIO_THRESHOLD (default 5.0 = 500%).

For each flagged (economy, process) pair, it also reports whether:
- the economy already has an `unallocated_policy` configured in
  TRANSFER_PROCESS_CONFIG (e.g. 20_USA), and
- that policy would already have collapsed the outlier into
  "Transfers unallocated" in the real pipeline (checked by comparing the
  raw pre-policy records against the actual build_transfer_rows() output).

Outputs (under outputs/transfers_efficiency_outlier_review/):
- transfer_efficiency_outliers.csv  -- one row per (economy, process)
- transfer_efficiency_outliers.png  -- horizontal bar chart, log x-axis,
  outliers highlighted, threshold line at OUTLIER_RATIO_THRESHOLD.

Nothing here writes back to TRANSFER_PROCESS_CONFIG or any codebase file.
"""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
CURRENT_DIR = Path.cwd()
if CURRENT_DIR != REPO_ROOT:
    os.chdir(REPO_ROOT)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.functions import transformation_analysis_utils as core
from codebase.functions.transfers_utils import _max_efficiency_ratio
from codebase.transfers_workflow import (
    TRANSFER_PROCESS_CONFIG,
    TRANSFER_ECONOMY_CONFIG_ALIASES,
    TRANSFER_PROCESS_NAMES,
    build_transfer_rows,
)

# --- Settings ---
OUTLIER_RATIO_THRESHOLD = 5.0  # ratio, i.e. 500% output/input
ECONOMIES = list(core.ECONOMIES_TO_ANALYZE)
OUTPUT_DIR = Path("outputs/transfers_efficiency_outlier_review")
CSV_PATH = OUTPUT_DIR / "transfer_efficiency_outliers.csv"
PLOT_PATH = OUTPUT_DIR / "transfer_efficiency_outliers.png"
PLOT_DPI = 160
MAX_PLOT_ROWS = 60  # cap chart rows so it stays readable; outliers always kept

# Palette (validated categorical + status colors; see dataviz skill palette.md)
COLOR_NORMAL = "#6E7787"      # muted neutral for in-range ratios
COLOR_OUTLIER = "#C1432D"     # status "critical" red for outliers
COLOR_THRESHOLD_LINE = "#22282F"


def _raw_config_without_unallocated_policy(config: dict) -> dict:
    """Deep-copy TRANSFER_PROCESS_CONFIG with unallocated_policy stripped per economy.

    This exposes the pre-collapse, per-process efficiency ratios that the real
    pipeline would compute before any "merge outliers into unallocated" logic runs.
    """
    raw = copy.deepcopy(config)
    for economy_cfg in raw.values():
        economy_cfg.pop("unallocated_policy", None)
    return raw


def _economy_has_unallocated_policy_enabled(economy: str) -> bool:
    economy_cfg = TRANSFER_PROCESS_CONFIG.get(economy)
    if not economy_cfg:
        alias = TRANSFER_ECONOMY_CONFIG_ALIASES.get(economy)
        economy_cfg = TRANSFER_PROCESS_CONFIG.get(alias) if alias else None
    if not economy_cfg:
        return False
    policy = economy_cfg.get("unallocated_policy")
    return bool(policy and policy.get("enabled"))


def _output_total(record: dict) -> float:
    total = 0.0
    for series in (record.get("output_values") or {}).values():
        total += sum(float(v) for v in series.values() if v is not None)
    return total


def collect_efficiency_rows() -> pd.DataFrame:
    core.prepare_transformation_assets()
    raw_config = _raw_config_without_unallocated_policy(TRANSFER_PROCESS_CONFIG)
    rows: list[dict] = []
    for economy in ECONOMIES:
        raw_records = build_transfer_rows(economy, process_config=raw_config)
        if not raw_records:
            continue
        final_records = build_transfer_rows(economy)
        final_process_names = {r.get("process_name") for r in final_records}
        already_unallocated = TRANSFER_PROCESS_NAMES["unallocated"] in final_process_names
        policy_enabled = _economy_has_unallocated_policy_enabled(economy)
        for record in raw_records:
            process_name = record.get("process_name")
            ratio = _max_efficiency_ratio(record)
            input_total = float(record.get("input_total") or 0.0)
            output_total = _output_total(record)
            is_outlier = ratio > OUTLIER_RATIO_THRESHOLD
            already_reallocated = (
                is_outlier
                and policy_enabled
                and already_unallocated
                and process_name != TRANSFER_PROCESS_NAMES["unallocated"]
            )
            rows.append(
                {
                    "economy": economy,
                    "process_name": process_name,
                    "max_efficiency_ratio": ratio,
                    "max_efficiency_pct": ratio * 100.0,
                    "input_total": input_total,
                    "output_total": output_total,
                    "is_outlier": is_outlier,
                    "unallocated_policy_enabled": policy_enabled,
                    "already_reallocated_in_pipeline": already_reallocated,
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("max_efficiency_ratio", ascending=False).reset_index(drop=True)


def plot_outliers(df: pd.DataFrame, path: Path) -> None:
    import matplotlib.pyplot as plt

    if df.empty:
        print("No transfer processes found; skipping plot.")
        return

    plot_df = df.copy()
    if len(plot_df) > MAX_PLOT_ROWS:
        outliers = plot_df[plot_df["is_outlier"]]
        context = plot_df[~plot_df["is_outlier"]].head(max(0, MAX_PLOT_ROWS - len(outliers)))
        plot_df = pd.concat([outliers, context]).sort_values(
            "max_efficiency_ratio", ascending=False
        )

    plot_df = plot_df.sort_values("max_efficiency_ratio", ascending=True)
    labels = [f"{row.economy} — {row.process_name}" for row in plot_df.itertuples()]
    ratios = plot_df["max_efficiency_ratio"].to_numpy()
    colors = [COLOR_OUTLIER if v else COLOR_NORMAL for v in plot_df["is_outlier"]]

    fig_height = max(4.0, 0.28 * len(plot_df) + 1.5)
    fig, ax = plt.subplots(figsize=(10, fig_height))
    ax.barh(labels, ratios, color=colors)
    ax.set_xscale("log")
    ax.axvline(
        OUTLIER_RATIO_THRESHOLD,
        color=COLOR_THRESHOLD_LINE,
        linewidth=1.5,
        linestyle="--",
        label=f"Outlier threshold ({OUTLIER_RATIO_THRESHOLD:.0f}x = {OUTLIER_RATIO_THRESHOLD*100:.0f}%)",
    )
    ax.set_xlabel("Max output/input efficiency ratio (log scale)")
    ax.set_title(
        "Transfers workflow: process efficiency ratios by economy\n"
        "(pre-unallocated-policy, raw per-process ratios)"
    )
    ax.legend(loc="lower right")
    ax.grid(axis="x", which="major", color="#DADFE5", linewidth=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=PLOT_DPI)
    plt.close(fig)


def main() -> None:
    df = collect_efficiency_rows()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if df.empty:
        print("No transfer process records were built for any configured economy.")
        return
    df.to_csv(CSV_PATH, index=False)

    try:
        plot_outliers(df, PLOT_PATH)
        plot_saved = True
    except ImportError as exc:
        plot_saved = False
        print(f"[WARN] Plotting skipped (missing dependency): {exc}")

    outliers = df[df["is_outlier"]].copy()
    print(f"\nSaved: {CSV_PATH}")
    if plot_saved:
        print(f"Saved: {PLOT_PATH}")

    print(
        f"\n{len(outliers)} of {len(df)} transfer processes exceed the "
        f"{OUTLIER_RATIO_THRESHOLD:.0f}x ({OUTLIER_RATIO_THRESHOLD*100:.0f}%) efficiency threshold:\n"
    )
    if outliers.empty:
        print("  (none)")
    else:
        for row in outliers.itertuples():
            reallocated = "already reallocated" if row.already_reallocated_in_pipeline else (
                "unallocated_policy enabled but NOT applied to this process"
                if row.unallocated_policy_enabled
                else "no unallocated_policy configured for this economy"
            )
            print(
                f"  - {row.economy:10s} {row.process_name:35s} "
                f"ratio={row.max_efficiency_ratio:8.2f}x  "
                f"input_total={row.input_total:12,.1f}  "
                f"[{reallocated}]"
            )

    needs_attention = outliers[~outliers["already_reallocated_in_pipeline"]]
    print(
        f"\n{len(needs_attention)} outlier process(es) are NOT currently being "
        "collapsed into \"Transfers unallocated\" by the pipeline."
    )
    if not needs_attention.empty:
        print("Candidate economies/processes to reallocate to 'Transfers unallocated':")
        for row in needs_attention.itertuples():
            print(f"  - {row.economy}: {row.process_name} ({row.max_efficiency_ratio:.1f}x)")
        print(
            "\nTo apply: for these economies, add/adjust an 'unallocated_policy' block "
            "in TRANSFER_PROCESS_CONFIG (see 20_USA for reference) with "
            "max_efficiency_ratio around the outlier threshold used above, or "
            "explicitly move the listed inputs/outputs into a 'Transfers unallocated' "
            "process config. No code was changed by this script."
        )


#%%
if __name__ == "__main__":
    main()
#%%
