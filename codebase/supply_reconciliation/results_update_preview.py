#%%
"""Format and run read-only previews of the current results-update allocator."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from codebase.supply_reconciliation import allocation
from codebase.functions.baseline_seed_balance_diagnostics import (
    classify_balance_variable,
    load_balance_variable_rules,
)
from codebase.utilities.workflow_utils import _resolve


DEFAULT_RESULTS_UPDATE_ISSUE_DECISIONS_PATH = Path(
    "config/runtime_tables/results_update_issue_decisions.csv"
)
DEFAULT_RESULTS_UPDATE_ADJUSTMENT_STRATEGIES_PATH = Path(
    "config/runtime_tables/results_update_adjustment_strategy_rules.csv"
)

ADJUSTMENT_STRATEGY_RULE_COLUMNS = [
    "economy",
    "scenario",
    "esto_product",
    "positive_gap_strategy",
    "negative_gap_strategy",
    "residual_error_signal",
    "reason",
    "enabled",
]
POSITIVE_GAP_STRATEGIES = {
    "residual_only",
    "configured_levers_then_residual",
    "review_required",
}
NEGATIVE_GAP_STRATEGIES = {
    "residual_only",
    "configured_decrease_then_residual",
    "exports_then_residual",
    "review_required",
}

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
    "gap_direction",
    "error_signal_before_pj",
    "selected_adjustment_strategy",
    "strategy_rule_reason",
    "residual_error_signal",
    "strategy_allows_proposal",
    "residual_signal_status",
    "next_cycle_error_signal_pj",
    "allocated_output_uplift_pj",
    "capacity_increment_output_equivalent_pj",
    "extra_exports_pj",
    "clipped_output_pj",
    "unresolved_output_pj",
    "safe_to_apply",
    "update_disposition",
    "safety_scope",
    "blocked_reason",
    "diagnostic_flow_scope",
    "diagnostic_provenance_status",
    "diagnostic_material_rows",
    "diagnostic_balance_variable_roles",
    "diagnostic_balance_contract_issues",
    "diagnostic_update_signal_eligible",
    "diagnostic_classifications",
    "diagnostic_update_allocation_required",
    "diagnostic_next_actions",
]


def load_results_update_issue_decisions(
    path: Path | str = DEFAULT_RESULTS_UPDATE_ISSUE_DECISIONS_PATH,
) -> pd.DataFrame:
    """Load reviewed issue dispositions used to override preliminary findings."""
    resolved_path = _resolve(path)
    return pd.read_csv(resolved_path)


def load_results_update_adjustment_strategy_rules(
    path: Path | str = DEFAULT_RESULTS_UPDATE_ADJUSTMENT_STRATEGIES_PATH,
) -> pd.DataFrame:
    """Load enabled residual-versus-model-lever strategy rules."""
    rules = pd.read_csv(_resolve(path))
    missing = sorted(set(ADJUSTMENT_STRATEGY_RULE_COLUMNS) - set(rules.columns))
    if missing:
        raise KeyError(f"Adjustment strategy rules are missing columns: {missing}")
    enabled = rules["enabled"].fillna(False).astype(str).str.lower().isin(
        {"true", "1", "yes"}
    )
    rules = rules[enabled].reset_index(drop=True)
    invalid_positive = sorted(
        set(rules["positive_gap_strategy"].fillna("").astype(str).str.strip())
        - POSITIVE_GAP_STRATEGIES
    )
    invalid_negative = sorted(
        set(rules["negative_gap_strategy"].fillna("").astype(str).str.strip())
        - NEGATIVE_GAP_STRATEGIES
    )
    if invalid_positive or invalid_negative:
        raise ValueError(
            "Unsupported adjustment strategies: "
            f"positive={invalid_positive}, negative={invalid_negative}"
        )
    return rules


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


def classify_results_update_adjustment_strategy(
    *,
    economy: object,
    scenario: object,
    esto_product: object,
    gap_direction: str,
    rules: pd.DataFrame,
) -> dict[str, str]:
    """Resolve the most-specific configured strategy for one error signal."""
    values = {
        "economy": _clean_text(economy),
        "scenario": _clean_text(scenario).lower(),
        "esto_product": _clean_text(esto_product),
    }
    matches: list[tuple[int, int, pd.Series]] = []
    for index, rule in rules.iterrows():
        specificity = 0
        matched = True
        for column, value in values.items():
            rule_value = _clean_text(rule.get(column))
            if column == "scenario":
                rule_value = rule_value.lower()
            if rule_value == "*":
                continue
            if rule_value != value:
                matched = False
                break
            specificity += 1
        if matched:
            matches.append((specificity, int(index), rule))
    if not matches:
        return {
            "selected_adjustment_strategy": "review_required",
            "residual_error_signal": "imports_gap",
            "strategy_rule_reason": (
                "No adjustment-strategy rule applies; review is required by default."
            ),
        }
    _, _, selected = sorted(matches, key=lambda item: (-item[0], item[1]))[0]
    strategy_column = (
        "positive_gap_strategy"
        if gap_direction == "positive"
        else "negative_gap_strategy"
    )
    return {
        "selected_adjustment_strategy": _clean_text(selected.get(strategy_column)),
        "residual_error_signal": _clean_text(
            selected.get("residual_error_signal")
        ),
        "strategy_rule_reason": _clean_text(selected.get("reason")),
    }


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
            "gap_direction": "",
            "error_signal_before_pj": comparison.get("import_gap_pj", pd.NA),
            "selected_adjustment_strategy": "",
            "strategy_rule_reason": "",
            "residual_error_signal": "",
            "strategy_allows_proposal": False,
            "residual_signal_status": "",
            "next_cycle_error_signal_pj": pd.NA,
            "allocated_output_uplift_pj": 0.0,
            "capacity_increment_output_equivalent_pj": 0.0,
            "extra_exports_pj": 0.0,
            "clipped_output_pj": 0.0,
            "unresolved_output_pj": 0.0,
            "safe_to_apply": True,
            "update_disposition": "allocator_candidate",
            "safety_scope": "current_allocator_only",
            "blocked_reason": "",
            "diagnostic_flow_scope": "",
            "diagnostic_provenance_status": "not_assessed",
            "diagnostic_material_rows": 0,
            "diagnostic_balance_variable_roles": "",
            "diagnostic_balance_contract_issues": "",
            "diagnostic_update_signal_eligible": False,
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
                update_disposition=(
                    "allocator_blocked" if blocked else "allocator_candidate"
                ),
                blocked_reason=str(source.get("reason") or "").strip() if blocked else "",
            )
            row[output_name] = float(source.get(value_name) or 0.0)
            rows.append(row)

    represented_keys = {
        _comparison_key(row)
        for row in rows
        if row.get("year") is not None
    }
    for comparison_key, comparison in comparison_lookup.items():
        import_gap = pd.to_numeric(comparison.get("import_gap_pj"), errors="coerce")
        if (
            comparison_key in represented_keys
            or pd.isna(import_gap)
            or abs(float(import_gap)) <= 1e-9
        ):
            continue
        row = _base_row(comparison)
        row.update(
            proposal_type="residual_signal",
            leap_branch_hint="",
            leap_variable="",
            safe_to_apply=False,
            update_disposition="residual_signal",
            blocked_reason="",
        )
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=RESULTS_UPDATE_PREVIEW_COLUMNS)
    frame = pd.DataFrame(rows)
    if pass_summary.get("fatal_unresolved_positive_rows"):
        frame["safe_to_apply"] = False
        frame["update_disposition"] = "allocator_blocked"
        frame["blocked_reason"] = frame["blocked_reason"].where(
            frame["blocked_reason"].astype(str).str.strip().ne(""),
            "The current allocator would abort this pass because a residual is fatal.",
        )
    return frame[RESULTS_UPDATE_PREVIEW_COLUMNS].sort_values(
        ["safe_to_apply", "economy", "scenario", "year", "esto_product", "proposal_type"],
        ascending=[True, True, True, True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)


def apply_results_update_adjustment_strategies(
    preview_table: pd.DataFrame,
    *,
    strategy_rules: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Apply residual-only, configured-lever, and review-required policies."""
    if preview_table.empty:
        return preview_table.copy()
    rules = (
        load_results_update_adjustment_strategy_rules()
        if strategy_rules is None
        else strategy_rules.copy()
    )
    output = preview_table.copy()
    output["safe_to_apply"] = _truthy_series(output["safe_to_apply"])
    output["strategy_allows_proposal"] = False
    for index, row in output.iterrows():
        gap = pd.to_numeric(row.get("import_gap_pj"), errors="coerce")
        if pd.isna(gap) or abs(float(gap)) <= 1e-9:
            gap_direction = "zero_or_unavailable"
        elif float(gap) > 0.0:
            gap_direction = "positive"
        else:
            gap_direction = "negative"
        output.at[index, "gap_direction"] = gap_direction
        output.at[index, "error_signal_before_pj"] = gap
        output.at[index, "safety_scope"] = "allocator_plus_adjustment_strategy"

        if gap_direction == "zero_or_unavailable":
            output.at[index, "selected_adjustment_strategy"] = "review_required"
            output.at[index, "residual_error_signal"] = "imports_gap"
            output.at[index, "strategy_rule_reason"] = (
                "The error signal is zero or unavailable."
            )
            output.at[index, "residual_signal_status"] = "not_actionable"
            if bool(row.get("safe_to_apply")):
                output.at[index, "safe_to_apply"] = False
                output.at[index, "update_disposition"] = (
                    "blocked_adjustment_strategy_review"
                )
                output.at[index, "blocked_reason"] = (
                    "The imports error signal is unavailable; the proposed "
                    "adjustment cannot be assessed."
                )
            continue

        classification = classify_results_update_adjustment_strategy(
            economy=row.get("economy"),
            scenario=row.get("scenario"),
            esto_product=row.get("esto_product"),
            gap_direction=gap_direction,
            rules=rules,
        )
        strategy = classification["selected_adjustment_strategy"]
        output.at[index, "selected_adjustment_strategy"] = strategy
        output.at[index, "residual_error_signal"] = classification[
            "residual_error_signal"
        ]
        output.at[index, "strategy_rule_reason"] = classification[
            "strategy_rule_reason"
        ]

        proposal_type = _clean_text(row.get("proposal_type"))
        existing_safe = bool(row.get("safe_to_apply"))
        allowed = False
        blocked_disposition = ""
        blocked_reason = ""
        residual_status = ""
        if gap_direction == "positive":
            if strategy == "configured_levers_then_residual":
                allowed = proposal_type in {
                    "primary_production",
                    "transformation_capacity",
                }
                residual_status = (
                    "no_configured_lever_proposal_residual_to_imports"
                    if proposal_type == "residual_signal"
                    else "recalculate_after_configured_levers"
                )
            elif strategy == "residual_only":
                residual_status = "leave_full_signal_to_imports"
                blocked_disposition = "residual_only_no_model_adjustment"
                blocked_reason = (
                    "The adjustment strategy leaves this positive gap to the "
                    "configured imports residual."
                )
            else:
                residual_status = "review_required"
                blocked_disposition = "blocked_adjustment_strategy_review"
                blocked_reason = "The positive-gap adjustment strategy requires review."
        else:
            if strategy == "exports_then_residual":
                allowed = proposal_type == "extra_exports"
                residual_status = (
                    "no_export_proposal_residual_to_imports"
                    if proposal_type == "residual_signal"
                    else "recalculate_after_exports"
                )
            elif strategy == "configured_decrease_then_residual":
                residual_status = "decrease_logic_not_implemented"
                blocked_disposition = "blocked_decrease_not_implemented"
                blocked_reason = (
                    "Safe production/transformation decrease logic is not implemented."
                )
            elif strategy == "residual_only":
                residual_status = "leave_full_signal_to_imports"
                blocked_disposition = "residual_only_no_model_adjustment"
                blocked_reason = (
                    "The adjustment strategy leaves this negative gap to the "
                    "configured imports residual."
                )
            else:
                residual_status = "review_required"
                blocked_disposition = "blocked_adjustment_strategy_review"
                blocked_reason = "The negative-gap adjustment strategy requires review."

        output.at[index, "strategy_allows_proposal"] = bool(allowed)
        output.at[index, "residual_signal_status"] = residual_status
        if existing_safe and not allowed:
            output.at[index, "safe_to_apply"] = False
            output.at[index, "update_disposition"] = blocked_disposition
            existing_reason = _clean_text(row.get("blocked_reason"))
            output.at[index, "blocked_reason"] = (
                f"{existing_reason} {blocked_reason}".strip()
                if existing_reason
                else blocked_reason
            )
        elif proposal_type == "residual_signal" and blocked_disposition:
            output.at[index, "update_disposition"] = blocked_disposition
            output.at[index, "blocked_reason"] = blocked_reason
    return output[RESULTS_UPDATE_PREVIEW_COLUMNS]


