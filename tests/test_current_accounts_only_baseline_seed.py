"""Regression coverage for a Current Accounts-only baseline-seed run."""

#%%

from codebase.functions import supply_results_saver
from codebase.supply_reconciliation_balance_tables import (
    _balance_export_filename_parts,
    _balance_export_parts_for_scenario,
)


def test_current_accounts_only_baseline_uses_reference_internally(
    monkeypatch,
    tmp_path,
) -> None:
    """The internal balance source must not expand the exported scenario list."""
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        supply_results_saver,
        "_is_capacity_unmet_baseline_seed_pass",
        lambda: True,
    )
    monkeypatch.setattr(
        supply_results_saver,
        "_resolve_results_saver_run_paths",
        lambda run_context: {
            "output_dir": tmp_path / "output",
            "export_dir": tmp_path / "export",
            "transformation_export_dir": tmp_path / "transformation",
            "yearly_balance_dir": tmp_path / "yearly",
            "conventional_balance_dir": tmp_path / "conventional",
            "archive_dir": tmp_path / "archive",
            "runtime_dir": tmp_path / "runtime",
            "checks_dir": tmp_path / "checks",
            "state_path": tmp_path / "state.json",
            "probe_catalog_path": tmp_path / "probe.csv",
        },
    )

    def stop_after_scenario_resolution(*, economies, scenarios, **kwargs):
        captured["economies"] = list(economies)
        captured["balance_scenarios"] = list(scenarios)
        raise RuntimeError("scenario-resolution-test-stop")

    monkeypatch.setattr(
        supply_results_saver,
        "load_balance_demand_inputs",
        stop_after_scenario_resolution,
    )
    monkeypatch.setattr(
        supply_results_saver,
        "archive_config_dir_once_per_day",
        lambda: None,
    )
    monkeypatch.setattr(
        supply_results_saver,
        "TRANSFORMATION_SUPPLY_CACHE_ENABLED",
        False,
    )

    try:
        supply_results_saver.run_results_linked_transformation_supply_workflow(
            economies=["01_AUS"],
            scenario_names=["Current Accounts"],
        )
    except RuntimeError as exc:
        assert str(exc) == "scenario-resolution-test-stop"
    else:
        raise AssertionError("Expected the test stop after scenario resolution.")

    assert captured == {
        "economies": ["01_AUS"],
        "balance_scenarios": ["Reference"],
    }


def test_projection_only_balance_filename_does_not_require_a_workbook(
    monkeypatch,
) -> None:
    """Projection-only baseline tables have no LEAP-export filename provenance."""
    monkeypatch.setattr(
        "codebase.supply_reconciliation_balance_tables.BALANCE_DEMAND_REF_WORKBOOK_PATH",
        None,
    )

    assert _balance_export_filename_parts(None) == (
        "unknown_date",
        "unknown_scenario",
    )
    assert _balance_export_parts_for_scenario("Reference") == (
        "unknown_date",
        "REF",
    )


#%%
