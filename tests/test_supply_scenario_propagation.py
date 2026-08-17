"""Regression coverage for scenario-aware supply projections and seed emission."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions import supply_export_builder
from codebase.supply_reconciliation import balance_tables, results_saver, tables


ECONOMY = "20_USA"
PRODUCT = "01 Coal"


def _projection_lookup(*, production: float, imports: float, exports: float) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [
            ("20USA", "01 Production", PRODUCT),
            ("20USA", "02 Imports", PRODUCT),
            ("20USA", "03 Exports", PRODUCT),
            ("20USA", "06 Stock changes", PRODUCT),
        ],
        names=["economy_key", "esto_flow", "esto_product"],
    )
    return pd.DataFrame(
        {2023: [production, imports, exports, 0.0]},
        index=index,
    )


def _assets() -> tuple:
    esto = pd.DataFrame(
        {
            "economy": ["20USA"] * 4,
            "flows": [
                "01 Production",
                "02 Imports",
                "03 Exports",
                "06 Stock changes",
            ],
            "products": [PRODUCT] * 4,
            2022: [5.0, 1.0, 2.0, 0.5],
        }
    )
    sector_config = {
        PRODUCT: {
            "fuel_label_esto": PRODUCT,
            "fuel_code_ninth": "01_coal",
            "fuel_name": "Coal",
        }
    }
    dataset_map = {
        "esto": (esto, [2022]),
        "ninth": (pd.DataFrame(), [2022, 2023]),
    }
    return dataset_map, sector_config, {}, pd.DataFrame(), esto


@pytest.fixture
def scenario_supply(monkeypatch: pytest.MonkeyPatch) -> tuple[pd.DataFrame, pd.DataFrame]:
    assets = _assets()
    lookups = {
        "Reference": _projection_lookup(production=100.0, imports=10.0, exports=20.0),
        "Target": _projection_lookup(production=200.0, imports=30.0, exports=40.0),
    }
    monkeypatch.setattr(tables, "BASE_YEAR", 2022)
    monkeypatch.setattr(tables, "FINAL_YEAR", 2023)
    monkeypatch.setattr(tables.supply_data_pipeline, "PROJECTION_YEAR_RANGE", [2023])
    monkeypatch.setattr(
        tables.supply_data_pipeline,
        "SUPPLY_PROJECTION_LOOKUPS_BY_SCENARIO",
        lookups,
    )
    monkeypatch.setattr(
        tables.supply_data_pipeline,
        "SUPPLY_PROJECTION_LOOKUP",
        lookups["Reference"],
    )
    monkeypatch.setattr(
        tables.supply_data_pipeline,
        "prepare_supply_assets",
        lambda economies: assets,
    )

    projected, returned_assets = tables.prepare_projected_supply_table(
        economies=[ECONOMY],
        scenarios=["Current Accounts", "Reference", "Target"],
    )
    primary = tables.prepare_supply_primary_table(
        returned_assets,
        economies=[ECONOMY],
        scenarios=["Current Accounts", "Reference", "Target"],
    )
    return projected, primary


def test_supply_tables_keep_reference_target_and_current_accounts_distinct(
    scenario_supply: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    projected, primary = scenario_supply
    projection_2023 = projected[projected["year"].eq(2023)].set_index("scenario")
    assert projection_2023.loc["Reference", "projected_imports"] == pytest.approx(10.0)
    assert projection_2023.loc["Reference", "projected_exports"] == pytest.approx(20.0)
    assert projection_2023.loc["Target", "projected_imports"] == pytest.approx(30.0)
    assert projection_2023.loc["Target", "projected_exports"] == pytest.approx(40.0)
    assert projection_2023.loc["Current Accounts", "projected_imports"] == pytest.approx(0.0)

    production_2023 = primary[primary["year"].eq(2023)].set_index("scenario")
    assert production_2023.loc["Reference", "production"] == pytest.approx(100.0)
    assert production_2023.loc["Target", "production"] == pytest.approx(200.0)
    assert production_2023.loc["Current Accounts", "production"] == pytest.approx(0.0)

    current_2022 = primary[
        primary["scenario"].eq("Current Accounts") & primary["year"].eq(2022)
    ].iloc[0]
    assert current_2022["production"] == pytest.approx(5.0)


def test_reconciliation_merges_supply_on_scenario_without_cross_copy(
    scenario_supply: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    projected, primary = scenario_supply
    demand = pd.DataFrame(
        [
            {
                "economy": ECONOMY,
                "scenario": scenario,
                "esto_product": PRODUCT,
                "year": 2023,
                "demand_value": 0.0,
                "demand_source": "test",
            }
            for scenario in ("Reference", "Target")
        ]
    )
    transformation = pd.DataFrame(
        [{
            "economy": ECONOMY,
            "esto_product": PRODUCT,
            "year": 2023,
            "transformation_output": 0.0,
            "transformation_input": 0.0,
            "transformation_losses": 0.0,
        }]
    )

    reconciled = tables.build_reconciliation_table(
        demand,
        transformation,
        projected[projected["year"].eq(2023)],
        supply_primary_table=primary[primary["year"].eq(2023)],
    ).set_index("scenario")

    assert reconciled.loc["Reference", "projected_exports"] == pytest.approx(20.0)
    assert reconciled.loc["Target", "projected_exports"] == pytest.approx(40.0)
    assert reconciled.loc["Reference", "production"] == pytest.approx(100.0)
    assert reconciled.loc["Target", "production"] == pytest.approx(200.0)


def test_conventional_balance_projection_reader_uses_requested_scenario(
    scenario_supply: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    del scenario_supply
    target_value = balance_tables._get_projection_value_for_flow_product(
        economy=ECONOMY,
        scenario="Target",
        flow="03 Exports",
        product=PRODUCT,
        year=2023,
    )
    reference_value = balance_tables._get_projection_value_for_flow_product(
        economy=ECONOMY,
        scenario="Reference",
        flow="03 Exports",
        product=PRODUCT,
        year=2023,
    )
    assert reference_value == pytest.approx(20.0)
    assert target_value == pytest.approx(40.0)


def test_reconciliation_rejects_stale_scenario_less_supply_table() -> None:
    stale = pd.DataFrame(
        [{"economy": ECONOMY, "esto_product": PRODUCT, "year": 2023}]
    )
    with pytest.raises(ValueError, match="scenario-less"):
        tables.build_reconciliation_table(
            pd.DataFrame(),
            pd.DataFrame(),
            stale,
        )


def test_transform_supply_cache_rejects_scenario_less_payload() -> None:
    stale = {
        "supply_projection_table": pd.DataFrame(
            [{"economy": ECONOMY, "esto_product": PRODUCT, "year": 2023}]
        ),
        "supply_primary_table": pd.DataFrame(
            [{"economy": ECONOMY, "esto_product": PRODUCT, "year": 2023}]
        ),
    }
    with pytest.raises(ValueError, match="scenario-less"):
        results_saver._validate_scenario_aware_supply_cache(stale)


def test_supply_workbook_emission_keeps_reference_target_and_current_accounts_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dataset_map, sector_config, code_map, _, esto = _assets()
    monkeypatch.setattr(
        supply_export_builder,
        "_get_supply_branch_roots_for_entry",
        lambda *_args, **_kwargs: [["Resources", "Primary"]],
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_resolve_supply_branch_label_from_export",
        lambda *_args, **_kwargs: "Coal",
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_supply_branch_exists_in_export_source",
        lambda *_args, **_kwargs: True,
    )
    overrides = {
        ECONOMY: {
            "Reference": {
                PRODUCT: {
                    "exports": {2022: 2.0, 2023: 20.0},
                    "max_production": {2022: 5.0, 2023: 100.0},
                }
            },
            "Target": {
                PRODUCT: {
                    "exports": {2022: 2.0, 2023: 40.0},
                    "max_production": {2022: 5.0, 2023: 200.0},
                }
            },
            "Current Accounts": {
                PRODUCT: {
                    "exports": {2022: 2.0},
                    "max_production": {2022: 5.0},
                }
            },
        }
    }
    source_paths = supply_export_builder.generate_supply_exports(
        dataset_map,
        sector_config,
        code_map,
        projection_lookups_by_scenario={
            "Reference": pd.DataFrame(),
            "Target": pd.DataFrame(),
        },
        dataset_key="esto",
        economies=[ECONOMY],
        scenario_names=["Current Accounts", "Reference", "Target"],
        base_year=2022,
        final_year=2023,
        export_output_dir=tmp_path / "supply",
        filename_template="supply_{economy}.xlsx",
        flow_value_overrides_by_economy=overrides,
    )
    seed = pd.read_excel(source_paths[0][1], sheet_name="FOR_VIEWING", header=2)

    def _value(variable: str, scenario: str, year: int) -> float:
        row = seed[
            seed["Branch Path"].eq(r"Resources\Primary\Coal")
            & seed["Variable"].eq(variable)
            & seed["Scenario"].eq(scenario)
        ].iloc[0]
        return float(row[str(year)] if str(year) in row.index else row[year])

    assert _value("Maximum Production", "Reference", 2023) == pytest.approx(100.0)
    assert _value("Maximum Production", "Target", 2023) == pytest.approx(200.0)
    assert _value("Exports", "Reference", 2023) == pytest.approx(20.0)
    assert _value("Exports", "Target", 2023) == pytest.approx(40.0)
    assert _value("Maximum Production", "Current Accounts", 2022) == pytest.approx(5.0)