def apply_balance_review_safety(
    preview_table: pd.DataFrame,
    balance_review: pd.DataFrame,
    *,
    reviewed_decisions: pd.DataFrame | None = None,
    balance_variable_rules: pd.DataFrame | None = None,
    require_fresh_leap_cycle: bool = False,
    approved_classifications: Iterable[str] = ("approved_results_update",),
    excluded_classifications: Iterable[str] = (
        "baseline_seed_generation_bug",
        "post_boundary_completion_bug",
        "diagnostic_bug",
        "mapping_defect",
        "leap_structure_or_export_issue",
    ),
) -> pd.DataFrame:
    """Triage allocator proposals without treating unresolved evidence as a veto."""
    if preview_table.empty:
        return preview_table.copy()

    required = {
        "economy",
        "scenario",
        "year",
        "esto_flow",
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
    contract_columns = {
        "balance_variable_role",
        "balance_contract_issue",
        "update_signal_eligible",
    }
    contract_available = contract_columns.issubset(review.columns)
    review["_reviewed_decision"] = False
    if reviewed_decisions is not None and not reviewed_decisions.empty:
        decision_required = {
            "economy",
            "scenario",
            "year",
            "esto_flow",
            "esto_product",
            "primary_classification",
            "next_action",
        }
        decision_missing = sorted(decision_required - set(reviewed_decisions.columns))
        if decision_missing:
            raise KeyError(
                "reviewed_decisions is missing required columns: "
                f"{decision_missing}"
            )
        decisions = reviewed_decisions.copy()
        decisions["_reviewed_decision"] = True
        if "material_for_review" not in decisions:
            decisions["material_for_review"] = True
        if "update_allocation_required" not in decisions:
            decisions["update_allocation_required"] = False
        for frame in (review, decisions):
            frame["economy"] = frame["economy"].fillna("").astype(str).str.strip()
            frame["scenario"] = (
                frame["scenario"].fillna("").astype(str).str.strip().str.lower()
            )
            frame["esto_flow"] = frame["esto_flow"].fillna("").astype(str).str.strip()
            frame["esto_product"] = (
                frame["esto_product"].fillna("").astype(str).str.strip()
            )
            frame["year"] = pd.to_numeric(frame["year"], errors="coerce").astype(
                "Int64"
            )
        review = pd.concat([review, decisions], ignore_index=True, sort=False)

    review["economy"] = review["economy"].fillna("").astype(str).str.strip()
    review["scenario"] = review["scenario"].fillna("").astype(str).str.strip().str.lower()
    review["esto_flow"] = review["esto_flow"].fillna("").astype(str).str.strip()
    review["esto_product"] = review["esto_product"].fillna("").astype(str).str.strip()
    review["year"] = pd.to_numeric(review["year"], errors="coerce").astype("Int64")
    review["_material_for_review"] = _truthy_series(review["material_for_review"])
    review = review[review["year"].notna()].copy()

    key_columns = ["economy", "scenario", "year", "esto_flow", "esto_product"]
    summaries: dict[tuple[str, str, int, str, str], dict[str, object]] = {}
    for key, group in review.groupby(key_columns, dropna=False, sort=False):
        decision_group = group[_truthy_series(group["_reviewed_decision"])]
        classification_group = (
            decision_group if not decision_group.empty else group
        )
        classifications = sorted(
            {
                _clean_text(value)
                for value in classification_group["primary_classification"]
                if _clean_text(value)
            }
        )
        next_actions = sorted(
            {
                _clean_text(value)
                for value in classification_group["next_action"]
                if _clean_text(value)
            }
        )
        allocation_required = _truthy_series(
            group["update_allocation_required"]
        ).any()
        summaries[
            (str(key[0]), str(key[1]), int(key[2]), str(key[3]), str(key[4]))
        ] = {
            "rows": int(len(group)),
            "material_rows": int(group["_material_for_review"].sum()),
            "classifications": "|".join(classifications),
            "classification_set": set(classifications),
            "allocation_required": bool(allocation_required),
            "next_actions": "|".join(next_actions),
        }
        if contract_available:
            roles = sorted(
                {
                    _clean_text(value)
                    for value in group["balance_variable_role"]
                    if _clean_text(value)
                }
            )
            contract_issues = sorted(
                {
                    _clean_text(value)
                    for value in group["balance_contract_issue"]
                    if _clean_text(value)
                }
            )
            summaries[
                (str(key[0]), str(key[1]), int(key[2]), str(key[3]), str(key[4]))
            ].update(
                balance_variable_roles="|".join(roles),
                balance_variable_role_set=set(roles),
                balance_contract_issues="|".join(contract_issues),
                balance_contract_issue_set=set(contract_issues),
                update_signal_eligible=bool(
                    _truthy_series(group["update_signal_eligible"]).any()
                ),
            )

    approved = {
        _clean_text(value)
        for value in approved_classifications
        if _clean_text(value)
    }
    excluded = {
        _clean_text(value)
        for value in excluded_classifications
        if _clean_text(value)
    }
    effective_rules = (
        load_balance_variable_rules()
        if balance_variable_rules is None
        else balance_variable_rules.copy()
    )
    output = preview_table.copy()
    for boolean_column in [
        "safe_to_apply",
        "diagnostic_update_allocation_required",
        "diagnostic_update_signal_eligible",
    ]:
        output[boolean_column] = _truthy_series(output[boolean_column])
    for index, row in output.iterrows():
        diagnostic_flow = (
            "03 Exports"
            if _clean_text(row.get("proposal_type")) == "extra_exports"
            else "02 Imports"
        )
        key = (
            _clean_text(row.get("economy")),
            _clean_text(row.get("scenario")).lower(),
            int(row.get("year")),
            diagnostic_flow,
            _clean_text(row.get("esto_product")),
        )
        summary = summaries.get(key)
        proposal_contract = classify_balance_variable(
            economy=key[0],
            scenario=key[1],
            esto_product=key[4],
            esto_flow=key[3],
            rules=effective_rules,
        )
        output.at[index, "safety_scope"] = (
            "allocator_plus_strategy_plus_balance_review"
            if _clean_text(row.get("selected_adjustment_strategy"))
            else "allocator_plus_balance_review"
        )
        output.at[index, "diagnostic_flow_scope"] = diagnostic_flow
        output.at[index, "diagnostic_balance_variable_roles"] = proposal_contract[
            "balance_variable_role"
        ]
        output.at[index, "diagnostic_provenance_status"] = (
            "predates_known_seed_fix"
            if require_fresh_leap_cycle
            else "current_or_unspecified"
        )
        if summary is not None:
            output.at[index, "diagnostic_material_rows"] = summary["material_rows"]
            output.at[index, "diagnostic_classifications"] = summary["classifications"]
            output.at[index, "diagnostic_update_allocation_required"] = summary[
                "allocation_required"
            ]
            output.at[index, "diagnostic_next_actions"] = summary["next_actions"]
            if contract_available:
                output.at[index, "diagnostic_balance_variable_roles"] = summary[
                    "balance_variable_roles"
                ]
                output.at[index, "diagnostic_balance_contract_issues"] = summary[
                    "balance_contract_issues"
                ]
                output.at[index, "diagnostic_update_signal_eligible"] = summary[
                    "update_signal_eligible"
                ]
        elif proposal_contract["balance_variable_role"] == "error_signal":
            output.at[index, "diagnostic_update_signal_eligible"] = True

        if summary is not None and set(summary["classification_set"]) & excluded:
            existing = _clean_text(row.get("blocked_reason"))
            reason = (
                "A reviewed upstream issue should be fixed before results_update: "
                f"{summary['classifications']}."
            )
            output.at[index, "safe_to_apply"] = False
            output.at[index, "update_disposition"] = "excluded_upstream_issue"
            output.at[index, "blocked_reason"] = (
                f"{existing} {reason}".strip() if existing else reason
            )
            continue

        if not bool(row.get("safe_to_apply")):
            if _clean_text(row.get("update_disposition")) in {
                "",
                "allocator_candidate",
            }:
                output.at[index, "update_disposition"] = "allocator_blocked"
            continue

        reason = ""
        if summary is not None and bool(summary["allocation_required"]):
            reason = "The diagnostic comparison requires a reviewed allocation rule."
            output.at[index, "update_disposition"] = "blocked_allocation_rule"
        elif (
            proposal_contract["balance_variable_role"] != "error_signal"
            or (
                contract_available
                and summary is not None
                and not bool(summary["update_signal_eligible"])
            )
        ):
            issue = (
                summary["balance_contract_issues"]
                if contract_available and summary is not None
                else ""
            )
            reason = (
                "The proposal flow is not an allowed balance error signal"
                f"{f': {issue}' if issue else ''}."
            )
            output.at[index, "update_disposition"] = (
                "blocked_balance_contract_issue"
            )
        elif (
            summary is not None
            and summary["classification_set"]
            and set(summary["classification_set"]).issubset(approved)
        ):
            output.at[index, "update_disposition"] = "approved_update_candidate"
        else:
            output.at[index, "update_disposition"] = "provisional_update_candidate"

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
    reviewed_decisions: pd.DataFrame | None = None,
    balance_variable_rules: pd.DataFrame | None = None,
    adjustment_strategy_rules: pd.DataFrame | None = None,
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
    preview_table = apply_results_update_adjustment_strategies(
        preview_table,
        strategy_rules=adjustment_strategy_rules,
    )
    if balance_review is not None:
        effective_decisions = (
            load_results_update_issue_decisions()
            if reviewed_decisions is None
            else reviewed_decisions
        )
        preview_table = apply_balance_review_safety(
            preview_table,
            balance_review,
            reviewed_decisions=effective_decisions,
            balance_variable_rules=balance_variable_rules,
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
