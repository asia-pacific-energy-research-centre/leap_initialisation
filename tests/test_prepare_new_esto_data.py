"""Focused tests for preparing a new ESTO vintage for baseline seeds."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.mapping_tools.prepare_new_esto_data import (  # noqa: E402
    build_commercial_services_unallocated_rows,
    UnreviewedEstoLabelError,
    build_lng_split_rows,
    normalise_esto_labels,
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


def test_canonical_labels_repair_drifted_flow_and_product_names() -> None:
    """The 2026 extract's real corruptions must be repaired, not passed through."""
    esto = _esto_rows([
        # Wrong word: a transfers subflow arriving as a transformation one.
        {"economy": "01AUS", "flows": "08.99 Transformation nonspecified", "products": "07.01 Motor gasoline", "2023": 1, "2024": 2},
        # Typo in the flow label.
        {"economy": "01AUS", "flows": "10.02 Transmision and distribution losses", "products": "17 Electricity", "2023": 3, "2024": 4},
        # Typo in the product label.
        {"economy": "01AUS", "flows": "09.01 Main activity producer", "products": "15.04 Black liqour", "2023": 5, "2024": 6},
        # Whitespace-only drift is repaired by its own explicit entry, not by
        # a blanket rule — that is the point of the canonical tables.
        {"economy": "01AUS", "flows": "09.01 Main activity producer", "products": "07.15 Paraffin  waxes", "2023": 7, "2024": 8},
    ])

    normalised, summary = normalise_esto_labels(esto)

    assert list(normalised["flows"]) == [
        "08.99 Transfers nonspecified",
        "10.02 Transmission and distribution losses",
        "09.01 Main activity producer",
        "09.01 Main activity producer",
    ]
    assert list(normalised["products"])[2:] == ["15.04 Black liquor", "07.15 Paraffin waxes"]
    assert summary["label_renames_applied"] == 4


def test_canonical_labels_leave_correct_labels_untouched() -> None:
    esto = _esto_rows([
        {"economy": "01AUS", "flows": "08.99 Transfers nonspecified", "products": "07.01 Motor gasoline", "2023": 1, "2024": 2},
    ])

    normalised, summary = normalise_esto_labels(esto)

    assert list(normalised["flows"]) == ["08.99 Transfers nonspecified"]
    assert summary["label_renames_applied"] == 0


def test_unreviewed_label_divergence_raises() -> None:
    """A reworded label with no canonical entry must stop the run, not pass."""
    esto = _esto_rows([
        {"economy": "01AUS", "flows": "09.01 Main activity producer plants",
         "products": "17 Electricity", "2023": 1, "2024": 2},
    ])

    with pytest.raises(UnreviewedEstoLabelError) as excinfo:
        normalise_esto_labels(esto)

    # The message must name the code and both spellings, or nobody can act on it.
    message = str(excinfo.value)
    assert "09.01" in message
    assert "09.01 Main activity producer plants" in message
    assert "CANONICAL_FLOW_LABELS" in message


def test_unreviewed_divergence_can_be_collected_instead_of_raised() -> None:
    esto = _esto_rows([
        {"economy": "01AUS", "flows": "09.01 Main activity producer plants",
         "products": "17 Electricity", "2023": 1, "2024": 2},
    ])

    normalised, summary = normalise_esto_labels(esto, strict=False)

    # Not silently renamed...
    assert list(normalised["flows"]) == ["09.01 Main activity producer plants"]
    # ...but recorded.
    assert summary["unreviewed_label_divergences"][0]["code"] == "09.01"


def test_new_esto_code_is_reported_but_does_not_raise() -> None:
    """ESTO adds codes between issues; that is not a corruption."""
    esto = _esto_rows([
        {"economy": "01AUS", "flows": "16.01 Commercial and public services",
         "products": "97.99 A brand new product", "2023": 1, "2024": 2},
    ])

    _, summary = normalise_esto_labels(esto)

    assert {"column": "products", "code": "97.99"}.items() <= (
        summary["codes_absent_from_vocabulary"][0].items()
    )
    assert summary["unreviewed_label_divergences"] == []


def test_prepare_normalises_labels_before_building_rows() -> None:
    """Step 0 must run before the label-matching builders in steps 1-2."""
    esto = _esto_rows([
        {"economy": "01AUS", "flows": "08.99 Transformation nonspecified", "products": "07.01 Motor gasoline", "2023": 1, "2024": 2},
    ])

    prepared, summary = prepare_new_esto_data(esto)

    flows = set(prepared["flows"])
    assert "08.99 Transfers nonspecified" in flows
    assert "08.99 Transformation nonspecified" not in flows
    assert summary["label_renames_applied"] == 1
