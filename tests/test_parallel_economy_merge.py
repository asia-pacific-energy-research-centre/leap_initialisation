"""Deterministic parent merges for parallel-worker reconciliation artifacts.

Isolated via a monkeypatched INTEGRATED_LEAP_EXPORTS_ROOT so nothing touches
the real outputs tree; safe alongside a live run.
"""
from __future__ import annotations

import pandas as pd
import pytest

import codebase.supply_reconciliation.config as config
from codebase.supply_reconciliation import parallel_merge as merge
from codebase.supply_reconciliation.parallel_runner import (
    EconomyWorkerResult,
    EconomyWorkerSnapshot,
)


@pytest.fixture(autouse=True)
def _isolated_exports_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "INTEGRATED_LEAP_EXPORTS_ROOT", tmp_path / "leap_exports")


def _fake_result(economy: str, label: str, *, succeeded: bool = True) -> EconomyWorkerResult:
    snapshot = EconomyWorkerSnapshot(economy=economy, run_output_label=label)
    return EconomyWorkerResult(
        economy=economy,
        snapshot=snapshot,
        returncode=0 if succeeded else 1,
        stdout_log=None,
        stderr_log=None,
        started_at=0.0,
        ended_at=1.0,
    )


def _write_worker_findings(label: str, economy: str, rows: list[dict]) -> None:
    context = config.resolve_reconciliation_run_context("baseline_seed", label)
    findings_dir = context.output_dir / "supporting_files" / "baseline_seed_validation"
    findings_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows) if rows else pd.DataFrame(columns=list(merge._FINDINGS_COLUMNS))
    frame.to_csv(findings_dir / "baseline_seed_20260723_consolidated_rule_findings.csv", index=False)


def _write_worker_diagnostic(
    label: str,
    filename: str,
    rows: list[dict],
) -> None:
    context = config.resolve_reconciliation_run_context("baseline_seed", label)
    checks_dir = context.output_dir / "supporting_files" / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(checks_dir / filename, index=False)


def _finding(economy: str, rule_id: str, **overrides: object) -> dict:
    row = {
        "economy": economy,
        "rule_id": rule_id,
        "status": "fail",
        "severity": "warning",
        "blocking": False,
        "violated_rule_expectation": "test finding",
        "scope": "",
        "message": "",
        "evidence": "",
        "documentation_reference": "",
        "Branch Path": "",
        "Variable": "",
        "Scenario": "",
        "Region": "",
        "source_workflow": "",
        "source_file": "",
        "year": "",
        "exception_applied": False,
        "exception_id": "",
        "exception_reason": "",
    }
    row.update(overrides)
    return row


def test_merge_concatenates_findings_from_every_successful_worker(tmp_path) -> None:
    _write_worker_findings("MERGE_TEST_01_AUS", "01_AUS", [_finding("01_AUS", "SEED-010")])
    _write_worker_findings("MERGE_TEST_12_NZ", "12_NZ", [_finding("12_NZ", "SEED-011")])
    results = [
        _fake_result("01_AUS", "MERGE_TEST_01_AUS"),
        _fake_result("12_NZ", "MERGE_TEST_12_NZ"),
    ]

    findings_path, issue_groups_path = merge.merge_consolidated_baseline_seed_findings(
        results,
        run_stamp="20260723",
        output_dir=tmp_path / "parent",
        economies_run_order=["01_AUS", "12_NZ"],
    )

    merged = pd.read_csv(findings_path)
    assert len(merged) == 2
    assert set(merged["economy"]) == {"01_AUS", "12_NZ"}
    assert set(merged["rule_id"]) == {"SEED-010", "SEED-011"}
    assert issue_groups_path.exists()
    branch_summary_path = (
        findings_path.parent
        / "baseline_seed_20260723_consolidated_branch_issue_summary.csv"
    )
    assert branch_summary_path.exists()


def test_merge_normalizes_legacy_description_heading(tmp_path) -> None:
    finding = _finding("20_USA", "SEED-003")
    finding["description"] = finding.pop("violated_rule_expectation")
    _write_worker_findings("MERGE_TEST_LEGACY", "20_USA", [finding])

    findings_path, _ = merge.merge_consolidated_baseline_seed_findings(
        [_fake_result("20_USA", "MERGE_TEST_LEGACY")],
        run_stamp="20260723",
        output_dir=tmp_path / "parent",
        economies_run_order=["20_USA"],
    )

    merged = pd.read_csv(findings_path)
    assert "description" not in merged.columns
    assert merged["violated_rule_expectation"].tolist() == ["test finding"]


def test_merge_orders_rows_by_economies_run_order_then_rule_id(tmp_path) -> None:
    _write_worker_findings(
        "MERGE_TEST_20_USA",
        "20_USA",
        [_finding("20_USA", "SEED-011"), _finding("20_USA", "SEED-003")],
    )
    _write_worker_findings("MERGE_TEST_01_AUS", "01_AUS", [_finding("01_AUS", "SEED-009")])
    results = [
        _fake_result("20_USA", "MERGE_TEST_20_USA"),
        _fake_result("01_AUS", "MERGE_TEST_01_AUS"),
    ]

    findings_path, _ = merge.merge_consolidated_baseline_seed_findings(
        results,
        run_stamp="20260723",
        output_dir=tmp_path / "parent",
        economies_run_order=["01_AUS", "20_USA"],
    )

    merged = pd.read_csv(findings_path)
    # 01_AUS sorts first (its ECONOMIES_RUN_ORDER position), then 20_USA's
    # two rows sort by rule_id within that economy.
    assert list(zip(merged["economy"], merged["rule_id"])) == [
        ("01_AUS", "SEED-009"),
        ("20_USA", "SEED-003"),
        ("20_USA", "SEED-011"),
    ]


