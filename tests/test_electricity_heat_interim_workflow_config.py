"""Tests for electricity/heat interim notebook configuration."""

from __future__ import annotations

from codebase import electricity_heat_interim_workflow
from codebase.configuration import workflow_config as workflow_cfg


def test_notebook_defaults_use_central_configuration() -> None:
    """The wrapper copies its maintained economy and scenario defaults."""
    assert electricity_heat_interim_workflow.NOTEBOOK_ECONOMIES == list(
        workflow_cfg.ELECTRICITY_HEAT_INTERIM_NOTEBOOK_ECONOMIES
    )
    assert electricity_heat_interim_workflow.NOTEBOOK_ECONOMIES is not (
        workflow_cfg.ELECTRICITY_HEAT_INTERIM_NOTEBOOK_ECONOMIES
    )
    assert electricity_heat_interim_workflow.NOTEBOOK_SCENARIOS == [
        "Target",
        "Current Accounts",
    ]


def test_run_with_notebook_config_forwards_settings(monkeypatch) -> None:
    """The notebook helper forwards settings without preparing source data."""
    captured: dict[str, object] = {}

    def fake_run_electricity_heat_interim_export_and_import(**kwargs):
        captured.update(kwargs)
        return ["sentinel"]

    monkeypatch.setattr(
        electricity_heat_interim_workflow,
        "run_electricity_heat_interim_export_and_import",
        fake_run_electricity_heat_interim_export_and_import,
    )
    monkeypatch.setattr(
        electricity_heat_interim_workflow,
        "NOTEBOOK_ECONOMIES",
        ["01_AUS"],
    )
    monkeypatch.setattr(
        electricity_heat_interim_workflow,
        "NOTEBOOK_SCENARIOS",
        ["Target"],
    )
    monkeypatch.setattr(
        electricity_heat_interim_workflow,
        "NOTEBOOK_INCLUDE_LEAP_IMPORT",
        False,
    )

    assert electricity_heat_interim_workflow.run_with_notebook_config() == [
        "sentinel"
    ]
    assert captured == {
        "economies": ["01_AUS"],
        "scenarios": ["Target"],
        "include_leap_import": False,
    }
