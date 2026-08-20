from pathlib import Path

import pytest

from codebase.leap_gui_batch_preflight_workflow import (
    build_batch_register,
    stage_reviewed_clean_slate_files,
    write_batch_register,
)


def _write_seed(root: Path, economy: str) -> Path:
    seed_path = root / "RUN_20260820" / f"leap_import_baseline_seed_{economy}_20260820.xlsx"
    seed_path.parent.mkdir(parents=True)
    seed_path.write_bytes(b"seed")
    return seed_path


def test_register_keeps_clean_slate_and_installed_area_candidates_separate(tmp_path: Path) -> None:
    clean_slates = tmp_path / "clean_slates"
    installed = tmp_path / "installed"
    seed_runs = tmp_path / "seed_runs"
    clean_slates.mkdir()
    installed.mkdir()
    (clean_slates / "AUS clean slate 18_08.leap").write_bytes(b"area")
    (installed / "aus clean slate 18_08").mkdir()
    seed_path = _write_seed(seed_runs, "01_AUS")

    register = build_batch_register(
        ["01_AUS", "02_BD"],
        clean_slate_source=clean_slates,
        installed_areas_root=installed,
        seed_runs_root=seed_runs,
        export_detail_level=4,
    )

    aus_job, bd_job = register["jobs"]
    assert aus_job["status"] == "REQUIRES_OPERATOR_SELECTION"
    assert aus_job["baseline_seed"]["path"] == str(seed_path)
    assert aus_job["area_selection"]["selected_path"] is None
    assert aus_job["area_selection"]["clean_slate_candidates"][0]["name"] == "AUS clean slate 18_08.leap"
    assert aus_job["area_selection"]["installed_area_candidates"][0]["name"] == "aus clean slate 18_08"
    assert aus_job["export"]["wait_policy"] == "POLL_VISIBLE_LEAP_COMPLETION_EVERY_60_MINUTES"
    assert bd_job["status"] == "BLOCKED_SEED_MISSING"


def test_staging_requires_an_explicit_reviewed_clean_slate_selection(tmp_path: Path) -> None:
    clean_slates = tmp_path / "clean_slates"
    installed = tmp_path / "installed"
    seed_runs = tmp_path / "seed_runs"
    clean_slates.mkdir()
    installed.mkdir()
    clean_slate = clean_slates / "AUS clean slate 18_08.leap"
    clean_slate.write_bytes(b"area")
    _write_seed(seed_runs, "01_AUS")
    register = build_batch_register(["01_AUS"], clean_slates, installed, seed_runs)

    assert stage_reviewed_clean_slate_files(register, tmp_path / "staged")["staged_jobs"] == []
    register["jobs"][0]["area_selection"].update(
        {"selected_source": "clean_slate_file", "selected_path": str(clean_slate)}
    )
    result = stage_reviewed_clean_slate_files(register, tmp_path / "staged")
    staged_path = Path(result["staged_jobs"][0]["staged_path"])
    assert staged_path.read_bytes() == b"area"

    with pytest.raises(FileExistsError):
        stage_reviewed_clean_slate_files(register, tmp_path / "staged")


def test_write_register_creates_json_and_review_csv(tmp_path: Path) -> None:
    clean_slates = tmp_path / "clean_slates"
    installed = tmp_path / "installed"
    seed_runs = tmp_path / "seed_runs"
    clean_slates.mkdir()
    installed.mkdir()
    (clean_slates / "AUS clean slate 18_08.leap").write_bytes(b"area")
    _write_seed(seed_runs, "01_AUS")
    register = build_batch_register(["01_AUS"], clean_slates, installed, seed_runs)

    paths = write_batch_register(register, tmp_path / "output")

    assert paths["json_path"].is_file()
    assert "01_AUS" in paths["csv_path"].read_text(encoding="utf-8")
