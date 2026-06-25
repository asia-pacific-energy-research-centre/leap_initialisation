from pathlib import Path

import pandas as pd

from codebase.utilities.leap_results_dashboard_balance import _load_active_balance_mapping_crosswalk


def test_active_balance_mapping_crosswalk_does_not_require_many_to_many_is_ok(tmp_path: Path) -> None:
    workbook = tmp_path / "leap_mappings.xlsx"
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
                "pair_mapping_cardinality": "many_to_many",
                "leap_is_subtotal": False,
                "esto_pair_is_subtotal": False,
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "ninth_sector": "16_01_commercial_and_public_services",
                "ninth_fuel": "08_gas",
                "pair_mapping_cardinality": "many_to_many",
                "leap_is_subtotal": False,
                "ninth_pair_is_subtotal": False,
            }
        ]
    )

    with pd.ExcelWriter(workbook) as writer:
        esto.to_excel(writer, sheet_name="leap_combined_esto", index=False)
        ninth.to_excel(writer, sheet_name="leap_combined_ninth", index=False)

    crosswalk = _load_active_balance_mapping_crosswalk(workbook)

    assert len(crosswalk) == 1
    assert "esto_many_to_many_is_ok" not in crosswalk.columns
    assert "ninth_many_to_many_is_ok" not in crosswalk.columns
    assert crosswalk.loc[0, "esto_pair_mapping_cardinality"] == "many_to_many"
    assert crosswalk.loc[0, "ninth_pair_mapping_cardinality"] == "many_to_many"
