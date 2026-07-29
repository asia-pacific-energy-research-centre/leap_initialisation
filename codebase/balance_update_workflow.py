#%%
"""Notebook presets for balance review workbooks and results-update runs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from codebase.functions.balance_review_workbooks import (
    build_balance_review_workbooks,
)
from codebase.functions.baseline_seed_balance_diagnostics import (
    DEFAULT_EXPORTS_ROOT,
    DEFAULT_OUTPUT_DIR,
    run_baseline_seed_balance_diagnostics,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve(path: Path | str) -> Path:
    raw = Path(str(path).replace("\\", "/"))
    return raw if raw.is_absolute() else REPO_ROOT / raw


_PRESET_REVIEW_ONLY = {
    "RUN_BALANCE_REVIEW": True,
    "RUN_RESULTS_UPDATE": False,
}

_PRESET_UPDATE_ONLY = {
    "RUN_BALANCE_REVIEW": False,
    "RUN_RESULTS_UPDATE": True,
}

_PRESET_REVIEW_AND_UPDATE = {
    "RUN_BALANCE_REVIEW": True,
    "RUN_RESULTS_UPDATE": True,
}


def run_balance_update_workflow(
    *,
    preset: dict[str, bool],
    economies: Sequence[str],
    review_years: Sequence[int],
    review_scenarios: Sequence[str],
    update_scenarios: Sequence[str],
    update_horizon: str = "full",
    exports_root: Path | str = DEFAULT_EXPORTS_ROOT,
    output_root: Path | str = DEFAULT_OUTPUT_DIR,
    review_output_label: str | None = None,
    update_run_output_label: str | None = None,
    date_ids_by_economy: dict[str, dict[str, str | None]] | None = None,
    workbook_paths_by_economy: dict[str, Path | str] | None = None,
    node_executable: Path | str | None = None,
    render_previews: bool = False,
    diagnostic_runner: Callable[..., dict[str, Any]] = (
        run_baseline_seed_balance_diagnostics
    ),
    review_workbook_builder: Callable[..., list[dict[str, Any]]] = (
        build_balance_review_workbooks
    ),
    update_runner: Callable[..., dict[str, object]] | None = None,
) -> dict[str, Any]:
    """Run review, update, or both while keeping their horizons independent."""
    run_review = bool(preset.get("RUN_BALANCE_REVIEW", False))
    run_update = bool(preset.get("RUN_RESULTS_UPDATE", False))
    if not run_review and not run_update:
        raise ValueError("The selected preset enables neither review nor update.")

    results: dict[str, Any] = {
        "preset": dict(preset),
        "review_years": [int(year) for year in review_years],
        "update_horizon": str(update_horizon),
    }
    if run_review:
        label = str(review_output_label or "").strip()
        if not label:
            label = f"review_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        diagnostic_output_dir = _resolve(output_root) / label
        diagnostics = diagnostic_runner(
            economies=economies,
            years=review_years,
            scenarios=review_scenarios,
            output_dir=diagnostic_output_dir,
            exports_root=exports_root,
            date_ids_by_economy=date_ids_by_economy,
            workbook_paths_by_economy=workbook_paths_by_economy,
        )
        review_workbooks = review_workbook_builder(
            diagnostic_results=diagnostics["economy_results"],
            diagnostics_directory=diagnostic_output_dir,
            output_directory=diagnostic_output_dir / "comparison_workbooks",
            node_executable=node_executable,
            render_previews=render_previews,
        )
        results["diagnostics"] = diagnostics
        results["review_workbooks"] = review_workbooks

    if run_update:
        if update_runner is None:
            from codebase.supply_reconciliation_workflow import (
                run_results_update_with_config,
            )

            update_runner = run_results_update_with_config
        results["results_update"] = update_runner(
            economies=economies,
            scenarios=update_scenarios,
            update_horizon=update_horizon,
            run_output_label=update_run_output_label,
        )
    return results


#%%
# ---------------------------------------------------------------------------
# NOTEBOOK CONTROLS
# ---------------------------------------------------------------------------
RUN_WORKFLOW = False

# Choose one:
ACTIVE_PRESET = _PRESET_REVIEW_ONLY
# ACTIVE_PRESET = _PRESET_UPDATE_ONLY
# ACTIVE_PRESET = _PRESET_REVIEW_AND_UPDATE

ECONOMIES = ["01_AUS"]

# These affect only the comparison diagnostics/workbooks.
REVIEW_YEARS = [2022]
REVIEW_SCENARIOS = ["Reference", "Target"]
REVIEW_OUTPUT_LABEL = None
DATE_IDS_BY_ECONOMY: dict[str, dict[str, str | None]] = {}
WORKBOOK_PATHS_BY_ECONOMY: dict[str, Path | str] = {}

# These affect only the existing results-update workflow.
UPDATE_SCENARIOS = ["Reference", "Target"]
UPDATE_HORIZON = "full"  # "full" | "base_year_plus_one"
UPDATE_RUN_OUTPUT_LABEL = None

# The workbook writer runs programmatically and does not render sheet images.
RENDER_PREVIEWS = False
NODE_EXECUTABLE: Path | str | None = None

if RUN_WORKFLOW:
    WORKFLOW_RESULT = run_balance_update_workflow(
        preset=ACTIVE_PRESET,
        economies=ECONOMIES,
        review_years=REVIEW_YEARS,
        review_scenarios=REVIEW_SCENARIOS,
        update_scenarios=UPDATE_SCENARIOS,
        update_horizon=UPDATE_HORIZON,
        exports_root=DEFAULT_EXPORTS_ROOT,
        output_root=DEFAULT_OUTPUT_DIR,
        review_output_label=REVIEW_OUTPUT_LABEL,
        update_run_output_label=UPDATE_RUN_OUTPUT_LABEL,
        date_ids_by_economy=DATE_IDS_BY_ECONOMY,
        workbook_paths_by_economy=WORKBOOK_PATHS_BY_ECONOMY,
        node_executable=NODE_EXECUTABLE,
        render_previews=RENDER_PREVIEWS,
    )

#%%
