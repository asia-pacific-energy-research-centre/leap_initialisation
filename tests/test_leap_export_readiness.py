from pathlib import Path

import pandas as pd

from codebase.utilities.leap_export_readiness import run_export_readiness


def _write_export(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _row(**overrides: object) -> dict[str, object]:
    row = {
        "BranchID": 1,
        "VariableID": 2,
        "ScenarioID": 3,
        "RegionID": 4,
        "Branch Path": "Demand\\All demand aggregated\\Natural gas",
        "Variable": "Activity Level",
        "Scenario": "Target",
        "Region": "New Zealand",
        "Expression": "Data(2023,0.0)",
    }
    row.update(overrides)
    return row


def _write_catalog(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "catalog_type": "demand",
                "scenario": "Target",
                "module_or_root": "All demand aggregated",
                "fuel_group": "",
                "fuel_name": "Natural gas",
                "branch_path": "Demand\\All demand aggregated\\Natural gas",
                "variable": "Activity Level",
            }
        ]
    ).to_csv(path, index=False)


def test_readiness_runner_passes_and_writes_reports(tmp_path):
    export = tmp_path / "export.csv"
    catalog = tmp_path / "catalog.csv"
    _write_export(export, [_row()])
    _write_catalog(catalog)

    result = run_export_readiness(
        export,
        producer="aggregated_demand_workflow",
        economy="12_NZ",
        scenario="Target",
        expected_region="New Zealand",
        catalog_path=catalog,
        output_dir=tmp_path / "readiness",
    )

    assert result.blocking_failures == 0
    assert set(result.findings["status"]) == {"pass"}
    assert result.findings_path is not None and result.findings_path.exists()
    assert result.summary_path is not None and result.summary_path.exists()


def test_readiness_runner_distinguishes_zero_and_nonzero_unresolved_ids(tmp_path):
    export = tmp_path / "export.csv"
    _write_export(
        export,
        [
            _row(BranchID=-1, VariableID=-1, Expression="Data(2023,0.0)"),
            {
                **_row(BranchID=-1, VariableID=-1, Expression="Data(2023,4.0)"),
                "Branch Path": "Demand\\All demand aggregated\\Coal",
            },
        ],
    )

    result = run_export_readiness(
        export,
        producer="test",
        economy="12_NZ",
        expected_region="New Zealand",
    )

    id_findings = result.findings[result.findings["check_name"].eq("leap_ids")]
    assert set(id_findings["status"]) == {"warning", "error"}
    assert result.blocking_failures == 1


def test_readiness_runner_catches_region_and_legacy_transfer_path(tmp_path):
    export = tmp_path / "export.csv"
    _write_export(
        export,
        [
            {
                **_row(Region="United States"),
                "Branch Path": "Transformation\\Transfers\\Legacy process",
            }
        ],
    )

    result = run_export_readiness(
        export,
        producer="transfers_workflow",
        economy="12_NZ",
        expected_region="New Zealand",
    )

    assert set(result.findings["check_name"]) == {
        "region_consistency",
        "legacy_transfer_path",
    }
    assert result.blocking_failures == 2
