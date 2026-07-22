"""Tests for the notebook-only two-year full-workflow test horizon."""

from __future__ import annotations

import pytest

from codebase.configuration import workflow_config
from codebase.functions import supply_data_pipeline
from codebase.functions import supply_demand_mapping
from codebase.functions import supply_preflight
from codebase.functions import supply_results_saver
from codebase import aggregated_demand_workflow, other_loss_own_use_proxy_workflow
from codebase import transformation_workflow


def _production_state() -> dict[str, object]:
    """Capture the consumer values whose temporary test horizon must restore."""
    return {
        "saver_final": supply_results_saver.FINAL_YEAR,
        "saver_balance_years": supply_results_saver.BALANCE_EXPORT_YEARS,
        "saver_economies": supply_results_saver.ECONOMIES,
        "saver_output": supply_results_saver.OUTPUT_DIR,
        "mapping_final": supply_demand_mapping.FINAL_YEAR,
        "mapping_projection_years": supply_demand_mapping.DIRECT_DEMAND_PROJECTION_YEARS,
        "pipeline_end": supply_data_pipeline.PROJECTION_END_YEAR,
        "pipeline_years": supply_data_pipeline.PROJECTION_YEAR_RANGE,
        "aggregated_end": aggregated_demand_workflow.PROJECTION_END_YEAR,
        "transformation_end": transformation_workflow.core.EXPORT_FINAL_YEAR,
        "own_use_end": other_loss_own_use_proxy_workflow.EXPORT_FINAL_YEAR,
        "validation_final": workflow_config.BASELINE_SEED_VALIDATION_FINAL_YEAR,
    }


def test_full_workflow_test_horizon_updates_all_year_consumers_and_restores() -> None:
    before = _production_state()
    base_year = int(supply_preflight.BASE_YEAR)
    test_final_year = base_year + 1

    with supply_preflight.full_workflow_test_horizon(enabled=True):
        assert supply_results_saver.FINAL_YEAR == test_final_year
        assert supply_results_saver.BALANCE_EXPORT_YEARS == [base_year, test_final_year]
        assert supply_results_saver.ECONOMIES == before["saver_economies"]
        assert supply_results_saver.OUTPUT_DIR == before["saver_output"]
        assert supply_demand_mapping.FINAL_YEAR == test_final_year
        assert supply_demand_mapping.DIRECT_DEMAND_PROJECTION_YEARS == (test_final_year,)
        assert supply_data_pipeline.PROJECTION_END_YEAR == test_final_year
        assert supply_data_pipeline.PROJECTION_YEAR_RANGE == [test_final_year]
        assert aggregated_demand_workflow.PROJECTION_END_YEAR == test_final_year
        assert transformation_workflow.core.EXPORT_FINAL_YEAR == test_final_year
        assert other_loss_own_use_proxy_workflow.EXPORT_FINAL_YEAR == test_final_year
        assert workflow_config.BASELINE_SEED_VALIDATION_FINAL_YEAR == test_final_year

    assert _production_state() == before


def test_full_workflow_test_horizon_restores_after_workflow_error() -> None:
    before = _production_state()

    with pytest.raises(RuntimeError, match="simulated workflow failure"):
        with supply_preflight.full_workflow_test_horizon(enabled=True):
            raise RuntimeError("simulated workflow failure")

    assert _production_state() == before


def test_full_workflow_test_horizon_disabled_leaves_production_state_unchanged() -> None:
    before = _production_state()

    with supply_preflight.full_workflow_test_horizon(enabled=False):
        assert _production_state() == before

    assert _production_state() == before
