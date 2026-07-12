from pathlib import Path

import pandas as pd

from codebase.functions.leap_excel_io import save_export_files


def test_for_viewing_sheet_uses_method_years_and_blank_spacer(tmp_path: Path) -> None:
    output_path = tmp_path / "leap_export.xlsx"
    export_df = pd.DataFrame(
        [
            {
                "BranchID": 1,
                "VariableID": 2,
                "ScenarioID": 3,
                "RegionID": 4,
                "Branch Path": r"Demand\A",
                "Variable": "Activity Level",
                "Scenario": "Reference",
                "Region": "United States",
                "Scale": "",
                "Units": "Petajoule",
                "Per...": "",
                "Expression": "Data(2022, 10, 2023, 20)",
                "Level 1": "Demand",
                "Level 2": "A",
            }
        ]
    )

    save_export_files(
        leap_export_df=export_df,
        export_df_for_viewing=export_df,
        leap_export_filename=output_path,
        base_year=2022,
        final_year=2023,
        model_name="test_model",
    )

    viewing_header = pd.read_excel(output_path, sheet_name="FOR_VIEWING", header=None).iloc[2].tolist()
    assert "Expression" not in viewing_header
    method_index = viewing_header.index("Method")
    assert [int(value) for value in viewing_header[method_index + 1 : method_index + 3]] == [2022, 2023]
    assert pd.isna(viewing_header[method_index + 3])
    assert viewing_header[method_index + 4 : method_index + 6] == ["Level 1", "Level 2"]

    viewing = pd.read_excel(output_path, sheet_name="FOR_VIEWING", header=2)
    assert viewing.loc[0, "Method"] == "Data"
    assert float(viewing.loc[0, "2022"]) == 10.0
    assert float(viewing.loc[0, "2023"]) == 20.0

    leap_header = pd.read_excel(output_path, sheet_name="LEAP", header=None).iloc[2].tolist()
    assert "Expression" in leap_header
