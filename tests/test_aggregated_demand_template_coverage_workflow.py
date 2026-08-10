"""Tests for the reusable aggregated-demand template coverage audit."""

#%%

import pandas as pd
import pytest

from codebase.aggregated_demand_template_coverage_workflow import (
    _add_branch_paths,
    build_missing_branch_cases,
)


def test_add_branch_paths_builds_exact_unique_leap_paths():
    pairs = pd.DataFrame(
        [
            {"economy": "04_CHL", "sector": "Road", "leap_fuel_name": "Kerosene type jet fuel"},
            {"economy": "04_CHL", "sector": "Road", "leap_fuel_name": "Kerosene type jet fuel"},
            {"economy": "20_USA", "sector": "Non Energy Use", "leap_fuel_name": "Natural gas"},
        ]
    )

    result = _add_branch_paths(pairs)

    assert result[["economy", "branch_path"]].to_dict("records") == [
        {
            "economy": "04_CHL",
            "branch_path": r"Demand\All demand aggregated\Road\Kerosene type jet fuel",
        },
        {
            "economy": "20_USA",
            "branch_path": r"Demand\All demand aggregated\Non Energy Use\Natural gas",
        },
    ]


def test_build_missing_cases_keeps_real_economies_and_adds_apec_union_gaps():
    generated = _add_branch_paths(
        pd.DataFrame(
            [
                {"economy": "01_AUS", "sector": "Industry", "leap_fuel_name": "Natural gas"},
                {"economy": "01_AUS", "sector": "Non Energy Use", "leap_fuel_name": "Ethane"},
                {"economy": "04_CHL", "sector": "Road", "leap_fuel_name": "Kerosene type jet fuel"},
                {"economy": "20_USA", "sector": "Industry", "leap_fuel_name": "Electricity"},
            ]
        )
    )
    industry_gas = r"Demand\All demand aggregated\Industry\Natural gas"
    industry_electricity = r"Demand\All demand aggregated\Industry\Electricity"

    result = build_missing_branch_cases(
        generated,
        template_paths_by_economy={
            "01_AUS": {industry_gas},
            "20_USA": {industry_electricity},
        },
        apec_branch_paths={industry_gas, industry_electricity},
    )

    assert result.to_dict("records") == [
        {
            "Economy": "01_AUS",
            "Branch Path": r"Demand\All demand aggregated\Non Energy Use\Ethane",
        },
        {
            "Economy": "APEC",
            "Branch Path": r"Demand\All demand aggregated\Non Energy Use\Ethane",
        },
        {
            "Economy": "APEC",
            "Branch Path": r"Demand\All demand aggregated\Road\Kerosene type jet fuel",
        },
    ]


def test_build_missing_cases_requires_branch_path_columns():
    with pytest.raises(KeyError, match="branch_path"):
        build_missing_branch_cases(
            pd.DataFrame({"economy": ["01_AUS"]}),
            template_paths_by_economy={},
            apec_branch_paths=set(),
        )

#%%
