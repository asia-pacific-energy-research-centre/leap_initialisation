#%%
"""Regression tests for the retained refining capacity heuristic."""

import pandas as pd

from codebase import refining_workflow


def test_refining_capacity_uses_historical_production_when_enabled(monkeypatch) -> None:
    rows = pd.DataFrame([
        {
            "Branch Path": "Transformation\\Oil Refining\\Processes\\Oil Refining",
            "Variable": "Historical Production",
            "Scenario": "Reference",
            "Units": "Petajoule",
            "Scale": "",
            "Per...": "",
            2022: 10.0,
            2060: 20.0,
        },
        {
            "Branch Path": "Transformation\\Oil Refining\\Processes\\Oil Refining",
            "Variable": "Exogenous Capacity",
            "Scenario": "Reference",
            "Units": "",
            "Scale": "",
            "Per...": "",
            2022: 0.0,
            2060: 0.0,
        },
    ])
    written: dict[str, pd.DataFrame] = {}
    monkeypatch.setattr(
        refining_workflow.workflow_cfg,
        "REFINING_USE_HISTORICAL_PRODUCTION_CAPACITY_HEURISTIC",
        True,
    )
    monkeypatch.setattr(
        refining_workflow,
        "read_export_sheet",
        lambda *_args, **_kwargs: (pd.DataFrame(), rows.copy(), list(rows.columns)),
    )
    monkeypatch.setattr(
        refining_workflow,
        "write_export_sheet",
        lambda **kwargs: written.setdefault("data", kwargs["data"].copy()),
    )

    refining_workflow._apply_transformation_capacity_logic_to_refining_export(
        "unused.xlsx", "refining"
    )
    capacity = written["data"][written["data"]["Variable"].eq("Exogenous Capacity")].iloc[0]
    assert capacity[2022] == 10.0
    assert capacity[2060] == 20.0
    assert capacity["Units"] == "Gigajoules/Year"
    assert capacity["Scale"] == "Million"


#%%
