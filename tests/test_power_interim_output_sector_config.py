#%%
"""Regression coverage for signed electricity/CHP/heat source sectors."""

import pandas as pd
import pytest

from codebase import electricity_heat_interim_workflow as workflow


def test_interim_modules_select_only_approved_signed_transformation_sectors() -> None:
    configured = {
        module: config["sub1sectors"]
        for module, config in workflow.INTERIM_MODULES.items()
    }
    assert configured == {
        "Electricity interim": ["09_01_electricity_plants"],
        "CHP interim": ["09_02_chp_plants"],
        "Heat plant interim": ["09_x_heat_plants"],
    }
    assert not (
        set(workflow.ALL_POWER_SUB1SECTORS)
        & workflow.FORBIDDEN_POWER_INTERIM_SUB1SECTORS
    )


@pytest.mark.parametrize("sector", sorted(workflow.FORBIDDEN_POWER_INTERIM_SUB1SECTORS))
def test_forbidden_output_accounting_sector_is_rejected(sector: str) -> None:
    with pytest.raises(ValueError, match="forbidden source-role sectors"):
        workflow.validate_power_interim_sub1sectors([sector])


def test_signed_09_rows_supply_outputs_and_inputs_without_forbidden_influence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = workflow.INTERIM_MODULES["CHP interim"]

    ninth_data = pd.DataFrame(
        [
            {
                "economy": "05_PRC",
                "sub1sectors": "09_02_chp_plants",
                "fuels": "07_petroleum_products",
                "subfuels": "x",
                2022: 0.0,
                2023: -10.0,
            },
            {
                "economy": "05_PRC",
                "sub1sectors": "09_02_chp_plants",
                "fuels": "17_electricity",
                "subfuels": "x",
                2022: 0.0,
                2023: 6.0,
            },
            {
                "economy": "05_PRC",
                "sub1sectors": "09_02_chp_plants",
                "fuels": "18_heat",
                "subfuels": "x",
                2022: 0.0,
                2023: 4.0,
            },
            {
                "economy": "05_PRC",
                "sub1sectors": "18_02_chp_plants",
                "fuels": "16_others",
                "subfuels": "x",
                2022: 0.0,
                2023: 999.0,
            },
        ]
    )
    monkeypatch.setattr(workflow.core, "esto_data", pd.DataFrame(columns=["economy", "flows"]))
    monkeypatch.setattr(workflow.core, "ninth_data", ninth_data)
    monkeypatch.setattr(workflow.core, "esto_year_cols", [2022, 2023])
    monkeypatch.setattr(workflow.core, "ninth_year_cols", [2022, 2023])

    rows, years = workflow._combine_module_source_rows(
        economy="05_PRC",
        sub1sectors=config["sub1sectors"],
        esto_flows=config["esto_flows"],
    )
    totals, _ = workflow.core.summarize_fuel_totals(
        rows,
        years,
        start_year=2023,
        allow_all_years_fallback=False,
    )

    assert totals["17_electricity"] == 6.0
    assert totals["18_heat"] == 4.0
    assert totals["07_petroleum_products"] == -10.0
    assert "16_others" not in totals


#%%
