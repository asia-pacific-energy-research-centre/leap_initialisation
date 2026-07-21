"""Tests for the notebook-facing supply workflow configuration."""

from __future__ import annotations

from codebase.configuration import workflow_config as workflow_cfg
from codebase import supply_workflow


def test_notebook_economies_use_the_central_configuration() -> None:
    """The wrapper should not silently narrow notebook runs to one economy."""
    assert supply_workflow.NOTEBOOK_WORKFLOW_ECONOMIES == list(
        workflow_cfg.SUPPLY_NOTEBOOK_ECONOMIES
    )


def test_run_with_config_forwards_notebook_settings(monkeypatch) -> None:
    """The notebook helper forwards settings without preparing supply data."""
    captured: dict[str, object] = {}

    def fake_run_supply_export_and_import(**kwargs):
        captured.update(kwargs)
        return ["sentinel"]

    monkeypatch.setattr(
        supply_workflow,
        "run_supply_export_and_import",
        fake_run_supply_export_and_import,
    )
    monkeypatch.setattr(supply_workflow, "NOTEBOOK_WORKFLOW_ECONOMIES", ["01_AUS"])
    monkeypatch.setattr(supply_workflow, "NOTEBOOK_INCLUDE_LEAP_IMPORT", False)
    monkeypatch.setattr(supply_workflow, "NOTEBOOK_SCENARIOS", ["Reference"])
    monkeypatch.setattr(supply_workflow, "NOTEBOOK_IMPORT_SCENARIOS", ["reference"])

    assert supply_workflow.run_with_config() == ["sentinel"]
    assert captured == {
        "economies": ["01_AUS"],
        "include_leap_import": False,
        "scenario_names": ["Reference"],
        "import_scenario": ["reference"],
    }
