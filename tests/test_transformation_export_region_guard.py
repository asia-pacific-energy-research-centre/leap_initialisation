"""Regression tests for LEAP export region/economy compatibility."""

#%%

import pandas as pd

from codebase.functions.leap_excel_io import attach_export_ids
from codebase.functions.transformation_record_builder import (
    resolve_export_region_from_process_economies,
)


def test_export_region_resolver_uses_economy_region_over_configured_default():
    records = [
        {
            "economy": "01_AUS",
            "sector_title": "Electricity interim",
            "process_name": "Electricity interim",
        }
    ]

    assert resolve_export_region_from_process_economies(records, "United States") == "Australia"


def test_export_region_resolver_accepts_matching_region():
    records = [
        {
            "economy": "01_AUS",
            "sector_title": "Electricity interim",
            "process_name": "Electricity interim",
        }
    ]

    assert resolve_export_region_from_process_economies(records, "Australia") == "Australia"


def test_attach_export_ids_refuses_to_borrow_ids_when_only_region_differs(tmp_path):
    template_path = tmp_path / "full model export.xlsx"
    template = pd.DataFrame(
        [
            {
                "BranchID": 101,
                "VariableID": 420,
                "ScenarioID": 1,
                "RegionID": 1,
                "Branch Path": r"Transformation\Electricity interim\Processes\Electricity interim",
                "Variable": "Historical Production",
                "Scenario": "Current Accounts",
                "Region": "United States",
            }
        ]
    )
    with pd.ExcelWriter(template_path, engine="openpyxl") as writer:
        template.to_excel(writer, sheet_name="Export", index=False, startrow=2)

    export = template.drop(columns=["BranchID", "VariableID", "ScenarioID", "RegionID"]).copy()
    export["Region"] = "Australia"

    result = attach_export_ids(export, template_path)

    # A United States template and an Australia export are different LEAP areas.
    # Borrowing 101/420 here resolves and imports into the wrong area's branch --
    # silently. -1 is the honest answer; the caller's -1 check catches it.
    assert result.loc[0, "Region"] == "Australia"
    assert result.loc[0, ["BranchID", "VariableID", "ScenarioID", "RegionID"]].tolist() == [
        -1,
        -1,
        -1,
        -1,
    ]


def test_attach_export_ids_matches_when_region_agrees(tmp_path):
    """The guard must not block the normal case: same area, IDs attach."""
    template_path = tmp_path / "template.xlsx"
    template = pd.DataFrame(
        [
            {
                "BranchID": 101,
                "VariableID": 420,
                "ScenarioID": 1,
                "RegionID": 1,
                "Branch Path": r"Transformation\Electricity interim\Processes\Electricity interim",
                "Variable": "Historical Production",
                "Scenario": "Current Accounts",
                "Region": "Australia",
            }
        ]
    )
    with pd.ExcelWriter(template_path, engine="openpyxl") as writer:
        template.to_excel(writer, sheet_name="Export", index=False, startrow=2)

    export = template.drop(columns=["BranchID", "VariableID", "ScenarioID", "RegionID"]).copy()

    result = attach_export_ids(export, template_path)

    assert result.loc[0, ["BranchID", "VariableID", "ScenarioID", "RegionID"]].tolist() == [
        101,
        420,
        1,
        1,
    ]


def test_attach_export_ids_does_not_borrow_across_scenarios(tmp_path):
    """The old second fallback dropped Scenario too, so a Target row could take
    Current Accounts' ScenarioID. Same area, wrong scenario, still wrong."""
    template_path = tmp_path / "template.xlsx"
    template = pd.DataFrame(
        [
            {
                "BranchID": 101,
                "VariableID": 420,
                "ScenarioID": 1,
                "RegionID": 1,
                "Branch Path": r"Transformation\Electricity interim\Processes\Electricity interim",
                "Variable": "Historical Production",
                "Scenario": "Current Accounts",
                "Region": "Australia",
            }
        ]
    )
    with pd.ExcelWriter(template_path, engine="openpyxl") as writer:
        template.to_excel(writer, sheet_name="Export", index=False, startrow=2)

    export = template.drop(columns=["BranchID", "VariableID", "ScenarioID", "RegionID"]).copy()
    export["Scenario"] = "Target"

    result = attach_export_ids(export, template_path)

    assert result.loc[0, "BranchID"] == -1
    assert result.loc[0, "ScenarioID"] == -1


#%%
