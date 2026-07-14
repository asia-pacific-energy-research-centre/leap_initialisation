"""Regression coverage for supply Maximum Production exports."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions import (
    supply_export_builder,
    supply_leap_io,
    supply_reconciliation_tables,
)


USA_MSW_PRODUCT = "16.04 Municipal solid waste (non-renewable)"
USA_MSW_BRANCH = "Resources\\Secondary\\Municipal solid waste non renewable"


def _supply_assets_with_usa_msw() -> tuple:
    esto_data = pd.DataFrame(
        {
            # ESTO retains compact economy codes even though reconciliation
            # requests the underscore-normalized code below.
            "economy": ["20USA"],
            "flows": ["01 Production"],
            "products": [USA_MSW_PRODUCT],
            2022: [147.926996],
        }
    )
    ninth_data = pd.DataFrame(
        {
            "economy": ["20_USA"],
            "sectors": ["01_production"],
            "fuels": ["16_04_municipal_solid_waste_nonrenewable"],
            "subfuels": ["x"],
            2022: [0.0],
        }
    )
    sector_config = {
        USA_MSW_PRODUCT: {
            "fuel_label_esto": USA_MSW_PRODUCT,
            "fuel_code_ninth": "16_04_municipal_solid_waste_nonrenewable",
            "fuel_name": "Municipal solid waste non renewable",
        }
    }
    dataset_map = {
        "esto": (esto_data, [2022]),
        "ninth": (ninth_data, [2022]),
    }
    return dataset_map, sector_config, {}, ninth_data, esto_data


def test_usa_msw_production_uses_esto_base_year_when_ninth_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observed ESTO production must survive the reconciliation seed path."""
    assets = _supply_assets_with_usa_msw()
    monkeypatch.setattr(
        supply_reconciliation_tables.supply_data_pipeline,
        "SUPPLY_PROJECTION_LOOKUP",
        None,
    )

    prepared = supply_reconciliation_tables.prepare_supply_primary_table(
        assets,
        economies=["20_USA"],
        dataset_key="ninth",
    )

    row = prepared.loc[
        (prepared["economy"] == "20_USA")
        & (prepared["esto_product"] == USA_MSW_PRODUCT)
        & (prepared["year"] == 2022)
    ].iloc[0]
    assert row["production"] == pytest.approx(147.926996)


def test_usa_msw_maximum_production_survives_baseline_seed_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The combined baseline seed must retain the reconciled supply value."""
    dataset_map, sector_config, code_to_name_mapping, _, esto_data = _supply_assets_with_usa_msw()
    del dataset_map
    monkeypatch.setattr(
        supply_export_builder,
        "_get_supply_branch_roots_for_entry",
        lambda fuel_key, entry: [["Resources", "Secondary"]],
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_resolve_supply_branch_label_from_export",
        lambda branch_type, display_name, fuel_label_esto, fuel_key: "Municipal solid waste non renewable",
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_supply_branch_exists_in_export_source",
        lambda branch_path: True,
    )
    monkeypatch.setattr(supply_leap_io, "_load_reference_export_data", lambda: pd.DataFrame())

    source_paths = supply_export_builder.generate_supply_exports(
        {"esto": (esto_data, [2022])},
        sector_config,
        code_to_name_mapping,
        dataset_key="esto",
        economies=["20_USA"],
        scenario_names=["Reference"],
        base_year=2022,
        final_year=2023,
        export_output_dir=tmp_path / "supply",
        filename_template="supply_{economy}.xlsx",
        flow_value_overrides_by_economy={
            "20_USA": {
                "Reference": {
                    USA_MSW_PRODUCT: {
                        "max_production": {2022: 147.926996, 2023: 147.926996},
                    }
                }
            }
        },
    )
    assert len(source_paths) == 1
    _, source_path = source_paths[0]

    baseline_paths = supply_leap_io.write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "baseline_seed",
        source_workbooks_by_workflow={"supply_workflow": [source_path]},
        enforce_validation=False,
    )

    assert len(baseline_paths) == 1
    seed = pd.read_excel(baseline_paths[0], sheet_name="LEAP", header=2)
    row = seed.loc[
        (seed["Branch Path"] == USA_MSW_BRANCH)
        & (seed["Variable"] == "Maximum Production")
        & (seed["Scenario"] == "Reference")
    ].iloc[0]
    assert "147.926996" in str(row["Expression"])


def test_wind_maximum_production_is_written_to_standalone_supply_workbook(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Standalone exports retain the unlimited Maximum Production Wind row."""
    wind_product = "14 Wind"
    wind_config = {
        wind_product: {
            "fuel_label_esto": wind_product,
            "fuel_code_ninth": "14_wind",
            "fuel_name": "Wind",
        }
    }
    wind_data = pd.DataFrame(
        {
            "economy": ["20_USA"],
            "flows": ["01 Production"],
            "products": [wind_product],
            2022: [0.0],
        }
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_get_supply_branch_roots_for_entry",
        lambda fuel_key, entry: [["Resources", "Primary"]],
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_resolve_supply_branch_label_from_export",
        lambda branch_type, display_name, fuel_label_esto, fuel_key: "Wind",
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_supply_branch_exists_in_export_source",
        lambda branch_path: True,
    )

    paths = supply_export_builder.generate_supply_exports(
        {"esto": (wind_data, [2022])},
        wind_config,
        {},
        dataset_key="esto",
        economies=["20_USA"],
        scenario_names=["Reference"],
        base_year=2022,
        final_year=2023,
        export_output_dir=tmp_path,
        filename_template="supply_{economy}.xlsx",
    )

    assert len(paths) == 1
    _, workbook_path = paths[0]
    exported = pd.read_excel(workbook_path, sheet_name="LEAP", header=2)
    row = exported.loc[
        (exported["Branch Path"] == "Resources\\Primary\\Wind")
        & (exported["Variable"] == "Maximum Production")
        & (exported["Scenario"] == "Reference")
    ].iloc[0]
    assert float(row[2023]) == pytest.approx(1e15)
