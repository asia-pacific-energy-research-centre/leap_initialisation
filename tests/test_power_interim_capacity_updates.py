"""Regression tests for electricity/CHP/heat capacity adjustment wiring."""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from codebase.functions import supply_leap_io
from codebase.functions import supply_preflight
from codebase.functions import supply_results_saver
from codebase.functions import transformation_record_builder


def _power_record(module: str = "Electricity interim") -> dict:
    return {
        "economy": "20_USA",
        "sector_title": module,
        "process_name": module,
        "output_values": {"Electricity": {2023: 100.0}},
        "feedstock_values": {"Natural gas": {2023: 200.0}},
        "efficiency": {2023: 0.5},
        "exogenous_capacity_by_year": {2023: 100.0},
        "historical_production_by_year": {2023: 100.0},
    }


def test_capacity_catalog_includes_power_interim_records(monkeypatch) -> None:
    power = _power_record()
    monkeypatch.setattr(
        supply_results_saver.electricity_heat_interim_workflow,
        "build_electricity_heat_interim_rows",
        lambda economies: [copy.deepcopy(power)],
    )

    records = supply_results_saver._build_capacity_allocation_process_records(
        [{"economy": "20_USA", "sector_title": "Oil Refining"}],
        economies=["20_USA"],
        include_power_interim=True,
    )

    assert [record["sector_title"] for record in records] == [
        "Oil Refining",
        "Electricity interim",
    ]


def test_power_interim_capacity_addition_updates_exogenous_capacity(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(supply_leap_io, "_use_capacity_like_mode", lambda: True)
    monkeypatch.setattr(supply_leap_io, "_use_legacy_trade_split_mode", lambda: False)
    monkeypatch.setattr(
        supply_leap_io,
        "_leap_export_template_for_economy",
        lambda economy: tmp_path / "usa.xlsx",
    )
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_module_names",
        lambda template_path=None: {"electricity interim"},
    )
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_output_fuel_labels_by_module",
        lambda module_names, template_path=None: {
            "electricity interim": ["Electricity"]
        },
    )
    monkeypatch.setattr(
        supply_leap_io,
        "_lookup_runtime_capacity_additions_for_record",
        lambda **kwargs: {2023: 10.0},
    )

    updated = supply_leap_io.apply_transformation_target_overrides_for_scenario(
        [_power_record()],
        pd.DataFrame(),
        pd.DataFrame(),
        "Reference",
    )[0]

    assert updated["exogenous_capacity_by_year"][2023] == pytest.approx(110.0)
    assert updated["historical_production_by_year"][2023] == pytest.approx(110.0)


def test_power_workbook_builder_receives_scenario_specific_adjusted_records(
    monkeypatch,
    tmp_path,
) -> None:
    base_record = _power_record()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        supply_leap_io.electricity_heat_interim_workflow,
        "build_electricity_heat_interim_rows",
        lambda economies: [copy.deepcopy(base_record)],
    )

    def fake_apply(records, targets, reconciliation, scenario, *, allocation_ledger=None):
        records = copy.deepcopy(records)
        addition = 10.0 if scenario == "Reference" else 20.0
        records[0]["exogenous_capacity_by_year"][2023] += addition
        return records

    monkeypatch.setattr(
        supply_leap_io,
        "apply_transformation_target_overrides_for_scenario",
        fake_apply,
    )

    def fake_assemble(**kwargs):
        captured.update(kwargs)
        return [tmp_path / "power.xlsx"]

    monkeypatch.setattr(
        supply_leap_io.electricity_heat_interim_workflow,
        "assemble_electricity_heat_interim_workbook",
        fake_assemble,
    )
    records_out: dict[str, list[dict]] = {}

    paths = supply_leap_io.build_electricity_heat_interim_workbooks_for_results_supply(
        economies=["20_USA"],
        scenarios=["Reference", "Target"],
        output_dir=tmp_path,
        reconciliation_table=pd.DataFrame(),
        allocation_ledger=object(),
        records_by_scenario_out=records_out,
    )

    by_scenario = captured["process_records_by_scenario"]
    assert paths == [tmp_path / "power.xlsx"]
    assert by_scenario["Reference"][0]["exogenous_capacity_by_year"][2023] == 110.0
    assert by_scenario["Target"][0]["exogenous_capacity_by_year"][2023] == 120.0
    assert records_out["Reference"][0]["exogenous_capacity_by_year"][2023] == 110.0
    assert records_out["Target"][0]["exogenous_capacity_by_year"][2023] == 120.0


def test_shared_transformation_writer_uses_scenario_specific_records(tmp_path) -> None:
    reference_record = _power_record()
    target_record = copy.deepcopy(reference_record)
    target_record["exogenous_capacity_by_year"][2023] = 120.0

    output_path = transformation_record_builder.save_transformation_export(
        process_records=[reference_record],
        region="United States of America",
        base_year=2022,
        final_year=2023,
        code_to_name_mapping={
            "Electricity interim": "Electricity interim",
            "Electricity": "Electricity",
            "Natural gas": "Natural gas",
        },
        output_dir=str(tmp_path),
        output_filename="power_scenario_capacity.xlsx",
        model_name="Test model",
        scenarios=["Reference", "Target"],
        process_records_by_scenario={
            "Reference": [reference_record],
            "Target": [target_record],
        },
    )

    exported = pd.read_excel(output_path, sheet_name="LEAP", header=2)
    capacity = exported[exported["Variable"].eq("Exogenous Capacity")].set_index(
        "Scenario"
    )

    assert "100" in str(capacity.loc["Reference", "Expression"])
    assert "120" in str(capacity.loc["Target", "Expression"])
