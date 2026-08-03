"""Tests for the input/output layout a release user works with."""

from pathlib import Path

import pytest

from codebase.portable_release import workspace


def _make_export(directory: Path, name: str) -> Path:
    """Write a minimal but real balance-export workbook."""
    from openpyxl import Workbook

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    book = Workbook()
    sheet = book.active
    sheet.title = "2022"
    sheet["A1"] = 'Energy Balance for Area "Test"'
    sheet["A2"] = "Scenario: Target, Year: 2022, Units: Petajoule"
    sheet["B3"] = "Electricity"
    sheet["A4"] = "Production"
    sheet["A5"] = "  Coal"  # indented child row => Level 2 detail
    sheet["B4"] = 1.0
    book.save(path)
    book.close()
    return path


def test_normalize_economy_folder_accepts_both_forms() -> None:
    assert workspace.normalize_economy_folder("20_USA") == "20_USA"
    assert workspace.normalize_economy_folder("20USA") == "20_USA"
    assert workspace.normalize_economy_folder(" 02_bd ") == "02_BD"


def test_suggested_review_year_prefers_the_base_year() -> None:
    assert workspace._suggested_review_year([2022, 2030, 2060]) == 2022
    # No base year present: offer the earliest, not the horizon end.
    assert workspace._suggested_review_year([2030, 2040, 2060]) == 2030
    assert workspace._suggested_review_year([]) == workspace.DEFAULT_REVIEW_YEAR


def test_discover_reports_scenarios_and_years(tmp_path: Path) -> None:
    root = workspace.balance_exports_root(tmp_path)
    _make_export(root / "20_USA", "full model output all years 03082026 TGT.xlsx")
    _make_export(root / "20_USA", "full model output all years 03082026 REF.xlsx")

    found = workspace.discover_economies(root)
    assert [item.economy for item in found] == ["20_USA"]
    usa = found[0]
    assert usa.scenario_codes == ["REF", "TGT"]
    assert usa.years == [2022]
    assert usa.workbook_for("TGT") is not None
    assert usa.workbook_for("REF") is not None


def test_discover_keeps_economies_separate(tmp_path: Path) -> None:
    root = workspace.balance_exports_root(tmp_path)
    _make_export(root / "20_USA", "full model output all years 03082026 TGT.xlsx")
    _make_export(root / "01_AUS", "full model output all years 04082026 TGT.xlsx")

    found = {item.economy: item for item in workspace.discover_economies(root)}
    assert set(found) == {"01_AUS", "20_USA"}
    assert found["20_USA"].workbook_for("TGT").path.name.endswith("03082026 TGT.xlsx")
    assert found["01_AUS"].workbook_for("TGT").path.name.endswith("04082026 TGT.xlsx")
    # An economy with no REF export simply has no REF entry, not an error.
    assert found["20_USA"].workbook_for("REF") is None


def test_newest_date_wins_and_archive_is_ignored(tmp_path: Path) -> None:
    root = workspace.balance_exports_root(tmp_path)
    economy_dir = root / "20_USA"
    _make_export(economy_dir, "full model output all years 01082026 TGT.xlsx")
    _make_export(economy_dir, "full model output all years 05082026 TGT.xlsx")
    _make_export(economy_dir / "archive", "full model output all years 09082026 TGT.xlsx")

    usa = workspace.discover_economies(root)[0]
    chosen = usa.workbook_for("TGT")
    assert chosen is not None
    # Newest of the two live files, and the newer archived file is not chosen.
    assert chosen.path.name == "full model output all years 05082026 TGT.xlsx"


def test_non_economy_folders_and_files_are_ignored(tmp_path: Path) -> None:
    root = workspace.balance_exports_root(tmp_path)
    _make_export(root / "20_USA", "full model output all years 03082026 TGT.xlsx")
    (root / "README.md").write_text("notes", encoding="utf-8")
    (root / "scratch").mkdir()

    assert [item.economy for item in workspace.discover_economies(root)] == ["20_USA"]


def test_unmatched_workbooks_are_reported_not_silently_dropped(tmp_path: Path) -> None:
    root = workspace.balance_exports_root(tmp_path)
    _make_export(root / "20_USA", "some random name.xlsx")

    usa = workspace.discover_economies(root, read_years=False)[0]
    assert usa.workbooks == []
    assert usa.problems
    assert "none could be matched to a scenario" in usa.problems[0]


def test_describe_workspace_guides_an_empty_folder(tmp_path: Path) -> None:
    text = workspace.describe_workspace(workspace.balance_exports_root(tmp_path))
    assert "does not exist yet" in text
    assert "full model output all years" in text
    assert "Level 2" in text


def test_describe_workspace_lists_runnable_commands(tmp_path: Path) -> None:
    root = workspace.balance_exports_root(tmp_path)
    _make_export(root / "20_USA", "full model output all years 03082026 TGT.xlsx")

    text = workspace.describe_workspace(root)
    assert "20_USA" in text
    assert "balance-review --economy 20_USA --year 2022" in text
    assert "dashboard --economy 20_USA" in text


def test_output_paths_are_per_economy(tmp_path: Path) -> None:
    usa = workspace.economy_output_root(tmp_path, "20USA")
    aus = workspace.economy_output_root(tmp_path, "01_AUS")
    assert usa == tmp_path / "20_USA"
    assert aus == tmp_path / "01_AUS"
    assert usa != aus


def test_input_readme_documents_the_rules_that_matter() -> None:
    text = workspace.INPUT_README
    for expected in ["archive", "Level 2", "newest date", "REF", "TGT", "output/"]:
        assert expected in text
