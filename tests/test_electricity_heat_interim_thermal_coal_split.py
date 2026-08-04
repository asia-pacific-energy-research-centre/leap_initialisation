#%%
"""Regression coverage for splitting the ambiguous 01_x_thermal_coal 9th fuel.

The 9th projection dataset carries anthracite, sub-bituminous coal, and other
bituminous coal as a single aggregate (01_x_thermal_coal) with no sub-fuel
breakdown, but ESTO and the LEAP export template distinguish all three. See
AMBIGUOUS_NINTH_FUEL_ESTO_SPLITS in electricity_heat_interim_workflow.py. The
split is delegated to allocate_ninth_projection_to_esto (the same engine used
by aggregated_demand_workflow.py) rather than reimplemented locally.
"""

import pandas as pd
import pytest

from codebase import electricity_heat_interim_workflow as workflow


ESTO_PRODUCTS = [
    "01.02 Other bituminous coal",
    "01.03 Sub-bituminous coal",
    "01.04 Anthracite",
]
ESTO_FLOWS = ["09.01.01 Electricity plants", "09.02.01 Electricity plants"]


def _esto_row(economy: str, flow: str, product: str, years: dict) -> dict:
    row = {"economy": economy, "flows": flow, "products": product}
    row.update(years)
    return row


def test_split_ambiguous_ninth_fuel_rows_splits_aggregate_by_esto_share(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    esto_data = pd.DataFrame(
        [
            _esto_row("01_AUS", "09.01.01 Electricity plants", "01.02 Other bituminous coal", {2020: -30.0}),
            _esto_row("01_AUS", "09.01.01 Electricity plants", "01.03 Sub-bituminous coal", {2020: -60.0}),
            _esto_row("01_AUS", "09.01.01 Electricity plants", "01.04 Anthracite", {2020: -10.0}),
        ]
    )
    monkeypatch.setattr(workflow.core, "esto_data", esto_data)
    monkeypatch.setattr(workflow.core, "BASE_YEAR", 2020)
    monkeypatch.setattr(workflow.core, "ninth_year_cols", [2025])

    ninth_rows = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "sub1sectors": "09_01_electricity_plants",
                "fuels": "01_x_thermal_coal",
                "subfuels": "x",
                2025: -100.0,
            }
        ]
    )

    split = workflow._split_ambiguous_ninth_fuel_rows(ninth_rows, "01_AUS", ESTO_FLOWS)

    by_product = split.set_index("subfuels")[2025]
    assert by_product["01.02 Other bituminous coal"] == pytest.approx(-30.0)
    assert by_product["01.03 Sub-bituminous coal"] == pytest.approx(-60.0)
    assert by_product["01.04 Anthracite"] == pytest.approx(-10.0)
    assert split["fuels"].tolist() == split["subfuels"].tolist()


def test_split_ambiguous_ninth_fuel_rows_falls_back_to_even_split_with_no_base_year_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow.core, "esto_data", pd.DataFrame(columns=["economy", "flows", "products"])
    )
    monkeypatch.setattr(workflow.core, "BASE_YEAR", 2020)
    monkeypatch.setattr(workflow.core, "ninth_year_cols", [2025])

    ninth_rows = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "sub1sectors": "09_01_electricity_plants",
                "fuels": "01_x_thermal_coal",
                "subfuels": "x",
                2025: -90.0,
            }
        ]
    )

    split = workflow._split_ambiguous_ninth_fuel_rows(ninth_rows, "01_AUS", ESTO_FLOWS)

    by_product = split.set_index("subfuels")[2025]
    assert by_product["01.02 Other bituminous coal"] == pytest.approx(-30.0)
    assert by_product["01.03 Sub-bituminous coal"] == pytest.approx(-30.0)
    assert by_product["01.04 Anthracite"] == pytest.approx(-30.0)


def test_split_ambiguous_ninth_fuel_rows_falls_back_to_apec_share_for_new_economy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An economy with no base-year coal history of its own should borrow the
    APEC-wide split instead of getting an arbitrary even split, matching the
    demand-side allocator's established fallback precedent."""
    esto_data = pd.DataFrame(
        [
            # 02_BD has real history and is used to build the APEC-wide fallback.
            _esto_row("02_BD", "09.01.01 Electricity plants", "01.02 Other bituminous coal", {2020: -80.0}),
            _esto_row("02_BD", "09.01.01 Electricity plants", "01.03 Sub-bituminous coal", {2020: -10.0}),
            _esto_row("02_BD", "09.01.01 Electricity plants", "01.04 Anthracite", {2020: -10.0}),
        ]
    )
    monkeypatch.setattr(workflow.core, "esto_data", esto_data)
    monkeypatch.setattr(workflow.core, "BASE_YEAR", 2020)
    monkeypatch.setattr(workflow.core, "ninth_year_cols", [2025])

    # 01_AUS itself has no base-year coal split to draw on.
    ninth_rows = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "sub1sectors": "09_01_electricity_plants",
                "fuels": "01_x_thermal_coal",
                "subfuels": "x",
                2025: -100.0,
            }
        ]
    )

    split = workflow._split_ambiguous_ninth_fuel_rows(ninth_rows, "01_AUS", ESTO_FLOWS)

    by_product = split.set_index("subfuels")[2025]
    assert by_product["01.02 Other bituminous coal"] == pytest.approx(-80.0)
    assert by_product["01.03 Sub-bituminous coal"] == pytest.approx(-10.0)
    assert by_product["01.04 Anthracite"] == pytest.approx(-10.0)


