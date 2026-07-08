"""Regression tests for inactive LNG scenario coverage."""

#%%

import pandas as pd

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


#%%
