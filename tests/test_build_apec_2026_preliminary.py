"""Tests for combining the 2026 ESTO extracts with backfilled economies."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.mapping_tools.build_apec_2026_preliminary import (  # noqa: E402
    backfill_missing_economies,
    build_apec_2026_preliminary,
    load_new_vintage_economies,
)


def _write_csv(path: Path, rows: list[dict[str, object]], columns: list[str]) -> Path:
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)
    return path


def test_load_new_vintage_economies_fills_missing_economy_column(tmp_path: Path) -> None:
    new_dir = tmp_path / "new_data"
    new_dir.mkdir()
    _write_csv(
        new_dir / "01AUS_2026.csv",
        [{"economy": "01AUS", "flows": "17 Electricity", "products": "17 Electricity", "2023": 1, "2024": 2}],
        ["economy", "flows", "products", "2023", "2024"],
    )
    _write_csv(
        new_dir / "08JPN_2026.csv",
        [{"flows": "17 Electricity", "products": "17 Electricity", "2023": 3, "2024": 4}],
        ["flows", "products", "2023", "2024"],
    )

    combined = load_new_vintage_economies(new_dir)

    assert sorted(combined["economy"].unique()) == ["01AUS", "08JPN"]


def test_load_new_vintage_economies_rejects_mismatched_economy_column(tmp_path: Path) -> None:
    new_dir = tmp_path / "new_data"
    new_dir.mkdir()
    _write_csv(
        new_dir / "01AUS_2026.csv",
        [{"economy": "99XYZ", "flows": "17 Electricity", "products": "17 Electricity", "2024": 1}],
        ["economy", "flows", "products", "2024"],
    )

    with pytest.raises(ValueError, match="does not match"):
        load_new_vintage_economies(new_dir)


def test_backfill_carries_the_latest_source_year_forward() -> None:
    new_vintage = pd.DataFrame(
        [{"economy": "01AUS", "flows": "17 Electricity", "products": "17 Electricity", "2024": 5}]
    )
    backfill_source = pd.DataFrame(
        [
            {
                "economy": "12NZ",
                "flows": "17 Electricity",
                "products": "17 Electricity",
                "is_subtotal": "FALSE",
                "2022": 10,
                "2023": 12,
            }
        ]
    )

    rows, backfilled, source_year = backfill_missing_economies(new_vintage, backfill_source, target_year=2024)

    assert backfilled == ["12NZ"]
    assert source_year == 2023
    assert rows.loc[rows.index[0], "2024"] == 12.0


def test_backfill_skips_economies_already_present_in_the_new_vintage() -> None:
    new_vintage = pd.DataFrame(
        [{"economy": "12NZ", "flows": "17 Electricity", "products": "17 Electricity", "2024": 1}]
    )
    backfill_source = pd.DataFrame(
        [{"economy": "12NZ", "flows": "17 Electricity", "products": "17 Electricity", "2023": 9}]
    )

    rows, backfilled, source_year = backfill_missing_economies(new_vintage, backfill_source, target_year=2024)

    assert backfilled == []
    assert source_year is None
    assert rows.empty


def test_build_apec_2026_preliminary_end_to_end(tmp_path: Path) -> None:
    new_dir = tmp_path / "new_data"
    new_dir.mkdir()
    _write_csv(
        new_dir / "01AUS_2026.csv",
        [
            {"economy": "01AUS", "flows": "16.01 Commercial and public services", "products": "01.01 Coking coal", "2023": 4, "2024": 6},
            {"economy": "01AUS", "flows": "09.06.02 Liquefaction/regasification plants", "products": "08.01 Natural gas", "2023": -10, "2024": -12},
            {"economy": "01AUS", "flows": "09.06.02 Liquefaction/regasification plants", "products": "08.02 LNG", "2023": 8, "2024": 9},
        ],
        ["economy", "flows", "products", "2023", "2024"],
    )

    backfill_path = tmp_path / "00APEC_2025_low_with_subtotals.csv"
    _write_csv(
        backfill_path,
        [
            {
                "economy": "12NZ",
                "flows": "16.01 Commercial and public services",
                "products": "01.01 Coking coal",
                "is_subtotal": "FALSE",
                "2022": 1,
                "2023": 2,
            },
            {
                "economy": "01AUS",
                "flows": "16.01 Commercial and public services",
                "products": "01.01 Coking coal",
                "is_subtotal": "FALSE",
                "2022": 3,
                "2023": 4,
            },
        ],
        ["economy", "flows", "products", "is_subtotal", "2022", "2023"],
    )

    output_path = tmp_path / "00APEC_2026_low_with_subtotals_PRELIMINARY.csv"

    summary = build_apec_2026_preliminary(
        new_data_dir=new_dir,
        backfill_vintage_path=backfill_path,
        secondary_reference_vintage_path=tmp_path / "does_not_exist.csv",
        ninth_projection_table_path=None,
        output_path=output_path,
        target_year=2026,
    )

    assert summary.new_vintage_economies == ["01AUS"]
    assert summary.backfilled_economies == ["12NZ"]
    assert summary.backfilled_from_year == 2023
    assert summary.backfilled_to_year == 2024
    assert output_path.is_file()

    result = pd.read_csv(output_path, dtype=object)
    assert sorted(result["economy"].unique()) == ["01AUS", "12NZ"]
    assert list(result.columns[:4]) == ["economy", "flows", "products", "is_subtotal"]

    nz_row = result[(result["economy"] == "12NZ") & (result["flows"] == "16.01 Commercial and public services")]
    assert float(nz_row.iloc[0]["2024"]) == 2.0

    liq = result[result["flows"] == "09.06.02.01 Liquefaction"]
    assert not liq.empty

    assert not result.duplicated(["economy", "flows", "products"]).any()


def test_build_apec_2026_preliminary_rejects_unrecognised_filenames(tmp_path: Path) -> None:
    new_dir = tmp_path / "new_data"
    new_dir.mkdir()
    _write_csv(
        new_dir / "not_an_economy_file.csv",
        [{"economy": "01AUS", "flows": "17 Electricity", "products": "17 Electricity", "2024": 1}],
        ["economy", "flows", "products", "2024"],
    )

    with pytest.raises(ValueError, match="Unrecognised new-vintage filename"):
        load_new_vintage_economies(new_dir)
