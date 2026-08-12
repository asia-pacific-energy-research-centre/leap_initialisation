from pathlib import Path

import pandas as pd

from codebase.aggregated_demand_workflow import _route_nonenergy_for_template_export
from codebase.supply_reconciliation import template_compatibility


def _write_template(path: Path, branch_paths: set[str]) -> None:
    rows = pd.DataFrame(
        {
            "BranchID": range(1, len(branch_paths) + 1),
            "VariableID": 1,
            "ScenarioID": 1,
            "RegionID": 1,
            "Branch Path": sorted(branch_paths),
            "Variable": "Total Energy",
            "Scenario": "Reference",
            "Region": "Region 1",
        }
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        rows.to_excel(writer, sheet_name="Export", startrow=2, index=False)


def _nonenergy_paths(sector: str) -> set[str]:
    return {
        rf"Demand\All demand aggregated\{sector}\{fuel}"
        for fuel in template_compatibility.NONENERGY_FUELS
    }


def _hydrogen_path(label: str) -> str:
    return (
        r"Transformation\Hydrogen transformation\Processes\Electrolysers"
        rf"\Feedstock Fuels\{label}"
    )


def test_resolver_selects_complete_legacy_destinations(tmp_path: Path) -> None:
    template_path = tmp_path / "template.xlsx"
    _write_template(
        template_path,
        _nonenergy_paths("Other sector") | {_hydrogen_path("Electricity")},
    )

    decision = template_compatibility.resolve_template_compatibility(
        "20_USA",
        template_path,
    )

    assert decision["selected_nonenergy_sector"] == "Other sector"
    assert decision["selected_green_electricity_label"] == "Electricity"
    assert decision["preferred_nonenergy_supported"] is False


def test_resolver_selects_preferred_destinations_independently(tmp_path: Path) -> None:
    template_path = tmp_path / "template.xlsx"
    _write_template(
        template_path,
        _nonenergy_paths("Other sector")
        | {_hydrogen_path("Electricity for hydrogen")},
    )

    decision = template_compatibility.resolve_template_compatibility(
        "16_RUS",
        template_path,
    )

    assert decision["selected_nonenergy_sector"] == "Other sector"
    assert decision["selected_green_electricity_label"] == "Electricity for hydrogen"


def test_resolver_uses_new_behavior_when_complete_preferred_rows_exist(tmp_path: Path) -> None:
    template_path = tmp_path / "template.xlsx"
    _write_template(
        template_path,
        _nonenergy_paths("Non Energy Use")
        | {_hydrogen_path("Electricity for hydrogen")},
    )

    decision = template_compatibility.resolve_template_compatibility(
        "20_USA",
        template_path,
    )

    assert decision["selected_nonenergy_sector"] == "Non Energy Use"
    assert decision["selected_green_electricity_label"] == "Electricity for hydrogen"
    assert decision["preferred_nonenergy_supported"] is True


def test_nonenergy_legacy_route_adds_to_existing_other_sector() -> None:
    demand = pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "sector": "Other sector",
                "leap_fuel_name": "Naphtha",
                "scenario": "Reference",
                "year": 2023,
                "value": 2.0,
            },
            {
                "economy": "20_USA",
                "sector": "Non Energy Use",
                "leap_fuel_name": "Naphtha",
                "scenario": "Reference",
                "year": 2023,
                "value": 5.0,
            },
        ]
    )

    routed = _route_nonenergy_for_template_export(demand, "Other sector")

    assert len(routed) == 1
    assert routed.iloc[0]["sector"] == "Other sector"
    assert routed.iloc[0]["value"] == 7.0


def test_retirement_warning_requires_every_real_template(monkeypatch, tmp_path, capsys) -> None:
    audit_path = tmp_path / "audit.csv"
    pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "preferred_nonenergy_supported": True,
                "preferred_green_electricity_supported": True,
            },
            {
                "economy": "20_USA",
                "preferred_nonenergy_supported": True,
                "preferred_green_electricity_supported": True,
            },
        ]
    ).to_csv(audit_path, index=False)
    monkeypatch.setattr(
        template_compatibility.leap_export_template_resolver,
        "available_template_economies",
        lambda include_provisional=False: ["01_AUS", "20_USA"],
    )

    warned = template_compatibility.warn_if_all_templates_support_preferred(audit_path)

    assert warned is True
    assert "remove the legacy compatibility behavior" in capsys.readouterr().out


def test_retirement_warning_does_not_fire_for_partial_run(monkeypatch, tmp_path, capsys) -> None:
    audit_path = tmp_path / "audit.csv"
    pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "preferred_nonenergy_supported": True,
                "preferred_green_electricity_supported": True,
            }
        ]
    ).to_csv(audit_path, index=False)
    monkeypatch.setattr(
        template_compatibility.leap_export_template_resolver,
        "available_template_economies",
        lambda include_provisional=False: ["01_AUS", "20_USA"],
    )

    warned = template_compatibility.warn_if_all_templates_support_preferred(audit_path)

    assert warned is False
    assert capsys.readouterr().out == ""
