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


def test_attach_export_ids_uses_template_ids_when_only_region_differs(tmp_path):
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

    assert result.loc[0, "Region"] == "Australia"
    assert result.loc[0, ["BranchID", "VariableID", "ScenarioID", "RegionID"]].tolist() == [
        101,
        420,
        1,
        1,
    ]


#%%
