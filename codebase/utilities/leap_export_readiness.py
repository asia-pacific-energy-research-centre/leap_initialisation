"""Shared post-write checks for LEAP export workbooks.

The runner is intentionally small and diagnostic-first. Producer workflows keep
their domain-specific checks; this module covers properties that can be checked
from the emitted workbook and shared catalog alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from codebase.functions.leap_expressions import parse_expression
from codebase.utilities import fuel_catalog_preflight


LOGICAL_KEY_COLUMNS = ["Branch Path", "Variable", "Scenario", "Region"]
ID_COLUMNS = ["BranchID", "VariableID", "ScenarioID", "RegionID"]
FINDING_COLUMNS = [
    "workbook",
    "economy",
    "scenario",
    "branch_path",
    "variable",
    "producer",
    "check_name",
    "status",
    "severity",
    "reason",
    "suggested_fix",
]


@dataclass(frozen=True)
class ReadinessResult:
    findings: pd.DataFrame
    summary: pd.DataFrame
    findings_path: Path | None = None
    summary_path: Path | None = None

    @property
    def blocking_failures(self) -> int:
        return int(
            (
                self.findings["severity"].eq("blocking")
                & self.findings["status"].eq("error")
            ).sum()
        )


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _finding(
    *,
    workbook: Path,
    economy: str,
    scenario: str,
    branch_path: str = "",
    variable: str = "",
    producer: str,
    check_name: str,
    status: str,
    severity: str,
    reason: str,
    suggested_fix: str,
) -> dict[str, str]:
    return {
        "workbook": str(workbook),
        "economy": economy,
        "scenario": scenario,
        "branch_path": branch_path,
        "variable": variable,
        "producer": producer,
        "check_name": check_name,
        "status": status,
        "severity": severity,
        "reason": reason,
        "suggested_fix": suggested_fix,
    }


def _expression_has_nonzero_value(expression: object) -> bool:
    mode, payload = parse_expression(expression)
    if mode == "const":
        return payload is not None and float(payload) != 0.0
    if mode == "series" and isinstance(payload, dict):
        return any(float(value) != 0.0 for value in payload.values())
    return bool(_text(expression))


def _check_duplicate_keys(
    rows: pd.DataFrame,
    *,
    workbook: Path,
    economy: str,
    producer: str,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    available = [column for column in LOGICAL_KEY_COLUMNS if column in rows.columns]
    if len(available) != len(LOGICAL_KEY_COLUMNS):
        return [
            _finding(
                workbook=workbook,
                economy=economy,
                scenario="",
                producer=producer,
                check_name="duplicate_logical_keys",
                status="error",
                severity="blocking",
                reason=f"Workbook is missing logical-key columns: {sorted(set(LOGICAL_KEY_COLUMNS) - set(available))}.",
                suggested_fix="Emit Branch Path, Variable, Scenario, and Region for every row.",
            )
        ]
    duplicate_mask = rows.duplicated(subset=LOGICAL_KEY_COLUMNS, keep=False)
    for _, row in rows.loc[duplicate_mask].drop_duplicates(subset=LOGICAL_KEY_COLUMNS).iterrows():
        findings.append(
            _finding(
                workbook=workbook,
                economy=economy,
                scenario=_text(row.get("Scenario")),
                branch_path=_text(row.get("Branch Path")),
                variable=_text(row.get("Variable")),
                producer=producer,
                check_name="duplicate_logical_keys",
                status="error",
                severity="blocking",
                reason="Multiple rows share the LEAP logical key (Branch Path, Variable, Scenario, Region).",
                suggested_fix="Deduplicate producer output before the import boundary.",
            )
        )
    return findings


def _check_ids(
    rows: pd.DataFrame,
    *,
    workbook: Path,
    economy: str,
    producer: str,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    missing_columns = [column for column in ID_COLUMNS if column not in rows.columns]
    if missing_columns:
        return [
            _finding(
                workbook=workbook,
                economy=economy,
                scenario="",
                producer=producer,
                check_name="leap_ids",
                status="error",
                severity="blocking",
                reason=f"Workbook is missing LEAP identity columns: {missing_columns}.",
                suggested_fix="Preserve or explicitly attach all four LEAP ID columns.",
            )
        ]
    missing_mask = pd.Series(False, index=rows.index)
    for column in ID_COLUMNS:
        missing_mask |= pd.to_numeric(rows[column], errors="coerce").eq(-1)
    for _, row in rows.loc[missing_mask].iterrows():
        nonzero = _expression_has_nonzero_value(row.get("Expression", ""))
        findings.append(
            _finding(
                workbook=workbook,
                economy=economy,
                scenario=_text(row.get("Scenario")),
                branch_path=_text(row.get("Branch Path")),
                variable=_text(row.get("Variable")),
                producer=producer,
                check_name="leap_ids",
                status="error" if nonzero else "warning",
                severity="blocking" if nonzero else "warning",
                reason="One or more LEAP identity columns contain -1.",
                suggested_fix=(
                    "Resolve the row against the target economy template before import."
                    if nonzero
                    else "Review the zero-valued unresolved row; do not borrow another economy's IDs."
                ),
            )
        )
    return findings


def _check_region(
    rows: pd.DataFrame,
    *,
    workbook: Path,
    economy: str,
    expected_region: str | None,
    producer: str,
) -> list[dict[str, str]]:
    if not expected_region or "Region" not in rows.columns:
        return []
    actual = rows["Region"].map(_text)
    mismatches = rows.loc[actual.ne(expected_region)]
    return [
        _finding(
            workbook=workbook,
            economy=economy,
            scenario=_text(row.get("Scenario")),
            branch_path=_text(row.get("Branch Path")),
            variable=_text(row.get("Variable")),
            producer=producer,
            check_name="region_consistency",
            status="error",
            severity="blocking",
            reason=f"Region is {_text(row.get('Region'))!r}; expected {expected_region!r} for {economy}.",
            suggested_fix="Resolve Region from the same economy used for template IDs.",
        )
        for _, row in mismatches.iterrows()
    ]


def _check_legacy_transfer_paths(
    rows: pd.DataFrame,
    *,
    workbook: Path,
    economy: str,
    producer: str,
) -> list[dict[str, str]]:
    if "Branch Path" not in rows.columns:
        return []
    mask = rows["Branch Path"].map(_text).str.startswith("Transformation\\Transfers\\")
    return [
        _finding(
            workbook=workbook,
            economy=economy,
            scenario=_text(row.get("Scenario")),
            branch_path=_text(row.get("Branch Path")),
            variable=_text(row.get("Variable")),
            producer=producer,
            check_name="legacy_transfer_path",
            status="error",
            severity="blocking",
            reason="Transfer output uses the rejected legacy Transformation\\Transfers\\ path.",
            suggested_fix="Route transfer-adjacent outputs through their configured Transformation module path.",
        )
        for _, row in rows.loc[mask].iterrows()
    ]


def _check_catalog_coverage(
    rows: pd.DataFrame,
    *,
    catalog_path: Path,
    workbook: Path,
    economy: str,
    producer: str,
    scenario: str | None,
) -> list[dict[str, str]]:
    catalog = fuel_catalog_preflight.load_fuel_catalog(catalog_path)
    scoped = fuel_catalog_preflight._scope_rows_from_export_df(rows, scenario=scenario)
    expected = {
        (row.branch_path.strip(), row.variable.strip())
        for row in catalog.itertuples(index=False)
        if _text(row.branch_path)
    }
    findings: list[dict[str, str]] = []
    for _, row in scoped.iterrows():
        key = (_text(row.get("branch_path")), _text(row.get("variable")))
        if key in expected:
            continue
        findings.append(
            _finding(
                workbook=workbook,
                economy=economy,
                scenario=_text(row.get("scenario")),
                branch_path=key[0],
                variable=key[1],
                producer=producer,
                check_name="fuel_catalog_coverage",
                status="error",
                severity="blocking",
                reason="Generated fuel branch/variable is absent from the shared union catalog.",
                suggested_fix="Review the template union or source label; do not merge fuel labels automatically.",
            )
        )
    return findings


def run_export_readiness(
    workbook_path: Path | str,
    *,
    producer: str,
    economy: str = "",
    scenario: str | None = None,
    expected_region: str | None = None,
    catalog_path: Path | str | None = None,
    sheet_name: str = "LEAP",
    output_dir: Path | str | None = None,
) -> ReadinessResult:
    """Run shared post-write readiness checks and optionally persist reports."""
    workbook = Path(workbook_path).resolve()
    rows = fuel_catalog_preflight._read_branch_variable_rows(workbook, sheet_name=sheet_name)
    findings: list[dict[str, str]] = []
    if rows.empty:
        findings.append(
            _finding(
                workbook=workbook,
                economy=economy,
                scenario=scenario or "",
                producer=producer,
                check_name="workbook_read",
                status="error",
                severity="blocking",
                reason=f"No LEAP rows could be read from sheet {sheet_name!r}.",
                suggested_fix="Check the workbook path, sheet name, and LEAP header structure.",
            )
        )
    else:
        findings.extend(_check_duplicate_keys(rows, workbook=workbook, economy=economy, producer=producer))
        findings.extend(_check_ids(rows, workbook=workbook, economy=economy, producer=producer))
        findings.extend(
            _check_region(
                rows,
                workbook=workbook,
                economy=economy,
                expected_region=expected_region,
                producer=producer,
            )
        )
        findings.extend(
            _check_legacy_transfer_paths(rows, workbook=workbook, economy=economy, producer=producer)
        )
        if catalog_path is not None:
            findings.extend(
                _check_catalog_coverage(
                    rows,
                    catalog_path=Path(catalog_path).resolve(),
                    workbook=workbook,
                    economy=economy,
                    producer=producer,
                    scenario=scenario,
                )
            )

    findings_df = pd.DataFrame(findings, columns=FINDING_COLUMNS)
    if findings_df.empty:
        findings_df = pd.DataFrame(
            [{
                "workbook": str(workbook),
                "economy": economy,
                "scenario": scenario or "",
                "branch_path": "",
                "variable": "",
                "producer": producer,
                "check_name": "readiness",
                "status": "pass",
                "severity": "info",
                "reason": "All enabled readiness checks passed.",
                "suggested_fix": "",
            }],
            columns=FINDING_COLUMNS,
        )

    summary_df = (
        findings_df.groupby(["check_name", "status", "severity"], dropna=False)
        .size()
        .rename("rows_checked")
        .reset_index()
        .sort_values(["check_name", "status", "severity"])
        .reset_index(drop=True)
    )

    findings_path = None
    summary_path = None
    if output_dir is not None:
        output = Path(output_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)
        findings_path = output / "leap_export_readiness_findings.csv"
        summary_path = output / "leap_export_readiness_summary.json"
        findings_df.to_csv(findings_path, index=False)
        summary_path.write_text(
            json.dumps(
                {
                    "workbook": str(workbook),
                    "economy": economy,
                    "producer": producer,
                    "blocking_failures": int(
                        ((findings_df["status"] == "error") & (findings_df["severity"] == "blocking")).sum()
                    ),
                    "findings": summary_df.to_dict("records"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return ReadinessResult(
        findings=findings_df,
        summary=summary_df,
        findings_path=findings_path,
        summary_path=summary_path,
    )
