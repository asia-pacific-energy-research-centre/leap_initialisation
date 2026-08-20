#%%
"""Regression coverage for signed electricity/CHP/heat source sectors."""

import pandas as pd
import pytest

from codebase import electricity_heat_interim_workflow as workflow


def test_power_ninth_cleanup_removes_only_parent_fuel_rollups() -> None:
    source = pd.DataFrame([
        {
            "economy": "10_MAS", "scenarios": "reference",
            "sectors": "09_total_transformation_sector",
            "sub1sectors": "09_02_chp_plants", "sub2sectors": "x",
            "fuels": "08_gas", "subfuels": "x", "subtotal_results": False,
            2023: -10.0,
        },
        {
            "economy": "10_MAS", "scenarios": "reference",
            "sectors": "09_total_transformation_sector",
            "sub1sectors": "09_02_chp_plants", "sub2sectors": "x",
            "fuels": "08_gas", "subfuels": "08_01_natural_gas", "subtotal_results": False,
            2023: -10.0,
        },
        {
            "economy": "10_MAS", "scenarios": "reference",
            "sectors": "09_total_transformation_sector",
            "sub1sectors": "09_02_chp_plants", "sub2sectors": "x",
            "fuels": "17_electricity", "subfuels": "x", "subtotal_results": False,
            2023: 5.0,
        },
    ])

    result = workflow._drop_ninth_projection_subtotals(source)

    assert result["subfuels"].tolist() == ["08_01_natural_gas", "x"]


def test_interim_modules_select_only_approved_signed_transformation_sectors() -> None:
    configured = {
        module: config["sub1sectors"]
        for module, config in workflow.INTERIM_MODULES.items()
    }
    assert configured == {
        "Electricity interim": ["09_01_electricity_plants"],
        "CHP interim": ["09_02_chp_plants"],
        "Heat plant interim": ["09_x_heat_plants"],
    }
    assert workflow.INTERIM_MODULES["Electricity interim"]["output_labels"] == ["Electricity"]
    assert workflow.INTERIM_MODULES["CHP interim"]["output_labels"] == ["Electricity", "Heat"]
    assert workflow.INTERIM_MODULES["Heat plant interim"]["output_labels"] == ["Heat"]
    assert not (
        set(workflow.ALL_POWER_SUB1SECTORS)
        & workflow.FORBIDDEN_POWER_INTERIM_SUB1SECTORS
    )


@pytest.mark.parametrize("sector", sorted(workflow.FORBIDDEN_POWER_INTERIM_SUB1SECTORS))
def test_forbidden_output_accounting_sector_is_rejected(sector: str) -> None:
    with pytest.raises(ValueError, match="forbidden source-role sectors"):
        workflow.validate_power_interim_sub1sectors([sector])


def test_signed_09_rows_supply_outputs_and_inputs_without_forbidden_influence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = workflow.INTERIM_MODULES["CHP interim"]

    ninth_data = pd.DataFrame(
        [
            {
                "economy": "05_PRC",
                "sub1sectors": "09_02_chp_plants",
                "fuels": "07_petroleum_products",
                "subfuels": "x",
                2022: 0.0,
                2023: -10.0,
            },
            {
                "economy": "05_PRC",
                "sub1sectors": "09_02_chp_plants",
                "fuels": "17_electricity",
                "subfuels": "x",
                2022: 0.0,
                2023: 6.0,
            },
            {
                "economy": "05_PRC",
                "sub1sectors": "09_02_chp_plants",
                "fuels": "18_heat",
                "subfuels": "x",
                2022: 0.0,
                2023: 4.0,
            },
            {
                "economy": "05_PRC",
                "sub1sectors": "18_02_chp_plants",
                "fuels": "16_others",
                "subfuels": "x",
                2022: 0.0,
                2023: 999.0,
            },
        ]
    )
    monkeypatch.setattr(workflow.core, "esto_data", pd.DataFrame(columns=["economy", "flows"]))
    monkeypatch.setattr(workflow.core, "ninth_data", ninth_data)
    monkeypatch.setattr(workflow.core, "esto_year_cols", [2022, 2023])
    monkeypatch.setattr(workflow.core, "ninth_year_cols", [2022, 2023])

    rows, years = workflow._combine_module_source_rows(
        economy="05_PRC",
        sub1sectors=config["sub1sectors"],
        esto_flows=config["esto_flows"],
    )
    totals, _ = workflow.core.summarize_fuel_totals(
        rows,
        years,
        start_year=2023,
        allow_all_years_fallback=False,
    )

    assert totals["17_electricity"] == 6.0
    assert totals["18_heat"] == 4.0
    assert totals["07_petroleum_products"] == -10.0
    assert "16_others" not in totals


