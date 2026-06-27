#%%
"""Validate LEAP baseline-seed rows against stable import rules.

The validators operate on a dataframe already read from a LEAP workbook. They
do not require a comparison workbook, and duplicate rows are resolved before
share totals or coverage are evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from codebase.functions.leap_expressions import parse_expression


# --- Stable rule definitions ---

LOGICAL_KEY_COLUMNS = ["Branch Path", "Variable", "Scenario", "Region"]
ID_COLUMNS = ["BranchID", "VariableID", "ScenarioID", "RegionID"]
SHARE_VARIABLE_RULE_IDS = {
    "Output Share": "SEED-006",
    "Process Share": "SEED-007",
    "Feedstock Fuel Share": "SEED-008",
}


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


def _row_sort_signature(row: pd.Series) -> tuple[object, ...]:
    id_validity = tuple(0 if _id_valid(row.get(column)) else 1 for column in ID_COLUMNS)
    ids = tuple(_normalized(row.get(column)) for column in ID_COLUMNS)
    expression = _expression_signature(row.get("Expression"))
    metadata = tuple(
        _normalized(row.get(column))
        for column in sorted(set(row.index) - {"source_excel_row", *LOGICAL_KEY_COLUMNS, *ID_COLUMNS, "Expression"})
    )
    return (sum(id_validity), id_validity, ids, expression, metadata)


def _duplicate_classification(group: pd.DataFrame) -> tuple[str, int]:
    expression_signatures = {_expression_signature(value) for value in group["Expression"]}
    id_signatures = {
        tuple(_normalized(row.get(column)) for column in ID_COLUMNS)
        for _, row in group.iterrows()
    }
    valid_rows = [index for index, row in group.iterrows() if _row_has_all_valid_ids(row)]

    if len(expression_signatures) == 1 and len(id_signatures) == 1:
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
            }
            if unknown_rows or missing:
                findings.append(_finding(rule_id, "fail", "Share group contains missing or unparseable values.", evidence=f"missing={missing}; unparseable={unknown_rows}", **context))
                continue
            share_sum = float(sum(values))
            if abs(share_sum) <= tolerance and variable in {"Output Share", "Process Share"}:
                findings.append(_finding(rule_id, "info", "All-zero share group treated as inactive.", evidence=f"sum={share_sum:.12g}", **context))
            elif abs(share_sum - 100.0) <= tolerance:
                findings.append(_finding(rule_id, "pass", "Share group sums to 100 percent.", evidence=f"sum={share_sum:.12g}", **context))
            else:
                findings.append(_finding(rule_id, "fail", "Share group does not sum to 100 percent.", evidence=f"sum={share_sum:.12g}", **context))
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
    return {_text(value).lower() for value in data["Branch Path"] if _text(value)}


def _exception_matches(finding: dict[str, object], exception: dict[str, object]) -> bool:
    metadata_keys = {"exception_id", "reason", "note"}
    match_fields = {
        key: value for key, value in exception.items() if key not in metadata_keys
    }
    return bool(match_fields) and all(
        _normalized(finding.get(key)) == _normalized(value)
        for key, value in match_fields.items()
    )


def validate_seed_rows(
    data: pd.DataFrame,
    *,
    template_path: str | Path | None = None,
    required_years: Iterable[int] | None = None,
    required_scenarios: Iterable[str] | None = None,
    share_tolerance: float = 1e-6,
    zero_tolerance: float = 1e-12,
    exceptions: Iterable[dict[str, object]] | None = None,
) -> ValidationResult:
    """Run focused baseline-seed rules without requiring a reference workbook."""
    resolved, duplicate_groups = resolve_logical_duplicates(data)
    findings: list[dict[str, object]] = []

    for _, duplicate in duplicate_groups.iterrows():
        context = {column: duplicate.get(column, "") for column in LOGICAL_KEY_COLUMNS}
        classification = _text(duplicate["classification"])
        exact = classification == "exact_duplicate_same_ids_and_expression"
        findings.append(_finding(
            "SEED-001", "fail", "Logical key occurs more than once in the physical workbook.",
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
            context = {column: row.get(column, "") for column in LOGICAL_KEY_COLUMNS}
            findings.append(_finding("SEED-003", "fail", "Resolved row has one or more missing IDs.", evidence="|".join(invalid_columns), **context))
            is_zero = _expression_is_zero(row.get("Expression"), zero_tolerance)
            if is_zero is True:
                findings.append(_finding("SEED-005", "warn", "Missing-ID zero row may be an intended reset but cannot reset LEAP by ID.", evidence="|".join(invalid_columns), **context))
            else:
                detail = "unparseable" if is_zero is None else "nonzero"
                findings.append(_finding("SEED-004", "fail", "Missing-ID row contains a nonzero or unparseable expression.", evidence=f"{detail}; ids={'|'.join(invalid_columns)}", **context))

    findings.extend(_validate_shares(resolved, tolerance=share_tolerance))

    configured_years = sorted({int(year) for year in required_years or []})
    if configured_years and "Expression" in resolved:
        for _, row in resolved.iterrows():
            mode, payload = parse_expression(row["Expression"])
            context = {column: row.get(column, "") for column in LOGICAL_KEY_COLUMNS}
            if mode == "series" and isinstance(payload, dict):
                missing_years = [year for year in configured_years if year not in payload]
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
                findings.append(_finding("SEED-010", "fail", "Branch-variable-region key omits configured scenarios.", evidence="|".join(missing_scenarios), **dict(zip(coverage_key, key_values))))

    if template_path is not None:
        path = Path(template_path)
        valid_paths = _load_template_paths(path)
        for _, row in resolved.iterrows():
            branch_path = _text(row.get("Branch Path"))
            if branch_path and branch_path.lower() not in valid_paths:
                findings.append(_finding("SEED-011", "fail", "Branch path is absent from the canonical full-model export.", evidence=str(path), **{column: row.get(column, "") for column in LOGICAL_KEY_COLUMNS}))

    exception_rows = list(exceptions or [])
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


__all__ = [
    "ID_COLUMNS",
    "LOGICAL_KEY_COLUMNS",
    "RULE_SPECS",
    "RuleSpec",
    "ValidationResult",
    "resolve_logical_duplicates",
    "validate_seed_rows",
]

#%%
