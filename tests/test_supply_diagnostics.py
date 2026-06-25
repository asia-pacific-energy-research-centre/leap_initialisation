from __future__ import annotations

import pandas as pd

from codebase.functions import supply_diagnostics


def test_print_flow_rows_respects_nonzero_filter_and_columns(capsys) -> None:
    df = pd.DataFrame(
        {
            "economy": ["20_USA", "20_USA"],
            "flows": ["02 Imports", "03 Exports"],
            "products": ["01 Coal", "01 Coal"],
            2022: [1.0, 0.0],
        }
    )

    supply_diagnostics.print_flow_rows(
        df,
        "flow label",
        [2022],
        print_only_nonzero_rows=True,
    )

    output = capsys.readouterr().out

    assert "flow label: rows 1" in output
    assert "02 Imports" in output
    assert "03 Exports" not in output


def test_list_unique_fuels_and_products_prints_sorted_unique_values(capsys) -> None:
    ninth_data = pd.DataFrame(
        {
            "fuels": ["02_gas", "01_coal", "01_coal"],
            "subfuels": ["x", "x", "x"],
        }
    )
    esto_data = pd.DataFrame({"products": ["02 Gas", "01 Coal", "01 Coal"]})

    supply_diagnostics.list_unique_fuels_and_products(ninth_data, esto_data)

    output = capsys.readouterr().out

    assert "9th fuel/subfuel combos: 2" in output
    assert "- 01_coal / x" in output
    assert "- 02_gas / x" in output
    assert "ESTO products: 2" in output
    assert "- 01 Coal" in output
    assert "- 02 Gas" in output
