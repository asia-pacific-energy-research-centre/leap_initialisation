"""Regression tests for inactive LNG scenario coverage."""

#%%

import pandas as pd
import pytest

from codebase.functions.transformation_sector_analysis import (
    analyze_lng_liquefaction_regas,
)


def test_inactive_lng_scenario_writes_zero_skeletons():
    """Configured LNG processes remain present when a scenario has no activity."""
    empty_data = pd.DataFrame(columns=["economy", "flows", "products", 2023])
    process_records = []

    analyze_lng_liquefaction_regas(
        esto_data=empty_data,
        year_cols=[2023],
        start_year=2023,
        economy="12_NZ",
        code_to_name_mapping={},
        loss_data=empty_data,
        loss_year_cols=[2023],
        process_records=process_records,
    )

    assert {
        (record["sector_title"], record["process_name"])
        for record in process_records
    } == {
        ("LNG regasification", "Regasification"),
        ("NG Liquefaction", "Liquefaction"),
    }
    assert all(record["is_zero_skeleton"] for record in process_records)
    assert all(
        all(value == 0 for value in output_values.values())
        for record in process_records
        for output_values in record["output_values"].values()
    )


def _lng_projection_rows(
    economy: str,
    natural_gas_values: dict[int, float],
    lng_values: dict[int, float],
) -> pd.DataFrame:
    """Build the signed 9th-derived rows consumed by the LNG analyser."""
    shared = {
        "economy": economy,
        "sub2sectors": "09_06_02_liquefaction_regasification_plants",
        "fuels": "08_gas",
    }
    return pd.DataFrame(
        [
            {**shared, "subfuels": "08_01_natural_gas", **natural_gas_values},
            {**shared, "subfuels": "08_02_lng", **lng_values},
        ]
    )


def _record_for_process(process_records: list[dict], process_name: str) -> dict:
    return next(record for record in process_records if record["process_name"] == process_name)


def test_lng_historical_split_does_not_suppress_prc_projection() -> None:
    """A 2022 ESTO split must not replace PRC's 9th regasification series."""
    projected_data = _lng_projection_rows(
        "05_PRC",
        {2022: 3201.754142, 2023: 3658.535632, 2030: 4660.286230},
        {2022: -3292.703662, 2023: -3658.535632, 2030: -4660.286230},
    )
    historical_split = pd.DataFrame(
        [
            {"economy": "05_PRC", "flows": "09.06.02.02 Regasification", "products": "08.01 Natural gas", 2022: 3201.754142},
            {"economy": "05_PRC", "flows": "09.06.02.02 Regasification", "products": "08.02 LNG", 2022: -3292.703662},
        ]
    )
    process_records: list[dict] = []

    analyze_lng_liquefaction_regas(
        esto_data=projected_data,
        year_cols=[2022, 2023, 2030],
        start_year=2022,
        economy="05_PRC",
        code_to_name_mapping={"08_01_natural_gas": "Natural gas", "08_02_lng": "LNG"},
        loss_data=projected_data,
        loss_year_cols=[2022, 2023, 2030],
        process_records=process_records,
        esto_reference_data=historical_split,
        esto_reference_year_cols=[2022],
    )

    regasification = _record_for_process(process_records, "Regasification")
    output = regasification["output_values"]["08_01_natural_gas"]
    assert output[2022] == pytest.approx(3201.754142)
    assert output[2023] == pytest.approx(3658.535632)
    assert output[2030] == pytest.approx(4660.286230)


def test_lng_projection_can_change_direction_after_historical_split() -> None:
    """Malaysia can switch from liquefaction to regasification after 2022."""
    projected_data = _lng_projection_rows(
        "10_MAS",
        {2022: -1678.672339, 2023: -914.875236, 2040: 1267.880593},
        {2022: 1098.783792, 2023: 914.875236, 2040: -1267.880593},
    )
    historical_split = pd.DataFrame(
        [
            {"economy": "10_MAS", "flows": "09.06.02.01 Liquefaction", "products": "08.01 Natural gas", 2022: -1678.672339},
            {"economy": "10_MAS", "flows": "09.06.02.01 Liquefaction", "products": "08.02 LNG", 2022: 1098.783792},
        ]
    )
    process_records: list[dict] = []

    analyze_lng_liquefaction_regas(
        esto_data=projected_data,
        year_cols=[2022, 2023, 2040],
        start_year=2022,
        economy="10_MAS",
        code_to_name_mapping={"08_01_natural_gas": "Natural gas", "08_02_lng": "LNG"},
        loss_data=projected_data,
        loss_year_cols=[2022, 2023, 2040],
        process_records=process_records,
        esto_reference_data=historical_split,
        esto_reference_year_cols=[2022],
    )

    liquefaction = _record_for_process(process_records, "Liquefaction")
    regasification = _record_for_process(process_records, "Regasification")
    assert liquefaction["output_values"]["08_02_lng"][2023] == pytest.approx(914.875236)
    assert regasification["output_values"]["08_01_natural_gas"][2040] == pytest.approx(1267.880593)


#%%
