#%%
"""Regression coverage for signed electricity/CHP/heat source sectors."""

import pandas as pd
import pytest

from codebase import electricity_heat_interim_workflow as workflow


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


def test_no_data_chp_skeleton_emits_output_and_capacity_rows(
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
    zero_measures = {
        "Output Share",
        "Import Target",
        "Export Target",
        "Historical Production",
        "Exogenous Capacity",
    }
    assert all(
        float(row["Value"]) == 0.0
        for row in rows
        if row["Measure"] in zero_measures
    )


#%%
