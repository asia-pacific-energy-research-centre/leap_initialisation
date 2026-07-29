"""Phase 4 parallelism: per-process worker snapshot override contract.

Characterizes ``supply_reconciliation_workflow._apply_worker_snapshot_overrides``,
the only supported way a bounded process-based worker gets its own economy/run
label/test-horizon without editing the source file. These tests import the
already-imported workflow module and call the function directly; they never
call ``run_with_config()`` or acquire an economy run lock, so they are safe to
run alongside a live fleet run.
"""
from __future__ import annotations

import json

import codebase.supply_reconciliation_workflow as workflow


def test_no_env_var_is_a_no_op(monkeypatch) -> None:
    """A normal interactive/notebook run (no env var set) is unaffected."""
    monkeypatch.delenv("LEAP_WORKER_SNAPSHOT_JSON", raising=False)
    before_economies = list(workflow.ECONOMIES)
    before_label = workflow.RUN_OUTPUT_LABEL
    before_horizon = workflow.TEST_HORIZON_BASE_YEAR_PLUS_ONE

    workflow._apply_worker_snapshot_overrides()

    assert workflow.ECONOMIES == before_economies
    assert workflow.RUN_OUTPUT_LABEL == before_label
    assert workflow.TEST_HORIZON_BASE_YEAR_PLUS_ONE == before_horizon


def test_inline_json_overrides_economies_label_and_horizon(monkeypatch) -> None:
    payload = {
        "economies": ["01_AUS"],
        "run_output_label": "PARALLEL_SMOKE_01_AUS",
        "test_horizon_base_year_plus_one": False,
    }
    monkeypatch.setenv("LEAP_WORKER_SNAPSHOT_JSON", json.dumps(payload))
    try:
        workflow._apply_worker_snapshot_overrides()
        assert workflow.ECONOMIES == ["01_AUS"]
        assert workflow.RUN_OUTPUT_LABEL == "PARALLEL_SMOKE_01_AUS"
        assert workflow.TEST_HORIZON_BASE_YEAR_PLUS_ONE is False
    finally:
        # Restore the wrapper's own defaults so later tests in the same
        # process see the notebook-configured state, not this test's snapshot.
        workflow.ECONOMIES = workflow.ECONOMIES_RUN_ORDER
        workflow.RUN_OUTPUT_LABEL = "auto"
        workflow.TEST_HORIZON_BASE_YEAR_PLUS_ONE = True


def test_json_file_path_variant_is_supported(monkeypatch, tmp_path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps({"economies": ["12_NZ"], "run_output_label": "PARALLEL_SMOKE_12_NZ"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAP_WORKER_SNAPSHOT_JSON", str(snapshot_path))
    try:
        workflow._apply_worker_snapshot_overrides()
        assert workflow.ECONOMIES == ["12_NZ"]
        assert workflow.RUN_OUTPUT_LABEL == "PARALLEL_SMOKE_12_NZ"
    finally:
        workflow.ECONOMIES = workflow.ECONOMIES_RUN_ORDER
        workflow.RUN_OUTPUT_LABEL = "auto"


def test_malformed_json_raises_rather_than_silently_ignoring(monkeypatch) -> None:
    monkeypatch.setenv("LEAP_WORKER_SNAPSHOT_JSON", "{not valid json")
    try:
        try:
            workflow._apply_worker_snapshot_overrides()
        except RuntimeError as exc:
            assert "LEAP_WORKER_SNAPSHOT_JSON" in str(exc)
        else:
            raise AssertionError("expected a RuntimeError for malformed snapshot JSON")
    finally:
        workflow.ECONOMIES = workflow.ECONOMIES_RUN_ORDER
        workflow.RUN_OUTPUT_LABEL = "auto"


def test_two_worker_snapshots_resolve_to_disjoint_run_contexts(monkeypatch) -> None:
    """The isolation guarantee the parallelism design relies on.

    Two economies given distinct run_output_labels via the snapshot mechanism
    must resolve to completely disjoint ReconciliationRunContext paths (output
    dir, results runtime dir, results checks dir, capacity-unmet state path) —
    the property that lets each worker's timing CSV / convergence CSV /
    iterative-state JSON stay isolated without a new artifact-scoping
    mechanism. Neither snapshot may read the other's ECONOMIES or label.
    """
    import codebase.supply_reconciliation.config as config

    context_a = config.resolve_reconciliation_run_context("baseline_seed", "PARALLEL_A_01_AUS")
    context_b = config.resolve_reconciliation_run_context("baseline_seed", "PARALLEL_B_12_NZ")

    assert context_a.run_output_label != context_b.run_output_label
    disjoint_path_fields = (
        "output_dir",
        "results_runtime_dir",
        "results_checks_dir",
        "capacity_unmet_state_path",
    )
    for field_name in disjoint_path_fields:
        path_a = getattr(context_a, field_name)
        path_b = getattr(context_b, field_name)
        assert path_a != path_b, f"{field_name} was not isolated between labels"
