"""Tests for transformation workflow notebook configuration."""

from __future__ import annotations

from codebase import transformation_workflow
from codebase.configuration import workflow_config as workflow_cfg


def test_notebook_defaults_use_central_configuration() -> None:
    """Central defaults are copied while None retains the core fallback."""
    expected_economies = (
        list(transformation_workflow.core.ECONOMIES_TO_ANALYZE)
        if workflow_cfg.TRANSFORMATION_NOTEBOOK_ECONOMIES is None
        else list(workflow_cfg.TRANSFORMATION_NOTEBOOK_ECONOMIES)
    )

    assert transformation_workflow.NOTEBOOK_ECONOMIES == expected_economies
    assert transformation_workflow.NOTEBOOK_ECONOMIES is not expected_economies
    assert transformation_workflow.NOTEBOOK_SCENARIOS == list(
        workflow_cfg.TRANSFORMATION_NOTEBOOK_SCENARIOS
    )
    assert transformation_workflow.NOTEBOOK_CURRENT_ACCOUNTS is True
    assert (
        transformation_workflow.NOTEBOOK_AGGREGATE_ECONOMY_LABEL
        == workflow_cfg.TRANSFORMATION_NOTEBOOK_AGGREGATE_ECONOMY_LABEL
    )


def test_run_with_notebook_config_forwards_settings(monkeypatch) -> None:
    """The notebook helper forwards settings without preparing source data."""
    captured: dict[str, object] = {}

    def fake_run_transformation_export_and_import(**kwargs):
        captured.update(kwargs)
        return ["sentinel"]

    monkeypatch.setattr(
        transformation_workflow,
        "run_transformation_export_and_import",
        fake_run_transformation_export_and_import,
    )
    monkeypatch.setattr(transformation_workflow, "NOTEBOOK_ECONOMIES", ["01_AUS"])
    monkeypatch.setattr(
        transformation_workflow,
        "NOTEBOOK_SCENARIOS",
        ["Reference", "Current Accounts"],
    )
    monkeypatch.setattr(
        transformation_workflow,
        "NOTEBOOK_INCLUDE_LEAP_IMPORT",
        False,
    )
    monkeypatch.setattr(
        transformation_workflow,
        "NOTEBOOK_IMPORT_SCENARIOS",
        ["reference"],
    )
    monkeypatch.setattr(
        transformation_workflow,
        "NOTEBOOK_CURRENT_ACCOUNTS",
        False,
    )
    monkeypatch.setattr(
        transformation_workflow,
        "NOTEBOOK_AGGREGATE_ECONOMY_LABEL",
        "00_APEC",
    )

    assert transformation_workflow.run_with_notebook_config() == ["sentinel"]
    assert captured == {
        "economies": ["01_AUS"],
        "scenarios": ["Reference", "Current Accounts"],
        "include_leap_import": False,
        "import_scenario": ["reference"],
        "handle_current_accounts": False,
        "aggregate_economy_label": "00_APEC",
    }
