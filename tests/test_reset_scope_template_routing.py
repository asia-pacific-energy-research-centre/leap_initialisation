"""Regression tests for economy-specific reset scopes."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from codebase.supply_reconciliation import leap_io as supply_leap_io
from codebase.supply_reconciliation import preflight as supply_preflight
from codebase.supply_reconciliation import tables as supply_reconciliation_tables


def test_reset_scope_cache_is_keyed_by_template_source(monkeypatch, tmp_path):
    usa_template = tmp_path / "usa.xlsx"
    nz_template = tmp_path / "nz.xlsx"
    calls: list[Path] = []

    def _catalog_rows(*, source_path, sheet_name):
        calls.append(Path(source_path))
        module = "USA-only module" if Path(source_path) == usa_template else "NZ-only module"
        return [{
            "catalog_type": "transformation", "module_or_root": module,
            "fuel_name": "Fuel", "fuel_group": "Output Fuels",
        }]

    monkeypatch.setattr(supply_preflight, "_RESET_SCOPE_FROM_EXPORT_CACHE", {})
    monkeypatch.setattr(
        "codebase.supply_reconciliation.results_saver._extract_catalog_rows_from_full_model_export",
        _catalog_rows,
    )

    assert supply_preflight._configured_reset_module_names(usa_template) == {"usa-only module"}
    assert supply_preflight._configured_reset_module_names(nz_template) == {"nz-only module"}
    assert supply_preflight._configured_reset_module_names(usa_template) == {"usa-only module"}
    assert calls == [usa_template.resolve(), nz_template.resolve()]


def test_multi_economy_reset_uses_each_economys_template_scope(monkeypatch, tmp_path):
    usa_template = tmp_path / "usa.xlsx"
    nz_template = tmp_path / "nz.xlsx"
    templates = {"20_USA": usa_template, "12_NZ": nz_template}

    monkeypatch.setattr(
        "codebase.utilities.leap_export_template_resolver.resolve_leap_export_template_or_fallback",
        lambda economy, *, fallback: templates[str(economy)],
    )
    monkeypatch.setattr(
        supply_reconciliation_tables,
        "_build_label_to_esto_product_lookup",
        lambda: {"USA fuel": "USA fuel", "NZ fuel": "NZ fuel"},
    )
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_module_names",
        lambda template_path=None: {
            "usa module" if Path(template_path) == usa_template else "nz module"
        },
    )
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_fuel_labels",
        lambda template_path=None: ["USA fuel" if Path(template_path) == usa_template else "NZ fuel"],
    )

    reconciliation = pd.DataFrame({
        "economy": ["20_USA", "12_NZ"], "esto_product": ["USA fuel", "NZ fuel"],
        "year": [2022, 2022], "adjusted_imports": [3.0, 4.0],
    })
    records = [
        {"economy": "20_USA", "sector_title": "USA module", "output_import_targets": {"USA fuel": {2022: 3.0}}},
        {"economy": "12_NZ", "sector_title": "NZ module", "output_import_targets": {"NZ fuel": {2022: 4.0}}},
    ]

    updated_table, updated_records = supply_reconciliation_tables.reset_supply_and_transformation_import_export_to_zero(
        reconciliation, records, economies=["20_USA", "12_NZ"], years=[2022],
    )

    assert updated_table["adjusted_imports"].tolist() == [0.0, 0.0]
    assert updated_records[0]["output_import_targets"]["USA fuel"][2022] == 0.0
    assert updated_records[1]["output_import_targets"]["NZ fuel"][2022] == 0.0


def test_capacity_target_reset_uses_only_template_output_fuels(monkeypatch, tmp_path):
    """Active projection children outside the template must not get target rows."""
    monkeypatch.setattr(supply_leap_io, "_use_capacity_like_mode", lambda: True)
    monkeypatch.setattr(supply_leap_io, "_use_legacy_trade_split_mode", lambda: False)
    monkeypatch.setattr(supply_leap_io, "_leap_export_template_for_economy", lambda economy: tmp_path / "aus.xlsx")
    monkeypatch.setattr(supply_preflight, "_configured_reset_module_names", lambda template_path=None: {"coke ovens"})
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_output_fuel_labels_by_module",
        lambda module_names, template_path=None: {"coke ovens": ["Coke oven coke"]},
    )

    record = {
        "economy": "01_AUS",
        "sector_title": "Coke ovens",
        "process_name": "Coke ovens",
        "output_values": {
            "Coke oven coke": {2024: 10.0},
            "BKB and PB": {2024: 2.0},
        },
    }
    updated = supply_leap_io.apply_transformation_target_overrides_for_scenario(
        [record], pd.DataFrame(), pd.DataFrame(), "Reference",
    )

    assert set(updated[0]["output_import_targets"]) == {"Coke oven coke"}
    assert set(updated[0]["output_export_targets"]) == {"Coke oven coke"}


def test_capacity_target_reset_skips_module_without_template_scope(monkeypatch, tmp_path):
    """An absent module must not create zero-target rows from active outputs."""
    monkeypatch.setattr(supply_leap_io, "_use_capacity_like_mode", lambda: True)
    monkeypatch.setattr(supply_leap_io, "_use_legacy_trade_split_mode", lambda: False)
    monkeypatch.setattr(supply_leap_io, "_leap_export_template_for_economy", lambda economy: tmp_path / "aus.xlsx")
    monkeypatch.setattr(supply_preflight, "_configured_reset_module_names", lambda template_path=None: {"coke ovens"})
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_output_fuel_labels_by_module",
        lambda module_names, template_path=None: {"coke ovens": ["Coke oven coke"]},
    )

    record = {
        "economy": "01_AUS",
        "sector_title": "Liquefaction coal to oil",
        "process_name": "Liquefaction coal to oil",
        "output_values": {"Gas coke": {2024: 2.0}},
    }
    updated = supply_leap_io.apply_transformation_target_overrides_for_scenario(
        [record], pd.DataFrame(), pd.DataFrame(), "Reference",
    )

    assert updated[0]["output_import_targets"] == {}
    assert updated[0]["output_export_targets"] == {}


def test_reset_sector_scope_narrows_reconciliation_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(
        supply_reconciliation_tables,
        "_build_label_to_esto_product_lookup",
        lambda: {"Fuel": "Fuel"},
    )
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_module_names",
        lambda template_path=None: set(),
    )
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_fuel_labels",
        lambda template_path=None: [],
    )
    reconciliation = pd.DataFrame(
        {
            "economy": ["20_USA", "20_USA"],
            "scenario": ["Reference", "Reference"],
            "sector_title": ["Selected module", "Other module"],
            "esto_product": ["Fuel", "Fuel"],
            "year": [2022, 2022],
            "adjusted_imports": [3.0, 4.0],
        }
    )

    updated_table, _ = supply_reconciliation_tables.reset_supply_and_transformation_import_export_to_zero(
        reconciliation,
        economies=["20_USA"],
        sector_titles=["Selected module"],
        esto_products=["Fuel"],
        years=[2022],
        template_path=tmp_path / "scope.xlsx",
    )

    assert updated_table["adjusted_imports"].tolist() == [0.0, 4.0]


def test_aggregate_reset_uses_explicit_fallback_template(monkeypatch, tmp_path):
    fallback = tmp_path / "aggregate_scope.xlsx"
    calls: list[tuple[str, Path]] = []

    def _fallback_resolver(economy, *, fallback):
        calls.append((str(economy), Path(fallback)))
        return fallback

    monkeypatch.setattr(
        "codebase.utilities.leap_export_template_resolver.resolve_leap_export_template_or_fallback",
        _fallback_resolver,
    )
    monkeypatch.setattr(
        supply_reconciliation_tables,
        "RESULTS_VERIFICATION_EXPORT_PATH",
        fallback,
    )
    monkeypatch.setattr(
        supply_reconciliation_tables,
        "_build_label_to_esto_product_lookup",
        lambda: {"Fuel": "Fuel"},
    )
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_module_names",
        lambda template_path=None: set(),
    )
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_fuel_labels",
        lambda template_path=None: [],
    )
    reconciliation = pd.DataFrame(
        {
            "economy": ["00_APEC"],
            "scenario": ["Reference"],
            "esto_product": ["Fuel"],
            "year": [2022],
            "adjusted_imports": [3.0],
        }
    )

    updated_table, _ = supply_reconciliation_tables.reset_supply_and_transformation_import_export_to_zero(
        reconciliation,
        economies=["00_APEC"],
        esto_products=["Fuel"],
        years=[2022],
    )

    assert calls == [("00_APEC", fallback)]
    assert updated_table["adjusted_imports"].tolist() == [0.0]


def test_demand_zeroing_resolves_template_per_economy(monkeypatch, tmp_path):
    templates = {"20_USA": tmp_path / "usa.xlsx", "12_NZ": tmp_path / "nz.xlsx"}
    calls: list[tuple[Path, Path]] = []

    monkeypatch.setattr(supply_leap_io, "_leap_export_template_for_economy", lambda economy: templates[economy])
    monkeypatch.setattr(
        "codebase.aggregated_demand_workflow.save_demand_zeroing_workbook",
        lambda *, output_path, source_path, **kwargs: calls.append((Path(output_path), Path(source_path))) or Path(output_path),
    )

    paths = supply_leap_io.build_other_demand_zeroing_workbooks(
        scenarios=["Reference"], economies=["20_USA", "12_NZ"], output_dir=tmp_path,
    )

    assert [source for _, source in calls] == [templates["20_USA"], templates["12_NZ"]]
    assert [path.name for path in paths] == ["demand_zeroing_20_USA.xlsx", "demand_zeroing_12_NZ.xlsx"]


def test_supply_transformation_zeroing_skips_aggregate_before_template_resolution(
    monkeypatch, tmp_path, capsys,
):
    """00_APEC preflight must not inspect member-area templates or write an import."""
    calls: list[str] = []

    monkeypatch.setattr(
        supply_leap_io,
        "_leap_export_template_for_economy",
        lambda economy: calls.append(str(economy)) or tmp_path / "should_not_be_used.xlsx",
    )
    monkeypatch.setattr(
        supply_leap_io.pd,
        "read_excel",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("template must not be read")),
    )

    paths = supply_leap_io.build_supply_transformation_zeroing_workbooks(
        scenarios=["Reference"], economies=["00_APEC"], output_dir=tmp_path / "zeroing",
    )

    assert paths == []
    assert calls == []
    assert not (tmp_path / "zeroing").exists()
    assert "Skipping supply/transformation zeroing workbook for aggregate economy 00_APEC" in capsys.readouterr().out


def test_supply_transformation_zeroing_still_writes_real_economy_workbook(monkeypatch, tmp_path):
    template = tmp_path / "usa_template.xlsx"
    calls: list[str] = []
    raw = pd.DataFrame(
        [
            ["LEAP export"],
            ["Branch Path", "Variable", "Scenario", "Scale", "Units", "Per..."],
            ["Resources\\Crude oil", "Imports", "Reference", "PJ", "PJ", "Year"],
        ]
    )

    monkeypatch.setattr(
        supply_leap_io,
        "_leap_export_template_for_economy",
        lambda economy: calls.append(str(economy)) or template,
    )
    monkeypatch.setattr(supply_leap_io.pd, "read_excel", lambda *args, **kwargs: raw)

    paths = supply_leap_io.build_supply_transformation_zeroing_workbooks(
        scenarios=["Reference"], economies=["20_USA"], output_dir=tmp_path / "zeroing",
    )

    assert calls == ["20_USA"]
    assert [path.name for path in paths] == ["supply_transformation_zeroing_20_USA.xlsx"]
    assert paths[0].exists()


def test_supply_transformation_zeroing_ignores_unused_duplicate_blank_headers(monkeypatch, tmp_path):
    """USA's legacy template has repeated blank trailing headers."""
    template = tmp_path / "usa_template.xlsx"
    raw = pd.DataFrame(
        [
            ["LEAP export", None, None, None, None, None, None, None],
            ["Branch Path", "Variable", "Scenario", "Scale", "Units", "Per...", None, None],
            ["Resources\\Crude oil", "Imports", "Reference", "PJ", "PJ", "Year", None, None],
        ]
    )

    monkeypatch.setattr(supply_leap_io, "_leap_export_template_for_economy", lambda economy: template)
    monkeypatch.setattr(supply_leap_io.pd, "read_excel", lambda *args, **kwargs: raw)

    paths = supply_leap_io.build_supply_transformation_zeroing_workbooks(
        scenarios=["Reference"], economies=["20_USA"], output_dir=tmp_path / "zeroing",
    )

    assert [path.name for path in paths] == ["supply_transformation_zeroing_20_USA.xlsx"]
