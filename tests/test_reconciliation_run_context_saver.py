"""B3 tests for the explicit run-context boundary at the results saver."""

from __future__ import annotations

from pathlib import Path

import codebase.supply_reconciliation_config as config
import codebase.supply_reconciliation_workflow as workflow
from codebase.functions import supply_results_saver as saver


def test_results_saver_context_paths_match_legacy_path_view(monkeypatch) -> None:
    """A context preserves the exact four paths legacy globals would resolve."""
    context = config.resolve_reconciliation_run_context(
        "baseline_seed",
        "SEED_01_AUS_CONTEXT_TEST",
    )
    monkeypatch.setattr(saver, "OUTPUT_DIR", context.output_dir)
    monkeypatch.setattr(saver, "RESULTS_RUNTIME_DIR", context.results_runtime_dir)
    monkeypatch.setattr(saver, "RESULTS_CHECKS_DIR", context.results_checks_dir)
    monkeypatch.setattr(saver, "CAPACITY_UNMET_STATE_PATH", context.capacity_unmet_state_path)

    legacy_paths = saver._resolve_results_saver_run_paths(None)
    context_paths = saver._resolve_results_saver_run_paths(context)

    assert context_paths == legacy_paths
    assert context_paths["output_dir"] == context.output_dir
    assert context_paths["runtime_dir"] == context.results_runtime_dir
    assert context_paths["checks_dir"] == context.results_checks_dir
    assert context_paths["state_path"] == context.capacity_unmet_state_path


def test_workflow_forwards_current_context_to_results_saver(monkeypatch) -> None:
    """Normal runs cross the B3 boundary without relying on saver globals."""
    context = config.resolve_reconciliation_run_context(
        "baseline_seed",
        "SEED_01_AUS_CONTEXT_FORWARD",
    )
    monkeypatch.setattr(workflow, "ACTIVE_RUN_CONTEXT", context)
    monkeypatch.setattr(workflow, "OUTPUT_DIR", context.output_dir)
    monkeypatch.setattr(workflow, "RESULTS_RUNTIME_DIR", context.results_runtime_dir)
    monkeypatch.setattr(workflow, "RESULTS_CHECKS_DIR", context.results_checks_dir)
    monkeypatch.setattr(workflow, "CAPACITY_UNMET_STATE_PATH", context.capacity_unmet_state_path)
    monkeypatch.setattr(workflow, "_sync_results_saver_overrides", lambda: None)

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        workflow._srs,
        "run_results_linked_transformation_supply_workflow",
        lambda **kwargs: captured.update(kwargs) or {"ok": True},
    )

    assert workflow.run_results_linked_transformation_supply_workflow() == {"ok": True}
    assert captured["run_context"] is context


def test_workflow_uses_legacy_fallback_for_temporary_preflight_paths(monkeypatch) -> None:
    """A direct preflight path override cannot accidentally receive a stale context."""
    context = config.resolve_reconciliation_run_context(
        "baseline_seed",
        "SEED_01_AUS_CONTEXT_STALE",
    )
    monkeypatch.setattr(workflow, "ACTIVE_RUN_CONTEXT", context)
    monkeypatch.setattr(workflow, "OUTPUT_DIR", Path("temporary_preflight_output"))
    monkeypatch.setattr(workflow, "RESULTS_RUNTIME_DIR", context.results_runtime_dir)
    monkeypatch.setattr(workflow, "RESULTS_CHECKS_DIR", context.results_checks_dir)
    monkeypatch.setattr(workflow, "CAPACITY_UNMET_STATE_PATH", context.capacity_unmet_state_path)

    assert workflow._active_run_context_for_results_saver() is None
