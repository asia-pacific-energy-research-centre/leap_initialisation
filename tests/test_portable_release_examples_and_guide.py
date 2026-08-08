"""Tests for the shipped example exports and the hand-edited user guide.

Both exist so a colleague's first run works and reads well: an example already
in the input folder, and a guide carrying screenshots that no build step is
allowed to overwrite.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codebase.portable_release import build_release, workspace


REPO_ROOT = Path(__file__).resolve().parents[1]


def _export(directory: Path, name: str) -> Path:
    from openpyxl import Workbook

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    book = Workbook()
    sheet = book.active
    sheet.title = "2022"
    sheet["A1"] = 'Energy Balance for Area "Test"'
    sheet["A2"] = "Scenario: Target, Year: 2022, Units: Petajoule"
    sheet["A4"] = "Production"
    book.save(path)
    book.close()
    return path


# ---------------------------------------------------------------------------
# Example exports
# ---------------------------------------------------------------------------


def test_the_newest_export_per_scenario_is_shipped(tmp_path: Path) -> None:
    source = tmp_path / "repo" / build_release.EXAMPLE_EXPORTS_SOURCE
    _export(source / "20_USA", "full model output all years 01082026 TGT.xlsx")
    _export(source / "20_USA", "full model output all years 05082026 TGT.xlsx")
    _export(source / "20_USA", "full model output all years 05082026 REF.xlsx")

    package = tmp_path / "package"
    notes = build_release._seed_example_exports(
        package, {"leap_initialisation": tmp_path / "repo"}, ["20_USA"]
    )

    shipped = sorted(
        p.name
        for p in (package / "input" / workspace.BALANCE_EXPORTS_DIRNAME / "20_USA").glob("*.xlsx")
    )
    assert shipped == [
        "full model output all years 05082026 REF.xlsx",
        "full model output all years 05082026 TGT.xlsx",
    ]
    # The superseded 01082026 file is not shipped.
    assert notes and "20_USA" in notes[0]


def test_an_archived_export_is_never_shipped(tmp_path: Path) -> None:
    """A user's own folder ignores archive/; the example must match."""
    source = tmp_path / "repo" / build_release.EXAMPLE_EXPORTS_SOURCE
    _export(source / "20_USA", "full model output all years 01082026 TGT.xlsx")
    _export(source / "20_USA" / "archive", "full model output all years 09082026 TGT.xlsx")

    package = tmp_path / "package"
    build_release._seed_example_exports(
        package, {"leap_initialisation": tmp_path / "repo"}, ["20_USA"]
    )

    shipped = sorted(
        p.name
        for p in (package / "input" / workspace.BALANCE_EXPORTS_DIRNAME / "20_USA").glob("*.xlsx")
    )
    assert shipped == ["full model output all years 01082026 TGT.xlsx"]


def test_an_economy_with_no_export_is_skipped_quietly(tmp_path: Path) -> None:
    """Most economies have no export yet; that is not a build problem."""
    source = tmp_path / "repo" / build_release.EXAMPLE_EXPORTS_SOURCE
    _export(source / "20_USA", "full model output all years 01082026 TGT.xlsx")

    package = tmp_path / "package"
    notes = build_release._seed_example_exports(
        package, {"leap_initialisation": tmp_path / "repo"}, ["20_USA", "01_AUS"]
    )
    assert not (package / "input" / workspace.BALANCE_EXPORTS_DIRNAME / "01_AUS").exists()
    assert len(notes) == 1 and "20_USA" in notes[0]


def test_a_missing_source_folder_is_reported_not_raised(tmp_path: Path) -> None:
    notes = build_release._seed_example_exports(
        tmp_path / "package", {"leap_initialisation": tmp_path / "absent"}, ["20_USA"]
    )
    assert notes and "does not exist" in notes[0]


