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
        for column in sorted(
            set(row.index)
            - {*PROVENANCE_COLUMNS, *LOGICAL_KEY_COLUMNS, *ID_COLUMNS, "Expression"}
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
        - {*PROVENANCE_COLUMNS, *LOGICAL_KEY_COLUMNS}
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
) -> tuple[bool, str]:
    capacity_path, prefix_match = _capacity_paths_for_share_group(group_path, variable)
    if not capacity_path:
        return False, "capacity relationship is undefined"
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
        return False, "relevant Exogenous Capacity row is missing"
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
        return False, f"owning Exogenous Capacity rows are missing: {missing_capacity_paths}"
    required_years = [int(year) for year in years]
    for _, row in capacity_rows.iterrows():
        values = _expression_values(row.get("Expression"), required_years)
        if values is None or any(year not in values for year in required_years):
            return False, "relevant Exogenous Capacity is missing or unparseable"
        if any(abs(value) > tolerance for value in values.values()):
            return False, "relevant Exogenous Capacity is positive or nonzero"
    return True, "relevant Exogenous Capacity is explicitly zero"


def complete_canonical_share_groups(
    data: pd.DataFrame,
    *,
    template_path: str | Path,
    required_years_by_scenario: Mapping[str, Iterable[int]],
    tolerance: float = 1e-12,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalize and complete every represented canonical share sibling group."""
    result, _ = resolve_logical_duplicates(data)
    template = load_template_rows(template_path)
    template["__parent"] = template["Branch Path"].map(_share_group_path)
    template_shares = template[
        template["Variable"].map(_text).isin(SHARE_VARIABLE_RULE_IDS)
    ].copy()
    shares = result[result.get("Variable", pd.Series("", index=result.index)).map(_text).isin(SHARE_VARIABLE_RULE_IDS)].copy()
    if shares.empty:
        return result, pd.DataFrame()

    shares["__parent"] = shares["Branch Path"].map(_share_group_path)
    additions: list[pd.Series] = []
    diagnostics: list[dict[str, object]] = []
    group_columns = ["__parent", "Variable", "Scenario", "Region"]
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

        present_paths = {_normalized(value).lower() for value in group["Branch Path"]}
        group_additions: list[pd.Series] = []
        exemplar = group.sort_values("Branch Path", kind="mergesort").iloc[0]
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
            allowed, capacity_evidence = _zero_capacity_is_explicit(
                result, template, group_path=group_path, variable=variable, scenario=scenario,
                region=region, years=years, tolerance=tolerance,
            )
            if allowed:
                anchor = sorted(parsed_by_path, key=str.lower)[0]
                profiles = {
                    year: {path: 100.0 if path == anchor else 0.0 for path in parsed_by_path}
                    for year in years
                }
                diagnostics.append(_finding(
                    SHARE_VARIABLE_RULE_IDS[variable], "info",
                    "Generated deterministic synthetic share anchor for an explicitly zero-capacity group.",
                    evidence=f"anchor={anchor}; {capacity_evidence}",
                    **group_context,
                ))
            else:
                diagnostics.append(_finding(
                    SHARE_VARIABLE_RULE_IDS[variable], "fail",
                    "Synthetic share fallback is blocked without explicit zero capacity.",
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
                path = _text(frame.at[index, "Branch Path"])
                frame.at[index, "Expression"] = _format_data_expression({year: profiles[year][path] for year in years})

        for new_row in group_additions:
            path = _text(new_row["Branch Path"])
            new_row["Expression"] = _format_data_expression({year: profiles[year][path] for year in years})

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
    shares = data[data.get("Variable", pd.Series("", index=data.index)).map(_text).isin(SHARE_VARIABLE_RULE_IDS)].copy()
    if shares.empty:
        return findings
    canonical = template[template["Variable"].map(_text).isin(SHARE_VARIABLE_RULE_IDS)].copy()
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
    return {_text(value).lower() for value in data["Branch Path"] if _text(value)}


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


def enrich_seed_ids_from_template(
    data: pd.DataFrame,
    template_path: str | Path,
) -> pd.DataFrame:
    """Replace all four IDs with canonical values from the full-model export.

    Branch and variable IDs are branch-specific. Scenario and region IDs come
    from the template; a sole template RegionID is valid for renamed economy
    regions because each target LEAP area uses that same region object.
    Unmatched keys remain ``-1`` so the rule validator blocks the write.
    """
    result = data.copy()
    template = load_template_rows(template_path)

    template["__branch_key"] = template["Branch Path"].map(_normalized).str.lower()
    template["__variable_key"] = template["Variable"].map(_normalized).str.lower()
    template["__scenario_key"] = template["Scenario"].map(_normalized).str.lower()
    template["__region_key"] = template["Region"].map(_normalized).str.lower()

    canonical_paths = (
        template.loc[template["__branch_key"].ne(""), ["__branch_key", "Branch Path"]]
        .drop_duplicates("__branch_key")
        .set_index("__branch_key")["Branch Path"]
        .to_dict()
    )

    def _valid_id_rows(columns: list[str], id_column: str) -> pd.DataFrame:
        selected = template[columns + [id_column]].copy()
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

    branch_keys = result.get("Branch Path", pd.Series("", index=result.index)).map(_normalized).str.lower()
    variable_keys = result.get("Variable", pd.Series("", index=result.index)).map(_normalized).str.lower()
    scenario_keys = result.get("Scenario", pd.Series("", index=result.index)).map(_normalized).str.lower()
    region_keys = result.get("Region", pd.Series("", index=result.index)).map(_normalized).str.lower()

    result["Branch Path"] = branch_keys.map(canonical_paths).fillna(
        result.get("Branch Path", pd.Series("", index=result.index))
    )
    result["BranchID"] = branch_keys.map(branch_ids).fillna(-1).astype(int)
    result["VariableID"] = pd.Series(
        list(zip(branch_keys, variable_keys)), index=result.index
    ).map(variable_ids).fillna(-1).astype(int)
    result["ScenarioID"] = scenario_keys.map(scenario_ids).fillna(-1).astype(int)
    mapped_region_ids = region_keys.map(region_ids)
    if sole_region_id is not None:
        mapped_region_ids = mapped_region_ids.fillna(sole_region_id)
    result["RegionID"] = mapped_region_ids.fillna(-1).astype(int)
    return result


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
            findings.append(_finding("SEED-003", "fail", "Resolved row has one or more missing IDs.", evidence="|".join(invalid_columns), **context))
            is_zero = _expression_is_zero(row.get("Expression"), zero_tolerance)
            if is_zero is True:
                findings.append(_finding("SEED-005", "warn", "Missing-ID zero row may be an intended reset but cannot reset LEAP by ID.", evidence="|".join(invalid_columns), **context))
            else:
                detail = "unparseable" if is_zero is None else "nonzero"
                findings.append(_finding("SEED-004", "fail", "Missing-ID row contains a nonzero or unparseable expression.", evidence=f"{detail}; ids={'|'.join(invalid_columns)}", **context))

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
            if branch_path and branch_path.lower() not in valid_paths:
                findings.append(_finding(
                    "SEED-011",
                    "fail",
                    "Branch path is absent from the canonical full-model export.",
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

    output_dir = Path(diagnostics_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    findings_path = output_dir / f"{diagnostic_stem}_rule_findings.csv"
    duplicates_path = output_dir / f"{diagnostic_stem}_duplicate_groups.csv"
    result.findings.to_csv(findings_path, index=False)
    result.duplicate_groups.to_csv(duplicates_path, index=False)

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
