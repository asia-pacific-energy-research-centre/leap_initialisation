from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.create_data_bundle import SOURCE_TABLE_PATHS, create_data_bundle
from scripts.extract_data_bundle import MANIFEST_NAME, extract_data_bundle


def _write(path: Path, content: bytes = b"test data\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _make_source_repo(root: Path) -> None:
    (root / ".git").mkdir(parents=True)
    for relative_path in SOURCE_TABLE_PATHS:
        _write(root / relative_path, relative_path.as_posix().encode("utf-8"))
    _write(root / "data/leap_export_templates/AUS current.xlsx")
    _write(root / "data/leap_export_templates/archive/AUS old.xlsx")
    _write(root / "data/leap balances exports/01_AUS/current.xlsx")
    _write(root / "data/leap balances exports/archive/01_AUS/old.xlsx")
    _write(root / "data/leap balances exports/README.md")


def test_bundle_round_trip_excludes_archives_and_has_no_hash_sidecar(tmp_path: Path) -> None:
    source_repo = tmp_path / "source"
    target_repo = tmp_path / "clone"
    bundle_path = tmp_path / "bundle.zip"
    _make_source_repo(source_repo)
    (target_repo / ".git").mkdir(parents=True)

    create_data_bundle(repo_root=source_repo, bundle_path=bundle_path)

    assert not bundle_path.with_suffix(".sha256").exists()
    with zipfile.ZipFile(bundle_path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read(MANIFEST_NAME))
    assert "data/leap_export_templates/AUS current.xlsx" in names
    assert "data/leap balances exports/01_AUS/current.xlsx" in names
    assert all("archive" not in name.casefold() for name in names)
    assert all("sha256" not in record for record in manifest["files"])

    installed = extract_data_bundle(bundle_path=bundle_path, repo_root=target_repo)
    assert len(installed) == manifest["file_count"]
    assert (target_repo / "data/leap_export_templates/AUS current.xlsx").is_file()
    assert (target_repo / "data/leap balances exports/01_AUS/current.xlsx").is_file()


def test_extraction_refuses_to_replace_different_data_by_default(tmp_path: Path) -> None:
    source_repo = tmp_path / "source"
    target_repo = tmp_path / "clone"
    bundle_path = tmp_path / "bundle.zip"
    _make_source_repo(source_repo)
    (target_repo / ".git").mkdir(parents=True)
    create_data_bundle(repo_root=source_repo, bundle_path=bundle_path)
    extract_data_bundle(bundle_path=bundle_path, repo_root=target_repo)

    (target_repo / SOURCE_TABLE_PATHS[0]).write_text("different", encoding="utf-8")
    with pytest.raises(FileExistsError, match="Refusing to replace"):
        extract_data_bundle(bundle_path=bundle_path, repo_root=target_repo)


def test_extraction_rejects_parent_directory_paths(tmp_path: Path) -> None:
    target_repo = tmp_path / "clone"
    (target_repo / ".git").mkdir(parents=True)
    bundle_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(bundle_path, "w") as archive:
        archive.writestr(MANIFEST_NAME, "{}")
        archive.writestr("../outside.txt", "unsafe")

    with pytest.raises(ValueError, match="Unsafe ZIP member path"):
        extract_data_bundle(bundle_path=bundle_path, repo_root=target_repo)
