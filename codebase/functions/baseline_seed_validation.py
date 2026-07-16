#%%
"""Validate LEAP baseline-seed rows against stable import rules.

The validators operate on a dataframe already read from a LEAP workbook. They
do not require a comparison workbook, and duplicate rows are resolved before
share totals or coverage are evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from codebase.configuration.known_leap_label_exceptions import KNOWN_LEAP_LABEL_EXCEPTIONS
from codebase.functions.leap_expressions import parse_expression


# --- Stable rule definitions ---

LOGICAL_KEY_COLUMNS = ["Branch Path", "Variable", "Scenario", "Region"]
ID_COLUMNS = ["BranchID", "VariableID", "ScenarioID", "RegionID"]
SOURCE_WORKFLOW_COLUMN = "source_workflow"
SOURCE_FILE_COLUMN = "source_file"
PROVENANCE_COLUMNS = {SOURCE_WORKFLOW_COLUMN, SOURCE_FILE_COLUMN, "source_excel_row"}
SHARE_VARIABLE_RULE_IDS = {
    "Output Share": "SEED-006",
    "Process Share": "SEED-007",
    "Feedstock Fuel Share": "SEED-008",
}
ACTIONABLE_FINDING_STATUSES = frozenset({"fail", "warn"})
SHARE_ROOT_CAUSE_RULE_IDS = set(SHARE_VARIABLE_RULE_IDS.values())
MISSING_BRANCH_ROOT_CAUSE_RULE_IDS = {"SEED-003", "SEED-004", "SEED-005", "SEED-011"}
PRODUCER_COVERAGE_ROOT_CAUSE_RULE_IDS = {"SEED-012"}
IGNORED_FULL_MODEL_EXPORT_BRANCH_LABELS = {"abc do not use"}

# When a share group is all-zero in one scenario, borrow the genuine profile from
# another scenario (first match wins) before falling back to a synthetic anchor.
SHARE_DONOR_SCENARIO_PRIORITY = ("Reference", "Current Accounts", "Target")
AGGREGATED_DEMAND_BRANCH_PREFIX = "demand\\all demand aggregated\\"


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    description: str
    scope: str
    severity: str
    blocking: bool
    documentation_reference: str
    applicable_variables: tuple[str, ...] = ()
    branch_grouping: tuple[str, ...] = tuple(LOGICAL_KEY_COLUMNS)
    scenarios: str = "all rows supplied by the caller"
    applicable_years: str = "all expression years supplied by the caller"
    tolerance: str = "exact"
    exception_mechanism: str = "exact field match in the exceptions iterable"


RULE_SPECS = {
    "SEED-001": RuleSpec(
        "SEED-001", "Final import logical keys are unique.", "all rows", "error", True,
        "docs/special_rules_and_design_decisions.md#cross-001-full-model-export-and-leap-import-id-integrity",
    ),
    "SEED-002": RuleSpec(
        "SEED-002", "Duplicate logical keys are classified and resolved deterministically.",
        "duplicate logical keys", "error", True,
        "docs/baseline_seed_rule_inventory.md#duplicate-handling",
    ),
    "SEED-003": RuleSpec(
        "SEED-003", "Every final import row contains all required LEAP IDs.", "all rows",
        "error", True,
        "docs/special_rules_and_design_decisions.md#cross-001-full-model-export-and-leap-import-id-integrity",
    ),
    "SEED-004": RuleSpec(
        "SEED-004", "Nonzero rows with a missing LEAP ID are invalid.", "missing-ID rows",
        "error", True,
        "docs/special_rules_and_design_decisions.md#cross-001-full-model-export-and-leap-import-id-integrity",
    ),
    "SEED-005": RuleSpec(
        "SEED-005", "Zero missing-ID reset rows require explicit review.", "missing-ID zero rows",
        "warning", False,
        "docs/special_rules_and_design_decisions.md#cross-001-full-model-export-and-leap-import-id-integrity",
    ),
    "SEED-006": RuleSpec(
        "SEED-006", "Active Output Share sibling groups sum to 100 percent.", "Output Share",
        "error", True, "docs/special_rules_and_design_decisions.md#init-003-share-group-invariants",
        applicable_variables=("Output Share",),
        branch_grouping=("parent branch", "Variable", "Scenario", "Region", "year"),
        tolerance="share_tolerance",
    ),
    "SEED-007": RuleSpec(
        "SEED-007", "Active Process Share sibling groups sum to 100 percent.", "Process Share",
        "error", True, "docs/special_rules_and_design_decisions.md#init-003-share-group-invariants",
        applicable_variables=("Process Share",),
        branch_grouping=("parent branch", "Variable", "Scenario", "Region", "year"),
        tolerance="share_tolerance",
    ),
    "SEED-008": RuleSpec(
        "SEED-008", "Feedstock Fuel Share sibling groups sum to 100 percent.",
        "Feedstock Fuel Share", "error", True,
        "docs/special_rules_and_design_decisions.md#init-003-share-group-invariants",
        applicable_variables=("Feedstock Fuel Share",),
        branch_grouping=("parent branch", "Variable", "Scenario", "Region", "year"),
        tolerance="share_tolerance",
    ),
    "SEED-009": RuleSpec(
        "SEED-009", "Series expressions cover the configured required years.", "series expressions",
        "error", True, "docs/baseline_seed_rule_inventory.md#coverage-validation",
        applicable_years="required_years supplied by the caller",
    ),
    "SEED-010": RuleSpec(
        "SEED-010", "Configured scenarios are present for each branch-variable-region key.",
        "configured scenario coverage", "error", True,
        "docs/baseline_seed_rule_inventory.md#coverage-validation",
        branch_grouping=("Branch Path", "Variable", "Region"),
        scenarios="required_scenarios supplied by the caller",
    ),
    "SEED-011": RuleSpec(
        "SEED-011", "Branch paths exist in the canonical full-model export.", "all rows",
        "error", True,
        "docs/special_rules_and_design_decisions.md#cross-001-full-model-export-and-leap-import-id-integrity",
    ),
    "SEED-012": RuleSpec(
        "SEED-012", "Every configured producer supplies rows for each requested economy.",
        "producer/economy coverage", "error", True,
        "docs/baseline_seed_rule_inventory.md#coverage-validation",
        branch_grouping=(SOURCE_WORKFLOW_COLUMN, "economy"),
    ),
}


@dataclass(frozen=True)
class ValidationResult:
    resolved_rows: pd.DataFrame
    duplicate_groups: pd.DataFrame
    findings: pd.DataFrame

    @property
    def blocking_findings(self) -> pd.DataFrame:
        if self.findings.empty or "blocking" not in self.findings:
            return self.findings.iloc[0:0].copy()
        return self.findings[self.findings["blocking"].fillna(False)].copy()


def _empty_missing_branch_issue_groups() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "issue_group_id",
        "issue_group_type",
        "economy",
        "Branch Path",
        "Variable",
        "Scenario",
        "Region",
        "source_workflow",
        "source_file",
        "primary_rule_id",
        "member_rule_ids",
        "member_count",
        "blocking_count",
        "blocking",
        "summary",
        "evidence",
    ])


def _issue_group_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def build_missing_branch_issue_groups(findings: pd.DataFrame) -> pd.DataFrame:
    """Summarize missing-branch findings into one row per root cause.

    The raw findings are preserved, but this grouped view makes it easier to
    see when SEED-003/004/005 are downstream symptoms of the same missing
    canonical branch that triggers SEED-011.
    """
    if findings.empty:
        return _empty_missing_branch_issue_groups()

    required_columns = {"rule_id", *LOGICAL_KEY_COLUMNS, SOURCE_WORKFLOW_COLUMN, SOURCE_FILE_COLUMN}
    if not required_columns.issubset(findings.columns):
        return _empty_missing_branch_issue_groups()

    work = findings[findings["rule_id"].isin(MISSING_BRANCH_ROOT_CAUSE_RULE_IDS)].copy()
    if work.empty:
        return _empty_missing_branch_issue_groups()

    group_columns = (["economy"] if "economy" in work.columns else []) + [
        *LOGICAL_KEY_COLUMNS,
        SOURCE_WORKFLOW_COLUMN,
        SOURCE_FILE_COLUMN,
    ]
    rows: list[dict[str, object]] = []
    for key, group in work.groupby(group_columns, dropna=False, sort=True):
        rule_ids = sorted({_text(value) for value in group["rule_id"] if _text(value)})
        if "SEED-011" not in rule_ids:
            continue
        symptom_rule_ids = [rule_id for rule_id in rule_ids if rule_id != "SEED-011"]
        if not symptom_rule_ids:
            continue

        key_values = key if isinstance(key, tuple) else (key,)
        context = dict(zip(group_columns, key_values))
        evidence_values = sorted({_text(value) for value in group.get("evidence", pd.Series(dtype=object)) if _text(value)})
        summary = (
            "Branch is missing from the canonical full-model export; "
            f"related findings: {'|'.join(rule_ids)}"
        )
        rows.append({
            "issue_group_id": "missing_branch::" + "|".join(
                _normalized(context.get(column)) for column in group_columns
            ),
            "issue_group_type": "missing_branch",
            "economy": context.get("economy", ""),
            "Branch Path": context.get("Branch Path", ""),
            "Variable": context.get("Variable", ""),
            "Scenario": context.get("Scenario", ""),
            "Region": context.get("Region", ""),
            "source_workflow": context.get(SOURCE_WORKFLOW_COLUMN, ""),
            "source_file": context.get(SOURCE_FILE_COLUMN, ""),
            "primary_rule_id": "SEED-011",
            "member_rule_ids": "|".join(rule_ids),
            "member_count": len(group),
            "blocking_count": int(group["blocking"].fillna(False).sum()) if "blocking" in group.columns else len(group),
            "blocking": bool(group["blocking"].fillna(False).any()) if "blocking" in group.columns else True,
            "summary": summary,
            "evidence": "|".join(evidence_values),
        })

    if not rows:
        return _empty_missing_branch_issue_groups()

    return pd.DataFrame(rows)


def build_share_issue_groups(findings: pd.DataFrame) -> pd.DataFrame:
    """Summarize blocking share findings into one row per share-group issue."""
    columns = [
        "issue_group_id",
        "issue_group_type",
        "economy",
        "Branch Path",
        "Variable",
        "Scenario",
        "Region",
        "year_min",
        "year_max",
        "source_workflow",
        "source_file",
        "primary_rule_id",
        "member_rule_ids",
        "member_count",
        "blocking_count",
        "blocking",
        "summary",
        "evidence",
    ]
    if findings.empty or not {"rule_id", "blocking", "Branch Path", "Variable", "Scenario", "Region"}.issubset(findings.columns):
        return _issue_group_frame(columns)

    work = findings[
        findings["rule_id"].isin(SHARE_ROOT_CAUSE_RULE_IDS)
        & findings.get("blocking", pd.Series(False, index=findings.index)).fillna(False)
    ].copy()
    if work.empty:
        return _issue_group_frame(columns)

    group_columns = ["Branch Path", "Variable", "Scenario", "Region"]
    if "economy" in work.columns:
        group_columns = ["economy"] + group_columns
    rows: list[dict[str, object]] = []
    for key, group in work.groupby(group_columns, dropna=False, sort=True):
        key_values = key if isinstance(key, tuple) else (key,)
        context = dict(zip(group_columns, key_values))
        rule_ids = sorted({_text(value) for value in group["rule_id"] if _text(value)})
        years = sorted({
            year
            for value in group.get("year", pd.Series(dtype=object))
            if (year := _int_or_none(value)) is not None
        })
        evidence_values = sorted({
            _text(value)
            for value in group.get("evidence", pd.Series(dtype=object))
            if _text(value)
        })
        primary_rule_id = rule_ids[0] if rule_ids else ""
        summary = "Share group does not sum to 100 percent or contains missing/unparseable values."
        rows.append({
            "issue_group_id": "share_group::" + "|".join(
                _normalized(context.get(column))
                for column in group_columns
            ),
            "issue_group_type": "share_group",
            "economy": context.get("economy", ""),
            "Branch Path": context.get("Branch Path", ""),
            "Variable": context.get("Variable", ""),
            "Scenario": context.get("Scenario", ""),
            "Region": context.get("Region", ""),
            "year_min": min(years) if years else "",
            "year_max": max(years) if years else "",
            "source_workflow": "|".join(sorted({
                _text(value)
                for value in group.get(SOURCE_WORKFLOW_COLUMN, pd.Series(dtype=object))
                if _text(value)
            })),
            "source_file": "|".join(sorted({
                _text(value)
                for value in group.get(SOURCE_FILE_COLUMN, pd.Series(dtype=object))
                if _text(value)
            })),
            "primary_rule_id": primary_rule_id,
            "member_rule_ids": "|".join(rule_ids),
            "member_count": len(group),
            "blocking_count": int(group["blocking"].fillna(False).sum()),
            "blocking": True,
            "summary": summary,
            "evidence": "|".join(evidence_values),
        })
    return pd.DataFrame(rows, columns=columns)


def build_producer_coverage_issue_groups(findings: pd.DataFrame) -> pd.DataFrame:
    """Summarize producer/economy coverage failures into one row per missing producer."""
    columns = [
        "issue_group_id",
        "issue_group_type",
        "economy",
        "source_workflow",
        "source_file",
        "primary_rule_id",
        "member_rule_ids",
        "member_count",
        "blocking_count",
        "blocking",
        "summary",
        "evidence",
    ]
    if findings.empty or not {"rule_id", "blocking"}.issubset(findings.columns):
        return _issue_group_frame(columns)

    work = findings[
        findings["rule_id"].isin(PRODUCER_COVERAGE_ROOT_CAUSE_RULE_IDS)
        & findings.get("blocking", pd.Series(False, index=findings.index)).fillna(False)
    ].copy()
    if work.empty:
        return _issue_group_frame(columns)

    group_columns = ["economy", SOURCE_WORKFLOW_COLUMN]
    rows: list[dict[str, object]] = []
    for key, group in work.groupby(group_columns, dropna=False, sort=True):
        key_values = key if isinstance(key, tuple) else (key,)
        context = dict(zip(group_columns, key_values))
        rule_ids = sorted({_text(value) for value in group["rule_id"] if _text(value)})
        rows.append({
            "issue_group_id": "producer_coverage::" + "|".join(
                _normalized(context.get(column))
                for column in group_columns
            ),
            "issue_group_type": "producer_coverage",
            "economy": context.get("economy", ""),
            "source_workflow": context.get(SOURCE_WORKFLOW_COLUMN, ""),
            "source_file": "|".join(sorted({
                _text(value)
                for value in group.get(SOURCE_FILE_COLUMN, pd.Series(dtype=object))
                if _text(value)
            })),
            "primary_rule_id": rule_ids[0] if rule_ids else "",
            "member_rule_ids": "|".join(rule_ids),
            "member_count": len(group),
            "blocking_count": int(group["blocking"].fillna(False).sum()),
            "blocking": True,
            "summary": "Configured producer has no readable source workbook for this economy.",
            "evidence": "|".join(sorted({
                _text(value)
                for value in group.get("evidence", pd.Series(dtype=object))
                if _text(value)
            })),
        })
    return pd.DataFrame(rows, columns=columns)


def check_producer_coverage(
    economy: str,
    found_sources: Iterable[str],
    *,
    source_workbooks_by_workflow: Mapping[str, object] | None,
    source_probe: Mapping[str, Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Return SEED-012 findings for producers with no readable source for this economy.

    A producer is "missing" if it is configured (a key in
    source_workbooks_by_workflow) but none of its source files were found for
    this economy. Returns one SEED-012 finding per missing producer, or an
    empty list if source_workbooks_by_workflow is None (caller has not
    supplied current-run paths, so coverage cannot be assessed) or every
    configured producer was found.

    source_probe, when supplied, maps producer name to what the caller
    observed while probing that producer's configured paths for this economy
    (``missing_paths``, ``read_errors``, ``other_economy_count``,
    ``searched_dirs``). It is used only to make the finding self-describing:
    the message says why each path was rejected and SOURCE_FILE_COLUMN carries
    the concrete paths, so a wrong-directory run is diagnosable from the
    findings CSV alone.
    """
    if source_workbooks_by_workflow is None:
        return []
    missing_sources = sorted(set(source_workbooks_by_workflow) - set(found_sources))
    findings: list[dict[str, object]] = []
    for source_workflow in missing_sources:
        message = "Configured producer has no readable source workbook for this economy."
        source_files = ""
        probe = (source_probe or {}).get(str(source_workflow))
        if probe:
            missing_paths = [str(p) for p in probe.get("missing_paths", [])]
            read_errors = [str(e) for e in probe.get("read_errors", [])]
            other_count = int(probe.get("other_economy_count", 0) or 0)
            details: list[str] = []
            if missing_paths:
                details.append(
                    f"{len(missing_paths)} expected workbook(s) do not exist on disk"
                )
            if read_errors:
                details.append(
                    f"{len(read_errors)} workbook(s) matched this economy but failed to read"
                )
            if other_count:
                details.append(
                    f"{other_count} configured workbook(s) exist only for other economies"
                )
            if not details:
                searched = sorted(str(d) for d in probe.get("searched_dirs", set()))
                details.append(
                    "no configured path names this economy; searched: "
                    + ("; ".join(searched) if searched else "(no configured paths)")
                )
            message = f"{message} ({'; '.join(details)})"
            source_files = "|".join(missing_paths + read_errors)
        findings.append(
            _finding(
                "SEED-012",
                "fail",
                message,
                evidence=source_workflow,
                economy=economy,
                **{SOURCE_WORKFLOW_COLUMN: source_workflow, SOURCE_FILE_COLUMN: source_files},
            )
        )
    return findings


