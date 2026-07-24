"""Focused tests for preparing a new ESTO vintage for baseline seeds."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.mapping_tools.prepare_new_esto_data import (  # noqa: E402
    build_commercial_services_unallocated_rows,
    build_lng_split_rows,
    prepare_new_esto_data,
)


YEAR_COLUMNS = ["2023", "2024"]


def _esto_rows(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["economy", "flows", "products", *YEAR_COLUMNS])


def test_completion_can_be_limited_to_reference_product_set() -> None:
    esto = _esto_rows([
        {"economy": "12NZ", "flows": "16.01 Commercial and public services", "products": "01 Coal", "2023": 10, "2024": 12},
        {"economy": "12NZ", "flows": "16.01 Commercial and public services", "products": "01.01 Coking coal", "2023": 4, "2024": 5},
        {"economy": "12NZ", "flows": "16.01.01 Datacentres", "products": "01.01 Coking coal", "2023": 1, "2024": 2},
    ])

    rows = build_commercial_services_unallocated_rows(esto, eligible_product_codes={"01.01"})

    assert rows[["flows", "products"]].to_dict("records") == [{
        "flows": "16.01.99 Commercial and public services unallocated",
        "products": "01.01 Coking coal",
    }]
    assert rows.loc[0, "2023"] == 3.0
    assert rows.loc[0, "2024"] == 3.0


def test_lng_split_uses_signs_and_preserves_product_rows() -> None:
    esto = _esto_rows([
        {"economy": "01AUS", "flows": "09.06.02 Liquefaction/regasification plants", "products": "08.01 Natural gas", "2023": -10, "2024": 10},
        {"economy": "01AUS", "flows": "09.06.02 Liquefaction/regasification plants", "products": "08.02 LNG", "2023": 8, "2024": -8},
        {"economy": "01AUS", "flows": "09.06.02 Liquefaction/regasification plants", "products": "07.03 Naphtha", "2023": 2, "2024": -2},
    ])

    rows = build_lng_split_rows(esto)
    liq = rows[rows["flows"].str.startswith("09.06.02.01")].set_index("products")
    regas = rows[rows["flows"].str.startswith("09.06.02.02")].set_index("products")

    assert liq.loc["08.01 Natural gas", "2023"] == -10.0
    assert liq.loc["08.01 Natural gas", "2024"] == 0.0
    assert regas.loc["08.01 Natural gas", "2023"] == 0.0
    assert regas.loc["08.01 Natural gas", "2024"] == 10.0
    assert liq.loc["07.03 Naphtha", "2023"] == 2.0
    assert regas.loc["07.03 Naphtha", "2023"] == 0.0


def test_prepare_is_idempotent_when_reference_rows_already_exist() -> None:
    esto = _esto_rows([
        {"economy": "12NZ", "flows": "16.01 Commercial and public services", "products": "01.01 Coking coal", "2023": 4, "2024": 5},
        {"economy": "12NZ", "flows": "16.01.99 Commercial and public services unallocated", "products": "01.01 Coking coal", "2023": 4, "2024": 5},
    ])
    reference = esto.assign(is_subtotal=[False, False])

    prepared, summary = prepare_new_esto_data(esto, [reference])

    assert len(prepared) == len(esto)
    assert summary["commercial_services_unallocated_rows_added"] == 0
    assert summary["lng_split_rows_added"] == 0
    assert prepared.duplicated(["economy", "flows", "products"]).sum() == 0
