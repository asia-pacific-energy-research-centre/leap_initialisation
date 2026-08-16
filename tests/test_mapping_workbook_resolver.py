"""Tests for sibling-first canonical mapping workbook resolution."""
from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
import pytest

from codebase.utilities import mapping_workbook_resolver as resolver


def _write_contract_workbook(path: Path, *, broken: bool = False) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name, columns in resolver.REQUIRED_SHEET_COLUMNS.items():
        sheet = workbook.create_sheet(sheet_name)
        values = list(columns)
        if broken and sheet_name == "leap_combined_esto":
            values.remove("esto_product")
        sheet.append(values)
    workbook.save(path)


def _point_resolver(monkeypatch: pytest.MonkeyPatch, root: Path) -> tuple[Path, Path, Path]:
    live = root / "leap_mappings" / "config" / "outlook_mappings_master.xlsx"
    fallback = root / "leap_initialisation" / "config" / "outlook_mappings_master_DO_NOT_EDIT.xlsx"
    provenance = fallback.with_name("outlook_mappings_master_DO_NOT_EDIT.provenance.json")
    live.parent.mkdir(parents=True)
    fallback.parent.mkdir(parents=True)
    monkeypatch.setattr(resolver, "LIVE_MAPPING_WORKBOOK_PATH", live)
    monkeypatch.setattr(resolver, "FALLBACK_MAPPING_WORKBOOK_PATH", fallback)
    monkeypatch.setattr(resolver, "FALLBACK_PROVENANCE_PATH", provenance)
    monkeypatch.setattr(resolver, "LEAP_MAPPINGS_REPO_ROOT", live.parents[1])
    monkeypatch.setattr(resolver, "_git_commit", lambda path: "abc123")
    return live, fallback, provenance


def _write_provenance(workbook: Path, provenance: Path) -> None:
    provenance.write_text(
        json.dumps(
            {
                "contract_version": resolver.MAPPING_CONTRACT_VERSION,
                "source_repository_commit": "source456",
                "source_path": "leap_mappings/config/outlook_mappings_master.xlsx",
                "workbook_sha256": resolver.sha256_file(workbook),
                "copied_at_utc": "2026-08-16T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )


def test_live_sibling_is_preferred_even_when_fallback_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live, fallback, provenance = _point_resolver(monkeypatch, tmp_path)
    _write_contract_workbook(live)
    _write_contract_workbook(fallback)
    # Make the fallback byte content differ without breaking its workbook schema.
    with fallback.open("ab") as stream:
        stream.write(b"fallback-snapshot")
    _write_provenance(fallback, provenance)

    with pytest.warns(RuntimeWarning, match="differs from the vendored fallback"):
        selection = resolver.resolve_mapping_workbook()

    assert selection.path == live
    assert selection.selected_source == "sibling_live"
    assert selection.source_commit == "abc123"
    assert selection.fallback_refresh_required is True


def test_missing_live_uses_hash_verified_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, fallback, provenance = _point_resolver(monkeypatch, tmp_path)
    _write_contract_workbook(fallback)
    _write_provenance(fallback, provenance)

    selection = resolver.resolve_mapping_workbook()

    assert selection.path == fallback
    assert selection.selected_source == "vendored_fallback"
    assert selection.source_commit == "source456"


def test_broken_present_live_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live, fallback, provenance = _point_resolver(monkeypatch, tmp_path)
    _write_contract_workbook(live, broken=True)
    _write_contract_workbook(fallback)
    _write_provenance(fallback, provenance)

    with pytest.raises(resolver.MappingWorkbookResolutionError, match="esto_product"):
        resolver.resolve_mapping_workbook()


def test_fallback_hash_mismatch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, fallback, provenance = _point_resolver(monkeypatch, tmp_path)
    _write_contract_workbook(fallback)
    _write_provenance(fallback, provenance)
    provenance.write_text(
        provenance.read_text(encoding="utf-8").replace(
            resolver.sha256_file(fallback), "0" * 64
        ),
        encoding="utf-8",
    )

    with pytest.raises(resolver.MappingWorkbookResolutionError, match="hash does not match"):
        resolver.resolve_mapping_workbook()
