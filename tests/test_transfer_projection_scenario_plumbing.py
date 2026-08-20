"""Scenario-specific transfer inputs must remain scenario-specific in reconciliation."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.supply_reconciliation import tables  # noqa: E402


def test_reconciliation_transfer_collection_receives_projection_scenario(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    def fake_transformation_rows(*, economies, projection_scenario):
        seen.append(("transformation", projection_scenario))
        return []

    def fake_transfer_rows(*, economy, use_output_targets, scenario):
        assert economy == "12_NZ"
        assert use_output_targets is False
        seen.append(("transfer", scenario))
        return []

    monkeypatch.setattr(
        tables.transformation_workflow, "collect_transformation_rows", fake_transformation_rows
    )
    monkeypatch.setattr(
        tables.transfers_workflow, "build_transfer_process_records", fake_transfer_rows
    )

    assert tables._collect_transformation_and_transfer_rows(
        economies=["12_NZ"], projection_scenario="target"
    ) == []
    assert seen == [("transformation", "target"), ("transfer", "target")]
