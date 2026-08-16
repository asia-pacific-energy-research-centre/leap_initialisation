#%%
"""Central post-write validation for final baseline-seed artifact sets.

The producer boundary still performs fail-fast and pre-write validation. This
module reopens the saved workbooks and emits one deterministic, run-level audit
package. Production callers configure every check as ``audit`` in this phase.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import pandas as pd

from codebase.functions.baseline_seed_validation import (
    AGGREGATED_DEMAND_BRANCH_PREFIX,
    ID_COLUMNS,
    LOGICAL_KEY_COLUMNS,
    SOURCE_WORKFLOW_COLUMN,
    apply_template_ids,
    build_template_id_lookup,
    drop_zero_only_optional_unmatched_rows,
    row_has_only_zero_payload,
    validate_seed_rows,
)
from codebase.functions.baseline_seed_structure_migration import (
    CLASSIFICATION_COLUMN,
    classify_structure_migration_findings,
)
from codebase.functions.leap_excel_io import LeapSheet, read_leap_sheet
from codebase.functions.leap_expressions import parse_expression
from codebase.utilities.typed_storage import write_manifested_parquet


# --- Stable contract -------------------------------------------------------

CONTRACT_VERSION = "1.0.0-audit"
CHECK_IDS = tuple(f"BSA-{number:03d}" for number in range(1, 11))
ENFORCEMENT_MODES = frozenset({"disabled", "audit", "warn", "block"})
DEFAULT_ENFORCEMENT_BY_CHECK = {check_id: "audit" for check_id in CHECK_IDS}
CONTRACT_SEVERITY_BY_CHECK = {check_id: "hard" for check_id in CHECK_IDS}

REQUIRED_SHEETS = ("LEAP", "FOR_VIEWING")
REQUIRED_COMMON_COLUMNS = (
    *ID_COLUMNS,
    *LOGICAL_KEY_COLUMNS,
    "Scale",
    "Units",
    "Per...",
)
REQUIRED_COLUMNS_BY_SHEET = {
    "LEAP": (*REQUIRED_COMMON_COLUMNS, "Expression"),
    "FOR_VIEWING": (*REQUIRED_COMMON_COLUMNS, "Method"),
}

FINDING_COLUMNS = [
    "run_id",
    "economy",
    "workbook",
    "check_id",
    "contract_severity",
    "enforcement_mode",
    "status",
    "would_block",
    "would_block_without_migration_policy",
    "run_was_blocked",
    CLASSIFICATION_COLUMN,
    "migration_backlog_id",
    "migration_review_status",
    "branch_path",
    "variable",
    "scenario",
    "year",
    "expected",
    "actual",
    "evidence",
    "source_workflow",
    "exception_id",
    "suggested_fix",
]

SUMMARY_COLUMNS = [
    "check_id",
    "contract_severity",
    "enforcement_mode",
    "status",
    "finding_count",
    "would_block_count",
    "run_was_blocked_count",
]

SEED_RULE_TO_BSA = {
    "SEED-001": "BSA-003",
    "SEED-002": "BSA-003",
    "SEED-003": "BSA-004",
    "SEED-004": "BSA-005",
    "SEED-005": "BSA-005",
    "SEED-006": "BSA-006",
    "SEED-007": "BSA-006",
    "SEED-008": "BSA-006",
    "SEED-009": "BSA-007",
    "SEED-010": "BSA-007",
    "SEED-011": "BSA-004",
    "SEED-013": "BSA-005",
}


@dataclass(frozen=True)
class ArtifactValidationResult:
    """In-memory result plus the three persisted acceptance-package paths."""

    findings: pd.DataFrame
    summary: pd.DataFrame
    manifest: dict[str, object]
    findings_path: Path
    findings_review_path: Path
    summary_path: Path
    manifest_path: Path

    @property
    def shadow_status(self) -> str:
        return str(self.manifest["final_shadow_status"])

    @property
    def accepted(self) -> bool:
        return bool(self.manifest["accepted"])


# --- Small shared helpers --------------------------------------------------

def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _normalized(value: object) -> str:
    return " ".join(_text(value).split()).casefold()


def _normalize_economies(values: Iterable[object]) -> list[str]:
    return sorted({_text(value) for value in values if _text(value)})


def _normalize_path(path: Path | str) -> Path:
    return Path(str(path).replace("\\", "/")).resolve()


def sha256_file(path: Path | str) -> str:
    """Return a streaming SHA-256 digest, or an empty string when absent."""
    resolved = _normalize_path(path)
    if not resolved.is_file():
        return ""
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_enforcement(
    enforcement_by_check: Mapping[str, str] | None,
) -> dict[str, str]:
    configured = dict(DEFAULT_ENFORCEMENT_BY_CHECK)
    configured.update({str(key): str(value).strip().lower() for key, value in (enforcement_by_check or {}).items()})
    unknown_checks = sorted(set(configured) - set(CHECK_IDS))
    if unknown_checks:
        raise ValueError(f"Unknown baseline-seed artifact check IDs: {unknown_checks}")
    invalid_modes = {
        check_id: mode for check_id, mode in configured.items() if mode not in ENFORCEMENT_MODES
    }
    if invalid_modes:
        raise ValueError(f"Invalid baseline-seed artifact enforcement modes: {invalid_modes}")
    return {check_id: configured[check_id] for check_id in CHECK_IDS}


def _finding(
    *,
    run_id: str,
    check_id: str,
    enforcement_mode: str,
    status: str,
    economy: str = "",
    workbook: Path | str | None = None,
    branch_path: object = "",
    variable: object = "",
    scenario: object = "",
    year: object = "",
    expected: object = "",
    actual: object = "",
    evidence: object = "",
    source_workflow: object = "",
    exception_id: object = "",
    suggested_fix: object = "",
) -> dict[str, object]:
    normalized_status = str(status).strip().upper()
    severity = CONTRACT_SEVERITY_BY_CHECK[check_id]
    would_block = severity == "hard" and normalized_status in {
        "FAIL",
        "INCOMPLETE",
        "CHECK_ERROR",
    }
    return {
        "run_id": str(run_id),
        "economy": str(economy),
        "workbook": str(_normalize_path(workbook)) if workbook else "",
        "check_id": check_id,
        "contract_severity": severity,
        "enforcement_mode": enforcement_mode,
        "status": normalized_status,
        "would_block": bool(would_block),
        "would_block_without_migration_policy": bool(would_block),
        "run_was_blocked": bool(would_block and enforcement_mode == "block"),
        CLASSIFICATION_COLUMN: "not_structure_migration",
        "migration_backlog_id": "",
        "migration_review_status": "",
        "branch_path": _text(branch_path),
        "variable": _text(variable),
        "scenario": _text(scenario),
        "year": _text(year),
        "expected": _text(expected),
        "actual": _text(actual),
        "evidence": _text(evidence),
        "source_workflow": _text(source_workflow),
        "exception_id": _text(exception_id),
        "suggested_fix": _text(suggested_fix),
    }


def _pass_finding(
    *,
    run_id: str,
    check_id: str,
    enforcement_mode: str,
    economy: str = "",
    workbook: Path | str | None = None,
    evidence: str = "",
) -> dict[str, object]:
    return _finding(
        run_id=run_id,
        check_id=check_id,
        enforcement_mode=enforcement_mode,
        status="PASS",
        economy=economy,
        workbook=workbook,
        evidence=evidence,
    )


def _error_finding(
    *,
    run_id: str,
    check_id: str,
    enforcement_mode: str,
    exc: Exception,
    economy: str = "",
    workbook: Path | str | None = None,
) -> dict[str, object]:
    return _finding(
        run_id=run_id,
        check_id=check_id,
        enforcement_mode=enforcement_mode,
        status="CHECK_ERROR",
        economy=economy,
        workbook=workbook,
        evidence=f"{type(exc).__name__}: {exc}",
        suggested_fix="Repair the check or its required evidence; do not treat this artifact as passed.",
    )


def _sort_findings(findings: Sequence[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(findings, columns=FINDING_COLUMNS)
    if frame.empty:
        return frame
    sort_columns = [
        "check_id",
        "economy",
        "workbook",
        "status",
        "branch_path",
        "variable",
        "scenario",
        "year",
        "evidence",
    ]
    return frame.sort_values(sort_columns, kind="stable").reset_index(drop=True)


def _logical_key(row: pd.Series) -> tuple[str, str, str, str]:
    return tuple(_normalized(row.get(column)) for column in LOGICAL_KEY_COLUMNS)


def _id_number(value: object) -> int | None:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return None
    return int(number)


def _read_candidate_workbook(path: Path) -> dict[str, LeapSheet]:
    with pd.ExcelFile(path, engine="openpyxl") as workbook:
        sheet_names = set(workbook.sheet_names)
    missing = sorted(set(REQUIRED_SHEETS) - sheet_names)
    if missing:
        raise ValueError(f"missing required sheets: {missing}")
    return {
        sheet_name: read_leap_sheet(
            path,
            sheet_name=sheet_name,
            drop_blank_columns=True,
        )
        for sheet_name in REQUIRED_SHEETS
    }


# --- BSA-001 / BSA-002 -----------------------------------------------------

def check_required_artifact_set(
    *,
    run_id: str,
    expected_economies: Iterable[str],
    candidate_workbooks: Mapping[str, Path | str],
    enforcement_mode: str,
) -> list[dict[str, object]]:
    """Check explicit expected economy coverage without directory discovery."""
    expected = set(_normalize_economies(expected_economies))
    supplied = {_text(economy) for economy in candidate_workbooks if _text(economy)}
    findings: list[dict[str, object]] = []
    for economy in sorted(expected - supplied):
        findings.append(_finding(
            run_id=run_id,
            check_id="BSA-001",
            enforcement_mode=enforcement_mode,
            status="FAIL",
            economy=economy,
            expected="one candidate workbook",
            actual="no path supplied",
            suggested_fix="Pass the exact workbook path produced for this economy.",
        ))
    for economy in sorted(supplied - expected):
        findings.append(_finding(
            run_id=run_id,
            check_id="BSA-001",
            enforcement_mode=enforcement_mode,
            status="FAIL",
            economy=economy,
            workbook=candidate_workbooks[economy],
            expected="economy listed in expected_economies",
            actual="unexpected supplied economy",
            suggested_fix="Correct the explicit run inventory before qualification.",
        ))
    for economy in sorted(expected & supplied):
        path = _normalize_path(candidate_workbooks[economy])
        if not path.is_file():
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-001",
                enforcement_mode=enforcement_mode,
                status="FAIL",
                economy=economy,
                workbook=path,
                expected="existing candidate workbook",
                actual="missing file",
                suggested_fix="Restore or regenerate the expected economy workbook.",
            ))
    if not findings:
        findings.append(_pass_finding(
            run_id=run_id,
            check_id="BSA-001",
            enforcement_mode=enforcement_mode,
            evidence=f"expected_economies={'|'.join(sorted(expected))}",
        ))
    return findings


def check_workbook_structure(
    *,
    run_id: str,
    economy: str,
    workbook: Path,
    enforcement_mode: str,
) -> tuple[list[dict[str, object]], dict[str, LeapSheet] | None]:
    """Reopen a workbook and validate sheets, preamble, header, and columns."""
    findings: list[dict[str, object]] = []
    try:
        sheets = _read_candidate_workbook(workbook)
    except Exception as exc:
        findings.append(_finding(
            run_id=run_id,
            check_id="BSA-002",
            enforcement_mode=enforcement_mode,
            status="FAIL",
            economy=economy,
            workbook=workbook,
            expected="readable workbook with LEAP and FOR_VIEWING sheets",
            actual=f"{type(exc).__name__}: {exc}",
            suggested_fix="Repair or regenerate the saved workbook and rerun the audit.",
        ))
        return findings, None

    for sheet_name, sheet in sheets.items():
        if sheet.header_row != 2:
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-002",
                enforcement_mode=enforcement_mode,
                status="FAIL",
                economy=economy,
                workbook=workbook,
                expected=f"{sheet_name} header row index 2",
                actual=sheet.header_row,
                evidence=sheet_name,
                suggested_fix="Restore the two-row LEAP preamble before the column header.",
            ))
        first_row = {_normalized(value) for value in sheet.preamble.iloc[0].tolist()} if len(sheet.preamble) >= 1 else set()
        second_is_blank = len(sheet.preamble) >= 2 and bool(sheet.preamble.iloc[1].isna().all())
        if "area:" not in first_row or "ver:" not in first_row or not second_is_blank:
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-002",
                enforcement_mode=enforcement_mode,
                status="FAIL",
                economy=economy,
                workbook=workbook,
                expected="row 0 contains Area:/Ver: and row 1 is blank",
                actual=f"sheet={sheet_name}; preamble_rows={len(sheet.preamble)}; blank_row={second_is_blank}",
                evidence=sheet_name,
                suggested_fix="Write the standard LEAP preamble without modifying its two rows.",
            ))
        missing_columns = sorted(set(REQUIRED_COLUMNS_BY_SHEET[sheet_name]) - set(sheet.data.columns))
        if missing_columns:
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-002",
                enforcement_mode=enforcement_mode,
                status="FAIL",
                economy=economy,
                workbook=workbook,
                expected="|".join(REQUIRED_COLUMNS_BY_SHEET[sheet_name]),
                actual=f"missing={missing_columns}",
                evidence=sheet_name,
                suggested_fix="Restore the required LEAP identity, key, metadata, and payload columns.",
            ))
    if not findings:
        findings.append(_pass_finding(
            run_id=run_id,
            check_id="BSA-002",
            enforcement_mode=enforcement_mode,
            economy=economy,
            workbook=workbook,
            evidence="LEAP and FOR_VIEWING structure valid",
        ))
    return findings, sheets


# --- Shared SEED validation: BSA-003/005/006/007 --------------------------

def check_shared_seed_rules(
    *,
    run_id: str,
    economy: str,
    workbook: Path,
    rows: pd.DataFrame,
    template_path: Path,
    expected_scenarios: Iterable[str],
    expected_years_by_scenario: Mapping[str, Iterable[int]],
    enforcement_by_check: Mapping[str, str],
    validation_exceptions: Iterable[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Reuse the pre-write SEED validator against reopened final rows."""
    validation_rows = rows.copy()
    if SOURCE_WORKFLOW_COLUMN not in validation_rows.columns:
        validation_rows[SOURCE_WORKFLOW_COLUMN] = ""
    aggregate_namespace = (
        validation_rows.get("Branch Path", pd.Series("", index=validation_rows.index))
        .map(_normalized)
        .str.startswith(AGGREGATED_DEMAND_BRANCH_PREFIX)
    )
    missing_provenance = validation_rows[SOURCE_WORKFLOW_COLUMN].map(_normalized).eq("")
    validation_rows.loc[
        aggregate_namespace & missing_provenance,
        SOURCE_WORKFLOW_COLUMN,
    ] = "aggregated_demand_workflow"
    result = validate_seed_rows(
        validation_rows,
        template_path=template_path,
        required_years_by_scenario=expected_years_by_scenario,
        required_scenarios=expected_scenarios,
        exceptions=validation_exceptions,
        allow_exact_duplicate_resolution=False,
    )
    classified_seed_findings, _migration_report = classify_structure_migration_findings(
        result.findings,
        economy=economy,
        run_id=run_id,
        template_path=template_path,
    )
    findings: list[dict[str, object]] = []
    failed_check_ids: set[str] = set()
    for _, seed_finding in classified_seed_findings.iterrows():
        seed_rule = _text(seed_finding.get("rule_id"))
        check_id = SEED_RULE_TO_BSA.get(seed_rule)
        if check_id not in {"BSA-003", "BSA-004", "BSA-005", "BSA-006", "BSA-007"}:
            continue
        seed_status = _normalized(seed_finding.get("status"))
        if seed_status not in {"fail", "warn", "excepted"}:
            continue
        exception_id = _text(seed_finding.get("exception_id"))
        final_status = (
            "EXCEPTED"
            if exception_id or seed_status == "excepted"
            else "WARN"
            if seed_status == "warn"
            else "FAIL"
        )
        failed_check_ids.add(check_id)
        artifact_finding = _finding(
            run_id=run_id,
            check_id=check_id,
            enforcement_mode=enforcement_by_check[check_id],
            status=final_status,
            economy=economy,
            workbook=workbook,
            branch_path=seed_finding.get("Branch Path"),
            variable=seed_finding.get("Variable"),
            scenario=seed_finding.get("Scenario"),
            year=seed_finding.get("year"),
            expected=seed_finding.get("violated_rule_expectation"),
            actual=seed_finding.get("message"),
            evidence=f"{seed_rule}: {_text(seed_finding.get('evidence'))}",
            source_workflow=seed_finding.get("source_workflow"),
            exception_id=exception_id,
            suggested_fix="Correct the producer or shared pre-write assembly rule, then regenerate the workbook.",
        )
        artifact_finding["would_block_without_migration_policy"] = bool(
            seed_finding.get("would_block_without_migration_policy", artifact_finding["would_block"])
        )
        artifact_finding[CLASSIFICATION_COLUMN] = seed_finding.get(
            CLASSIFICATION_COLUMN, "not_structure_migration"
        )
        artifact_finding["migration_backlog_id"] = seed_finding.get("migration_backlog_id", "")
        artifact_finding["migration_review_status"] = seed_finding.get("migration_review_status", "")
        findings.append(artifact_finding)
    for check_id in ("BSA-003", "BSA-005", "BSA-006", "BSA-007"):
        if check_id not in failed_check_ids:
            findings.append(_pass_finding(
                run_id=run_id,
                check_id=check_id,
                enforcement_mode=enforcement_by_check[check_id],
                economy=economy,
                workbook=workbook,
                evidence="shared validate_seed_rows produced no actionable mapped finding",
            ))
    return findings


