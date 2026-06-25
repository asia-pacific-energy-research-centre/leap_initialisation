import pandas as pd

from codebase.utilities.leap_results_dashboard_balance import build_total_balance_mapping_checks


def _row(
    *,
    flow_path: str,
    fuel_name: str,
    value: float,
    esto_flow: str,
    esto_product: str,
    ninth_sector: str,
    ninth_fuel: str,
    subtotal: bool = False,
) -> dict[str, object]:
    return {
        "scenario": "Reference",
        "year": 2022,
        "source_workbook": "mock.xlsx",
        "source_sheet": "Energy Balance 2022",
        "leap_sector_name": flow_path.split("/")[-1],
        "leap_sector_name_original": flow_path.split("/")[-1],
        "leap_sector_name_full_path": flow_path,
        "leap_fuel_name": fuel_name,
        "leap_fuel_name_raw": fuel_name,
        "value_petajoule": value,
        "esto_flow": esto_flow,
        "esto_product": esto_product,
        "leap_sector": ninth_sector,
        "leap_fuel": ninth_fuel,
        "leap_is_subtotal": subtotal,
        "esto_is_subtotal": subtotal,
        "ninth_is_subtotal": subtotal,
    }


def test_total_balance_check_passes_with_signed_tpes_components() -> None:
    rows = [
        _row(
            flow_path="Supply/Total Primary Supply",
            fuel_name="Total",
            value=85.0,
            esto_flow="07 Total primary energy supply",
            esto_product="19 Total",
            ninth_sector="07_total_primary_energy_supply",
            ninth_fuel="19_total",
            subtotal=True,
        ),
        _row(
            flow_path="Production",
            fuel_name="Total",
            value=100.0,
            esto_flow="01 Production",
            esto_product="01 Coal",
            ninth_sector="01_production",
            ninth_fuel="01_coal",
        ),
        _row(
            flow_path="Imports",
            fuel_name="Total",
            value=10.0,
            esto_flow="02 Imports",
            esto_product="01 Coal",
            ninth_sector="02_imports",
            ninth_fuel="01_coal",
        ),
        _row(
            flow_path="Exports",
            fuel_name="Total",
            value=-25.0,
            esto_flow="03 Exports",
            esto_product="01 Coal",
            ninth_sector="03_exports",
            ninth_fuel="01_coal",
        ),
    ]

    checks = build_total_balance_mapping_checks(pd.DataFrame(rows), tolerance_pj=1e-9)
    tpes = checks[checks["check_name"].eq("total_primary_supply")].iloc[0]

    assert tpes["status"] == "pass"
    assert tpes["esto_component_total_pj"] == 85.0
    assert tpes["ninth_component_total_pj"] == 85.0


def test_total_balance_check_flags_component_mismatch() -> None:
    rows = [
        _row(
            flow_path="Total Final Energy Demand",
            fuel_name="Total",
            value=60.0,
            esto_flow="13 Total final energy consumption",
            esto_product="19 Total",
            ninth_sector="13_total_final_energy_consumption",
            ninth_fuel="19_total",
            subtotal=True,
        ),
        _row(
            flow_path="Industry",
            fuel_name="Total",
            value=20.0,
            esto_flow="14 Industry sector",
            esto_product="01 Coal",
            ninth_sector="14_industry_sector",
            ninth_fuel="01_coal",
        ),
        _row(
            flow_path="Transport",
            fuel_name="Total",
            value=25.0,
            esto_flow="15 Transport sector",
            esto_product="01 Coal",
            ninth_sector="15_transport_sector",
            ninth_fuel="01_coal",
        ),
    ]

    checks = build_total_balance_mapping_checks(pd.DataFrame(rows), tolerance_pj=1e-9)
    final_demand = checks[checks["check_name"].eq("total_final_energy_demand")].iloc[0]

    assert final_demand["status"] == "fail"
    assert final_demand["severity"] == "error"
    assert final_demand["esto_component_difference_pj"] == -15.0
    assert "component sum differs" in final_demand["details"]
