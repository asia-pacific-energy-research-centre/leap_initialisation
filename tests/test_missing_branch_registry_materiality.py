"""Tests for source-based missing-branch registry materiality refresh."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from codebase.mapping_tools.missing_branch_registry_materiality_workflow import (
    _registry_source_keys,
    refresh_missing_branch_registry_materiality,
)
from codebase.functions.baseline_seed_structure_migration import (
    build_missing_branch_validation_exceptions,
)


def test_refresh_preserves_notes_and_uses_configured_base_and_projection_years(tmp_path: Path) -> None:
    registry = tmp_path / "registry.csv"
    registry.write_text(
        "branch_path,date_added,notes\n"
        "Demand\\Other loss and own use\\Coal mines\\BKB and PB,2026-08-20,Keep this note.\n",
        encoding="utf-8",
    )
    esto = tmp_path / "esto.csv"
    pd.DataFrame([{
        "economy": "01AUS", "flows": "10.01.06 Coal mines", "products": "02.08 BKB/PB",
        "is_subtotal": False, "2022": -3.0,
    }]).to_csv(esto, index=False)
    ninth = tmp_path / "ninth.csv"
    rows = []
    for scenario, value in (("reference", -4.0), ("target", -5.0)):
        rows.append({
            "scenarios": scenario, "sectors": "x", "sub1sectors": "x", "sub2sectors": "10_01_06_coal_mines",
            "fuels": "02_coal_products", "subfuels": "02_08_bkb_pb", "subtotal_layout": False,
            "subtotal_results": False, "2023": value, "2024": value,
        })
    pd.DataFrame(rows).to_csv(ninth, index=False)

    refreshed = refresh_missing_branch_registry_materiality(
        registry, esto_path=esto, esto_base_year=2022, ninth_path=ninth,
        projection_start_year=2023, projection_final_year=2024,
    )

    assert refreshed.at[0, "date_added"] == "2026-08-20"
    assert refreshed.at[0, "notes"] == "Keep this note."
    assert refreshed.at[0, "esto_base_year_absolute_pj_all_economies"] == 3.0
    assert refreshed.at[0, "reference_projection_absolute_average_pj_per_year_all_economies"] == 4.0
    assert refreshed.at[0, "target_projection_absolute_average_pj_per_year_all_economies"] == 5.0
    assert len(build_missing_branch_validation_exceptions(registry)) == 6

    # A later refresh does not overwrite approved/materialised values.
    pd.DataFrame([{
        "economy": "01AUS", "flows": "10.01.06 Coal mines", "products": "02.08 BKB/PB",
        "is_subtotal": False, "2022": -99.0,
    }]).to_csv(esto, index=False)
    preserved = refresh_missing_branch_registry_materiality(
        registry, esto_path=esto, esto_base_year=2022, ninth_path=ninth,
        projection_start_year=2023, projection_final_year=2024,
    )
    assert float(preserved.at[0, "esto_base_year_absolute_pj_all_economies"]) == 3.0


def test_refresh_fills_every_blank_row_not_just_the_first(tmp_path: Path) -> None:
    registry = tmp_path / "registry.csv"
    registry.write_text(
        "branch_path,date_added,notes\n"
        "Demand\\Other loss and own use\\Coal mines\\BKB and PB,2026-08-20,First.\n"
        "Demand\\Other loss and own use\\Non specified own uses\\BKB and PB,2026-08-20,Second.\n",
        encoding="utf-8",
    )
    esto = tmp_path / "esto.csv"
    pd.DataFrame([
        {"economy": "01AUS", "flows": "10.01.06 Coal mines", "products": "02.08 BKB/PB", "is_subtotal": False, "2022": -1.0},
        {"economy": "01AUS", "flows": "10.01.17 Non-specified own uses", "products": "02.08 BKB/PB", "is_subtotal": False, "2022": -2.0},
    ]).to_csv(esto, index=False)
    ninth = tmp_path / "ninth.csv"
    pd.DataFrame([
        {"scenarios": scenario, "sectors": "x", "sub1sectors": "x", "sub2sectors": sector,
         "fuels": "02_coal_products", "subfuels": "02_08_bkb_pb", "subtotal_layout": False,
         "subtotal_results": False, "2023": value}
        for scenario in ("reference", "target")
        for sector, value in (("10_01_06_coal_mines", -1.0), ("10_01_17_nonspecified_own_uses", -2.0))
    ]).to_csv(ninth, index=False)

    refreshed = refresh_missing_branch_registry_materiality(
        registry, esto_path=esto, esto_base_year=2022, ninth_path=ninth,
        projection_start_year=2023, projection_final_year=2023,
    )

    assert refreshed["esto_base_year_absolute_pj_all_economies"].notna().all()


def test_unrefreshed_registry_entry_cannot_suppress_a_missing_branch(tmp_path: Path) -> None:
    registry = tmp_path / "registry.csv"
    registry.write_text(
        "branch_path,date_added,notes\n"
        "Demand\\Other loss and own use\\Coal mines\\BKB and PB,2026-08-20,Needs refresh.\n",
        encoding="utf-8",
    )

    assert build_missing_branch_validation_exceptions(registry) == []


def test_transformation_leaf_uses_its_module_not_the_fuel_group() -> None:
    """Deep transfer-style branches still resolve to their transformation sector."""
    keys = _registry_source_keys([
        {
            "branch_path": (
                "Transformation\\Coke ovens\\Processes\\Coke ovens\\Feedstock Fuels"
                "\\Coke oven coke"
            )
        },
        {
            "branch_path": (
                "Transformation\\Non specified transformation\\Output Fuels"
                "\\Additives and oxygenates"
            )
        },
    ])

    assert keys[["sector", "fuel", "esto_flow", "esto_product"]].to_dict("records") == [
        {
            "sector": "Coke ovens",
            "fuel": "Coke oven coke",
            "esto_flow": "09.08.01 Coke ovens",
            "esto_product": "02.01 Coke oven coke",
        },
        {
            "sector": "Non specified transformation",
            "fuel": "Additives and oxygenates",
            "esto_flow": "09.12 Non-specified transformation",
            "esto_product": "06.04 Additives/ oxygenates",
        },
    ]