def test_merge_skips_a_failed_worker_rather_than_treating_it_as_clean(tmp_path) -> None:
    _write_worker_findings("MERGE_TEST_02_BD", "02_BD", [_finding("02_BD", "SEED-012")])
    results = [
        _fake_result("02_BD", "MERGE_TEST_02_BD", succeeded=False),
    ]

    findings_path, _ = merge.merge_consolidated_baseline_seed_findings(
        results,
        run_stamp="20260723",
        output_dir=tmp_path / "parent",
        economies_run_order=["02_BD"],
    )

    merged = pd.read_csv(findings_path)
    assert merged.empty


def test_merge_with_no_findings_anywhere_writes_empty_reports(tmp_path) -> None:
    _write_worker_findings("MERGE_TEST_CLEAN", "01_AUS", [])
    results = [_fake_result("01_AUS", "MERGE_TEST_CLEAN")]

    findings_path, issue_groups_path = merge.merge_consolidated_baseline_seed_findings(
        results,
        run_stamp="20260723",
        output_dir=tmp_path / "parent",
    )

    assert pd.read_csv(findings_path).empty
    assert findings_path.exists() and issue_groups_path.exists()


def test_merge_parallel_diagnostic_families_writes_ordered_parent_views(tmp_path) -> None:
    source_name = "supply_reconciliation_source_diagnostics.csv"
    conservation_name = "supply_reconciliation_balance_demand_conservation.csv"
    _write_worker_diagnostic(
        "DIAGNOSTICS_12_NZ",
        source_name,
        [{"economy": "12_NZ", "issue_type": "nz_issue"}],
    )
    _write_worker_diagnostic(
        "DIAGNOSTICS_01_AUS",
        source_name,
        [{"economy": "", "issue_type": "aus_issue"}],
    )
    _write_worker_diagnostic(
        "DIAGNOSTICS_12_NZ",
        conservation_name,
        [{"economy": "12_NZ", "is_mismatch": False}],
    )
    results = [
        _fake_result("12_NZ", "DIAGNOSTICS_12_NZ"),
        _fake_result("01_AUS", "DIAGNOSTICS_01_AUS"),
    ]

    outputs = merge.merge_parallel_diagnostic_families(
        results,
        output_dir=tmp_path / "parent",
        economies_run_order=["01_AUS", "12_NZ"],
    )

    assert set(outputs) == set(merge._PARALLEL_DIAGNOSTIC_FILENAMES)
    source = pd.read_csv(outputs[source_name])
    assert source[["economy", "issue_type"]].to_dict("records") == [
        {"economy": "01_AUS", "issue_type": "aus_issue"},
        {"economy": "12_NZ", "issue_type": "nz_issue"},
    ]
    assert pd.read_csv(outputs[conservation_name]).loc[0, "economy"] == "12_NZ"
    empty_lineage = merge.read_manifested_parquet_file(
        outputs["supply_reconciliation_balance_demand_conservation_lineage.parquet"]
    )
    assert empty_lineage.empty
    assert list(empty_lineage.columns) == ["economy"]

    worker_source = (
        config.resolve_reconciliation_run_context(
            "baseline_seed", "DIAGNOSTICS_01_AUS"
        ).output_dir
        / "supporting_files"
        / "checks"
        / source_name
    )
    assert pd.read_csv(worker_source, keep_default_na=False).loc[0, "economy"] == ""


def test_merge_parallel_diagnostic_families_skips_failed_workers(tmp_path) -> None:
    filename = "supply_reconciliation_source_diagnostics.csv"
    _write_worker_diagnostic(
        "DIAGNOSTICS_OK",
        filename,
        [{"economy": "01_AUS", "issue_type": "keep"}],
    )
    _write_worker_diagnostic(
        "DIAGNOSTICS_FAILED",
        filename,
        [{"economy": "12_NZ", "issue_type": "do_not_merge"}],
    )

    outputs = merge.merge_parallel_diagnostic_families(
        [
            _fake_result("12_NZ", "DIAGNOSTICS_FAILED", succeeded=False),
            _fake_result("01_AUS", "DIAGNOSTICS_OK"),
        ],
        output_dir=tmp_path / "parent",
    )

    merged = pd.read_csv(outputs[filename])
    assert merged["issue_type"].tolist() == ["keep"]


def test_worker_output_dir_matches_the_workflow_own_context_resolution() -> None:
    result = _fake_result("01_AUS", "MERGE_TEST_DIR_CHECK")
    expected = config.resolve_reconciliation_run_context(
        "baseline_seed", "MERGE_TEST_DIR_CHECK"
    ).output_dir
    assert merge.worker_output_dir(result) == expected
