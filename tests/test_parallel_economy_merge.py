"""Deterministic parent merge for parallel-worker baseline-seed findings.

Scope: only the consolidated findings/issue-groups CSVs (see the module
docstring in codebase/functions/parallel_economy_merge.py for why the
single-file combined workbook is deliberately NOT covered here). Isolated
via a monkeypatched INTEGRATED_LEAP_EXPORTS_ROOT so nothing touches the real
outputs/ tree; safe alongside a live run.
"""
from __future__ import annotations

import pandas as pd
import pytest

import codebase.supply_reconciliation_config as config
from codebase.functions import parallel_economy_merge as merge
from codebase.functions.parallel_economy_runner import (
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


def _finding(economy: str, rule_id: str, **overrides: object) -> dict:
    row = {
        "economy": economy,
        "rule_id": rule_id,
        "status": "fail",
        "severity": "warning",
        "blocking": False,
        "description": "test finding",
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


def test_worker_output_dir_matches_the_workflow_own_context_resolution() -> None:
    result = _fake_result("01_AUS", "MERGE_TEST_DIR_CHECK")
    expected = config.resolve_reconciliation_run_context(
        "baseline_seed", "MERGE_TEST_DIR_CHECK"
    ).output_dir
    assert merge.worker_output_dir(result) == expected


# ---------------------------------------------------------------------------
# Parent combined workbook merge. These fixtures mirror the sequential
# two-economy/two-year workbook structure: raw LEAP preamble, a blank spacer
# column between values and hierarchy, IDs, and an ordinary RUN_MANIFEST.
# ---------------------------------------------------------------------------


def _write_worker_results_workbook(
    label: str,
    economy: str,
    *,
    preamble_area: str = "Reference area",
    extra_header_column: str | None = None,
    include_shared_proxy_row: bool = False,
) -> None:
    context = config.resolve_reconciliation_run_context("baseline_seed", label)
    path = context.output_dir / f"supply_recon_run_baseline_seed_{economy}_tgt_ref_ca.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "BranchID", "VariableID", "ScenarioID", "RegionID",
        "Branch Path", "Variable", "Scenario", "Region",
        "Scale", "Units", "Per...", "Method", "2022", "2023", "", "Level 1",
    ]
    if extra_header_column:
        header.append(extra_header_column)
    row0 = ["", "", "", "", "Area:", preamble_area, "Ver:", "2"] + [""] * (len(header) - 8)
    row1 = [""] * len(header)
    rows = [
        [
            101, 201, 301, 1,
            f"Resources\\Primary\\Fuel {economy}", "Maximum Production", "Reference", economy,
            "", "PJ", "", "Interp", 1.0, 2.0, "", "Resources",
        ],
        [
            102, 202, 302, 1,
            f"Demand\\All demand\\Fuel {economy}", "Activity Level", "Target", economy,
            "", "PJ", "", "Interp", 3.0, 4.0, "", "Demand",
        ],
    ]
    if extra_header_column:
        rows = [row + ["extra"] for row in rows]
    if include_shared_proxy_row:
        shared_row = [
            999, 888, 777, 1,
            "Transformation\\Shared proxy", "Activity Level", "Target", "United States",
            "", "PJ", "", "Interp", 10.0 if economy == "01_AUS" else 20.0,
            11.0 if economy == "01_AUS" else 21.0, "", "Transformation",
        ]
        rows.append(shared_row + (["extra"] if extra_header_column else []))
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame([row0, row1, header] + rows).to_excel(
            writer, sheet_name="Export", index=False, header=False
        )
        pd.DataFrame(
            [{"workbook_type": "supply", "path": f"{economy}.xlsx", "exists": True}]
        ).to_excel(writer, sheet_name="RUN_MANIFEST", index=False)


def _read_raw_export(path):
    return pd.read_excel(path, sheet_name="Export", header=None)


def test_merge_parallel_results_workbooks_preserves_sequential_layout_and_data(tmp_path) -> None:
    _write_worker_results_workbook("WORKER_01_AUS", "01_AUS")
    _write_worker_results_workbook("WORKER_12_NZ", "12_NZ")
    # Completion order deliberately differs from parent economy order.
    results = [
        _fake_result("12_NZ", "WORKER_12_NZ"),
        _fake_result("01_AUS", "WORKER_01_AUS"),
    ]
    output = merge.merge_parallel_results_workbooks(
        results,
        output_path=tmp_path / "parent" / "supply_recon_run_baseline_seed_01_AUS-12_NZ_tgt_ref_ca.xlsx",
        economies_run_order=["01_AUS", "12_NZ"],
    )

    raw = _read_raw_export(output)
    # The sequential reference's preamble/header is copied without alteration,
    # including the blank spacer after the two-year values.
    assert raw.iloc[:3].equals(_read_raw_export(
        config.resolve_reconciliation_run_context("baseline_seed", "WORKER_01_AUS").output_dir
        / "supply_recon_run_baseline_seed_01_AUS_tgt_ref_ca.xlsx"
    ).iloc[:3])
    header = list(raw.iloc[2])
    assert header[:14] == [
        "BranchID", "VariableID", "ScenarioID", "RegionID",
        "Branch Path", "Variable", "Scenario", "Region",
        "Scale", "Units", "Per...", "Method", 2022, 2023,
    ]
    assert pd.isna(header[14])
    assert header[15] == "Level 1"
    assert list(raw.iloc[3:, 7]) == ["01_AUS", "01_AUS", "12_NZ", "12_NZ"]
    assert list(raw.iloc[3:, 0]) == [101, 102, 101, 102]
    manifest = pd.read_excel(output, sheet_name="RUN_MANIFEST")
    assert list(manifest["path"]) == ["01_AUS.xlsx", "12_NZ.xlsx"]


def test_merge_parallel_results_workbooks_rejects_failed_or_missing_worker(tmp_path) -> None:
    _write_worker_results_workbook("WORKER_01_AUS", "01_AUS")
    with pytest.raises(RuntimeError, match="partial parallel combined workbook"):
        merge.merge_parallel_results_workbooks(
            [_fake_result("01_AUS", "WORKER_01_AUS", succeeded=False)],
            output_path=tmp_path / "parent.xlsx",
            economies_run_order=["01_AUS"],
        )


def test_merge_parallel_results_workbooks_rejects_layout_drift(tmp_path) -> None:
    _write_worker_results_workbook("WORKER_01_AUS", "01_AUS")
    _write_worker_results_workbook("WORKER_12_NZ", "12_NZ", extra_header_column="Level 2")
    with pytest.raises(ValueError, match="preamble/header layout differs"):
        merge.merge_parallel_results_workbooks(
            [_fake_result("01_AUS", "WORKER_01_AUS"), _fake_result("12_NZ", "WORKER_12_NZ")],
            output_path=tmp_path / "parent.xlsx",
            economies_run_order=["01_AUS", "12_NZ"],
        )


def test_merge_parallel_results_workbooks_uses_later_economy_for_shared_proxy_rows(tmp_path) -> None:
    _write_worker_results_workbook("WORKER_01_AUS", "01_AUS", include_shared_proxy_row=True)
    _write_worker_results_workbook("WORKER_12_NZ", "12_NZ", include_shared_proxy_row=True)
    output = merge.merge_parallel_results_workbooks(
        [_fake_result("12_NZ", "WORKER_12_NZ"), _fake_result("01_AUS", "WORKER_01_AUS")],
        output_path=tmp_path / "parent.xlsx",
        economies_run_order=["01_AUS", "12_NZ"],
    )

    raw = _read_raw_export(output)
    shared = raw.iloc[3:]
    shared = shared[shared.iloc[:, 4].eq("Transformation\\Shared proxy")]
    assert len(shared) == 1
    # The configured later economy wins, matching sequential multi-economy
    # packaging rather than the worker process completion order.
    assert shared.iloc[0, 12] == 20.0
