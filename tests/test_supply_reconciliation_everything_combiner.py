#%%
"""Tests for the side script that combines supply reconciliation workbooks."""

from pathlib import Path

from codebase.scrapbook import supply_reconciliation_combine_everything_workflow as combine_workflow


def test_discover_complete_economies_skips_missing_sources(tmp_path: Path, monkeypatch) -> None:
    workbooks_dir = tmp_path / "outputs" / "leap_exports" / "supply_reconciliation" / "workbooks"
    standalone_dir = tmp_path / "outputs" / "leap_exports" / "standalone"
    workbooks_dir.mkdir(parents=True, exist_ok=True)
    standalone_dir.mkdir(parents=True, exist_ok=True)

    complete_supply = workbooks_dir / "supply_leap_imports_20_USA_Target_Reference_CurrentAccounts.xlsx"
    complete_supply.write_text("x")
    for name in [
        "transformation_leap_imports_20_USA_Current_Accounts.xlsx",
        "transformation_leap_imports_20_USA_Reference.xlsx",
        "transformation_leap_imports_20_USA_Target.xlsx",
        "transfer_leap_imports_20_USA_Current_Accounts.xlsx",
        "transfer_leap_imports_20_USA_Reference.xlsx",
        "transfer_leap_imports_20_USA_Target.xlsx",
        "aggregated_demand_20_USA_Target_Reference_CurrentAccounts.xlsx",
    ]:
        (workbooks_dir / name).write_text("x")
    (standalone_dir / "other_loss_own_use_proxy_20_USA_Target_Reference_Current_Accounts.xlsx").write_text("x")

    monkeypatch.setattr(combine_workflow, "WORKBOOKS_DIR", workbooks_dir)
    monkeypatch.setattr(combine_workflow, "OTHER_LOSS_DIR", standalone_dir)

    complete, skipped = combine_workflow.discover_complete_economies(["20_USA", "05_PRC"])

    assert complete == ["20_USA"]
    assert "05_PRC" in skipped


def test_build_source_workbooks_for_economy_returns_expected_workflows(tmp_path: Path, monkeypatch) -> None:
    workbooks_dir = tmp_path / "outputs" / "leap_exports" / "supply_reconciliation" / "workbooks"
    standalone_dir = tmp_path / "outputs" / "leap_exports" / "standalone"
    workbooks_dir.mkdir(parents=True, exist_ok=True)
    standalone_dir.mkdir(parents=True, exist_ok=True)

    supply = workbooks_dir / "supply_leap_imports_20_USA_Target_Reference_CurrentAccounts.xlsx"
    supply.write_text("x")
    for name in [
        "transformation_leap_imports_20_USA_Current_Accounts.xlsx",
        "transformation_leap_imports_20_USA_Reference.xlsx",
        "transformation_leap_imports_20_USA_Target.xlsx",
        "transfer_leap_imports_20_USA_Current_Accounts.xlsx",
        "transfer_leap_imports_20_USA_Reference.xlsx",
        "transfer_leap_imports_20_USA_Target.xlsx",
        "aggregated_demand_20_USA_Target_Reference_CurrentAccounts.xlsx",
    ]:
        (workbooks_dir / name).write_text("x")
    other_loss = standalone_dir / "other_loss_own_use_proxy_20_USA_Target_Reference_Current_Accounts.xlsx"
    other_loss.write_text("x")

    monkeypatch.setattr(combine_workflow, "WORKBOOKS_DIR", workbooks_dir)
    monkeypatch.setattr(combine_workflow, "OTHER_LOSS_DIR", standalone_dir)

    source_map, missing = combine_workflow._build_source_workbooks_for_economy("20_USA")

    assert missing == []
    assert source_map["supply_workflow"] == [supply]
    assert source_map["other_loss_own_use_proxy_workflow"] == [other_loss]
    assert len(source_map["transformation_workflow"]) == 3
    assert len(source_map["transfers_workflow"]) == 3

#%%
