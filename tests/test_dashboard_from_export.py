"""Tests for the dashboard-from-export command wiring.

The mapping-chain worker itself is exercised end to end in leap_mappings'
own tests/test_portable_mapping_chain.py (a ~3 minute real run against
12_NZ). Here, mapping_chain_client.run_mapping_chain is mocked to return
that chain's real, already-generated outputs — this test instead proves the
command wires validation, the mocked chain result, and the real dashboard
renderer together correctly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codebase.portable_release import commands, validation
from codebase.portable_release.runtime import RuntimeContext

LEAP_MAPPINGS_ROOT = Path(__file__).resolve().parents[2] / "leap_mappings"
LEAP_DASHBOARD_ROOT = Path(__file__).resolve().parents[2] / "leap_dashboard"
LEAP_INITIALISATION_ROOT = Path(__file__).resolve().parents[1]

EXPORT_DIR = LEAP_INITIALISATION_ROOT / "data" / "leap balances exports" / "12_NZ"
COMPARISON_DATA = LEAP_MAPPINGS_ROOT / "results" / "common_esto" / "common_esto_comparison_data.csv"
COMMON_ROWS = LEAP_MAPPINGS_ROOT / "results" / "common_esto" / "common_esto_rows.csv"
POWER_INTERIM_AUDIT = (
    LEAP_MAPPINGS_ROOT
    / "results"
    / "mapping_relationships"
    / "leap_source_branch_fallback_audit.csv"
)

REQUIRED_PATHS = [
    EXPORT_DIR,
    COMPARISON_DATA,
    COMMON_ROWS,
    LEAP_DASHBOARD_ROOT / "config" / "common_esto_dashboard" / "common_esto_dashboard_template.json",
    LEAP_DASHBOARD_ROOT / "config" / "common_esto_dashboard" / "series_config.json",
    LEAP_DASHBOARD_ROOT / "config" / "common_esto_dashboard" / "code_colors.json",
    LEAP_MAPPINGS_ROOT / "config" / "outlook_mappings_master.xlsx",
    LEAP_MAPPINGS_ROOT / "config" / "source_branch_fallback_rules.csv",
    LEAP_MAPPINGS_ROOT / "config" / "all_demand_aggregated_components.json",
]

pytestmark = pytest.mark.skipif(
    not all(path.exists() for path in REQUIRED_PATHS),
    reason="requires the real 12_NZ export, dashboard config, and mapping config on disk",
)


def _context(tmp_path: Path) -> RuntimeContext:
    return RuntimeContext(
        mode="developer",
        release_name="leap-review-tools",
        release_version="test",
        package_root=tmp_path,
        config_root=tmp_path / "config",
        output_root=tmp_path / "output",
        log_root=tmp_path / "logs",
        input_root=tmp_path / "input",
        sys_path_roots=(LEAP_DASHBOARD_ROOT / "codebase", LEAP_MAPPINGS_ROOT / "codebase"),
        config_assets={
            "dashboard_template": LEAP_DASHBOARD_ROOT
            / "config" / "common_esto_dashboard" / "common_esto_dashboard_template.json",
            "dashboard_series_config": LEAP_DASHBOARD_ROOT
            / "config" / "common_esto_dashboard" / "series_config.json",
            "dashboard_code_colors": LEAP_DASHBOARD_ROOT
            / "config" / "common_esto_dashboard" / "code_colors.json",
            "outlook_mappings_master": LEAP_MAPPINGS_ROOT / "config" / "outlook_mappings_master.xlsx",
            "source_branch_fallback_rules": LEAP_MAPPINGS_ROOT
            / "config" / "source_branch_fallback_rules.csv",
            "all_demand_aggregated_components": LEAP_MAPPINGS_ROOT
            / "config" / "all_demand_aggregated_components.json",
        },
        data_assets={
            "mapping_chain_relationships": LEAP_MAPPINGS_ROOT
            / "results" / "mapping_relationships" / "energy_balance_relationships.csv",
            "mapping_chain_esto_exact_rows": LEAP_MAPPINGS_ROOT
            / "results" / "mapping_relationships" / "esto_results_exact_rows.csv.gz",
            "mapping_chain_ninth_converted": LEAP_MAPPINGS_ROOT
            / "results" / "mapping_relationships" / "ninth_results_converted_to_esto.csv.gz",
            "mapping_chain_common_esto_rows": COMMON_ROWS,
        },
        repository_roots={"leap_mappings": LEAP_MAPPINGS_ROOT},
    )


def test_run_dashboard_from_export_uses_mapping_chain_and_renders(tmp_path, monkeypatch):
    context = _context(tmp_path)
    context.activate_sys_path()

    def _fake_run_mapping_chain(ctx, job):
        assert job["economy"] == "12_NZ"
        assert Path(job["export_dir"]) == EXPORT_DIR
        return {
            "comparison_data_path": str(COMPARISON_DATA),
            "common_rows_path": str(COMMON_ROWS),
            "power_interim_audit_path": str(POWER_INTERIM_AUDIT),
            "raw_leap_rows": 385_035,
            "converted_rows": 48_068,
            "comparison_rows": 194_694,
            "scenarios": ["historical", "reference"],
            "years": [2022],
            "notes": [],
        }

    monkeypatch.setattr(
        "codebase.portable_release.mapping_chain_client.run_mapping_chain",
        _fake_run_mapping_chain,
    )

    result = commands.run_dashboard_from_export(
        context, economy="12_NZ", export_dir=str(EXPORT_DIR)
    )

    assert result.ok, result.error
    assert Path(result.outputs["dashboard_index"]).is_file()
    assert result.outputs["mapping_chain"]["comparison_rows"] == 194_694
    assert result.outputs["power_interim_placeholder_branches"] == [
        "Electricity interim",
        "CHP interim",
    ]


def test_run_dashboard_from_export_escape_hatch_skips_mapping_chain(tmp_path, monkeypatch):
    context = _context(tmp_path)
    context.activate_sys_path()

    def _unexpected_call(*args, **kwargs):
        raise AssertionError("mapping chain must not run when comparison_data_path is supplied")

    monkeypatch.setattr(
        "codebase.portable_release.mapping_chain_client.run_mapping_chain",
        _unexpected_call,
    )

    result = commands.run_dashboard_from_export(
        context,
        economy="12_NZ",
        comparison_data_path=COMPARISON_DATA,
        common_rows_path=COMMON_ROWS,
    )

    assert result.ok, result.error
    assert Path(result.outputs["dashboard_index"]).is_file()


def test_validate_dashboard_from_export_inputs_reports_missing_export_dir(tmp_path):
    report = validation.validate_dashboard_from_export_inputs(
        economy="12_NZ",
        export_dir=tmp_path / "does_not_exist",
        template_path=None,
        series_config_path=None,
        mapping_workbook_path=None,
        source_branch_fallback_rules_path=None,
        all_demand_components_path=None,
        mapping_chain_data_assets={},
    )
    assert not report.ok
    assert "export_dir" in report.failure_message() or "does not exist" in report.failure_message()
