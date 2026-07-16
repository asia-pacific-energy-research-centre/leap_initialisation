"""Tests for per-economy LEAP export template resolution."""

#%%

import pandas as pd
import pytest

from codebase.utilities.leap_export_template_resolver import (
    available_template_economies,
    find_leap_export_template,
    find_shared_template_areas,
    is_aggregate_economy,
    is_provisional_template,
    provisional_template_economies,
    read_leap_export_template_area,
    reset_provisional_template_warnings,
    resolve_leap_export_template,
)


@pytest.fixture(autouse=True)
def _clear_warning_state():
    reset_provisional_template_warnings()
    yield
    reset_provisional_template_warnings()


def _write_template(root, economy, *, area="Some area"):
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"leap_export_template {economy}.xlsx"
    preamble = pd.DataFrame(
        [
            [None, None, None, None, "Area:", area, "Ver:", 2],
            [None] * 8,
            ["BranchID", "VariableID", "ScenarioID", "RegionID", "Branch Path", "Variable", "Scenario", "Region"],
        ]
    )
    with pd.ExcelWriter(path) as writer:
        preamble.to_excel(writer, sheet_name="Export", header=False, index=False)
    return path


def test_resolves_template_for_economy(tmp_path):
    expected = _write_template(tmp_path, "20_USA")

    assert resolve_leap_export_template("20_USA", templates_root=tmp_path) == expected


def test_resolution_is_case_insensitive_and_strips_whitespace(tmp_path):
    expected = _write_template(tmp_path, "01_AUS")

    assert resolve_leap_export_template(" 01_aus ", templates_root=tmp_path) == expected


def test_missing_template_raises_instead_of_borrowing_another_economy(tmp_path):
    _write_template(tmp_path, "20_USA")

    with pytest.raises(FileNotFoundError) as excinfo:
        resolve_leap_export_template("01_AUS", templates_root=tmp_path)

    message = str(excinfo.value)
    assert "01_AUS" in message
    # The available list must not read as a suggested substitute.
    assert "20_USA" in message
    assert "Do not copy another economy's template" in message


def test_empty_templates_root_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_leap_export_template("20_USA", templates_root=tmp_path)


def test_aggregate_sentinels_have_no_template(tmp_path):
    _write_template(tmp_path, "20_USA")

    for sentinel in ("00_APEC", "ALL_ECONOMIES", "ALL"):
        assert is_aggregate_economy(sentinel)
        with pytest.raises(ValueError, match="aggregate sentinel"):
            resolve_leap_export_template(sentinel, templates_root=tmp_path)


def test_blank_economy_raises(tmp_path):
    with pytest.raises(ValueError, match="cannot be blank"):
        resolve_leap_export_template("  ", templates_root=tmp_path)


def test_available_template_economies_ignores_unrelated_and_lock_files(tmp_path):
    _write_template(tmp_path, "20_USA")
    _write_template(tmp_path, "01_AUS")
    (tmp_path / "~$leap_export_template 09_ROK.xlsx").write_text("lock")
    (tmp_path / "notes.xlsx").write_text("unrelated")

    assert available_template_economies(tmp_path) == ["01_AUS", "20_USA"]


def test_find_shared_template_areas_detects_copied_template(tmp_path):
    _write_template(tmp_path, "20_USA", area="USA clean slate 15_07")
    _write_template(tmp_path, "01_AUS", area="USA clean slate 15_07")
    _write_template(tmp_path, "09_ROK", area="ROK area")

    assert find_shared_template_areas(tmp_path) == {
        "USA clean slate 15_07": ["01_AUS", "20_USA"]
    }


def test_find_shared_template_areas_empty_when_areas_distinct(tmp_path):
    _write_template(tmp_path, "20_USA", area="USA area")
    _write_template(tmp_path, "01_AUS", area="AUS area")

    assert find_shared_template_areas(tmp_path) == {}


def test_read_area_from_real_usa_template():
    path = resolve_leap_export_template("20_USA")

    assert read_leap_export_template_area(path) == "USA clean slate 15_07"


