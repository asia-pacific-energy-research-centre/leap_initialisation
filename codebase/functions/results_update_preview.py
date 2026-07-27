#%%
"""Format and run read-only previews of the current results-update allocator."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from codebase import supply_reconciliation_allocation as allocation
from codebase.utilities.workflow_utils import _resolve


RESULTS_UPDATE_PREVIEW_COLUMNS = [
    "economy",
    "scenario",
    "year",
    "esto_product",
    "proposal_type",
    "leap_branch_hint",
    "leap_variable",
    "baseline_imports_pj",
    "observed_imports_pj",
    "import_gap_pj",
    "allocated_output_uplift_pj",
    "capacity_increment_output_equivalent_pj",
    "extra_exports_pj",
    "clipped_output_pj",
    "unresolved_output_pj",
    "safe_to_apply",
    "safety_scope",
    "blocked_reason",
    "diagnostic_material_rows",
    "diagnostic_classifications",
    "diagnostic_update_allocation_required",
    "diagnostic_next_actions",
]


def _clean_text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _truthy_series(values: pd.Series) -> pd.Series:
    if values.dtype == bool:
        return values.fillna(False)
    return values.fillna(False).astype(str).str.strip().str.lower().isin(
        {"true", "1", "yes"}
    )


def _comparison_key(row: dict[str, object]) -> tuple[str, str, str, int]:
    return (
        _clean_text(row.get("economy")),
        _clean_text(row.get("scenario")).lower(),
        _clean_text(row.get("esto_product")),
        int(row.get("year")),
    )


def build_results_update_preview_table(
    pass_summary: dict[str, object],
) -> pd.DataFrame:
    """Normalize one allocator pass summary into a human-review proposal table."""
    comparison_lookup = {
        _comparison_key(row): row
        for row in pass_summary.get("comparison_rows", [])
        if isinstance(row, dict) and row.get("year") is not None
    }
    rows: list[dict[str, object]] = []

    def _base_row(source: dict[str, object]) -> dict[str, object]:
        economy, scenario, product, year = _comparison_key(source)
        comparison = comparison_lookup.get((economy, scenario, product, year), {})
        return {
            "economy": economy,
            "scenario": scenario,
            "year": year,
            "esto_product": product,
            "baseline_imports_pj": comparison.get("baseline_imports_pj", pd.NA),
            "observed_imports_pj": comparison.get("observed_imports_pj", pd.NA),
            "import_gap_pj": comparison.get("import_gap_pj", pd.NA),
            "allocated_output_uplift_pj": 0.0,
            "capacity_increment_output_equivalent_pj": 0.0,
            "extra_exports_pj": 0.0,
            "clipped_output_pj": 0.0,
            "unresolved_output_pj": 0.0,
            "safe_to_apply": True,
            "safety_scope": "current_allocator_only",
            "blocked_reason": "",
            "diagnostic_material_rows": 0,
            "diagnostic_classifications": "",
            "diagnostic_update_allocation_required": False,
            "diagnostic_next_actions": "",
        }

    for source in pass_summary.get("allocation_rows", []):
        if not isinstance(source, dict):
            continue
        row = _base_row(source)
        if str(source.get("allocation_type") or "").strip() == "primary_production":
            row.update(
                proposal_type="primary_production",
                leap_branch_hint="Resources\\Primary",
                leap_variable="Maximum Production",
            )
        else:
            module = str(source.get("module") or "").strip()
            process = str(source.get("process") or "").strip()
            row.update(
                proposal_type="transformation_capacity",
                leap_branch_hint=f"Transformation\\{module}\\Processes\\{process}",
                leap_variable="Exogenous Capacity",
            )
        row["allocated_output_uplift_pj"] = float(
            source.get("allocated_output_uplift") or 0.0
        )
        row["capacity_increment_output_equivalent_pj"] = float(
            source.get("capacity_increment") or 0.0
        )
        rows.append(row)

    simple_sources = [
        ("export_rows", "extra_exports", "Exports", "extra_exports", "extra_exports_pj"),
        (
            "clipping_rows",
            "clipped",
            "",
            "clipped_output_uplift",
            "clipped_output_pj",
        ),
        (
            "unresolved_positive_rows",
            "unresolved",
            "",
            "unresolved_output_uplift",
            "unresolved_output_pj",
        ),
        (
            "fatal_unresolved_positive_rows",
            "unresolved",
            "",
            "unresolved_output_uplift",
            "unresolved_output_pj",
        ),
    ]
    for source_name, proposal_type, variable, value_name, output_name in simple_sources:
        for source in pass_summary.get(source_name, []):
            if not isinstance(source, dict):
                continue
            row = _base_row(source)
            blocked = proposal_type in {"clipped", "unresolved"}
            row.update(
                proposal_type=proposal_type,
                leap_branch_hint="Resources\\Primary" if proposal_type == "extra_exports" else "",
                leap_variable=variable,
                safe_to_apply=not blocked,
                blocked_reason=str(source.get("reason") or "").strip() if blocked else "",
            )
            row[output_name] = float(source.get(value_name) or 0.0)
            rows.append(row)

    if not rows:
        return pd.DataFrame(columns=RESULTS_UPDATE_PREVIEW_COLUMNS)
    frame = pd.DataFrame(rows)
    if pass_summary.get("fatal_unresolved_positive_rows"):
        frame["safe_to_apply"] = False
        frame["blocked_reason"] = frame["blocked_reason"].where(
            frame["blocked_reason"].astype(str).str.strip().ne(""),
            "The current allocator would abort this pass because a residual is fatal.",
        )
    return frame[RESULTS_UPDATE_PREVIEW_COLUMNS].sort_values(
        ["safe_to_apply", "economy", "scenario", "year", "esto_product", "proposal_type"],
        ascending=[True, True, True, True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)


def apply_balance_review_safety(
    preview_table: pd.DataFrame,
    balance_review: pd.DataFrame,
    *,
    require_fresh_leap_cycle: bool = False,
    approved_classifications: Iterable[str] = ("approved_results_update",),
) -> pd.DataFrame:
    """Default-deny preview rows unless diagnostic evidence approves updating."""
    if preview_table.empty:
        return preview_table.copy()

    required = {
        "economy",
        "scenario",
        "year",
        "esto_product",
        "material_for_review",
        "primary_classification",
        "update_allocation_required",
        "next_action",
    }
    missing = sorted(required - set(balance_review.columns))
    if missing:
        raise KeyError(f"balance_review is missing required columns: {missing}")

    review = balance_review.copy()
    review["economy"] = review["economy"].fillna("").astype(str).str.strip()
    review["scenario"] = review["scenario"].fillna("").astype(str).str.strip().str.lower()
    review["esto_product"] = review["esto_product"].fillna("").astype(str).str.strip()
    review["year"] = pd.to_numeric(review["year"], errors="coerce").astype("Int64")
    material = _truthy_series(review["material_for_review"])
    review = review[material & review["year"].notna()].copy()

    key_columns = ["economy", "scenario", "year", "esto_product"]
    summaries: dict[tuple[str, str, int, str], dict[str, object]] = {}
    for key, group in review.groupby(key_columns, dropna=False, sort=False):
        classifications = sorted(
            {
                _clean_text(value)
                for value in group["primary_classification"]
                if _clean_text(value)
            }
        )
        next_actions = sorted(
            {
                _clean_text(value)
                for value in group["next_action"]
                if _clean_text(value)
            }
        )
        allocation_required = _truthy_series(
            group["update_allocation_required"]
        ).any()
        summaries[(str(key[0]), str(key[1]), int(key[2]), str(key[3]))] = {
            "rows": int(len(group)),
            "classifications": "|".join(classifications),
            "classification_set": set(classifications),
            "allocation_required": bool(allocation_required),
            "next_actions": "|".join(next_actions),
        }

    approved = {
        _clean_text(value)
        for value in approved_classifications
        if _clean_text(value)
    }
    output = preview_table.copy()
    for index, row in output.iterrows():
        key = (
            _clean_text(row.get("economy")),
            _clean_text(row.get("scenario")).lower(),
            int(row.get("year")),
            _clean_text(row.get("esto_product")),
        )
        summary = summaries.get(key)
        output.at[index, "safety_scope"] = "allocator_plus_balance_review"
        if summary is not None:
            output.at[index, "diagnostic_material_rows"] = summary["rows"]
            output.at[index, "diagnostic_classifications"] = summary["classifications"]
            output.at[index, "diagnostic_update_allocation_required"] = summary[
                "allocation_required"
            ]
            output.at[index, "diagnostic_next_actions"] = summary["next_actions"]

        reason = ""
        if require_fresh_leap_cycle:
            reason = (
                "The diagnostic export predates a relevant seed fix; regenerate the "
                "seed, import it into LEAP, recalculate, and export again."
            )
        elif summary is None:
            reason = "No material balance-review evidence explicitly approves this update."
        elif bool(summary["allocation_required"]):
            reason = "The diagnostic comparison requires a reviewed allocation rule."
        elif not summary["classification_set"] or not set(
            summary["classification_set"]
        ).issubset(approved):
            reason = (
                "Material diagnostic classification is not approved for results_update: "
                f"{summary['classifications'] or 'unclassified'}."
            )

        if reason:
            existing = str(row.get("blocked_reason") or "").strip()
            output.at[index, "safe_to_apply"] = False
            output.at[index, "blocked_reason"] = (
                f"{existing} {reason}".strip() if existing else reason
            )

    return output[RESULTS_UPDATE_PREVIEW_COLUMNS]


def run_results_update_allocation_preview(
    *,
    reconciliation_table: pd.DataFrame,
    process_records: list[dict],
    economies: Iterable[str],
    scenarios: Iterable[str],
    resolve_scenario_key: Callable[[pd.DataFrame, str], str],
    results_dir: Path | str | Iterable[Path | str] | None = None,
    state_path: Path | str | None = None,
    allow_same_results_reuse: bool | None = None,
    output_path: Path | str | None = None,
    balance_review: pd.DataFrame | None = None,
    require_fresh_leap_cycle: bool = False,
) -> dict[str, object]:
    """Run the current balanced allocator without mutating iterative state."""
    summary = allocation._run_capacity_unmet_iterative_balanced_pass(
        reconciliation_table=reconciliation_table,
        process_records=process_records,
        economies=economies,
        scenarios=scenarios,
        resolve_scenario_key=resolve_scenario_key,
        results_dir=(
            allocation.CAPACITY_UNMET_RESULTS_DIR if results_dir is None else results_dir
        ),
        state_path=(
            allocation.CAPACITY_UNMET_STATE_PATH if state_path is None else state_path
        ),
        allow_same_results_reuse=(
            allocation.CAPACITY_UNMET_ALLOW_SAME_RESULTS_REUSE
            if allow_same_results_reuse is None
            else allow_same_results_reuse
        ),
        preview_only=True,
        iteration_run_mode="results_update",
    )
    preview_table = build_results_update_preview_table(summary)
    if balance_review is not None:
        preview_table = apply_balance_review_safety(
            preview_table,
            balance_review,
            require_fresh_leap_cycle=require_fresh_leap_cycle,
        )
    resolved_output_path: Path | None = None
    if output_path is not None:
        resolved_output_path = _resolve(output_path)
        resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
        preview_table.to_csv(resolved_output_path, index=False)
        print(f"[INFO] Wrote results-update allocation preview: {resolved_output_path}")
    return {
        "preview_table": preview_table,
        "preview_path": resolved_output_path,
        "pass_summary": summary,
    }

#%%
