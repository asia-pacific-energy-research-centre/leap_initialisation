#%%
"""Apply opt-in, template-backed expression overrides to final baseline seeds.

The rules are deliberately narrow: they select canonical rows from an
economy-specific LEAP export template, optionally check the template's populated
year values, and insert or replace the matching row in the final seed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd


LOGICAL_KEY_COLUMNS = ("Branch Path", "Variable", "Scenario", "Region")
YEAR_TOKEN_LENGTH = 4
AUDIT_COLUMNS = (
    "economy",
    "rule_id",
    "action",
    "branch_path",
    "variable",
    "scenario",
    "region",
    "previous_expression",
    "replacement_expression",
    "template_differing_year_values",
    "template_blank_years",
    "config_path",
)


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _normalized(value: object) -> str:
    return " ".join(_text(value).split()).casefold()


def _as_string_list(value: object, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ValueError(f"{field_name} must be a string or list of strings.")


def _year_columns(frame: pd.DataFrame) -> list[object]:
    columns: list[object] = []
    for column in frame.columns:
        token = str(column).strip()
        if len(token) == YEAR_TOKEN_LENGTH and token.isdigit():
            columns.append(column)
    return sorted(columns, key=lambda column: int(str(column)))


def load_postprocess_rules(config_path: str | Path) -> list[dict[str, object]]:
    """Load and validate the version-1 JSON post-processing configuration."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Baseline-seed post-process config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Baseline-seed post-process config must be a JSON object.")
    if payload.get("version") != 1:
        raise ValueError("Baseline-seed post-process config version must be 1.")
    rules = payload.get("rules")
    if not isinstance(rules, list):
        raise ValueError("Baseline-seed post-process config 'rules' must be a list.")
    return [validate_postprocess_rule(rule) for rule in rules]


def validate_postprocess_rule(rule: object) -> dict[str, object]:
    """Return one normalized rule or raise for an ambiguous rule."""
    if not isinstance(rule, dict):
        raise ValueError("Each baseline-seed post-process rule must be an object.")
    normalized = dict(rule)
    rule_id = _text(normalized.get("rule_id"))
    if not rule_id:
        raise ValueError("Each baseline-seed post-process rule requires rule_id.")
    normalized["rule_id"] = rule_id
    normalized["enabled"] = bool(normalized.get("enabled", True))

    for field in (
        "economies",
        "branch_path_equals",
        "branch_path_contains",
        "variable_equals",
        "scenarios",
    ):
        normalized[field] = _as_string_list(
            normalized.get(field),
            field_name=f"{rule_id}.{field}",
        )

    if not any(
        normalized[field]
        for field in ("branch_path_equals", "branch_path_contains", "variable_equals")
    ):
        raise ValueError(
            f"Rule {rule_id!r} must constrain branch_path_equals, "
            "branch_path_contains, or variable_equals."
        )
    replacement_expression = _text(normalized.get("replacement_expression"))
    if not replacement_expression:
        raise ValueError(f"Rule {rule_id!r} requires replacement_expression.")
    normalized["replacement_expression"] = replacement_expression

    if "template_value_not_equal_to" in normalized:
        try:
            normalized["template_value_not_equal_to"] = float(
                normalized["template_value_not_equal_to"]
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Rule {rule_id!r}.template_value_not_equal_to must be numeric."
            ) from exc
    normalized["include_blank_template_values"] = bool(
        normalized.get("include_blank_template_values", False)
    )
    normalized["require_match"] = bool(normalized.get("require_match", False))
    return normalized


def _matches_allowed_value(value: object, allowed: Iterable[str]) -> bool:
    allowed_values = {_normalized(item) for item in allowed if _text(item)}
    return not allowed_values or _normalized(value) in allowed_values


def _rule_mask(
    template_rows: pd.DataFrame,
    rule: Mapping[str, object],
    *,
    economy: str,
) -> pd.Series:
    mask = pd.Series(True, index=template_rows.index)
    if not _matches_allowed_value(economy, rule.get("economies", [])):
        return pd.Series(False, index=template_rows.index)

    paths = template_rows["Branch Path"].map(_normalized)
    exact_paths = {
        _normalized(value) for value in rule.get("branch_path_equals", []) if _text(value)
    }
    if exact_paths:
        mask &= paths.isin(exact_paths)

    for fragment in rule.get("branch_path_contains", []):
        token = _normalized(fragment)
        if token:
            mask &= paths.str.contains(token, regex=False, na=False)

    variables = {
        _normalized(value) for value in rule.get("variable_equals", []) if _text(value)
    }
    if variables:
        mask &= template_rows["Variable"].map(_normalized).isin(variables)

    scenarios = {
        _normalized(value) for value in rule.get("scenarios", []) if _text(value)
    }
    if scenarios:
        mask &= template_rows["Scenario"].map(_normalized).isin(scenarios)
    return mask