def test_shipped_examples_are_discoverable_by_the_tools(tmp_path: Path) -> None:
    """The point of shipping them: the guided flow must see them.

    Copying files into the right folders is worthless if discovery - which
    reads scenario and year out of each workbook - does not pick them up.
    """
    source = tmp_path / "repo" / build_release.EXAMPLE_EXPORTS_SOURCE
    _export(source / "20_USA", "full model output all years 05082026 TGT.xlsx")

    package = tmp_path / "package"
    build_release._seed_example_exports(
        package, {"leap_initialisation": tmp_path / "repo"}, ["20_USA"]
    )

    found = workspace.discover_economies(
        workspace.balance_exports_root(package / "input")
    )
    assert [item.economy for item in found] == ["20_USA"]
    assert found[0].workbooks and found[0].workbooks[0].scenario == "Target"


# ---------------------------------------------------------------------------
# The hand-edited guide
# ---------------------------------------------------------------------------


def test_the_guide_is_excluded_from_docx_regeneration() -> None:
    """Regenerating it from Markdown would throw away the screenshots."""
    source = (REPO_ROOT / "scripts" / "convert_docs.py").read_text(encoding="utf-8")
    assert "HAND_EDITED_DOCX" in source
    assert "leap_review_tools_user_guide.md" in source


def test_the_importer_targets_the_path_the_builder_reads() -> None:
    """A guide imported anywhere else would simply never ship."""
    from scripts import import_user_guide

    expected = REPO_ROOT / build_release.USER_GUIDE_SOURCE_PATH
    assert import_user_guide.REPO_GUIDE == expected
    assert import_user_guide.PACKAGE_GUIDE_NAME == build_release.USER_GUIDE_PACKAGE_NAME


def test_the_master_guide_is_the_one_that_ships_under_the_same_name() -> None:
    """One document, one name, in the repository and in the package.

    Two names invited exactly one failure: editing the file whose name matched
    the package while the builder read a differently-named generated one, and
    shipping the wrong guide with no error anywhere.
    """
    master = REPO_ROOT / build_release.USER_GUIDE_SOURCE_PATH
    assert master.name == build_release.USER_GUIDE_PACKAGE_NAME
    assert master.is_file(), f"the master guide is missing: {master}"


def test_the_superseded_generated_guide_is_gone() -> None:
    """Leaving it behind leaves two files to drift apart."""
    stale = REPO_ROOT / "docs" / "docx" / "leap_review_tools_user_guide.docx"
    assert not stale.exists(), f"still present and no longer built or shipped: {stale}"


def test_importing_an_edited_guide_replaces_the_repository_copy(tmp_path: Path) -> None:
    from scripts import import_user_guide

    repo_copy = tmp_path / "docs" / "docx" / "leap_review_tools_user_guide.docx"
    repo_copy.parent.mkdir(parents=True)
    repo_copy.write_bytes(b"old guide")
    edited = tmp_path / import_user_guide.PACKAGE_GUIDE_NAME
    edited.write_bytes(b"guide with screenshots")

    original = import_user_guide.REPO_GUIDE
    import_user_guide.REPO_GUIDE = repo_copy
    try:
        assert import_user_guide.import_guide(edited) == 0
        assert repo_copy.read_bytes() == b"guide with screenshots"
    finally:
        import_user_guide.REPO_GUIDE = original


def test_check_mode_reports_a_difference_without_making_one(tmp_path: Path) -> None:
    from scripts import import_user_guide

    repo_copy = tmp_path / "guide.docx"
    repo_copy.write_bytes(b"old guide")
    edited = tmp_path / "edited.docx"
    edited.write_bytes(b"new guide")

    original = import_user_guide.REPO_GUIDE
    import_user_guide.REPO_GUIDE = repo_copy
    try:
        assert import_user_guide.import_guide(edited, check_only=True) == 1
        assert repo_copy.read_bytes() == b"old guide"
    finally:
        import_user_guide.REPO_GUIDE = original
