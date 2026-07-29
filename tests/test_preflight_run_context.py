"""Focused B3 contracts for compressed-preflight output contexts."""

from __future__ import annotations

from pathlib import Path

import pytest

from codebase.supply_reconciliation import preflight
import codebase.supply_reconciliation_workflow as workflow


@pytest.mark.parametrize(
    ("mode", "expected_pass_mode"),
    [
        ("projection", "baseline_seed"),
        ("results_update", "results_update"),
    ],
)
def test_preflight_run_context_preserves_special_child_output_layout(
    tmp_path: Path,
    mode: str,
    expected_pass_mode: str,
) -> None:
    """Preflight contexts resolve the historical isolated paths exactly."""
    root = tmp_path / f"preflight_compressed_{mode}"

    context = preflight._build_preflight_run_context(
        preflight_root=root,
        mode=mode,  # type: ignore[arg-type]  # parametrized literals above
    )

    assert context.capacity_unmet_pass_mode == expected_pass_mode
    assert context.run_output_label is None
    assert context.output_dir == root
    assert context.export_output_dir == root / "workbooks"
    assert context.yearly_balance_dir == root / "yearly_balance_tables"
    assert context.conventional_balance_dir == root / "conventional_balance_tables"
    assert context.results_runtime_dir == root / "runtime"
    assert context.results_checks_dir == root / "checks"
    assert context.capacity_unmet_state_path == root / "runtime" / "capacity_unmet_iterative_state.json"


def test_projection_preflight_forwards_its_explicit_context_to_results_saver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Temporary preflight globals cannot make the saver use a stale normal context."""
    preflight_root = tmp_path / "normal_run" / "preflight_compressed_projection"
    source_files = {
        "esto_path": tmp_path / "sources" / "esto.csv",
        "ninth_path": tmp_path / "sources" / "ninth.csv",
        "ninth_abs_diagnostics_path": tmp_path / "sources" / "ninth_abs.csv",
        "base_year": 2022,
        "compressed_year": 2023,
    }
    monkeypatch.setattr(preflight, "OUTPUT_DIR", tmp_path / "normal_run")
    monkeypatch.setattr(preflight, "PREFLIGHT_COMPRESSED_INCLUDE_CURRENT_ACCOUNTS", False)
    monkeypatch.setattr(
        preflight,
        "_create_preflight_compressed_source_files",
        lambda **_kwargs: source_files,
    )
    monkeypatch.setattr(preflight, "_snapshot_preflight_state", lambda: {})
    monkeypatch.setattr(preflight, "_restore_preflight_state", lambda _state: None)
    monkeypatch.setattr(preflight, "_apply_preflight_compressed_state", lambda **_kwargs: [])
    monkeypatch.setattr(workflow, "_sync_results_saver_overrides", lambda: None)

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        workflow._srs,
        "run_results_linked_transformation_supply_workflow",
        lambda **kwargs: captured.update(kwargs) or {"ok": True},
    )

    assert preflight.run_preflight_compressed_projection(
        scenario_names=["Reference"],
    )["ok"] is True

    context = captured["run_context"]
    assert context.output_dir == preflight_root
    assert context.results_runtime_dir == preflight_root / "runtime"
    assert context.results_checks_dir == preflight_root / "checks"
    assert context.capacity_unmet_state_path == (
        preflight_root / "runtime" / "capacity_unmet_iterative_state.json"
    )
