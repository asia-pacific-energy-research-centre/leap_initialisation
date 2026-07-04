"""Focused tests for supply preservation and results-update closure checks."""

#%%

import pandas as pd
import pytest

from codebase.functions.supply_conservation import (
    build_baseline_supply_conservation_artifacts,
    build_baseline_supply_source_preservation,
    build_results_update_closure_diagnostics,
    find_exported_supply_products,
)


def _supply_fixture():
    esto = pd.DataFrame([
        {"economy": "20USA", "flows": "01 Production", "products": "01 Coal", "is_subtotal": False, 2022: 10.0},
        {"economy": "20USA", "flows": "02 Imports", "products": "01 Coal", "is_subtotal": False, 2022: 5.0},
        {"economy": "20USA", "flows": "03 Exports", "products": "01 Coal", "is_subtotal": False, 2022: -2.0},
    ])
    ninth = pd.DataFrame([
        {"economy": "20_USA", "sectors": "01_production", "fuels": "01_coal", "subtotal_results": False, 2023: 12.0},
        {"economy": "20_USA", "sectors": "02_imports", "fuels": "01_coal", "subtotal_results": False, 2023: 6.0},
        {"economy": "20_USA", "sectors": "03_exports", "fuels": "01_coal", "subtotal_results": False, 2023: -3.0},
    ])
    assets = ({"esto": (esto, [2022]), "ninth": (ninth, [2023])}, {}, {}, None, None)
    projection = pd.DataFrame([
        {"economy": "20_USA", "esto_product": "01 Coal", "year": 2022, "projected_imports": 5.0, "projected_exports": 2.0},
        {"economy": "20_USA", "esto_product": "01 Coal", "year": 2023, "projected_imports": 6.0, "projected_exports": 3.0},
    ])
    primary = pd.DataFrame([
        {"economy": "20_USA", "esto_product": "01 Coal", "year": 2022, "production": 10.0},
        {"economy": "20_USA", "esto_product": "01 Coal", "year": 2023, "production": 12.0},
    ])
    return assets, projection, primary


def test_supply_artifacts_pass_and_breakdown_reproduces_headline():
    assets, projection, primary = _supply_fixture()
    totals, breakdown, lineage = build_baseline_supply_conservation_artifacts(
        assets, projection, primary, ["20_USA"], 2022, 2023
    )

    assert not totals["is_mismatch"].any()
    assert breakdown["breakdown_remainder"].abs().max() == pytest.approx(0.0)
    assert {"row_id", "schema_version", "value_classification"}.issubset(lineage.columns)
    export_reference = lineage[(lineage.stage == "reference") & (lineage.flow == "exports")]
    assert set(export_reference["value"]) == {2.0, 3.0}


def test_supply_dropped_product_is_localized_and_aggregate_is_excluded():
    assets, projection, primary = _supply_fixture()
    esto = assets[0]["esto"][0]
    assets[0]["esto"] = (pd.concat([esto, pd.DataFrame([
        {"economy": "20USA", "flows": "01 Production", "products": "02 Parent", "is_subtotal": False, 2022: 4.0},
        {"economy": "20USA", "flows": "01 Production", "products": "02.01 Child", "is_subtotal": False, 2022: 4.0},
    ])], ignore_index=True), [2022])
    totals, breakdown, lineage = build_baseline_supply_conservation_artifacts(
        assets, projection, primary, ["20_USA"], 2022, 2023
    )

    row = totals[(totals.flow == "production") & (totals.year == 2022)].iloc[0]
    assert row.difference == pytest.approx(-4.0)
    assert ((lineage.source_product == "02 Parent") & (lineage.exclusion_reason == "structural_parent_aggregate")).any()
    assert ((breakdown.source_product == "02.01 Child") & (breakdown.difference == -4.0)).any()


def test_supply_empty_comparison_fails():
    assets = ({"esto": (pd.DataFrame(columns=["economy", "flows", "products", 2022]), [2022]),
               "ninth": (pd.DataFrame(columns=["economy", "sectors", "fuels", 2023]), [2023])}, {}, {}, None, None)
    empty_projection = pd.DataFrame(columns=["economy", "esto_product", "year", "projected_imports", "projected_exports"])
    empty_primary = pd.DataFrame(columns=["economy", "esto_product", "year", "production"])
    with pytest.raises(ValueError, match="empty"):
        build_baseline_supply_conservation_artifacts(assets, empty_projection, empty_primary, ["20_USA"], 2022, 2023)


def test_ninth_parent_fuel_row_is_excluded_when_detailed_subfuels_exist():
    assets, projection, primary = _supply_fixture()
    ninth = assets[0]["ninth"][0].copy()
    production = ninth[ninth["sectors"] == "01_production"].iloc[0].to_dict()
    production.update({"fuels": "01_coal", "subfuels": "x", 2023: 12.0})
    child = dict(production)
    child.update({"subfuels": "01_x_thermal_coal", 2023: 12.0})
    other = ninth[ninth["sectors"] != "01_production"].copy()
    assets[0]["ninth"] = (pd.concat([other, pd.DataFrame([production, child])], ignore_index=True), [2023])

    totals, _, lineage = build_baseline_supply_conservation_artifacts(
        assets, projection, primary, ["20_USA"], 2022, 2023
    )

    production_total = totals[(totals.flow == "production") & (totals.year == 2023)].iloc[0]
    assert production_total.reference_total == pytest.approx(12.0)
    parent = lineage[
        (lineage.source_system == "9TH")
        & (lineage.flow == "production")
        & (lineage.source_product == "01_coal")
    ]
    assert set(parent.exclusion_reason) == {"structural_parent_aggregate"}


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
