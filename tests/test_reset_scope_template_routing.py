"""Regression tests for economy-specific reset scopes."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from codebase.functions import supply_preflight, supply_reconciliation_tables
from codebase.functions import supply_leap_io


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
        "codebase.functions.supply_results_saver._extract_catalog_rows_from_full_model_export",
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
        "codebase.utilities.leap_export_template_resolver.resolve_leap_export_template",
        lambda economy: templates[str(economy)],
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
