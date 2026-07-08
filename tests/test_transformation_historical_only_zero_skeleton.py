"""Regression checks for transformation activity outside the export window."""

#%%

import pandas as pd

from codebase.functions import transformation_sector_analysis as analysis


def test_historical_only_output_label_is_not_added_to_zero_skeleton() -> None:
    """Historical NZ GTL output must not create a current LEAP output branch."""
    data = pd.DataFrame(
        [
            {
                "economy": "12_NZ",
                "flows": "09.06.04 Gas-to-liquids plants",
                "products": "06.05 Other hydrocarbons",
                1990: 26.879256,
                2022: 0.0,
            },
            {
                "economy": "12_NZ",
                "flows": "09.06.04 Gas-to-liquids plants",
                "products": "08.01 Natural gas",
                1990: -31.411802,
                2022: 0.0,
            },
        ]
    )
    process_records: list[dict] = []

    analysis.summarize_transformation_flows(
        data=data,
        year_cols=[1990, 2022],
        start_year=2022,
        economy="12_NZ",
        flow_codes=["09.06.04 Gas-to-liquids plants"],
        title="Gas to liquids plants",
        code_to_name_mapping={
            "06.05 Other hydrocarbons": "Other hydrocarbons",
            "08.01 Natural gas": "Natural gas",
        },
        loss_data=pd.DataFrame(),
        loss_year_cols=[],
        sector_key="gas_to_liquids_plants",
        process_records=process_records,
    )

    assert len(process_records) == 1
    record = process_records[0]
    assert record["is_zero_skeleton"] is True
    assert record["output_values"] == {}
    assert record["output_import_targets"] == {}
    assert record["output_export_targets"] == {}


#%%