# --- BSA-004 ---------------------------------------------------------------

def check_template_identity(
    *,
    run_id: str,
    economy: str,
    workbook: Path,
    rows: pd.DataFrame,
    template_path: Path,
    enforcement_mode: str,
) -> list[dict[str, object]]:
    """Compare saved IDs with the canonical shared template lookup output."""
    lookup = build_template_id_lookup(template_path)
    expected_rows = apply_template_ids(rows, lookup)
    findings: list[dict[str, object]] = []
    for index, actual_row in rows.reset_index(drop=True).iterrows():
        expected_row = expected_rows.reset_index(drop=True).loc[index]
        mismatches = {
            column: (_id_number(expected_row.get(column)), _id_number(actual_row.get(column)))
            for column in ID_COLUMNS
            if _id_number(expected_row.get(column)) != _id_number(actual_row.get(column))
        }
        if not mismatches:
            continue
        findings.append(_finding(
            run_id=run_id,
            check_id="BSA-004",
            enforcement_mode=enforcement_mode,
            status="FAIL",
            economy=economy,
            workbook=workbook,
            branch_path=actual_row.get("Branch Path"),
            variable=actual_row.get("Variable"),
            scenario=actual_row.get("Scenario"),
            expected=json.dumps({key: pair[0] for key, pair in mismatches.items()}, sort_keys=True),
            actual=json.dumps({key: pair[1] for key, pair in mismatches.items()}, sort_keys=True),
            evidence=str(template_path),
            source_workflow=actual_row.get(SOURCE_WORKFLOW_COLUMN),
            suggested_fix="Resolve labels and all four IDs from this economy's target template.",
        ))
    if not findings:
        findings.append(_pass_finding(
            run_id=run_id,
            check_id="BSA-004",
            enforcement_mode=enforcement_mode,
            economy=economy,
            workbook=workbook,
            evidence=f"template={template_path}",
        ))
    return findings