def build_validation_issue_groups(findings: pd.DataFrame) -> pd.DataFrame:
    """Build the grouped issue view used in diagnostics and console summaries."""
    frames = [
        frame for frame in (
            build_missing_branch_issue_groups(findings),
            build_share_issue_groups(findings),
            build_producer_coverage_issue_groups(findings),
        )
        if not frame.empty
    ]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _normalized(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{float(value):.12g}"
    return str(value).strip()


def _branch_path_tokens(branch_path: object) -> list[str]:
    text = _text(branch_path).replace("/", "\\")
    return [
        _normalized(part).lower()
        for part in text.split("\\")
        if _normalized(part)
    ]


def _is_ignored_full_model_export_branch_path(branch_path: object) -> bool:
    return any(token in IGNORED_FULL_MODEL_EXPORT_BRANCH_LABELS for token in _branch_path_tokens(branch_path))


def _exclude_ignored_full_model_export_rows(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty or "Branch Path" not in data.columns:
        return data.copy()
    mask = data["Branch Path"].map(_is_ignored_full_model_export_branch_path)
    if not bool(mask.any()):
        return data.copy()
    return data.loc[~mask].copy()


def _int_or_none(value: object) -> int | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return None
    return int(float(number))


def _expression_signature(value: object) -> tuple[str, str]:
    raw = _text(value)
    mode, payload = parse_expression(value)
    if mode == "series" and isinstance(payload, dict):
        kind = "interp" if raw.lower().startswith("interp(") else "data"
        values = "|".join(
            f"{int(year)}={float(number):.12g}" for year, number in sorted(payload.items())
        )
        return kind, values
    if mode == "const" and payload is not None:
        return mode, f"{float(payload):.12g}"
    return mode, raw


def _id_valid(value: object) -> bool:
    number = pd.to_numeric(value, errors="coerce")
    return bool(pd.notna(number) and float(number) >= 0.0)


def _row_has_all_valid_ids(row: pd.Series) -> bool:
    return all(column in row.index and _id_valid(row[column]) for column in ID_COLUMNS)


def _is_warning_only_aggregated_demand_branch(row: pd.Series) -> bool:
    """Return True for explicit placeholder fuel branches absent from LEAP.

    These rows remain in the workbook with ``BranchID=-1`` as an audit signal.
    They cannot import into LEAP, but their absence must not block generation of
    the other valid baseline-seed rows (Finn decision, 2026-07-03).
    """
    return (
        _normalized(row.get(SOURCE_WORKFLOW_COLUMN)).lower() == "aggregated_demand_workflow"
        and _normalized(row.get("Branch Path")).lower().startswith(AGGREGATED_DEMAND_BRANCH_PREFIX)
        and not _id_valid(row.get("BranchID"))
        and all(_id_valid(row.get(column)) for column in ["VariableID", "ScenarioID", "RegionID"])
    )


def _row_sort_signature(row: pd.Series) -> tuple[object, ...]:
    id_validity = tuple(0 if _id_valid(row.get(column)) else 1 for column in ID_COLUMNS)
    ids = tuple(_normalized(row.get(column)) for column in ID_COLUMNS)
    expression = _expression_signature(row.get("Expression"))
    metadata = tuple(
        _normalized(row.get(column))
        for column in sorted(
            set(row.index)
            - {*PROVENANCE_COLUMNS, *LOGICAL_KEY_COLUMNS, *ID_COLUMNS, "Expression"},
            key=str,
        )
    )
    return (sum(id_validity), id_validity, ids, expression, metadata)


def _duplicate_classification(group: pd.DataFrame) -> tuple[str, int]:
    expression_signatures = {_expression_signature(value) for value in group["Expression"]}
    id_signatures = {
        tuple(_normalized(row.get(column)) for column in ID_COLUMNS)
        for _, row in group.iterrows()
    }
    valid_rows = [index for index, row in group.iterrows() if _row_has_all_valid_ids(row)]

    comparison_columns = sorted(
        set(group.columns)
        - {*PROVENANCE_COLUMNS, *LOGICAL_KEY_COLUMNS},
        key=str,
    )
    row_signatures = {
        tuple(
            _expression_signature(row.get(column))
            if column == "Expression"
            else _normalized(row.get(column))
            for column in comparison_columns
        )
        for _, row in group.iterrows()
    }

    if len(row_signatures) == 1:
        return "exact_duplicate_same_ids_and_expression", len(valid_rows)
    if len(expression_signatures) == 1:
        if len(valid_rows) <= 1:
            return "same_expression_different_id_validity", len(valid_rows)
        return "possible_false_duplicate_insufficient_key", len(valid_rows)
    if len(valid_rows) == 1:
        return "conflicting_expression_one_valid_id_row", len(valid_rows)
    if len(valid_rows) > 1:
        return "conflicting_expression_multiple_valid_id_rows", len(valid_rows)
    return "conflicting_expression_no_valid_id_row", 0


def resolve_logical_duplicates(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return one deterministic row per logical key plus duplicate diagnostics.

    A unique valid-ID row wins over sentinel-ID rows. Otherwise selection uses
    normalized IDs, expression, and metadata; Excel row order is never used.
    Conflicting groups remain blocking findings even though one row is selected
    so downstream share diagnostics can be calculated safely.
    """
    missing = [column for column in LOGICAL_KEY_COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(f"Cannot resolve duplicates without logical key columns: {missing}")
    working = data.copy()
    if "Expression" not in working:
        working["Expression"] = pd.NA
    helper_columns = []
    for column in LOGICAL_KEY_COLUMNS:
        helper = f"__key_{column}"
        helper_columns.append(helper)
        working[helper] = working[column].map(_normalized)

    selected_indices: list[object] = []
    diagnostics: list[dict[str, object]] = []
    for key, group in working.groupby(helper_columns, dropna=False, sort=True):
        key_values = key if isinstance(key, tuple) else (key,)
        ordered_indices = sorted(group.index, key=lambda index: _row_sort_signature(group.loc[index]))
        chosen_index = ordered_indices[0]
        valid_indices = [index for index in ordered_indices if _row_has_all_valid_ids(group.loc[index])]
        if len(valid_indices) == 1:
            chosen_index = valid_indices[0]
        selected_indices.append(chosen_index)
        if len(group) == 1:
            continue
        classification, valid_count = _duplicate_classification(group)
        diagnostics.append(
            {
                **dict(zip(LOGICAL_KEY_COLUMNS, key_values)),
                "duplicate_count": len(group),
                "classification": classification,
                "valid_id_row_count": valid_count,
                "selected_source_excel_row": group.loc[chosen_index].get("source_excel_row", pd.NA),
                "source_excel_rows": "|".join(
                    str(group.loc[index].get("source_excel_row", "")) for index in ordered_indices
                ),
                "source_workflows": "|".join(sorted({
                    _text(value)
                    for value in group.get(SOURCE_WORKFLOW_COLUMN, pd.Series(dtype=object))
                    if _text(value)
                })),
                "source_files": "|".join(sorted({
                    _text(value)
                    for value in group.get(SOURCE_FILE_COLUMN, pd.Series(dtype=object))
                    if _text(value)
                })),
                "blocking": classification != "exact_duplicate_same_ids_and_expression",
            }
        )

    resolved = working.loc[selected_indices].copy()
    resolved = resolved.drop(columns=helper_columns).reset_index(drop=True)
    duplicate_groups = pd.DataFrame(diagnostics)
    return resolved, duplicate_groups


def _finding(
    rule_id: str,
    status: str,
    message: str,
    *,
    evidence: str = "",
    **context: object,
) -> dict[str, object]:
    spec = RULE_SPECS[rule_id]
    return {
        "rule_id": rule_id,
        "status": status,
        "severity": spec.severity,
        "blocking": bool(spec.blocking and status == "fail"),
        "description": spec.description,
        "scope": spec.scope,
        "message": message,
        "evidence": evidence,
        "documentation_reference": spec.documentation_reference,
        **context,
    }


def filter_actionable_findings(findings: pd.DataFrame) -> pd.DataFrame:
    """Keep only findings that require review in persisted rule reports."""
    if findings.empty or "status" not in findings.columns:
        return findings.copy()
    statuses = findings["status"].astype(str).str.strip().str.lower()
    return findings.loc[statuses.isin(ACTIONABLE_FINDING_STATUSES)].copy()


def _row_context(row: pd.Series) -> dict[str, object]:
    context = {column: row.get(column, "") for column in LOGICAL_KEY_COLUMNS}
    for column in (SOURCE_WORKFLOW_COLUMN, SOURCE_FILE_COLUMN):
        value = row.get(column, "")
        if _text(value):
            context[column] = value
    return context


def _expression_is_zero(value: object, tolerance: float) -> bool | None:
    mode, payload = parse_expression(value)
    if mode == "empty":
        return True
    if mode == "const" and payload is not None:
        return abs(float(payload)) <= tolerance
    if mode == "series" and isinstance(payload, dict):
        return all(abs(float(number)) <= tolerance for number in payload.values())
    return None


def _share_group_path(branch_path: object) -> str:
    parts = [part.strip() for part in _text(branch_path).split("\\") if part.strip()]
    return "\\".join(parts[:-1]) if len(parts) >= 2 else _text(branch_path)


def _format_data_expression(values: Mapping[int, float]) -> str:
    tokens: list[str] = []
    for year, value in sorted(values.items()):
        number = 0.0 if abs(float(value)) <= 1e-12 else float(value)
        tokens.extend([str(int(year)), f"{number:.12g}"])
    return f"Data({','.join(tokens)})"


def _expression_values(value: object, years: Iterable[int]) -> dict[int, float] | None:
    mode, payload = parse_expression(value)
    required = [int(year) for year in years]
    if mode == "const" and payload is not None:
        return {year: float(payload) for year in required}
    if mode == "series" and isinstance(payload, dict):
        return {
            year: float(payload[year])
            for year in required
            if year in payload and payload[year] is not None
        }
    return None


def _capacity_paths_for_share_group(group_path: str, variable: str) -> tuple[str, bool]:
    if variable == "Output Share" and group_path.lower().endswith("\\output fuels"):
        return group_path[: -len("\\Output Fuels")] + "\\Processes\\", True
    if variable == "Process Share" and group_path.lower().endswith("\\processes"):
        return group_path + "\\", True
    if variable == "Feedstock Fuel Share" and group_path.lower().endswith("\\feedstock fuels"):
        return group_path[: -len("\\Feedstock Fuels")], False
    return "", False


def _zero_capacity_is_explicit(
    data: pd.DataFrame,
    template: pd.DataFrame,
    *,
    group_path: str,
    variable: str,
    scenario: str,
    region: str,
    years: Iterable[int],
    tolerance: float,
) -> tuple[str, str]:
    """Classify the owning capacity/activity evidence for a zero-share group.

    Returns ``(status, reason)`` where ``status`` is one of:
      - ``"zero"``: the owning Exogenous Capacity rows are present and explicitly
        zero for every required year.
      - ``"unavailable"``: no owning Exogenous Capacity data could be found at
        all (undefined relationship, missing rows, or unparseable values). The
        share group itself already has no genuine nonzero activity in any
        scenario (checked by the caller before this runs), so an unmodeled
        capacity fact is treated the same as a proven-zero one for fallback
        purposes -- LEAP still needs an importable 100%/0% profile either way.
      - ``"nonzero"``: capacity is explicitly proven positive while the share
        group has no activity. This is a genuine data conflict, not an inert
        branch, so the caller must keep blocking it rather than fall back.
    """
    capacity_path, prefix_match = _capacity_paths_for_share_group(group_path, variable)
    if not capacity_path:
        return "unavailable", "capacity relationship is undefined"
    paths = data.get("Branch Path", pd.Series("", index=data.index)).map(_text)
    if prefix_match:
        path_mask = paths.str.lower().str.startswith(capacity_path.lower())
    else:
        path_mask = paths.str.lower().eq(capacity_path.lower())
    mask = (
        path_mask
        & data.get("Variable", pd.Series("", index=data.index)).map(_text).eq("Exogenous Capacity")
        & data.get("Scenario", pd.Series("", index=data.index)).map(_text).eq(scenario)
        & data.get("Region", pd.Series("", index=data.index)).map(_text).eq(region)
    )
    capacity_rows = data[mask]
    if capacity_rows.empty:
        return "unavailable", "relevant Exogenous Capacity row is missing"
    template_paths = template.get("Branch Path", pd.Series("", index=template.index)).map(_text)
    if prefix_match:
        template_path_mask = template_paths.str.lower().str.startswith(capacity_path.lower())
    else:
        template_path_mask = template_paths.str.lower().eq(capacity_path.lower())
    expected_capacity_paths = {
        path.lower()
        for path in template_paths[
            template_path_mask
            & template.get("Variable", pd.Series("", index=template.index)).map(_text).eq("Exogenous Capacity")
            & template.get("Scenario", pd.Series("", index=template.index)).map(_text).eq(scenario)
        ]
    }
    present_capacity_paths = {
        _text(path).lower() for path in capacity_rows["Branch Path"]
    }
    missing_capacity_paths = sorted(expected_capacity_paths - present_capacity_paths)
    if missing_capacity_paths:
        return "unavailable", f"owning Exogenous Capacity rows are missing: {missing_capacity_paths}"
    required_years = [int(year) for year in years]
    for _, row in capacity_rows.iterrows():
        values = _expression_values(row.get("Expression"), required_years)
        if values is None or any(year not in values for year in required_years):
            return "unavailable", "relevant Exogenous Capacity is missing or unparseable"
        if any(abs(value) > tolerance for value in values.values()):
            return "nonzero", "relevant Exogenous Capacity is positive or nonzero"
    return "zero", "relevant Exogenous Capacity is explicitly zero"


def complete_canonical_share_groups(
    data: pd.DataFrame,
    *,
    template_path: str | Path,
    required_years_by_scenario: Mapping[str, Iterable[int]],
    tolerance: float = 1e-12,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalize and complete every represented canonical share sibling group."""
    result, _ = resolve_logical_duplicates(data)
    result = _exclude_ignored_full_model_export_rows(result)
    template = load_template_rows(template_path)
    template = _exclude_ignored_full_model_export_rows(template)
    template["__parent"] = template["Branch Path"].map(_share_group_path)
    template_shares = template[
        template["Variable"].map(_text).isin(SHARE_VARIABLE_RULE_IDS)
    ].copy()
    shares = result[result.get("Variable", pd.Series("", index=result.index)).map(_text).isin(SHARE_VARIABLE_RULE_IDS)].copy()
    if shares.empty:
        return result, pd.DataFrame()

    shares["__parent"] = shares["Branch Path"].map(_share_group_path)
    additions: list[pd.Series] = []
    dropped_indices: list = []
    diagnostics: list[dict[str, object]] = []
    group_columns = ["__parent", "Variable", "Scenario", "Region"]

    # Pass 0: genuine normalized profiles per (group, variable, region) and scenario,
    # so an all-zero group can borrow the profile from a scenario with real data
    # instead of falling straight to the deterministic synthetic anchor.
    donor_profiles: dict[tuple[str, str, str], dict[str, dict[int, dict[str, float]]]] = {}
    for key, group in shares.groupby(group_columns, dropna=False, sort=True):
        group_path, variable, scenario, region = map(_text, key)
        years = sorted({int(year) for year in required_years_by_scenario.get(scenario, [])})
        if not years:
            continue
        parsed_by_path: dict[str, dict[int, float]] = {}
        for _, row in group.iterrows():
            parsed = _expression_values(row.get("Expression"), years)
            if parsed:
                parsed_by_path[_text(row["Branch Path"])] = parsed
        for year in years:
            raw = {
                path: max(values.get(year, 0.0), 0.0)
                for path, values in parsed_by_path.items()
            }
            total = sum(raw.values())
            if total > tolerance:
                profile = {path: value * 100.0 / total for path, value in raw.items()}
                anchor = sorted(profile, key=lambda path: (-profile[path], path.lower()))[0]
                profile[anchor] += 100.0 - sum(profile.values())
                donor_profiles.setdefault(
                    (_normalized(group_path), _normalized(variable), _normalized(region)), {}
                ).setdefault(_normalized(scenario), {})[year] = profile

    for key, group in shares.groupby(group_columns, dropna=False, sort=True):
        group_path, variable, scenario, region = map(_text, key)
        group_context = {
            "Branch Path": group_path,
            "Variable": variable,
            "Scenario": scenario,
            "Region": region,
            SOURCE_WORKFLOW_COLUMN: "|".join(sorted({
                _text(value) for value in group.get(SOURCE_WORKFLOW_COLUMN, pd.Series(dtype=object)) if _text(value)
            })),
            SOURCE_FILE_COLUMN: "|".join(sorted({
                _text(value) for value in group.get(SOURCE_FILE_COLUMN, pd.Series(dtype=object)) if _text(value)
            })),
        }
        years = sorted({int(year) for year in required_years_by_scenario.get(scenario, [])})
        if not years:
            continue
        canonical = template_shares[
            template_shares["__parent"].map(_normalized).eq(_normalized(group_path))
            & template_shares["Variable"].map(_normalized).eq(_normalized(variable))
            & template_shares["Scenario"].map(_normalized).eq(_normalized(scenario))
        ].drop_duplicates("Branch Path")
        if canonical.empty:
            diagnostics.append(_finding(
                SHARE_VARIABLE_RULE_IDS[variable], "fail",
                "Canonical share group is absent from the full-model export.",
                evidence=group_path, **group_context,
            ))
            continue

        # A generated sibling that has no matching branch anywhere in the
        # full-model export is not a valid LEAP import target (it fails
        # SEED-011 on its own) and it is not part of this group's canonical
        # sibling set either, so it cannot be completed to 100% alongside the
        # real siblings. Drop it here, at the shared completion step, instead
        # of letting it reach the workbook: its value is excluded from the
        # group's total before normalization, and the row is removed so the
        # exported group contains exactly the canonical siblings.
        canonical_paths = {_normalized(value).lower() for value in canonical["Branch Path"]}
        noncanonical_mask = ~group["Branch Path"].map(_normalized).str.lower().isin(canonical_paths)
        exemplar = group.sort_values("Branch Path", kind="mergesort").iloc[0]
        if noncanonical_mask.any():
            for _, row in group[noncanonical_mask].iterrows():
                diagnostics.append(_finding(
                    SHARE_VARIABLE_RULE_IDS[variable], "info",
                    "Removed noncanonical sibling absent from the full-model export; "
                    "its value is excluded from the group total.",
                    evidence=_text(row["Branch Path"]),
                    **group_context,
                ))
            dropped_indices.extend(group.index[noncanonical_mask].tolist())
            group = group[~noncanonical_mask]

        present_paths = {_normalized(value).lower() for value in group["Branch Path"]}
        group_additions: list[pd.Series] = []
        for _, template_row in canonical.sort_values("Branch Path", kind="mergesort").iterrows():
            if _normalized(template_row["Branch Path"]).lower() in present_paths:
                continue
            new_row = exemplar.copy()
            for column in template.columns:
                if not str(column).startswith("__") and column in new_row.index:
                    new_row[column] = template_row[column]
            new_row["Branch Path"] = template_row["Branch Path"]
            new_row["Variable"] = variable
            new_row["Scenario"] = scenario
            new_row["Region"] = region
            new_row["Expression"] = _format_data_expression({year: 0.0 for year in years})
            new_row[SOURCE_WORKFLOW_COLUMN] = exemplar.get(SOURCE_WORKFLOW_COLUMN, "")
            new_row[SOURCE_FILE_COLUMN] = exemplar.get(SOURCE_FILE_COLUMN, "")
            additions.append(new_row)
            group_additions.append(new_row)
            diagnostics.append(_finding(
                SHARE_VARIABLE_RULE_IDS[variable], "info",
                "Added explicit zero for unused canonical sibling.",
                evidence=_text(template_row["Branch Path"]),
                **group_context,
            ))

        all_rows = (
            pd.concat([group, pd.DataFrame(group_additions)], ignore_index=False)
            if group_additions
            else group.copy()
        )
        profiles: dict[int, dict[str, float]] = {}
        parsed_by_path: dict[str, dict[int, float]] = {}
        for _, row in all_rows.iterrows():
            path = _text(row["Branch Path"])
            parsed = _expression_values(row.get("Expression"), years)
            if parsed is None:
                diagnostics.append(_finding(
                    SHARE_VARIABLE_RULE_IDS[variable], "fail",
                    "Share expression is missing or unparseable before canonical completion.",
                    evidence=_text(row.get("Expression")),
                    **{**group_context, "Branch Path": path},
                ))
                parsed = {}
            elif any(value < -tolerance for value in parsed.values()):
                diagnostics.append(_finding(
                    SHARE_VARIABLE_RULE_IDS[variable], "fail",
                    "Share expression contains a negative value.",
                    evidence=_text(row.get("Expression")),
                    **{**group_context, "Branch Path": path},
                ))
            parsed_by_path[path] = parsed
        for year in years:
            raw = {
                path: max(values.get(year, 0.0), 0.0)
                for path, values in parsed_by_path.items()
            }
            total = sum(raw.values())
            if total > tolerance:
                profile = {path: value * 100.0 / total for path, value in raw.items()}
                anchor = sorted(profile, key=lambda path: (-profile[path], path.lower()))[0]
                profile[anchor] += 100.0 - sum(profile.values())
                profiles[year] = profile
                diagnostics.append(_finding(
                    SHARE_VARIABLE_RULE_IDS[variable], "info",
                    "Normalized genuine canonical sibling values to 100 percent.",
                    evidence=f"year={year}; original_sum={total:.12g}",
                    **group_context,
                ))
        genuine_years = sorted(profiles)
        if genuine_years:
            for year in years:
                if year in profiles:
                    continue
                nearest = min(genuine_years, key=lambda candidate: (abs(candidate - year), 0 if candidate >= year else 1))
                profiles[year] = dict(profiles[nearest])
                diagnostics.append(_finding(
                    SHARE_VARIABLE_RULE_IDS[variable], "info",
                    "Reused nearest genuine normalized share profile.",
                    evidence=f"year={year}; source_year={nearest}",
                    **group_context,
                ))
        else:
            capacity_status, capacity_evidence = _zero_capacity_is_explicit(
                result, template, group_path=group_path, variable=variable, scenario=scenario,
                region=region, years=years, tolerance=tolerance,
            )
            # A group with no genuine share activity falls back deterministically
            # whenever capacity is proven zero *or* simply unavailable (no owning
            # Exogenous Capacity row exists to check): in both cases nothing in the
            # source data supports a nonzero profile, so LEAP still needs an
            # importable 100%/0% share. Only an *explicitly nonzero* capacity
            # paired with zero share activity is a genuine data conflict, so that
            # case keeps blocking instead of silently fabricating a profile.
            if capacity_status in ("zero", "unavailable"):
                # Prefer a genuine profile from another scenario over the synthetic
                # anchor: with zero capacity the shares are inert, and a borrowed
                # real profile is more useful if the module is later activated.
                borrowed_scenario = None
                scenario_profiles = donor_profiles.get(
                    (_normalized(group_path), _normalized(variable), _normalized(region)), {}
                )
                for donor_scenario in SHARE_DONOR_SCENARIO_PRIORITY:
                    donor_key = _normalized(donor_scenario)
                    if donor_key == _normalized(scenario):
                        continue
                    donor_by_year = scenario_profiles.get(donor_key)
                    if not donor_by_year:
                        continue
                    donor_years = sorted(donor_by_year)
                    for year in years:
                        nearest = min(
                            donor_years,
                            key=lambda candidate: (abs(candidate - year), 0 if candidate >= year else 1),
                        )
                        source_profile = donor_by_year[nearest]
                        raw = {
                            path: max(source_profile.get(path, 0.0), 0.0)
                            for path in parsed_by_path
                        }
                        total = sum(raw.values())
                        if total > tolerance:
                            profile = {path: value * 100.0 / total for path, value in raw.items()}
                        else:
                            fallback_anchor = sorted(parsed_by_path, key=str.lower)[0]
                            profile = {
                                path: 100.0 if path == fallback_anchor else 0.0
                                for path in parsed_by_path
                            }
                        anchor = sorted(profile, key=lambda path: (-profile[path], path.lower()))[0]
                        profile[anchor] += 100.0 - sum(profile.values())
                        profiles[year] = profile
                    borrowed_scenario = donor_scenario
                    break
                if borrowed_scenario is not None:
                    diagnostics.append(_finding(
                        SHARE_VARIABLE_RULE_IDS[variable], "info",
                        "Borrowed normalized share profile from another scenario for an "
                        f"inactive group (capacity {capacity_status}).",
                        evidence=f"donor_scenario={borrowed_scenario}; {capacity_evidence}",
                        **group_context,
                    ))
                else:
                    anchor = sorted(parsed_by_path, key=str.lower)[0]
                    profiles = {
                        year: {path: 100.0 if path == anchor else 0.0 for path in parsed_by_path}
                        for year in years
                    }
                    diagnostics.append(_finding(
                        SHARE_VARIABLE_RULE_IDS[variable], "info",
                        "Generated deterministic synthetic share anchor for an inactive group "
                        f"(capacity {capacity_status}).",
                        evidence=f"anchor={anchor}; {capacity_evidence}",
                        **group_context,
                    ))
            else:
                diagnostics.append(_finding(
                    SHARE_VARIABLE_RULE_IDS[variable], "fail",
                    "Synthetic share fallback is blocked: capacity is explicitly nonzero "
                    "while the share group has no activity.",
                    evidence=capacity_evidence,
                    **group_context,
                ))
                continue

        for frame in (result,):
            group_mask = (
                frame["Branch Path"].map(_share_group_path).map(_normalized).eq(_normalized(group_path))
                & frame["Variable"].map(_normalized).eq(_normalized(variable))
                & frame["Scenario"].map(_normalized).eq(_normalized(scenario))
                & frame["Region"].map(_normalized).eq(_normalized(region))
            )
            for index in frame[group_mask].index:
                if index in dropped_indices:
                    continue
                path = _text(frame.at[index, "Branch Path"])
                frame.at[index, "Expression"] = _format_data_expression({year: profiles[year][path] for year in years})

        for new_row in group_additions:
            path = _text(new_row["Branch Path"])
            new_row["Expression"] = _format_data_expression({year: profiles[year][path] for year in years})

    if dropped_indices:
        result = result.drop(index=dropped_indices)
    if additions:
        result = pd.concat([result, pd.DataFrame(additions)], ignore_index=True, sort=False)
    return result, pd.DataFrame(diagnostics)


def _validate_shares(data: pd.DataFrame, *, tolerance: float) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    if "Variable" not in data or "Expression" not in data:
        return findings
    shares = data[data["Variable"].map(_text).isin(SHARE_VARIABLE_RULE_IDS)].copy()
    if shares.empty:
        return findings
    shares["share_group_path"] = shares["Branch Path"].map(_share_group_path)
    group_columns = ["share_group_path", "Variable", "Scenario", "Region"]
    for key, group in shares.groupby(group_columns, dropna=False, sort=True):
        path, variable, scenario, region = key
        rule_id = SHARE_VARIABLE_RULE_IDS[_text(variable)]
        parsed = []
        years: set[int] = set()
        unknown_rows = 0
        for _, row in group.iterrows():
            mode, payload = parse_expression(row["Expression"])
            parsed.append((mode, payload))
            if mode == "series" and isinstance(payload, dict):
                years.update(int(year) for year in payload)
            elif mode in {"empty", "unknown"}:
                unknown_rows += 1
        evaluation_years: list[int | None] = sorted(years) if years else [None]
        for year in evaluation_years:
            values: list[float] = []
            missing = 0
            for mode, payload in parsed:
                if mode == "const" and payload is not None:
                    values.append(float(payload))
                elif mode == "series" and isinstance(payload, dict) and year in payload:
                    values.append(float(payload[year]))
                else:
                    missing += 1
            context = {
                "Branch Path": path,
                "Variable": variable,
                "Scenario": scenario,
                "Region": region,
                "year": year,
                SOURCE_WORKFLOW_COLUMN: "|".join(sorted({
                    _text(value)
                    for value in group.get(SOURCE_WORKFLOW_COLUMN, pd.Series(dtype=object))
                    if _text(value)
                })),
                SOURCE_FILE_COLUMN: "|".join(sorted({
                    _text(value)
                    for value in group.get(SOURCE_FILE_COLUMN, pd.Series(dtype=object))
                    if _text(value)
                })),
            }
            if unknown_rows or missing:
                findings.append(_finding(rule_id, "fail", "Share group contains missing or unparseable values.", evidence=f"missing={missing}; unparseable={unknown_rows}", **context))
                continue
            share_sum = float(sum(values))
            if abs(share_sum - 100.0) <= tolerance:
                findings.append(_finding(rule_id, "pass", "Share group sums to 100 percent.", evidence=f"sum={share_sum:.12g}", **context))
            else:
                findings.append(_finding(rule_id, "fail", "Share group does not sum to 100 percent.", evidence=f"sum={share_sum:.12g}", **context))
    return findings


def _validate_canonical_share_completeness(
    data: pd.DataFrame,
    template: pd.DataFrame,
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    shares = _exclude_ignored_full_model_export_rows(
        data[data.get("Variable", pd.Series("", index=data.index)).map(_text).isin(SHARE_VARIABLE_RULE_IDS)].copy()
    )
    if shares.empty:
        return findings
    canonical = _exclude_ignored_full_model_export_rows(
        template[template["Variable"].map(_text).isin(SHARE_VARIABLE_RULE_IDS)].copy()
    )
    shares["__parent"] = shares["Branch Path"].map(_share_group_path)
    canonical["__parent"] = canonical["Branch Path"].map(_share_group_path)
    for key, group in shares.groupby(["__parent", "Variable", "Scenario", "Region"], dropna=False, sort=True):
        parent, variable, scenario, region = map(_text, key)
        expected_rows = canonical[
            canonical["__parent"].map(_normalized).eq(_normalized(parent))
            & canonical["Variable"].map(_normalized).eq(_normalized(variable))
            & canonical["Scenario"].map(_normalized).eq(_normalized(scenario))
        ]
        expected = {_normalized(value).lower() for value in expected_rows["Branch Path"]}
        present = {_normalized(value).lower() for value in group["Branch Path"]}
        missing = sorted(expected - present)
        extra = sorted(present - expected)
        context = {
            "Branch Path": parent,
            "Variable": variable,
            "Scenario": scenario,
            "Region": region,
            SOURCE_WORKFLOW_COLUMN: "|".join(sorted({
                _text(value)
                for value in group.get(SOURCE_WORKFLOW_COLUMN, pd.Series(dtype=object))
                if _text(value)
            })),
            SOURCE_FILE_COLUMN: "|".join(sorted({
                _text(value)
                for value in group.get(SOURCE_FILE_COLUMN, pd.Series(dtype=object))
                if _text(value)
            })),
        }
        if not expected:
            findings.append(_finding(
                SHARE_VARIABLE_RULE_IDS[variable], "fail",
                "Canonical sibling group is missing from the template.",
                evidence=parent, **context,
            ))
        elif missing or extra:
            findings.append(_finding(
                SHARE_VARIABLE_RULE_IDS[variable], "fail",
                "Share group is a partial or noncanonical sibling set.",
                evidence=f"missing={missing}; extra={extra}", **context,
            ))
    return findings


def _load_template_paths(template_path: Path) -> set[str]:
    data = pd.read_excel(
        template_path,
        sheet_name="Export",
        header=2,
        dtype=object,
        engine="openpyxl",
        engine_kwargs={"read_only": True, "data_only": False},
    )
    if "Branch Path" not in data:
        raise ValueError(f"Template is missing Branch Path: {template_path}")
    return {
        _text(value).lower()
        for value in data["Branch Path"]
        if _text(value) and not _is_ignored_full_model_export_branch_path(value)
    }


def load_template_rows(template_path: str | Path) -> pd.DataFrame:
    """Load canonical LEAP template rows used for branch and ID validation."""
    path = Path(template_path)
    data = pd.read_excel(
        path,
        sheet_name="Export",
        header=2,
        dtype=object,
        engine="openpyxl",
        engine_kwargs={"read_only": True, "data_only": False},
    )
    required = [*ID_COLUMNS, *LOGICAL_KEY_COLUMNS]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ValueError(f"Template is missing required columns {missing}: {path}")
    return data


@dataclass(frozen=True)
class TemplateIdLookup:
    """Canonical full-model-export ID lookups keyed on normalized lowercase text.

    Extracted from ``enrich_seed_ids_from_template`` so every verification
    mechanism (seed enrichment, results-saver ID resolution, seed-file
    validation reports) answers "is this row canonical, and with which IDs"
    with the same algorithm.
    """

    branch_ids: Mapping[str, int]
    variable_ids: Mapping[tuple[str, str], int]
    scenario_ids: Mapping[str, int]
    region_ids: Mapping[str, int]
    sole_region_id: int | None
    canonical_paths: Mapping[str, str]


def normalize_template_key(value: object) -> str:
    """Normalize a Branch Path/Variable/Scenario/Region value to its lookup key."""
    return _normalized(value).lower()


def build_template_id_lookup(template: pd.DataFrame | str | Path) -> TemplateIdLookup:
    """Build canonical ID lookups from the full-model export (path or frame)."""
    if isinstance(template, pd.DataFrame):
        required = [*ID_COLUMNS, *LOGICAL_KEY_COLUMNS]
        missing = [column for column in required if column not in template.columns]
        if missing:
            raise ValueError(f"Template frame is missing required columns {missing}.")
        data = template.copy()
    else:
        data = load_template_rows(template)
    data = _exclude_ignored_full_model_export_rows(data)

    data["__branch_key"] = data["Branch Path"].map(_normalized).str.lower()
    data["__variable_key"] = data["Variable"].map(_normalized).str.lower()
    data["__scenario_key"] = data["Scenario"].map(_normalized).str.lower()
    data["__region_key"] = data["Region"].map(_normalized).str.lower()

    canonical_paths = (
        data.loc[data["__branch_key"].ne(""), ["__branch_key", "Branch Path"]]
        .drop_duplicates("__branch_key")
        .set_index("__branch_key")["Branch Path"]
        .to_dict()
    )

    def _valid_id_rows(columns: list[str], id_column: str) -> pd.DataFrame:
        selected = data[columns + [id_column]].copy()
        selected[id_column] = pd.to_numeric(selected[id_column], errors="coerce")
        return selected[selected[id_column].ge(0)].drop_duplicates(columns)

    branch_ids = _valid_id_rows(["__branch_key"], "BranchID").set_index("__branch_key")["BranchID"].to_dict()
    variable_ids = _valid_id_rows(
        ["__branch_key", "__variable_key"], "VariableID"
    ).set_index(["__branch_key", "__variable_key"])["VariableID"].to_dict()
    scenario_ids = _valid_id_rows(["__scenario_key"], "ScenarioID").set_index("__scenario_key")["ScenarioID"].to_dict()
    region_id_rows = _valid_id_rows(["__region_key"], "RegionID")
    region_ids = region_id_rows.set_index("__region_key")["RegionID"].to_dict()
    unique_region_ids = sorted(set(region_ids.values()))
    sole_region_id = unique_region_ids[0] if len(unique_region_ids) == 1 else None
    return TemplateIdLookup(
        branch_ids=branch_ids,
        variable_ids=variable_ids,
        scenario_ids=scenario_ids,
        region_ids=region_ids,
        sole_region_id=sole_region_id,
        canonical_paths=canonical_paths,
    )


def apply_template_ids(data: pd.DataFrame, lookup: TemplateIdLookup) -> pd.DataFrame:
    """Replace all four IDs with canonical values from the template lookup.

    Branch and variable IDs are branch-specific. Scenario and region IDs come
    from the template; a sole template RegionID is valid for renamed economy
    regions because each target LEAP area uses that same region object.
    Unmatched keys remain ``-1`` so the rule validator blocks the write.
    """
    result = data.copy()
    branch_keys = result.get("Branch Path", pd.Series("", index=result.index)).map(_normalized).str.lower()
    variable_keys = result.get("Variable", pd.Series("", index=result.index)).map(_normalized).str.lower()
    scenario_keys = result.get("Scenario", pd.Series("", index=result.index)).map(_normalized).str.lower()
    region_keys = result.get("Region", pd.Series("", index=result.index)).map(_normalized).str.lower()

    result["Branch Path"] = branch_keys.map(lookup.canonical_paths).fillna(
        result.get("Branch Path", pd.Series("", index=result.index))
    )
    result["BranchID"] = branch_keys.map(lookup.branch_ids).fillna(-1).astype(int)
    mapped_variable_ids = pd.Series(
        list(zip(branch_keys, variable_keys)), index=result.index
    ).map(lookup.variable_ids)
    existing_variable_ids = pd.to_numeric(
        result.get("VariableID", pd.Series(-1, index=result.index)), errors="coerce"
    )
    # Preserve a valid variable ID on an intentionally retained aggregate-demand
    # placeholder branch even when that branch itself has no canonical BranchID.
    mapped_variable_ids = mapped_variable_ids.where(
        mapped_variable_ids.notna(), existing_variable_ids.where(existing_variable_ids.ge(0))
    )
    result["VariableID"] = mapped_variable_ids.fillna(-1).astype(int)
    result["ScenarioID"] = scenario_keys.map(lookup.scenario_ids).fillna(-1).astype(int)
    mapped_region_ids = region_keys.map(lookup.region_ids)
    if lookup.sole_region_id is not None:
        mapped_region_ids = mapped_region_ids.fillna(lookup.sole_region_id)
    result["RegionID"] = mapped_region_ids.fillna(-1).astype(int)

    # --- Known LEAP-label exception rescue pass ------------------------------
    # A handful of fuel/sector labels are spelled differently in the live LEAP
    # model vs. outlook_mappings_master (see KNOWN_LEAP_LABEL_EXCEPTIONS, e.g.
    # "Black liqour"/"Black liquor"). When that gap leaves a row at -1 after the
    # normal lookup, retry the *same* branch_ids/variable_ids dicts against an
    # alias-substituted branch key. Only rows that flip from -1 to a real match
    # are overwritten; rows still -1 afterward stay exactly as blocking as
    # before. Substitution is tried in both directions because either the
    # template or the seed row may carry either spelling.
    _rescue_ids_via_known_leap_label_exceptions(
        result,
        branch_ids=lookup.branch_ids,
        variable_ids=lookup.variable_ids,
        canonical_paths=lookup.canonical_paths,
    )
    return result


def enrich_seed_ids_from_template(
    data: pd.DataFrame,
    template_path: str | Path,
) -> pd.DataFrame:
    """Replace all four IDs with canonical values from the full-model export.

    Thin wrapper over ``build_template_id_lookup`` + ``apply_template_ids``;
    see ``apply_template_ids`` for the matching semantics.
    """
    return apply_template_ids(data, build_template_id_lookup(template_path))


def _rescue_ids_via_known_leap_label_exceptions(
    result: pd.DataFrame,
    *,
    branch_ids: Mapping[str, int],
    variable_ids: Mapping[tuple[str, str], int],
    canonical_paths: Mapping[str, str],
) -> None:
    """Flip -1 BranchID/VariableID rows to real matches via label aliases in place."""
    if not KNOWN_LEAP_LABEL_EXCEPTIONS:
        return
    alias_pairs: list[tuple[str, str]] = []
    for leap_label, mapping_label in KNOWN_LEAP_LABEL_EXCEPTIONS.items():
        if leap_label and mapping_label:
            alias_pairs.append((leap_label, mapping_label))
            alias_pairs.append((mapping_label, leap_label))
    if not alias_pairs:
        return

    def _alias_branch_key(path_text: str) -> tuple[str, str] | None:
        for old, new in alias_pairs:
            if old in path_text:
                candidate_key = _normalized(path_text.replace(old, new)).lower()
                if candidate_key in branch_ids:
                    return candidate_key, f"{old} -> {new}"
        return None

    rescued_branch: list[str] = []
    rescued_variable: list[str] = []
    for idx in result.index:
        branch_id = int(result.at[idx, "BranchID"])
        variable_id = int(result.at[idx, "VariableID"])
        if branch_id >= 0 and variable_id >= 0:
            continue
        original_path = _text(result.at[idx, "Branch Path"])
        rescue = _alias_branch_key(original_path)
        if rescue is None:
            continue
        corrected_key, note = rescue
        if branch_id < 0:
            result.at[idx, "BranchID"] = int(branch_ids[corrected_key])
            result.at[idx, "Branch Path"] = canonical_paths.get(corrected_key, original_path)
            rescued_branch.append(f"{original_path} [{note}]")
        if variable_id < 0:
            variable_key = _normalized(result.at[idx, "Variable"]).lower() if "Variable" in result.columns else ""
            composite = (corrected_key, variable_key)
            if composite in variable_ids:
                result.at[idx, "VariableID"] = int(variable_ids[composite])
                rescued_variable.append(f"{original_path} [{note}]")

    if rescued_branch or rescued_variable:
        print(
            "[INFO] rescued "
            f"{len(rescued_branch)} BranchID and {len(rescued_variable)} VariableID "
            "row(s) via KNOWN_LEAP_LABEL_EXCEPTIONS. When the LEAP model spelling is "
            "corrected upstream this rescue should go quiet and the exception entry "
            f"can be deleted. Examples: {(rescued_branch or rescued_variable)[:5]}"
        )


def _exception_matches(finding: dict[str, object], exception: dict[str, object]) -> bool:
    metadata_keys = {"exception_id", "reason", "note"}
    match_fields = {
        key: value for key, value in exception.items() if key not in metadata_keys
    }
    return bool(match_fields) and all(
        _normalized(finding.get(key)) == _normalized(value)
        for key, value in match_fields.items()
    )


def validate_exception_records(
    exceptions: Iterable[dict[str, object]] | None,
) -> list[dict[str, object]]:
    """Validate explicit, narrowly scoped rule exceptions."""
    records = [dict(record) for record in exceptions or []]
    allowed_scope_fields = {
        *LOGICAL_KEY_COLUMNS,
        SOURCE_WORKFLOW_COLUMN,
        SOURCE_FILE_COLUMN,
        "year",
    }
    for index, record in enumerate(records):
        if not _text(record.get("rule_id")):
            raise ValueError(f"Validation exception {index} is missing rule_id.")
        scoped_fields = [
            field for field in allowed_scope_fields if _text(record.get(field))
        ]
        if not scoped_fields:
            raise ValueError(
                f"Validation exception {index} must include at least one measure/key "
                "field: Variable, Branch Path, Scenario, Region, source_workflow, "
                "source_file, or year."
            )
    return records


def validate_seed_rows(
    data: pd.DataFrame,
    *,
    template_path: str | Path | None = None,
    required_years: Iterable[int] | None = None,
    required_years_by_scenario: Mapping[str, Iterable[int]] | None = None,
    required_scenarios: Iterable[str] | None = None,
    required_scenarios_by_source: Mapping[str, Iterable[str]] | None = None,
    share_tolerance: float = 1e-6,
    zero_tolerance: float = 1e-12,
    exceptions: Iterable[dict[str, object]] | None = None,
    allow_exact_duplicate_resolution: bool = False,
) -> ValidationResult:
    """Run focused baseline-seed rules without requiring a reference workbook."""
    resolved, duplicate_groups = resolve_logical_duplicates(data)
    findings: list[dict[str, object]] = []

    for _, duplicate in duplicate_groups.iterrows():
        context = {column: duplicate.get(column, "") for column in LOGICAL_KEY_COLUMNS}
        context[SOURCE_WORKFLOW_COLUMN] = duplicate.get("source_workflows", "")
        classification = _text(duplicate["classification"])
        exact = classification == "exact_duplicate_same_ids_and_expression"
        exact_is_resolved = exact and allow_exact_duplicate_resolution
        findings.append(_finding(
            "SEED-001", "info" if exact_is_resolved else "fail",
            "Exact duplicate logical key was removed before workbook writing."
            if exact_is_resolved
            else "Logical key occurs more than once in the physical workbook.",
            evidence=f"count={duplicate['duplicate_count']}; classification={classification}", **context,
        ))
        findings.append(_finding(
            "SEED-002", "info" if exact else "fail",
            "Exact duplicate can be removed deterministically." if exact else "Conflicting duplicate requires correction before import.",
            evidence=f"classification={classification}; selected_row={duplicate.get('selected_source_excel_row', '')}", **context,
        ))

    missing_id_columns = [column for column in ID_COLUMNS if column not in resolved.columns]
    if missing_id_columns:
        findings.append(_finding("SEED-003", "fail", "Workbook is missing required ID columns.", evidence="|".join(missing_id_columns)))
    else:
        for _, row in resolved.iterrows():
            invalid_columns = [column for column in ID_COLUMNS if not _id_valid(row[column])]
            if not invalid_columns:
                continue
            context = _row_context(row)
            warning_only = _is_warning_only_aggregated_demand_branch(row)
            findings.append(_finding(
                "SEED-003", "warn" if warning_only else "fail",
                "Aggregate-demand placeholder branch is absent from LEAP; row retained with BranchID=-1."
                if warning_only else "Resolved row has one or more missing IDs.",
                evidence="|".join(invalid_columns), **context,
            ))
            is_zero = _expression_is_zero(row.get("Expression"), zero_tolerance)
            if is_zero is True:
                findings.append(_finding("SEED-005", "warn", "Missing-ID zero row may be an intended reset but cannot reset LEAP by ID.", evidence="|".join(invalid_columns), **context))
            else:
                detail = "unparseable" if is_zero is None else "nonzero"
                findings.append(_finding(
                    "SEED-004", "warn" if warning_only else "fail",
                    "Nonzero aggregate-demand placeholder cannot import because BranchID=-1."
                    if warning_only else "Missing-ID row contains a nonzero or unparseable expression.",
                    evidence=f"{detail}; ids={'|'.join(invalid_columns)}", **context,
                ))

    findings.extend(_validate_shares(resolved, tolerance=share_tolerance))

    configured_years = sorted({int(year) for year in required_years or []})
    scenario_years = {
        _normalized(scenario).lower(): sorted({int(year) for year in years})
        for scenario, years in (required_years_by_scenario or {}).items()
    }
    if (configured_years or scenario_years) and "Expression" in resolved:
        for _, row in resolved.iterrows():
            row_required_years = scenario_years.get(
                _normalized(row.get("Scenario")).lower(), configured_years
            )
            if not row_required_years:
                continue
            mode, payload = parse_expression(row["Expression"])
            context = _row_context(row)
            if _text(row["Expression"]).strip().lower() == "unlimited":
                continue
            if mode == "series" and isinstance(payload, dict):
                missing_years = [year for year in row_required_years if year not in payload]
                if missing_years:
                    findings.append(_finding("SEED-009", "fail", "Series expression omits required years.", evidence="|".join(map(str, missing_years)), **context))
            elif mode == "unknown":
                findings.append(_finding("SEED-009", "fail", "Expression cannot be parsed for year coverage.", evidence=_text(row["Expression"]), **context))

    configured_scenarios = {_text(value) for value in required_scenarios or [] if _text(value)}
    if configured_scenarios:
        coverage_key = ["Branch Path", "Variable", "Region"]
        for key, group in resolved.groupby(coverage_key, dropna=False, sort=True):
            key_values = key if isinstance(key, tuple) else (key,)
            present = {_text(value) for value in group["Scenario"]}
            missing_scenarios = sorted(configured_scenarios - present)
            if missing_scenarios:
                source_workflows = "|".join(sorted({
                    _text(value)
                    for value in group.get(SOURCE_WORKFLOW_COLUMN, pd.Series(dtype=object))
                    if _text(value)
                }))
                findings.append(_finding(
                    "SEED-010",
                    "fail",
                    "Branch-variable-region key omits configured scenarios.",
                    evidence="|".join(missing_scenarios),
                    **dict(zip(coverage_key, key_values)),
                    source_workflow=source_workflows,
                ))

    for source_workflow, source_scenarios in (required_scenarios_by_source or {}).items():
        if SOURCE_WORKFLOW_COLUMN not in resolved.columns:
            findings.append(_finding(
                "SEED-010",
                "fail",
                "Producer-specific scenario coverage was configured but source attribution is missing.",
                evidence=str(source_workflow),
            ))
            continue
        source_rows = resolved[
            resolved[SOURCE_WORKFLOW_COLUMN].map(_normalized).eq(_normalized(source_workflow))
        ]
        expected = {_text(value) for value in source_scenarios if _text(value)}
        coverage_key = ["Branch Path", "Variable", "Region"]
        for key, group in source_rows.groupby(coverage_key, dropna=False, sort=True):
            present = {_text(value) for value in group["Scenario"]}
            missing_scenarios = sorted(expected - present)
            if missing_scenarios:
                key_values = key if isinstance(key, tuple) else (key,)
                findings.append(_finding(
                    "SEED-010",
                    "fail",
                    "Producer row omits an explicitly configured scenario.",
                    evidence="|".join(missing_scenarios),
                    **dict(zip(coverage_key, key_values)),
                    source_workflow=source_workflow,
                ))

    if template_path is not None:
        path = Path(template_path)
        template_rows = load_template_rows(path)
        findings.extend(_validate_canonical_share_completeness(resolved, template_rows))
        valid_paths = _load_template_paths(path)
        for _, row in resolved.iterrows():
            branch_path = _text(row.get("Branch Path"))
            if _is_ignored_full_model_export_branch_path(branch_path):
                continue
            if branch_path and branch_path.lower() not in valid_paths:
                warning_only = _is_warning_only_aggregated_demand_branch(row)
                findings.append(_finding(
                    "SEED-011",
                    "warn" if warning_only else "fail",
                    "Aggregate-demand placeholder branch is absent from the canonical full-model export."
                    if warning_only else "Branch path is absent from the canonical full-model export.",
                    evidence=str(path),
                    **_row_context(row),
                ))

    exception_rows = validate_exception_records(exceptions)
    for finding in findings:
        matching = [exception for exception in exception_rows if _exception_matches(finding, exception)]
        if matching:
            finding["exception_applied"] = True
            finding["exception_id"] = _text(matching[0].get("exception_id"))
            finding["exception_reason"] = _text(
                matching[0].get("reason", matching[0].get("note", ""))
            )
            finding["blocking"] = False
            finding["status"] = "excepted"
        else:
            finding["exception_applied"] = False
            finding["exception_id"] = ""
            finding["exception_reason"] = ""

    return ValidationResult(
        resolved_rows=resolved,
        duplicate_groups=duplicate_groups,
        findings=pd.DataFrame(findings),
    )


class BaselineSeedValidationError(ValueError):
    """Raised only after production diagnostics have been written."""


def prepare_seed_rows_for_write(
    data: pd.DataFrame,
    *,
    template_path: str | Path,
    diagnostics_dir: str | Path,
    diagnostic_stem: str,
    required_years_by_scenario: Mapping[str, Iterable[int]] | None = None,
    required_scenarios_by_source: Mapping[str, Iterable[str]] | None = None,
    share_tolerance: float = 1e-6,
    exceptions: Iterable[dict[str, object]] | None = None,
    blocking_findings_are_warnings: bool = False,
    raise_on_blocking: bool = True,
) -> ValidationResult:
    """Complete, enrich, validate, and persist diagnostics before any write."""
    enriched = enrich_seed_ids_from_template(data, template_path)
    initial = validate_seed_rows(
        enriched,
        template_path=template_path,
        required_years_by_scenario=required_years_by_scenario,
        required_scenarios_by_source=required_scenarios_by_source,
        share_tolerance=share_tolerance,
        exceptions=exceptions,
        allow_exact_duplicate_resolution=True,
    )
    completed_rows = initial.resolved_rows
    completion_findings = pd.DataFrame()
    if required_years_by_scenario:
        completed_rows, completion_findings = complete_canonical_share_groups(
            completed_rows,
            template_path=template_path,
            required_years_by_scenario=required_years_by_scenario,
        )
        completed_rows = enrich_seed_ids_from_template(completed_rows, template_path)
    final = validate_seed_rows(
        completed_rows,
        template_path=template_path,
        required_years_by_scenario=required_years_by_scenario,
        required_scenarios_by_source=required_scenarios_by_source,
        share_tolerance=share_tolerance,
        exceptions=exceptions,
        allow_exact_duplicate_resolution=True,
    )
    initial_duplicate_findings = initial.findings[
        initial.findings.get("rule_id", pd.Series("", index=initial.findings.index)).isin({"SEED-001", "SEED-002"})
    ]
    final_nonduplicate_findings = final.findings[
        ~final.findings.get("rule_id", pd.Series("", index=final.findings.index)).isin({"SEED-001", "SEED-002"})
    ]
    finding_frames = [frame for frame in (initial_duplicate_findings, completion_findings, final_nonduplicate_findings) if not frame.empty]
    result = ValidationResult(
        resolved_rows=final.resolved_rows,
        duplicate_groups=initial.duplicate_groups,
        findings=pd.concat(finding_frames, ignore_index=True, sort=False) if finding_frames else pd.DataFrame(),
    )

    if blocking_findings_are_warnings and not result.findings.empty and "blocking" in result.findings.columns:
        work = result.findings.copy()
        blocking_mask = work["blocking"].fillna(False)
        if bool(blocking_mask.any()):
            work.loc[blocking_mask, "blocking"] = False
            if "severity" in work.columns:
                work.loc[blocking_mask, "severity"] = "warning"
            if "status" in work.columns:
                work.loc[blocking_mask, "status"] = "warn"
            result = ValidationResult(
                resolved_rows=result.resolved_rows,
                duplicate_groups=result.duplicate_groups,
                findings=work,
            )

    output_dir = Path(diagnostics_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    findings_path = output_dir / f"{diagnostic_stem}_rule_findings.csv"
    duplicates_path = output_dir / f"{diagnostic_stem}_duplicate_groups.csv"
    issue_groups_path = output_dir / f"{diagnostic_stem}_issue_groups.csv"
    filter_actionable_findings(result.findings).to_csv(findings_path, index=False)
    result.duplicate_groups.to_csv(duplicates_path, index=False)
    build_validation_issue_groups(filter_actionable_findings(result.findings)).to_csv(issue_groups_path, index=False)

    if raise_on_blocking and not result.blocking_findings.empty:
        rule_counts = result.blocking_findings["rule_id"].value_counts().sort_index()
        summary = ", ".join(f"{rule_id}={count}" for rule_id, count in rule_counts.items())
        raise BaselineSeedValidationError(
            "Baseline-seed workbook was not written because blocking validation "
            f"findings remain ({summary}). Diagnostics: {findings_path}"
        )
    return result


__all__ = [
    "ID_COLUMNS",
    "LOGICAL_KEY_COLUMNS",
    "RULE_SPECS",
    "RuleSpec",
    "ValidationResult",
    "BaselineSeedValidationError",
    "filter_actionable_findings",
    "build_missing_branch_issue_groups",
    "build_producer_coverage_issue_groups",
    "build_share_issue_groups",
    "build_validation_issue_groups",
    "check_producer_coverage",
    "SOURCE_FILE_COLUMN",
    "SOURCE_WORKFLOW_COLUMN",
    "enrich_seed_ids_from_template",
    "complete_canonical_share_groups",
    "load_template_rows",
    "prepare_seed_rows_for_write",
    "resolve_logical_duplicates",
    "validate_exception_records",
    "validate_seed_rows",
]

#%%
