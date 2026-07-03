"""Focused tests for supply preservation and results-update closure checks."""

#%%

import pandas as pd
import pytest

from codebase.functions.supply_conservation import (
    build_baseline_supply_source_preservation,
    build_results_update_closure_diagnostics,
    find_exported_supply_products,
)


def test_results_update_closure_passes_balanced_row():
    row = pd.DataFrame([{
        "economy": "20_USA", "scenario": "Reference", "esto_product": "p1", "year": 2030,
        "adjusted_imports": 25.0, "adjusted_exports": 5.0,
        "constrained_transformation_output": 40.0, "constrained_production": 50.0,
        "stock_changes": 0.0, "transformation_input": 30.0,
        "transformation_losses": 10.0, "demand_value": 70.0,
    }])

    result = build_results_update_closure_diagnostics(row)

    assert result.loc[0, "closure_residual"] == pytest.approx(0.0)
    assert result.loc[0, "status"] == "closed"


def test_results_update_closure_catches_shortfall():
    row = pd.DataFrame([{
        "economy": "20_USA", "scenario": "Reference", "esto_product": "p1", "year": 2030,
        "adjusted_imports": 20.0, "adjusted_exports": 5.0,
        "constrained_transformation_output": 40.0, "constrained_production": 50.0,
        "stock_changes": 0.0, "transformation_input": 30.0,
        "transformation_losses": 10.0, "demand_value": 70.0,
    }])

    result = build_results_update_closure_diagnostics(row)

    assert result.loc[0, "closure_residual"] == pytest.approx(-5.0)
    assert result.loc[0, "status"] == "closure_mismatch"


def test_baseline_supply_preservation_catches_unmapped_source_product(monkeypatch):
    esto = pd.DataFrame([
        {"economy": "20USA", "flows": "01 Production", 2022: 10.0},
        {"economy": "20USA", "flows": "02 Imports", 2022: 5.0},
        {"economy": "20USA", "flows": "03 Exports", 2022: -2.0},
    ])
    ninth = pd.DataFrame([
        {"economy": "20_USA", "sectors": "01_production", 2023: 12.0},
        {"economy": "20_USA", "sectors": "02_imports", 2023: 6.0},
        {"economy": "20_USA", "sectors": "03_exports", 2023: -3.0},
    ])
    assets = ({"esto": (esto, [2022]), "ninth": (ninth, [2023])}, {}, {}, None, None)
    projection = pd.DataFrame([
        {"economy": "20_USA", "esto_product": "p1", "year": 2022, "projected_imports": 4.0, "projected_exports": 2.0},
        {"economy": "20_USA", "esto_product": "p1", "year": 2023, "projected_imports": 6.0, "projected_exports": 3.0},
    ])
    primary = pd.DataFrame([
        {"economy": "20_USA", "esto_product": "p1", "year": 2022, "production": 10.0},
        {"economy": "20_USA", "esto_product": "p1", "year": 2023, "production": 12.0},
    ])

    result = build_baseline_supply_source_preservation(
        assets=assets,
        supply_projection_table=projection,
        supply_primary_table=primary,
        economies=["20_USA"],
        base_year=2022,
        final_year=2023,
    )
    imports_2022 = result[(result.flow == "imports") & (result.year == 2022)].iloc[0]

    assert imports_2022.reference_total == pytest.approx(5.0)
    assert imports_2022.resolved_total == pytest.approx(4.0)
    assert imports_2022.is_mismatch


def test_exported_supply_products_exclude_unwritten_aggregate_rows(monkeypatch, tmp_path):
    export_path = tmp_path / "supply.xlsx"
    export_path.touch()
    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *args, **kwargs: pd.DataFrame(
            {"Branch Path": ["Supply and Resources\\Primary\\Crude oil"]}
        ),
    )
    sector_config = {
        "06 Crude oil & NGL": {"fuel_name": "Crude oil & NGL"},
        "06.01 Crude oil": {"fuel_name": "Crude oil"},
    }

    included = find_exported_supply_products([export_path], sector_config)

    assert included == {"06.01 Crude oil"}


#%%