def check_producer_workbook_seed_rules(
    *,
    run_id: str,
    economy: str,
    source_workflow: str,
    workbook: Path,
    template_path: Path,
    expected_scenarios: Iterable[str],
    expected_years_by_scenario: Mapping[str, Iterable[int]],
    enforcement_by_check: Mapping[str, str],
    validation_exceptions: Iterable[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Audit one standalone producer workbook using the shared seed rules.

    Producer files deliberately retain their native single-sheet LEAP format,
    so they do not need the combined-workbook ``FOR_VIEWING`` structure check.
    They do need the same logical-key, template-ID, payload, and share checks
    before their rows are treated as ready for LEAP import.
    """
    try:
        rows = read_leap_sheet(workbook, sheet_name="LEAP").data.copy()
    except Exception as exc:
        return [_error_finding(
            run_id=run_id,
            check_id="BSA-002",
            enforcement_mode=enforcement_by_check["BSA-002"],
            exc=exc,
            economy=economy,
            workbook=workbook,
        )]
    rows[SOURCE_WORKFLOW_COLUMN] = source_workflow
    # Producer exports can intentionally defer ordinary template IDs to the
    # assembly stage. Resolve those labels exactly as the final seed writer
    # does; IDs that remain -1 are therefore genuine template mismatches.
    rows = apply_template_ids(rows, build_template_id_lookup(template_path))
    rows = drop_zero_only_optional_unmatched_rows(rows)
    shared_findings = check_shared_seed_rules(
        run_id=run_id,
        economy=economy,
        workbook=workbook,
        rows=rows,
        template_path=template_path,
        expected_scenarios=expected_scenarios,
        expected_years_by_scenario=expected_years_by_scenario,
        enforcement_by_check=enforcement_by_check,
        validation_exceptions=validation_exceptions,
    )
    identity_findings = check_template_identity(
        run_id=run_id,
        economy=economy,
        workbook=workbook,
        rows=rows,
        template_path=template_path,
        enforcement_mode=enforcement_by_check["BSA-004"],
    )
    findings = [*shared_findings, *identity_findings]
    for finding in findings:
        if not _text(finding.get("source_workflow")):
            finding["source_workflow"] = source_workflow
    return findings


# --- BSA-008 ---------------------------------------------------------------

def check_authorized_zero_scope(
    *,
    run_id: str,
    economy: str,
    workbook: Path,
    rows: pd.DataFrame,
    zero_scope_manifest: pd.DataFrame | Path | str | None,
    enforcement_mode: str,
    zero_tolerance: float = 1e-12,
) -> list[dict[str, object]]:
    """Validate declared reset/gap-fill rows; never infer authorization from zero."""
    if zero_scope_manifest is None:
        return [_finding(
            run_id=run_id,
            check_id="BSA-008",
            enforcement_mode=enforcement_mode,
            status="INCOMPLETE",
            economy=economy,
            workbook=workbook,
            expected="explicit zero-scope manifest",
            actual="not supplied",
            suggested_fix="Pass the producer-declared reset/gap-fill scope; zero values cannot prove authorization.",
        )]
    manifest = (
        zero_scope_manifest.copy()
        if isinstance(zero_scope_manifest, pd.DataFrame)
        else pd.read_csv(_normalize_path(zero_scope_manifest))
    )
    required = {*LOGICAL_KEY_COLUMNS, "authorized"}
    missing = sorted(required - set(manifest.columns))
    if missing:
        return [_finding(
            run_id=run_id,
            check_id="BSA-008",
            enforcement_mode=enforcement_mode,
            status="INCOMPLETE",
            economy=economy,
            workbook=workbook,
            expected="|".join(sorted(required)),
            actual=f"manifest missing={missing}",
            suggested_fix="Write a key-complete zero-scope manifest with an authorized flag.",
        )]
    row_lookup = {_logical_key(row): row for _, row in rows.iterrows()}
    findings: list[dict[str, object]] = []
    for _, declaration in manifest.iterrows():
        key = _logical_key(declaration)
        authorized_value = declaration.get("authorized")
        authorized = _normalized(authorized_value) in {"true", "1", "yes", "y"}
        final_row = row_lookup.get(key)
        context = {
            "branch_path": declaration.get("Branch Path"),
            "variable": declaration.get("Variable"),
            "scenario": declaration.get("Scenario"),
            "source_workflow": declaration.get("source_workflow", declaration.get("mechanism", "")),
            "exception_id": declaration.get("exception_id", ""),
        }
        if not authorized:
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-008",
                enforcement_mode=enforcement_mode,
                status="FAIL",
                economy=economy,
                workbook=workbook,
                expected="authorized reset/gap-fill declaration",
                actual="authorized=false",
                evidence="zero-scope manifest",
                suggested_fix="Remove the row or approve an exact producer-owned reset scope.",
                **context,
            ))
        elif final_row is None:
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-008",
                enforcement_mode=enforcement_mode,
                status="FAIL",
                economy=economy,
                workbook=workbook,
                expected="declared zero row present in final workbook",
                actual="missing logical key",
                evidence="zero-scope manifest",
                suggested_fix="Repair assembly so the authorized reset survives serialization.",
                **context,
            ))
        elif not row_has_only_zero_payload(final_row, tolerance=zero_tolerance):
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-008",
                enforcement_mode=enforcement_mode,
                status="FAIL",
                economy=economy,
                workbook=workbook,
                expected="zero payload",
                actual=final_row.get("Expression"),
                evidence="zero-scope manifest",
                suggested_fix="Keep reset declarations and serialized payloads consistent.",
                **context,
            ))
    if not findings:
        findings.append(_pass_finding(
            run_id=run_id,
            check_id="BSA-008",
            enforcement_mode=enforcement_mode,
            economy=economy,
            workbook=workbook,
            evidence=f"declared_zero_rows={len(manifest)}",
        ))
    return findings


# --- BSA-009 ---------------------------------------------------------------

def _row_values(row: pd.Series, years: Iterable[int]) -> tuple[dict[int, float] | None, str]:
    requested = [int(year) for year in years]
    expression = _text(row.get("Expression"))
    if expression:
        mode, payload = parse_expression(expression)
        if mode == "const" and payload is not None:
            return {year: float(payload) for year in requested}, ""
        if mode == "series" and isinstance(payload, dict):
            return ({year: float(payload[year]) for year in requested if year in payload}, "")
        if expression.casefold() == "unlimited":
            return None, "Unlimited"
        return None, f"unparseable expression: {expression}"
    values: dict[int, float] = {}
    for year in requested:
        column = next((candidate for candidate in (year, str(year), float(year)) if candidate in row.index), None)
        if column is None or pd.isna(row.loc[column]):
            continue
        raw_value = row.loc[column]
        value = pd.to_numeric(pd.Series([raw_value]), errors="coerce").iloc[0]
        if pd.isna(value):
            return None, f"non-numeric year value: {year}={raw_value}"
        values[year] = float(value)
    return values, ""


def check_serialized_value_conservation(
    *,
    run_id: str,
    economy: str,
    workbook: Path,
    leap_rows: pd.DataFrame,
    viewing_rows: pd.DataFrame,
    expected_rows: pd.DataFrame | Path | str | None,
    expected_years_by_scenario: Mapping[str, Iterable[int]],
    enforcement_mode: str,
    tolerance: float = 1e-9,
) -> list[dict[str, object]]:
    """Compare post-assembly expected rows with both serialized workbook views."""
    if expected_rows is None:
        return [_finding(
            run_id=run_id,
            check_id="BSA-009",
            enforcement_mode=enforcement_mode,
            status="INCOMPLETE",
            economy=economy,
            workbook=workbook,
            expected="post-assembly expected rows",
            actual="not supplied",
            suggested_fix="Pass the final resolved rows captured immediately before workbook serialization.",
        )]
    expected = expected_rows.copy() if isinstance(expected_rows, pd.DataFrame) else pd.read_csv(_normalize_path(expected_rows))
    missing_columns = sorted(set(LOGICAL_KEY_COLUMNS) - set(expected.columns))
    if missing_columns:
        raise ValueError(f"Expected post-assembly rows lack logical keys: {missing_columns}")

    expected_lookup = {_logical_key(row): row for _, row in expected.iterrows()}
    leap_lookup = {_logical_key(row): row for _, row in leap_rows.iterrows()}
    viewing_lookup = {_logical_key(row): row for _, row in viewing_rows.iterrows()}
    findings: list[dict[str, object]] = []
    for key in sorted(set(expected_lookup) | set(leap_lookup)):
        expected_row = expected_lookup.get(key)
        leap_row = leap_lookup.get(key)
        exemplar = expected_row if expected_row is not None else leap_row
        context = {
            "branch_path": exemplar.get("Branch Path") if exemplar is not None else "",
            "variable": exemplar.get("Variable") if exemplar is not None else "",
            "scenario": exemplar.get("Scenario") if exemplar is not None else "",
        }
        if expected_row is None or leap_row is None:
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-009",
                enforcement_mode=enforcement_mode,
                status="FAIL",
                economy=economy,
                workbook=workbook,
                expected="same logical-key set before and after serialization",
                actual="unexpected final row" if expected_row is None else "missing final row",
                suggested_fix="Repair final workbook assembly so no row is dropped or invented.",
                **context,
            ))
            continue
        scenario = _text(expected_row.get("Scenario"))
        years = list(expected_years_by_scenario.get(scenario, ()))
        expected_values, expected_error = _row_values(expected_row, years)
        actual_values, actual_error = _row_values(leap_row, years)
        if expected_error or actual_error:
            if expected_error == actual_error == "Unlimited":
                continue
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-009",
                enforcement_mode=enforcement_mode,
                status="FAIL",
                economy=economy,
                workbook=workbook,
                expected=expected_error or expected_row.get("Expression"),
                actual=actual_error or leap_row.get("Expression"),
                suggested_fix="Preserve the post-assembly expression form and values during workbook writing.",
                **context,
            ))
            continue
        expected_values = expected_values or {}
        actual_values = actual_values or {}
        viewing_row = viewing_lookup.get(key)
        for year in years:
            expected_value = expected_values.get(int(year))
            actual_value = actual_values.get(int(year))
            viewing_value = None
            if viewing_row is not None:
                viewing_column = next(
                    (
                        candidate
                        for candidate in (year, str(year), float(year))
                        if candidate in viewing_row.index
                    ),
                    None,
                )
                raw_viewing = (
                    viewing_row.loc[viewing_column]
                    if viewing_column is not None
                    else None
                )
                numeric_viewing = pd.to_numeric(pd.Series([raw_viewing]), errors="coerce").iloc[0]
                viewing_value = None if pd.isna(numeric_viewing) else float(numeric_viewing)
            values_match = (
                expected_value is not None
                and actual_value is not None
                and abs(expected_value - actual_value) <= tolerance
                and viewing_value is not None
                and abs(expected_value - viewing_value) <= tolerance
            )
            if values_match:
                continue
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-009",
                enforcement_mode=enforcement_mode,
                status="FAIL",
                economy=economy,
                workbook=workbook,
                year=year,
                expected=expected_value,
                actual=f"LEAP={actual_value}; FOR_VIEWING={viewing_value}",
                evidence=f"tolerance={tolerance}",
                suggested_fix="Repair expression/year serialization and regenerate the final workbook.",
                **context,
            ))
    if not findings:
        findings.append(_pass_finding(
            run_id=run_id,
            check_id="BSA-009",
            enforcement_mode=enforcement_mode,
            economy=economy,
            workbook=workbook,
            evidence=f"expected_rows={len(expected)}; tolerance={tolerance}",
        ))
    return findings


# --- BSA-010 and package ---------------------------------------------------

def check_diagnostics_and_manifests(
    *,
    run_id: str,
    enforcement_mode: str,
    expected_producers: Iterable[str],
    producer_artifacts_by_producer: Mapping[str, Iterable[Path | str]],
    required_diagnostics: Iterable[Path | str],
    prior_findings: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Verify evidence completeness and that BSA-001..009 all produced a row."""
    findings: list[dict[str, object]] = []
    for producer in sorted({_text(value) for value in expected_producers if _text(value)}):
        artifacts = [_normalize_path(path) for path in producer_artifacts_by_producer.get(producer, ())]
        existing = [path for path in artifacts if path.is_file()]
        if not existing:
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-010",
                enforcement_mode=enforcement_mode,
                status="INCOMPLETE",
                expected=f"artifact/manifest evidence for producer {producer}",
                actual="none supplied or readable",
                source_workflow=producer,
                suggested_fix="Pass exact current-run producer artifact or manifest paths.",
            ))
    for diagnostic in sorted({_normalize_path(path) for path in required_diagnostics}, key=str):
        if not diagnostic.is_file():
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-010",
                enforcement_mode=enforcement_mode,
                status="INCOMPLETE",
                expected="required diagnostic file",
                actual="missing",
                evidence=str(diagnostic),
                suggested_fix="Run or repair the required diagnostic before qualification.",
            ))
    represented = {str(finding.get("check_id")) for finding in prior_findings}
    for check_id in CHECK_IDS[:-1]:
        if check_id not in represented:
            findings.append(_finding(
                run_id=run_id,
                check_id="BSA-010",
                enforcement_mode=enforcement_mode,
                status="INCOMPLETE",
                expected=f"execution record for {check_id}",
                actual="missing",
                suggested_fix="Ensure every configured check emits PASS, FAIL, INCOMPLETE, or CHECK_ERROR.",
            ))
    if not findings:
        findings.append(_pass_finding(
            run_id=run_id,
            check_id="BSA-010",
            enforcement_mode=enforcement_mode,
            evidence="producer evidence, diagnostics, and check execution records are complete",
        ))
    return findings


