"""The standalone producer entry points must resolve their own economy's template.

`transformation_workflow`, `transfers_workflow` and `electricity_heat_interim_workflow`
each defaulted `id_lookup_path` to `EXPORT_ID_LOOKUP_PATH` (20_USA's area), so a
standalone run for any other economy stamped USA BranchIDs onto its rows. That was
dormant only while every template was COMP_GEN-copied from USA; `01_AUS` and
`12_NZ` are real areas now, so it bites.

These tests assert the *default* (`id_lookup_path=None`) path specifically. Tests
that pin the template exercise the override branch and cannot catch a pinning bug
-- that is exactly how `073c489` stayed a production no-op for a day with a green
suite.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import codebase.aggregated_demand_workflow as aggregated_demand
import codebase.electricity_heat_interim_workflow as elec_heat
import codebase.transfers_workflow as transfers
import codebase.transformation_workflow as transformation

MODULES = {
    "transformation": transformation,
    "transfers": transfers,
    "electricity_heat_interim": elec_heat,
}


@pytest.mark.parametrize("name,module", sorted(MODULES.items()))
def test_no_entry_point_defaults_to_the_pinned_export(name, module):
    """A pinned default is the bug. None means 'resolve from the economy'."""
    pinned = module.EXPORT_ID_LOOKUP_PATH
    offenders = []
    for attr in dir(module):
        func = getattr(module, attr)
        if not callable(func) or not hasattr(func, "__module__"):
            continue
        if getattr(func, "__module__", None) != module.__name__:
            continue
        try:
            params = inspect.signature(func).parameters
        except (TypeError, ValueError):
            continue
        param = params.get("id_lookup_path")
        if param is not None and param.default == pinned:
            offenders.append(attr)
    assert not offenders, (
        f"{name}: these entry points still default id_lookup_path to the pinned "
        f"export instead of None: {offenders}"
    )


@pytest.mark.parametrize("name,module", sorted(MODULES.items()))
def test_pinned_constant_is_only_a_fallback(name, module):
    """The constant must survive as the aggregate/no-template fallback."""
    assert module.EXPORT_ID_LOOKUP_PATH.name == "leap_export_template 20_USA.xlsx"


@pytest.mark.parametrize(
    "func",
    [
        aggregated_demand.save_aggregated_demand_as_leap_workbook,
        aggregated_demand.main,
    ],
    ids=["save_aggregated_demand", "main"],
)
def test_aggregated_demand_id_lookup_defaults_to_auto_not_the_pinned_export(func):
    """These take `economy`, so the default must resolve it -- not pin 20_USA.

    patch_baseline_seeds calls save_aggregated_demand_as_leap_workbook WITHOUT
    id_lookup_path, so a pinned default wrote USA BranchIDs into a non-USA
    economy's baseline seed.
    """
    default = inspect.signature(func).parameters["id_lookup_path"].default
    assert default == aggregated_demand.ID_LOOKUP_AUTO
    assert default != aggregated_demand.FULL_MODEL_EXPORT_PATH


def test_aggregated_demand_auto_resolves_the_economys_own_template():
    for economy in ("12_NZ", "01_AUS", "20_USA"):
        resolved = aggregated_demand._resolve_export_id_lookup(economy)
        assert economy in resolved.name, f"{economy} resolved to {resolved.name}"


def test_aggregated_demand_auto_falls_back_for_aggregate_sentinels():
    resolved = aggregated_demand._resolve_export_id_lookup("00_APEC")
    assert resolved == aggregated_demand.FULL_MODEL_EXPORT_PATH


def test_aggregated_demand_none_still_means_skip_the_id_merge():
    """None and "auto" are different instructions. Conflating them would turn a
    deliberate skip into a lookup, or a lookup into a silent skip."""
    assert aggregated_demand.ID_LOOKUP_AUTO is not None
    assert aggregated_demand.ID_LOOKUP_AUTO != aggregated_demand.FULL_MODEL_EXPORT_PATH


def test_electricity_heat_resolves_each_economy_in_a_multi_economy_call(monkeypatch, tmp_path):
    """This writer loops economies and writes one workbook each, so resolving
    once outside the loop would stamp the first economy's IDs on all of them."""
    seen: list[object] = []

    def _fake_resolver(economy, *, fallback, **kwargs):
        seen.append(economy)
        return Path(fallback)

    monkeypatch.setattr(
        elec_heat.leap_export_template_resolver,
        "resolve_leap_export_template_or_fallback",
        _fake_resolver,
    )
    monkeypatch.setattr(elec_heat, "validate_power_interim_fuel_coverage", lambda **kw: None)
    monkeypatch.setattr(elec_heat, "build_interim_branch_catalog", lambda: None)
    monkeypatch.setattr(
        elec_heat, "build_electricity_heat_interim_rows",
        lambda economies=None: [{"economy": economies[0]}],
    )
    monkeypatch.setattr(elec_heat.core, "consolidate_transformation_output_rows", lambda *a, **k: None)
    monkeypatch.setattr(elec_heat.core, "save_transformation_export", lambda *a, **k: None)

    elec_heat.assemble_electricity_heat_interim_workbook(
        economies=["12_NZ", "01_AUS", "05_PRC"],
        scenarios=["Reference"],
        export_output_dir=tmp_path,
    )

    assert seen == ["12_NZ", "01_AUS", "05_PRC"], (
        f"each economy must resolve its own template; resolver saw {seen!r}"
    )


def test_electricity_heat_explicit_path_still_bypasses_the_resolver(monkeypatch, tmp_path):
    """An explicit id_lookup_path is honoured, for callers that genuinely span areas."""

    def _explode(economy, *, fallback, **kwargs):
        raise AssertionError(f"resolver must not be consulted; got {economy!r}")

    monkeypatch.setattr(
        elec_heat.leap_export_template_resolver,
        "resolve_leap_export_template_or_fallback",
        _explode,
    )
    monkeypatch.setattr(elec_heat, "validate_power_interim_fuel_coverage", lambda **kw: None)
    monkeypatch.setattr(elec_heat, "build_interim_branch_catalog", lambda: None)
    monkeypatch.setattr(
        elec_heat, "build_electricity_heat_interim_rows",
        lambda economies=None: [{"economy": economies[0]}],
    )
    monkeypatch.setattr(elec_heat.core, "consolidate_transformation_output_rows", lambda *a, **k: None)

    captured: list[object] = []

    def _capture(*args, **kwargs):
        captured.append(kwargs.get("id_lookup_path"))
        return None

    monkeypatch.setattr(elec_heat.core, "save_transformation_export", _capture)

    explicit = tmp_path / "explicit.xlsx"
    elec_heat.assemble_electricity_heat_interim_workbook(
        economies=["12_NZ"],
        scenarios=["Reference"],
        export_output_dir=tmp_path,
        id_lookup_path=explicit,
    )

    assert captured == [explicit]