def _template_trigger_values(
    row: pd.Series,
    *,
    year_columns: Iterable[object],
    expected_value: float | None,
    include_blank_values: bool,
) -> dict[str, object]:
    populated: dict[str, float] = {}
    blank_years: list[str] = []
    for column in year_columns:
        value = pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
        if pd.isna(value):
            blank_years.append(str(column))
            continue
        populated[str(column)] = float(value)

    if expected_value is None:
        triggered = True
        differing = dict(populated)
    else:
        differing = {
            year: value
            for year, value in populated.items()
            if abs(value - expected_value) > 1e-12
        }
        triggered = bool(differing) or (include_blank_values and bool(blank_years))
    return {
        "triggered": triggered,
        "differing_values": differing,
        "blank_years": blank_years if include_blank_values else [],
    }


def apply_postprocess_rules(
    seed_rows: pd.DataFrame,
    template_rows: pd.DataFrame,
    rules: Iterable[Mapping[str, object]],
    *,
    economy: str,
    config_path: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Insert or replace seed rows selected from the canonical template.

    Template values are used only to decide whether a rule triggers and to
    provide canonical row metadata. The configured replacement expression is
    authoritative when a row is added to the seed.
    """
    required_template = {*LOGICAL_KEY_COLUMNS, "Branch Path", "Variable", "Scenario"}
    missing = sorted(required_template - set(template_rows.columns))
    if missing:
        raise ValueError(f"Template rows are missing required columns: {missing}")

    result = seed_rows.copy()
    template_year_columns = _year_columns(template_rows)
    audit_rows: list[dict[str, object]] = []

    for raw_rule in rules:
        rule = validate_postprocess_rule(raw_rule)
        if not rule["enabled"]:
            continue
        if not _matches_allowed_value(economy, rule.get("economies", [])):
            continue
        selected = template_rows.loc[
            _rule_mask(template_rows, rule, economy=economy)
        ].copy()

        triggered_rows: list[tuple[pd.Series, dict[str, object]]] = []
        for _, template_row in selected.iterrows():
            trigger = _template_trigger_values(
                template_row,
                year_columns=template_year_columns,
                expected_value=rule.get("template_value_not_equal_to"),
                include_blank_values=bool(rule["include_blank_template_values"]),
            )
            if trigger["triggered"]:
                triggered_rows.append((template_row, trigger))

        if rule["require_match"] and not triggered_rows:
            raise ValueError(
                f"Baseline-seed post-process rule {rule['rule_id']!r} did not "
                f"match a triggering template row for economy {economy}."
            )

        for template_row, trigger in triggered_rows:
            key_mask = pd.Series(True, index=result.index)
            for column in LOGICAL_KEY_COLUMNS:
                if column not in result.columns:
                    result[column] = pd.NA
                key_mask &= result[column].map(_normalized).eq(
                    _normalized(template_row.get(column))
                )

            prior = result.loc[key_mask].copy()
            action = "replace" if not prior.empty else "insert"
            previous_expression = "|".join(
                sorted(
                    {
                        _text(value)
                        for value in prior.get("Expression", pd.Series(dtype=object))
                        if _text(value)
                    }
                )
            )
            result = result.loc[~key_mask].copy()

            row = template_row.copy()
            row["Expression"] = rule["replacement_expression"]
            for column in template_year_columns:
                row[column] = pd.NA
            row["source_workflow"] = "baseline_seed_postprocess"
            row["source_file"] = str(config_path)
            row["source_excel_row"] = pd.NA
            result = pd.concat([result, pd.DataFrame([row])], ignore_index=True, sort=False)

            audit_rows.append(
                {
                    "economy": economy,
                    "rule_id": rule["rule_id"],
                    "action": action,
                    "branch_path": template_row["Branch Path"],
                    "variable": template_row["Variable"],
                    "scenario": template_row["Scenario"],
                    "region": template_row["Region"],
                    "previous_expression": previous_expression,
                    "replacement_expression": rule["replacement_expression"],
                    "template_differing_year_values": json.dumps(
                        trigger["differing_values"],
                        sort_keys=True,
                    ),
                    "template_blank_years": json.dumps(trigger["blank_years"]),
                    "config_path": str(config_path),
                }
            )

    audit = pd.DataFrame(audit_rows, columns=AUDIT_COLUMNS)
    return result, audit


#%%