def _summary(findings: pd.DataFrame) -> pd.DataFrame:
    if findings.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    summary = (
        findings.groupby(
            ["check_id", "contract_severity", "enforcement_mode", "status"],
            dropna=False,
        )
        .agg(
            finding_count=("status", "size"),
            would_block_count=("would_block", "sum"),
            run_was_blocked_count=("run_was_blocked", "sum"),
        )
        .reset_index()
    )
    return summary[SUMMARY_COLUMNS].sort_values(
        ["check_id", "status", "enforcement_mode"], kind="stable"
    ).reset_index(drop=True)


def _shadow_status(findings: pd.DataFrame) -> str:
    if findings["status"].isin({"INCOMPLETE", "CHECK_ERROR"}).any():
        return "SHADOW_INCOMPLETE"
    failed = findings["status"].eq("FAIL")
    if (failed & findings["contract_severity"].eq("hard")).any():
        return "SHADOW_WOULD_FAIL"
    if failed.any():
        return "SHADOW_WARN"
    if findings["status"].eq("WARN").any():
        return "SHADOW_WARN"
    return "SHADOW_PASS"


def _build_findings_review(findings: pd.DataFrame) -> pd.DataFrame:
    """Return a compact human review table for non-pass artifact findings."""
    review_columns = [
        "check_id",
        "status",
        "economy",
        "scenario",
        "source_workflow",
        "suggested_fix",
        "finding_count",
        "sample_branch_path",
        "sample_variable",
        "sample_year",
        "sample_expected",
        "sample_actual",
        "sample_evidence",
    ]
    actionable = findings.loc[~findings["status"].eq("PASS")].copy()
    if actionable.empty:
        return pd.DataFrame(columns=review_columns)
    group_columns = [
        "check_id",
        "status",
        "economy",
        "scenario",
        "source_workflow",
        "suggested_fix",
    ]
    review = (
        actionable.groupby(group_columns, dropna=False, sort=True)
        .agg(
            finding_count=("status", "size"),
            sample_branch_path=("branch_path", "first"),
            sample_variable=("variable", "first"),
            sample_year=("year", "first"),
            sample_expected=("expected", "first"),
            sample_actual=("actual", "first"),
            sample_evidence=("evidence", "first"),
        )
        .reset_index()
    )
    return review[review_columns]


