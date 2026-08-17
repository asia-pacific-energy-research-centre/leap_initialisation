"""Regression tests for mixed placeholder and detailed demand dashboards."""

from __future__ import annotations

import json
import sys
from pathlib import Path

MAPPINGS_CODEBASE = Path(__file__).resolve().parents[2] / "leap_mappings" / "codebase"
if str(MAPPINGS_CODEBASE) not in sys.path:
    sys.path.insert(0, str(MAPPINGS_CODEBASE))

from codebase.portable_release import commands


class _Context:
    def __init__(self, components_path: Path) -> None:
        self.components_path = components_path

    def config_asset(self, role: str) -> Path | None:
        if role == "all_demand_aggregated_components":
            return self.components_path
        return None


def _write_components(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "aggregated_branch": "All demand aggregated",
                "components": [
                    {
                        "component_branch": "Road",
                        "detailed_branches": ["Freight road", "Passenger road"],
                        "detail_activation": "all_present",
                        "include_by_default": True,
                        "economy_overrides": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_placeholder_only_audit_keeps_road_marked_missing(tmp_path: Path) -> None:
    components_path = tmp_path / "components.json"
    audit_path = tmp_path / "selection.csv"
    _write_components(components_path)
    audit_path.write_text(
        "economy,component_branch,status\n01_AUS,Road,placeholder_only_retained\n",
        encoding="utf-8",
    )

    missing = commands._missing_leap_demand_branches(
        _Context(components_path), "01_AUS", audit_path
    )

    assert missing == ["Road"]


def test_detailed_audit_makes_road_dashboard_page_available(tmp_path: Path) -> None:
    components_path = tmp_path / "components.json"
    audit_path = tmp_path / "selection.csv"
    _write_components(components_path)
    audit_path.write_text(
        "economy,component_branch,status\n01_AUS,Road,detailed_only_used\n",
        encoding="utf-8",
    )

    missing = commands._missing_leap_demand_branches(
        _Context(components_path), "01_AUS", audit_path
    )

    assert missing == []