def test_provisional_template_resolves_and_reports_economy_without_marker(tmp_path):
    expected = _write_template(tmp_path, "01_AUS_COMP_GEN")

    template = find_leap_export_template("01_AUS", templates_root=tmp_path)

    assert template.path == expected
    assert template.economy == "01_AUS"
    assert template.is_provisional
    assert available_template_economies(tmp_path) == ["01_AUS"]
    assert available_template_economies(tmp_path, include_provisional=False) == []


def test_using_a_provisional_template_warns_once_per_economy(tmp_path, capsys):
    _write_template(tmp_path, "01_AUS_COMP_GEN")

    resolve_leap_export_template("01_AUS", templates_root=tmp_path)
    first = capsys.readouterr().out
    assert "[WARN]" in first
    assert "COMP_GEN" in first
    assert "01_AUS" in first

    resolve_leap_export_template("01_AUS", templates_root=tmp_path)
    assert capsys.readouterr().out == ""


def test_final_template_supersedes_provisional_and_does_not_warn(tmp_path, capsys):
    _write_template(tmp_path, "12_NZ_COMP_GEN", area="USA clean slate 15_07")
    final = _write_template(tmp_path, "12_NZ", area="nz clean slate 16_07")

    path = resolve_leap_export_template("12_NZ", templates_root=tmp_path)

    assert path == final
    assert not find_leap_export_template("12_NZ", templates_root=tmp_path).is_provisional
    assert capsys.readouterr().out == ""
    assert provisional_template_economies(tmp_path) == []


def test_final_template_does_not_warn(tmp_path, capsys):
    _write_template(tmp_path, "20_USA")

    resolve_leap_export_template("20_USA", templates_root=tmp_path)

    assert capsys.readouterr().out == ""


def test_is_provisional_template_reads_the_filename_marker(tmp_path):
    assert is_provisional_template("leap_export_template 01_AUS_COMP_GEN.xlsx")
    assert not is_provisional_template("leap_export_template 20_USA.xlsx")


def test_shared_area_ignores_provisional_but_flags_copied_final_templates(tmp_path):
    # Provisional templates all share the source area by definition.
    _write_template(tmp_path, "01_AUS_COMP_GEN", area="USA clean slate 15_07")
    _write_template(tmp_path, "02_BD_COMP_GEN", area="USA clean slate 15_07")
    _write_template(tmp_path, "20_USA", area="USA clean slate 15_07")

    assert find_shared_template_areas(tmp_path) == {}

    # But a final template sharing another final template's area is a copy.
    _write_template(tmp_path, "03_CDA", area="USA clean slate 15_07")

    assert find_shared_template_areas(tmp_path) == {
        "USA clean slate 15_07": ["03_CDA", "20_USA"]
    }


def test_every_configured_economy_has_a_template():
    """Every economy the workflows run must resolve, or its export routes to another area."""
    from codebase.configuration.workflow_config import GLOBAL_ECONOMIES

    available = set(available_template_economies())
    missing = [economy for economy in GLOBAL_ECONOMIES if economy not in available]

    assert not missing, f"No LEAP export template for: {missing}"


def test_no_two_final_templates_claim_the_same_leap_area():
    """A final template sharing another's area name was copied, not exported.

    Provisional (COMP_GEN) templates are exempt by construction — sharing the
    source area is what being provisional means.
    """
    shared = find_shared_template_areas()

    assert not shared, (
        "Final templates share a LEAP area, so one was copied rather than exported "
        f"from its own area: {shared}"
    )


def test_finalized_economies_resolve_to_a_non_provisional_template():
    """Guards the rollout deadline.

    Economies whose real export has landed must not silently fall back to a
    provisional copy of another area. This list only grows; when an economy is
    finalized, add it here. The moment any economy is finalized, the un-routed
    code paths in docs/work_queue.md [7] start disagreeing with the routed ones
    about which LEAP area they are in.
    """
    finalized = {"12_NZ", "20_USA", "01_AUS"}

    still_provisional = sorted(
        economy
        for economy in finalized
        if find_leap_export_template(economy).is_provisional
    )

    assert not still_provisional, (
        f"Expected a real export for {still_provisional}, but resolved a COMP_GEN copy."
    )