def _file_records(paths_by_economy: Mapping[str, Path | str]) -> list[dict[str, str]]:
    return [
        {
            "economy": economy,
            "path": str(_normalize_path(path)),
            "sha256": sha256_file(path),
        }
        for economy, path in sorted(paths_by_economy.items())
    ]


def write_acceptance_package(
    *,
    run_id: str,
    output_dir: Path | str,
    findings: pd.DataFrame,
    expected_economies: Iterable[str],
    candidate_workbooks: Mapping[str, Path | str],
    template_paths_by_economy: Mapping[str, Path | str],
    enforcement_by_check: Mapping[str, str],
    required_diagnostics: Iterable[Path | str],
) -> ArtifactValidationResult:
    """Write deterministic CSV/JSON acceptance outputs."""
    output = _normalize_path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    ordered_findings = _sort_findings(findings.to_dict("records"))
    summary = _summary(ordered_findings)
    shadow_status = _shadow_status(ordered_findings)
    missing_diagnostics = sorted(
        str(_normalize_path(path))
        for path in required_diagnostics
        if not _normalize_path(path).is_file()
    )
    configured_checks = [
        {
            "check_id": check_id,
            "contract_severity": CONTRACT_SEVERITY_BY_CHECK[check_id],
            "enforcement_mode": enforcement_by_check[check_id],
            "ran": bool((ordered_findings["check_id"] == check_id).any())
            and enforcement_by_check[check_id] != "disabled",
        }
        for check_id in CHECK_IDS
    ]
    applied_exceptions = sorted({
        _text(value) for value in ordered_findings["exception_id"] if _text(value)
    })
    manifest: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "run_id": str(run_id),
        "expected_economies": _normalize_economies(expected_economies),
        "produced_economies": sorted(
            economy for economy, path in candidate_workbooks.items() if _normalize_path(path).is_file()
        ),
        "candidate_workbooks": _file_records(candidate_workbooks),
        "target_templates": _file_records(template_paths_by_economy),
        "configured_checks": configured_checks,
        "finding_counts": {
            str(key): int(value)
            for key, value in ordered_findings["status"].value_counts().sort_index().items()
        },
        "hard_findings_in_audit_mode": int(
            (
                ordered_findings["contract_severity"].eq("hard")
                & ordered_findings["enforcement_mode"].eq("audit")
                & ordered_findings["status"].isin({"FAIL", "INCOMPLETE", "CHECK_ERROR"})
            ).sum()
        ),
        "would_block_count": int(ordered_findings["would_block"].sum()),
        "run_was_blocked_count": int(ordered_findings["run_was_blocked"].sum()),
        "applied_exceptions": applied_exceptions,
        "missing_diagnostics": missing_diagnostics,
        "final_shadow_status": shadow_status,
        "accepted": not bool(ordered_findings["run_was_blocked"].any()),
    }
    findings_path = output / "baseline_seed_artifact_findings.parquet"
    findings_review_path = output / "baseline_seed_artifact_findings_review.csv"
    summary_path = output / "baseline_seed_artifact_summary.csv"
    manifest_path = output / "baseline_seed_artifact_manifest.json"
    findings_artifact = write_manifested_parquet(
        ordered_findings,
        findings_path,
        artifact_type="baseline_seed_artifact_findings_detail",
    )
    findings_review = _build_findings_review(ordered_findings)
    findings_review.to_csv(findings_review_path, index=False, lineterminator="\n")
    summary.to_csv(summary_path, index=False, lineterminator="\n")
    manifest["output_artifacts"] = {
        "findings_detail": findings_artifact,
        "findings_review": {
            "path": findings_review_path.name,
            "format": "csv",
            "row_count": int(len(findings_review)),
        },
        "summary": {
            "path": summary_path.name,
            "format": "csv",
            "row_count": int(len(summary)),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ArtifactValidationResult(
        findings=ordered_findings,
        summary=summary,
        manifest=manifest,
        findings_path=findings_path,
        findings_review_path=findings_review_path,
        summary_path=summary_path,
        manifest_path=manifest_path,
    )


# Individual check functions are referenced here so tests and notebook users can
# inject a failing check without changing production wiring.
CHECK_FUNCTIONS: dict[str, Callable[..., object]] = {
    "BSA-001": check_required_artifact_set,
    "BSA-002": check_workbook_structure,
    "BSA-004": check_template_identity,
    "BSA-008": check_authorized_zero_scope,
    "BSA-009": check_serialized_value_conservation,
    "BSA-010": check_diagnostics_and_manifests,
}


def run_baseline_seed_artifact_validation(
    *,
    run_id: str,
    candidate_workbooks: Mapping[str, Path | str],
    expected_economies: Iterable[str],
    template_paths_by_economy: Mapping[str, Path | str],
    expected_scenarios: Iterable[str],
    expected_years_by_scenario: Mapping[str, Iterable[int]],
    expected_producers: Iterable[str] = (),
    producer_artifacts_by_producer: Mapping[str, Iterable[Path | str]] | None = None,
    producer_workbooks_by_economy: Mapping[str, Mapping[str, Iterable[Path | str]]] | None = None,
    source_rows_by_economy: Mapping[str, pd.DataFrame | Path | str] | None = None,
    zero_scope_manifests_by_economy: Mapping[str, pd.DataFrame | Path | str] | None = None,
    required_diagnostics: Iterable[Path | str] = (),
    output_dir: Path | str,
    enforcement_by_check: Mapping[str, str] | None = None,
    validation_exceptions: Iterable[dict[str, object]] | None = None,
    check_functions: Mapping[str, Callable[..., object]] | None = None,
) -> ArtifactValidationResult:
    """Run all final-artifact checks and always return an acceptance package.

    Check-level exceptions become ``CHECK_ERROR`` findings. They never turn into
    passes and never raise in audit mode. Invalid function configuration still
    raises before execution because it is a programming/configuration error.
    """
    enforcement = _resolve_enforcement(enforcement_by_check)
    functions = dict(CHECK_FUNCTIONS)
    functions.update(check_functions or {})
    candidates = {_text(economy): _normalize_path(path) for economy, path in candidate_workbooks.items()}
    templates = {_text(economy): _normalize_path(path) for economy, path in template_paths_by_economy.items()}
    expected = _normalize_economies(expected_economies)
    required_diagnostic_paths = [_normalize_path(path) for path in required_diagnostics]
    producer_artifacts = producer_artifacts_by_producer or {}
    producer_workbooks = producer_workbooks_by_economy or {}
    source_rows = source_rows_by_economy or {}
    zero_manifests = zero_scope_manifests_by_economy or {}
    expected_scenario_list = [
        _text(scenario) for scenario in expected_scenarios if _text(scenario)
    ]
    expected_years = {
        str(scenario): sorted({int(year) for year in years})
        for scenario, years in expected_years_by_scenario.items()
    }
    findings: list[dict[str, object]] = []

    # BSA-001 is run-level.
    mode = enforcement["BSA-001"]
    if mode == "disabled":
        findings.append(_finding(run_id=run_id, check_id="BSA-001", enforcement_mode=mode, status="INCOMPLETE", actual="disabled"))
    else:
        try:
            findings.extend(functions["BSA-001"](
                run_id=run_id,
                expected_economies=expected,
                candidate_workbooks=candidates,
                enforcement_mode=mode,
            ))
        except Exception as exc:
            findings.append(_error_finding(run_id=run_id, check_id="BSA-001", enforcement_mode=mode, exc=exc))

    for economy in expected:
        workbook = candidates.get(economy)
        template = templates.get(economy)

        # Standalone producer workbooks are retained for audit and must meet the
        # same ID/readiness rules as the assembled seed, even when that combined
        # candidate is unavailable. Their native format is a LEAP sheet only, so
        # only the applicable shared checks are run here.
        for source_workflow, paths in sorted(producer_workbooks.get(economy, {}).items()):
            for producer_workbook in sorted({_normalize_path(path) for path in paths}, key=str):
                if not producer_workbook.is_file():
                    findings.append(_finding(
                        run_id=run_id,
                        check_id="BSA-001",
                        enforcement_mode=enforcement["BSA-001"],
                        status="INCOMPLETE",
                        economy=economy,
                        workbook=producer_workbook,
                        actual="configured standalone producer workbook unavailable",
                        source_workflow=source_workflow,
                    ))
                    continue
                if template is None or not template.is_file():
                    findings.append(_finding(
                        run_id=run_id,
                        check_id="BSA-004",
                        enforcement_mode=enforcement["BSA-004"],
                        status="INCOMPLETE",
                        economy=economy,
                        workbook=producer_workbook,
                        expected="target economy template",
                        actual="missing",
                        source_workflow=source_workflow,
                    ))
                    continue
                findings.extend(check_producer_workbook_seed_rules(
                    run_id=run_id,
                    economy=economy,
                    source_workflow=source_workflow,
                    workbook=producer_workbook,
                    template_path=template,
                    expected_scenarios=expected_scenario_list,
                    expected_years_by_scenario=expected_years,
                    enforcement_by_check=enforcement,
                    validation_exceptions=validation_exceptions,
                ))
        if workbook is None or not workbook.is_file():
            for check_id in CHECK_IDS[1:9]:
                findings.append(_finding(
                    run_id=run_id,
                    check_id=check_id,
                    enforcement_mode=enforcement[check_id],
                    status="INCOMPLETE",
                    economy=economy,
                    workbook=workbook,
                    expected="readable candidate workbook",
                    actual="unavailable",
                    suggested_fix="Restore the BSA-001 artifact before running workbook-level checks.",
                ))
            continue

        # BSA-002 produces the parsed physical sheets used by all later checks.
        sheets: dict[str, LeapSheet] | None = None
        mode = enforcement["BSA-002"]
        if mode == "disabled":
            findings.append(_finding(run_id=run_id, check_id="BSA-002", enforcement_mode=mode, status="INCOMPLETE", economy=economy, workbook=workbook, actual="disabled"))
        else:
            try:
                structure_findings, sheets = functions["BSA-002"](
                    run_id=run_id,
                    economy=economy,
                    workbook=workbook,
                    enforcement_mode=mode,
                )
                findings.extend(structure_findings)
            except Exception as exc:
                findings.append(_error_finding(run_id=run_id, check_id="BSA-002", enforcement_mode=mode, exc=exc, economy=economy, workbook=workbook))

        if sheets is None:
            for check_id in CHECK_IDS[2:9]:
                findings.append(_finding(
                    run_id=run_id,
                    check_id=check_id,
                    enforcement_mode=enforcement[check_id],
                    status="INCOMPLETE",
                    economy=economy,
                    workbook=workbook,
                    expected="parsed LEAP/FOR_VIEWING rows",
                    actual="BSA-002 did not provide them",
                    suggested_fix="Repair workbook structure, then rerun the gate.",
                ))
            continue

        leap_rows = sheets["LEAP"].data
        viewing_rows = sheets["FOR_VIEWING"].data
        # BSA-003/005/006/007 all route through one shared validator invocation.
        shared_checks = ("BSA-003", "BSA-005", "BSA-006", "BSA-007")
        if template is None or not template.is_file():
            for check_id in shared_checks:
                findings.append(_finding(
                    run_id=run_id,
                    check_id=check_id,
                    enforcement_mode=enforcement[check_id],
                    status="INCOMPLETE",
                    economy=economy,
                    workbook=workbook,
                    expected="target economy template",
                    actual="missing",
                    suggested_fix="Pass the exact template used to assemble this economy.",
                ))
        elif any(enforcement[check_id] == "disabled" for check_id in shared_checks):
            for check_id in shared_checks:
                if enforcement[check_id] == "disabled":
                    findings.append(_finding(run_id=run_id, check_id=check_id, enforcement_mode="disabled", status="INCOMPLETE", economy=economy, workbook=workbook, actual="disabled"))
            enabled_shared = [check_id for check_id in shared_checks if enforcement[check_id] != "disabled"]
            if enabled_shared:
                try:
                    shared_findings = check_shared_seed_rules(
                        run_id=run_id,
                        economy=economy,
                        workbook=workbook,
                        rows=leap_rows,
                        template_path=template,
                        expected_scenarios=expected_scenario_list,
                        expected_years_by_scenario=expected_years,
                        enforcement_by_check=enforcement,
                        validation_exceptions=validation_exceptions,
                    )
                    findings.extend([item for item in shared_findings if item["check_id"] in enabled_shared])
                except Exception as exc:
                    for check_id in enabled_shared:
                        findings.append(_error_finding(run_id=run_id, check_id=check_id, enforcement_mode=enforcement[check_id], exc=exc, economy=economy, workbook=workbook))
        else:
            try:
                findings.extend(check_shared_seed_rules(
                    run_id=run_id,
                    economy=economy,
                    workbook=workbook,
                    rows=leap_rows,
                    template_path=template,
                    expected_scenarios=expected_scenario_list,
                    expected_years_by_scenario=expected_years,
                    enforcement_by_check=enforcement,
                    validation_exceptions=validation_exceptions,
                ))
            except Exception as exc:
                for check_id in shared_checks:
                    findings.append(_error_finding(run_id=run_id, check_id=check_id, enforcement_mode=enforcement[check_id], exc=exc, economy=economy, workbook=workbook))

        # BSA-004 exact template identity.
        mode = enforcement["BSA-004"]
        if mode == "disabled":
            findings.append(_finding(run_id=run_id, check_id="BSA-004", enforcement_mode=mode, status="INCOMPLETE", economy=economy, workbook=workbook, actual="disabled"))
        elif template is None or not template.is_file():
            findings.append(_finding(run_id=run_id, check_id="BSA-004", enforcement_mode=mode, status="INCOMPLETE", economy=economy, workbook=workbook, expected="target economy template", actual="missing"))
        else:
            try:
                findings.extend(functions["BSA-004"](
                    run_id=run_id,
                    economy=economy,
                    workbook=workbook,
                    rows=leap_rows,
                    template_path=template,
                    enforcement_mode=mode,
                ))
            except Exception as exc:
                findings.append(_error_finding(run_id=run_id, check_id="BSA-004", enforcement_mode=mode, exc=exc, economy=economy, workbook=workbook))

        for check_id, kwargs in (
            ("BSA-008", {
                "rows": leap_rows,
                "zero_scope_manifest": zero_manifests.get(economy),
            }),
            ("BSA-009", {
                "leap_rows": leap_rows,
                "viewing_rows": viewing_rows,
                "expected_rows": source_rows.get(economy),
                "expected_years_by_scenario": expected_years,
            }),
        ):
            mode = enforcement[check_id]
            if mode == "disabled":
                findings.append(_finding(run_id=run_id, check_id=check_id, enforcement_mode=mode, status="INCOMPLETE", economy=economy, workbook=workbook, actual="disabled"))
                continue
            try:
                findings.extend(functions[check_id](
                    run_id=run_id,
                    economy=economy,
                    workbook=workbook,
                    enforcement_mode=mode,
                    **kwargs,
                ))
            except Exception as exc:
                findings.append(_error_finding(run_id=run_id, check_id=check_id, enforcement_mode=mode, exc=exc, economy=economy, workbook=workbook))

    # BSA-010 sees the execution records for every earlier check.
    mode = enforcement["BSA-010"]
    if mode == "disabled":
        findings.append(_finding(run_id=run_id, check_id="BSA-010", enforcement_mode=mode, status="INCOMPLETE", actual="disabled"))
    else:
        try:
            findings.extend(functions["BSA-010"](
                run_id=run_id,
                enforcement_mode=mode,
                expected_producers=expected_producers,
                producer_artifacts_by_producer=producer_artifacts,
                required_diagnostics=required_diagnostic_paths,
                prior_findings=findings,
            ))
        except Exception as exc:
            findings.append(_error_finding(run_id=run_id, check_id="BSA-010", enforcement_mode=mode, exc=exc))

    return write_acceptance_package(
        run_id=run_id,
        output_dir=output_dir,
        findings=_sort_findings(findings),
        expected_economies=expected,
        candidate_workbooks=candidates,
        template_paths_by_economy=templates,
        enforcement_by_check=enforcement,
        required_diagnostics=required_diagnostic_paths,
    )


__all__ = [
    "ArtifactValidationResult",
    "CHECK_FUNCTIONS",
    "CHECK_IDS",
    "CONTRACT_VERSION",
    "DEFAULT_ENFORCEMENT_BY_CHECK",
    "FINDING_COLUMNS",
    "check_authorized_zero_scope",
    "check_diagnostics_and_manifests",
    "check_producer_workbook_seed_rules",
    "check_required_artifact_set",
    "check_serialized_value_conservation",
    "check_shared_seed_rules",
    "check_template_identity",
    "check_workbook_structure",
    "run_baseline_seed_artifact_validation",
    "sha256_file",
    "write_acceptance_package",
]

#%%
