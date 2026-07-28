"""Regression coverage for scenario-source reuse in transformation exports."""

#%%

from pathlib import Path

import pandas as pd

from codebase.functions import supply_leap_io


def test_transformation_exports_reuse_reference_projection_for_current_accounts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Reference and Current Accounts share a source build, never mutable rows."""
    collect_calls: list[str] = []
    borrowed_record_ids: dict[str, int] = {}
    applied_records: list[tuple[str, int, str]] = []

    def fake_collect_transformation_rows(*, economies, projection_scenario):
        collect_calls.append(str(projection_scenario))
        return [
            {
                "economy": "01_AUS",
                "sector_title": "Test sector",
                "process_name": "Test process",
                "projection_source": str(projection_scenario),
            }
        ]

    def fake_build_trade_targets(*, economies, process_records):
        return pd.DataFrame({"economy": ["01_AUS"]}), process_records

    def fake_borrow(records_by_scenario):
        for scenario, records in records_by_scenario.items():
            borrowed_record_ids[str(scenario)] = id(records[0])
        return 0

    def fake_apply(
        records,
        targets,
        reconciliation_table,
        scenario,
        *,
        allocation_ledger=None,
    ):
        applied_records.append((str(scenario), id(records[0]), records[0]["projection_source"]))
        # Mimic later processing that can mutate a scenario's records.
        records[0]["export_scenario"] = str(scenario)
        return records

    saved_paths: list[Path] = []

    def fake_save(*args, **kwargs):
        path = tmp_path / f"transformation_{len(saved_paths)}.xlsx"
        saved_paths.append(path)
        return path

    monkeypatch.setattr(
        supply_leap_io.transformation_workflow,
        "collect_transformation_rows",
        fake_collect_transformation_rows,
    )
    monkeypatch.setattr(
        supply_leap_io,
        "build_transformation_trade_target_rows",
        fake_build_trade_targets,
    )
    monkeypatch.setattr(
        supply_leap_io.transformation_workflow.core,
        "borrow_zero_skeleton_measures",
        fake_borrow,
    )
    monkeypatch.setattr(supply_leap_io, "apply_transformation_target_overrides_for_scenario", fake_apply)
    monkeypatch.setattr(
        supply_leap_io.transformation_workflow.core,
        "consolidate_transformation_output_rows",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        supply_leap_io.transformation_workflow.core,
        "save_transformation_export",
        fake_save,
    )

    paths = supply_leap_io.save_transformation_exports_with_split_targets(
        reconciliation_table=pd.DataFrame(),
        process_target_rows=pd.DataFrame(),
        process_records=[{"economy": "01_AUS"}],
        scenarios=["Reference", "Current Accounts", "Target"],
        output_dir=tmp_path,
    )

    assert collect_calls == ["reference", "target"]
    assert [item[2] for item in applied_records] == ["reference", "reference", "target"]
    assert borrowed_record_ids["Reference"] != borrowed_record_ids["Current Accounts"]
    assert applied_records[0][1] != applied_records[1][1]
    assert paths == saved_paths


#%%