def test_split_ambiguous_ninth_fuel_rows_splits_other_petroleum_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never collapse the aggregate 9th petroleum code entirely to Bitumen."""
    petroleum_products = [
        "07.14 Bitumen",
        "07.16 Petroleum coke",
        "07.17 Other products",
    ]
    esto_data = pd.DataFrame(
        [
            _esto_row("11_MEX", ESTO_FLOWS[0], petroleum_products[0], {2022: -10.0}),
            _esto_row("11_MEX", ESTO_FLOWS[0], petroleum_products[1], {2022: -20.0}),
            _esto_row("11_MEX", ESTO_FLOWS[0], petroleum_products[2], {2022: -70.0}),
        ]
    )
    ninth_rows = pd.DataFrame(
        [
            {
                "economy": "11_MEX",
                "sub1sectors": "09_01_electricity_plants",
                "fuels": "07_x_other_petroleum_products",
                "subfuels": "x",
                2023: -100.0,
            }
        ]
    )
    monkeypatch.setattr(workflow.core, "esto_data", esto_data)
    monkeypatch.setattr(workflow.core, "BASE_YEAR", 2022)
    monkeypatch.setattr(workflow.core, "ninth_year_cols", [2023])

    split = workflow._split_ambiguous_ninth_fuel_rows(ninth_rows, "11_MEX", ESTO_FLOWS)
    by_product = split.set_index("subfuels")[2023]

    assert by_product["07.14 Bitumen"] == pytest.approx(-10.0)
    assert by_product["07.16 Petroleum coke"] == pytest.approx(-20.0)
    assert by_product["07.17 Other products"] == pytest.approx(-70.0)


def test_combine_module_source_rows_splits_thermal_coal_across_projection_years(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: the merged Electricity-interim rows must not dump the
    entire projected thermal-coal aggregate onto Anthracite alone."""
    esto_data = pd.DataFrame(
        [
            _esto_row(
                "01_AUS", "09.01.01 Electricity plants", "01.02 Other bituminous coal",
                {2020: -30.0, 2025: 0.0},
            ),
            _esto_row(
                "01_AUS", "09.01.01 Electricity plants", "01.03 Sub-bituminous coal",
                {2020: -60.0, 2025: 0.0},
            ),
            _esto_row(
                "01_AUS", "09.01.01 Electricity plants", "01.04 Anthracite",
                {2020: -10.0, 2025: 0.0},
            ),
        ]
    )
    ninth_data = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "sub1sectors": "09_01_electricity_plants",
                "fuels": "01_x_thermal_coal",
                "subfuels": "x",
                2020: 0.0,
                2025: -100.0,
            }
        ]
    )
    monkeypatch.setattr(workflow.core, "esto_data", esto_data)
    monkeypatch.setattr(workflow.core, "ninth_data", ninth_data)
    monkeypatch.setattr(workflow.core, "esto_year_cols", [2020, 2025])
    monkeypatch.setattr(workflow.core, "ninth_year_cols", [2020, 2025])
    monkeypatch.setattr(workflow.core, "BASE_YEAR", 2020)
    monkeypatch.setattr(workflow.core, "PROJECTION_START_YEAR", 2025)
    monkeypatch.setattr(workflow, "_ESTO_PRODUCT_TO_NINTH_FUEL", {})
    monkeypatch.setattr(workflow, "_load_esto_product_to_ninth_fuel", lambda: {})

    config = workflow.INTERIM_MODULES["Electricity interim"]
    rows, years = workflow._combine_module_source_rows(
        economy="01_AUS",
        sub1sectors=config["sub1sectors"],
        esto_flows=config["esto_flows"],
    )
    totals, _ = workflow.core.summarize_fuel_totals(
        rows, years, start_year=2025, allow_all_years_fallback=False
    )

    assert totals["01.04 Anthracite"] == pytest.approx(-10.0)
    assert totals["01.02 Other bituminous coal"] == pytest.approx(-30.0)
    assert totals["01.03 Sub-bituminous coal"] == pytest.approx(-60.0)
