"""Regression tests: the exported Region must follow the economy being written.

A single-economy run must never inherit another economy's region. Before this
was routed, the aggregated-demand writer, the other-loss/own-use proxy, and the
demand-zeroing writer all resolved their id_lookup template per economy but took
Region from the global GLOBAL_REGION default ("United States"). A 12_NZ run
therefore emitted New Zealand data labelled Region='United States', whose IDs
then failed to resolve and landed as BranchID=-1.
"""

from __future__ import annotations

import inspect

import pytest

import codebase.aggregated_demand_workflow as aggregated_demand_workflow
import codebase.other_loss_own_use_proxy_workflow as other_loss_own_use_proxy_workflow
from codebase.functions import supply_leap_io

EXPECTED_REGIONS = {
    "12_NZ": "New Zealand",
    "20_USA": "United States",
    "01_AUS": "Australia",
    "05_PRC": "China",
}


@pytest.mark.parametrize("economy,expected", sorted(EXPECTED_REGIONS.items()))
@pytest.mark.parametrize(
    "module",
    [aggregated_demand_workflow, other_loss_own_use_proxy_workflow],
    ids=["aggregated_demand", "own_use_proxy"],
)
def test_export_region_follows_economy(module, economy, expected):
    assert module._resolve_export_region(economy) == expected


@pytest.mark.parametrize(
    "module",
    [aggregated_demand_workflow, other_loss_own_use_proxy_workflow],
    ids=["aggregated_demand", "own_use_proxy"],
)
def test_unresolvable_economy_falls_back_rather_than_raising(module):
    fallback = getattr(module, "EXPORT_REGION", None) or module.DEFAULT_EXPORT_REGION
    assert module._resolve_export_region("99_NOT_AN_ECONOMY") == fallback


def test_aggregate_sentinel_keeps_its_global_region():
    """00_APEC has no region of its own; the preflight relies on this fallback."""
    assert aggregated_demand_workflow._resolve_export_region("00_APEC") == "United States"


@pytest.mark.parametrize(
    "func",
    [
        aggregated_demand_workflow.save_aggregated_demand_as_leap_workbook,
        other_loss_own_use_proxy_workflow.assemble_proxy_workbook,
        supply_leap_io.build_aggregated_demand_workbooks_for_results_supply,
        supply_leap_io.build_other_demand_zeroing_workbooks,
    ],
    ids=["save_agg_demand", "assemble_proxy", "build_agg_demand", "build_zeroing"],
)
def test_region_defaults_to_per_economy_resolution(func):
    """A non-None default would silently pin every economy to one region."""
    assert inspect.signature(func).parameters["region"].default is None


def test_zeroing_writer_resolves_region_per_economy_in_loop(monkeypatch, tmp_path):
    """Each economy in one multi-economy call gets its own region."""
    seen: list[tuple[str, str]] = []

    def _fake_save_demand_zeroing_workbook(*, output_path, region, **kwargs):
        seen.append((output_path.stem, region))
        return output_path

    monkeypatch.setattr(
        "codebase.aggregated_demand_workflow.save_demand_zeroing_workbook",
        _fake_save_demand_zeroing_workbook,
    )
    monkeypatch.setattr(
        supply_leap_io, "_leap_export_template_for_economy", lambda economy: tmp_path / f"{economy}.xlsx"
    )

    supply_leap_io.build_other_demand_zeroing_workbooks(
        scenarios=["Reference"],
        economies=["20_USA", "01_AUS", "05_PRC"],
        output_dir=tmp_path,
    )

    assert [region for _, region in seen] == ["United States", "Australia", "China"]
