from codebase import supply_reconciliation_workflow as workflow


def test_explicit_results_update_runner_sets_and_restores_scope(monkeypatch) -> None:
    before = {
        "ACTIVE_PRESET": workflow.ACTIVE_PRESET,
        "ECONOMIES": list(workflow.ECONOMIES),
        "SCENARIOS": list(workflow.SCENARIOS),
        "TEST_HORIZON_BASE_YEAR_PLUS_ONE": workflow.TEST_HORIZON_BASE_YEAR_PLUS_ONE,
        "RUN_OUTPUT_LABEL": workflow.RUN_OUTPUT_LABEL,
    }
    observed = {}

    def fake_run_with_config():
        observed.update(
            {
                "ACTIVE_PRESET": workflow.ACTIVE_PRESET,
                "ECONOMIES": list(workflow.ECONOMIES),
                "SCENARIOS": list(workflow.SCENARIOS),
                "TEST_HORIZON_BASE_YEAR_PLUS_ONE": (
                    workflow.TEST_HORIZON_BASE_YEAR_PLUS_ONE
                ),
                "RUN_OUTPUT_LABEL": workflow.RUN_OUTPUT_LABEL,
                "CAPACITY_UNMET_PASS_MODE": workflow.CAPACITY_UNMET_PASS_MODE,
            }
        )
        return {"ok": True}

    monkeypatch.setattr(workflow, "run_with_config", fake_run_with_config)
    result = workflow.run_results_update_with_config(
        economies=["01_AUS"],
        scenarios=["Reference", "Target"],
        update_horizon="full",
        run_output_label="TEST_RESULTS_UPDATE",
    )

    assert result == {"ok": True}
    assert observed == {
        "ACTIVE_PRESET": workflow._PRESET_RESULTS_UPDATE,
        "ECONOMIES": ["01_AUS"],
        "SCENARIOS": ["Reference", "Target"],
        "TEST_HORIZON_BASE_YEAR_PLUS_ONE": False,
        "RUN_OUTPUT_LABEL": "TEST_RESULTS_UPDATE",
        "CAPACITY_UNMET_PASS_MODE": "results_update",
    }
    assert workflow.ACTIVE_PRESET == before["ACTIVE_PRESET"]
    assert workflow.ECONOMIES == before["ECONOMIES"]
    assert workflow.SCENARIOS == before["SCENARIOS"]
    assert (
        workflow.TEST_HORIZON_BASE_YEAR_PLUS_ONE
        == before["TEST_HORIZON_BASE_YEAR_PLUS_ONE"]
    )
    assert workflow.RUN_OUTPUT_LABEL == before["RUN_OUTPUT_LABEL"]
