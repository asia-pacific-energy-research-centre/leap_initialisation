from pathlib import Path

import pandas as pd

from codebase.functions.transformation_analysis_utils import (
    save_missing_ninth_fill_diagnostics,
    save_unallocated_projection_diagnostics,
)


def test_unallocated_projection_context_is_written_with_warning(
    tmp_path: Path,
    capsys,
) -> None:
    diagnostics = pd.DataFrame(
        [
            {
                "diagnostic_type": "unallocated_projection_context",
                "diagnostic_record_type": "unallocated_projection",
                "economy_key": "20USA",
                "ninth_sector": "09_08_coal_transformation",
                "ninth_fuel": "02_coal_products",
                "flow_family": "09.08",
                "year": 2023,
                "value": 50.0,
            },
            {
                "diagnostic_type": "unallocated_projection_context",
                "diagnostic_record_type": "historical_flow_family",
                "economy_key": "20USA",
                "ninth_sector": "",
                "ninth_fuel": "",
                "flow_family": "09.08",
                "esto_flow": "09.08.05 Liquefaction (coal to oil)",
                "esto_product": "02.04 Coal tar",
                "year": 2022,
                "value": 0.0,
            },
        ]
    )

    output_path = save_unallocated_projection_diagnostics(
        diagnostics,
        scenario="Reference",
        output_dir=tmp_path,
    )

    expected = (
        tmp_path
        / "supporting_files"
        / "diagnostics"
        / "transformation_unallocated_projection_values_reference.csv"
    )
    assert output_path == expected
    assert expected.exists()
    saved = pd.read_csv(expected)
    assert set(saved["diagnostic_record_type"]) == {
        "unallocated_projection",
        "historical_flow_family",
    }
    warning = capsys.readouterr().out
    assert "[WARN] Left 1 projected aggregate pair(s) unallocated" in warning
    assert str(expected) in warning


def test_missing_ninth_fill_inventory_is_written(tmp_path: Path) -> None:
    diagnostics = pd.DataFrame(
        [
            {
                "diagnostic_type": "missing_ninth_sector_fill_applied",
                "economy_key": "20USA",
                "parent_flow": "08 Transfers",
                "child_flow": "08.02 Interproduct transfers",
                "esto_product": "08.01 Natural gas",
                "allocation_method": "parent_residual_base_year_share",
                "owner_workflow": "transfers_workflow",
                "year": 2023,
                "residual_value": 12.0,
                "allocation_share": 1.0,
            },
            {"diagnostic_type": "share_fallback", "economy_key": "20USA"},
        ]
    )

    output_path = save_missing_ninth_fill_diagnostics(
        diagnostics,
        scenario="Reference",
        output_dir=tmp_path,
    )

    expected = (
        tmp_path
        / "supporting_files"
        / "diagnostics"
        / "transformation_missing_ninth_sector_fills_reference.csv"
    )
    assert output_path == expected
    saved = pd.read_csv(expected)
    assert saved["diagnostic_type"].tolist() == ["missing_ninth_sector_fill_applied"]