def test_target_interim_records_use_target_9th_projection_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Target exports must not reuse the Reference power projection series."""
    rows = []
    for scenario, electricity, heat in [
        ("reference", 100.0, 40.0),
        ("target", 125.0, 50.0),
    ]:
        rows.extend(
            [
                {
                    "scenarios": scenario,
                    "economy": "20_USA",
                    "sub1sectors": "09_02_chp_plants",
                    "fuels": "08_gas",
                    "subfuels": "08_01_natural_gas",
                    "subtotal_results": False,
                    2022: 0.0,
                    2023: -200.0,
                },
                {
                    "scenarios": scenario,
                    "economy": "20_USA",
                    "sub1sectors": "09_02_chp_plants",
                    "fuels": "17_electricity",
                    "subfuels": "x",
                    "subtotal_results": False,
                    2022: 0.0,
                    2023: electricity,
                },
                {
                    "scenarios": scenario,
                    "economy": "20_USA",
                    "sub1sectors": "09_02_chp_plants",
                    "fuels": "18_heat",
                    "subfuels": "x",
                    "subtotal_results": False,
                    2022: 0.0,
                    2023: heat,
                },
            ]
        )
    raw_ninth = pd.DataFrame(rows)
    monkeypatch.setattr(
        workflow.core,
        "ninth_data",
        raw_ninth[raw_ninth["scenarios"].eq("reference")].copy(),
    )
    monkeypatch.setattr(workflow.core, "ninth_data_raw", raw_ninth)
    monkeypatch.setattr(workflow.core, "esto_data", pd.DataFrame(columns=["economy", "flows"]))
    monkeypatch.setattr(workflow.core, "esto_year_cols", [2022, 2023])
    monkeypatch.setattr(workflow.core, "ninth_year_cols", [2022, 2023])
    monkeypatch.setattr(workflow.core, "EXPORT_BASE_YEAR", 2022)
    monkeypatch.setattr(workflow.core, "EXPORT_FINAL_YEAR", 2023)
    monkeypatch.setattr(
        workflow.core,
        "code_to_name_mapping",
        {
            "08_01_natural_gas": "Natural gas",
            "17_electricity": "Electricity",
            "18_heat": "Heat",
        },
    )

    records = workflow.build_electricity_heat_interim_rows(
        economies=["20_USA"], scenario="Target"
    )
    chp = next(record for record in records if record["sector_title"] == "CHP interim")

    assert chp["output_values"]["17_electricity"][2023] == pytest.approx(125.0)
    assert chp["output_values"]["18_heat"][2023] == pytest.approx(50.0)


def test_power_interim_display_names_and_never_output_use_canonical_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "build_code_to_display_name",
        lambda **kwargs: (
            {
                "01_coal": "Coal",
                "12_solar_unallocated": "Solar nonspecified",
                "15_04_black_liquor": "Black liquor",
            },
            pd.DataFrame(),
        ),
    )
    monkeypatch.setattr(workflow, "_POWER_INTERIM_DISPLAY_NAME_MAP", None)

    assert workflow._safe_power_interim_display_label("01_coal") == "Coal"
    assert (
        workflow._safe_power_interim_display_label("12_solar_unallocated")
        == "Solar nonspecified"
    )
    assert workflow._safe_power_interim_display_label("15_04_black_liquor") == "Black liquor"
    assert workflow._safe_power_interim_display_label("01_x_thermal_coal") == "01_x_thermal_coal"
    assert workflow._safe_power_interim_display_label("07_x_jet_fuel") == "07_x_jet_fuel"
    assert "Coal" in workflow.POWER_INTERIM_NEVER_OUTPUT_LABELS
    assert "Solar nonspecified" not in workflow.POWER_INTERIM_NEVER_OUTPUT_LABELS


def test_esto_product_mapping_reads_only_canonical_sheet(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_load(sheet_name: str, required_columns, **kwargs) -> pd.DataFrame:
        calls.append((sheet_name, tuple(required_columns)))
        return pd.DataFrame(
            [
                {"ninth_fuel": "01_coal", "esto_product": "01 Coal"},
                {"ninth_fuel": "12_solar_unallocated", "esto_product": "12.99 Solar nonspecified"},
            ]
        )

    monkeypatch.setattr(workflow, "load_canonical_sheet", fake_load)
    monkeypatch.setattr(workflow, "_ESTO_PRODUCT_TO_NINTH_FUEL", None)

    mapping = workflow._load_esto_product_to_ninth_fuel()

    assert calls == [("ninth fuel to esto product", ("ninth_fuel", "esto_product"))]
    assert mapping["01 Coal"] == "01_coal"
    assert mapping["12.99 Solar nonspecified"] == "12_solar_unallocated"


def test_no_data_chp_skeleton_anchors_shares_but_keeps_energy_rows_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow.core, "esto_data", pd.DataFrame(columns=["economy", "flows"]))
    monkeypatch.setattr(
        workflow.core,
        "ninth_data",
        pd.DataFrame(columns=["economy", "sub1sectors", "fuels", "subfuels"]),
    )
    monkeypatch.setattr(workflow.core, "esto_year_cols", [2022, 2023])
    monkeypatch.setattr(workflow.core, "ninth_year_cols", [2022, 2023])

    record = workflow._build_interim_process_record(
        economy="01_AUS",
        sector_title="CHP interim",
        process_name="CHP interim",
        sub1sectors=workflow.INTERIM_MODULES["CHP interim"]["sub1sectors"],
        esto_flows=workflow.INTERIM_MODULES["CHP interim"]["esto_flows"],
        output_labels=workflow.INTERIM_MODULES["CHP interim"]["output_labels"],
    )
    rows = workflow.core.build_transformation_log_rows(
        [record],
        scenario="Reference",
        region="Australia",
        base_year=2022,
        final_year=2023,
        code_to_name_mapping={
            "CHP interim": "CHP interim",
            "Electricity": "Electricity",
            "Heat": "Heat",
        },
    )
    paths_by_measure = {
        (row["Branch_Path"], row["Measure"])
        for row in rows
    }

    assert (
        "Transformation\\CHP interim\\Output Fuels\\Electricity",
        "Output Share",
    ) in paths_by_measure
    assert (
        "Transformation\\CHP interim\\Output Fuels\\Heat",
        "Output Share",
    ) in paths_by_measure
    assert (
        "Transformation\\CHP interim\\Output Fuels\\Electricity",
        "Import Target",
    ) in paths_by_measure
    assert (
        "Transformation\\CHP interim\\Processes\\CHP interim",
        "Historical Production",
    ) in paths_by_measure
    assert (
        "Transformation\\CHP interim\\Processes\\CHP interim",
        "Exogenous Capacity",
    ) in paths_by_measure
    output_share_rows = [
        row for row in rows if row["Measure"] == "Output Share"
    ]
    output_share_values = {
        (
            row["Branch_Path"].rsplit("\\", 1)[-1],
            int(row["Date"]),
        ): float(row["Value"])
        for row in output_share_rows
    }
    assert output_share_values == {
        ("Electricity", 2022): 100.0,
        ("Electricity", 2023): 100.0,
        ("Heat", 2022): 0.0,
        ("Heat", 2023): 0.0,
    }
    assert all(
        sum(
            value
            for (_fuel, row_year), value in output_share_values.items()
            if row_year == year
        )
        == pytest.approx(100.0)
        for year in [2022, 2023]
    )

    zero_energy_measures = {
        "Import Target",
        "Export Target",
        "Exogenous Capacity",
    }
    assert all(
        float(row["Value"]) == 0.0
        for row in rows
        if row["Measure"] in zero_energy_measures
    )
    historical_rows = [
        row for row in rows if row["Measure"] == "Historical Production"
    ]
    assert historical_rows
    assert all(float(row["Value"]) == 0.0 for row in historical_rows)


#%%
