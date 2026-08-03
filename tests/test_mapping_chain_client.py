"""Tests for codebase.portable_release.mapping_chain_client."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from codebase.portable_release.mapping_chain_client import (
    MappingChainError,
    locate_worker,
    run_mapping_chain,
)
from codebase.portable_release.runtime import RuntimeContext

REPO_ROOT = Path(__file__).resolve().parents[1]
LEAP_MAPPINGS_ROOT = REPO_ROOT.parent / "leap_mappings"


def _developer_context(tmp_path: Path, *, repository_roots: dict[str, Path]) -> RuntimeContext:
    return RuntimeContext(
        mode="developer",
        release_name="leap-review-tools",
        release_version="test",
        package_root=tmp_path,
        config_root=tmp_path / "config",
        output_root=tmp_path / "output",
        log_root=tmp_path / "logs",
        input_root=tmp_path / "input",
        repository_roots=repository_roots,
    )


def _portable_context(tmp_path: Path) -> RuntimeContext:
    return RuntimeContext(
        mode="portable",
        release_name="leap-review-tools",
        release_version="test",
        package_root=tmp_path,
        config_root=tmp_path / "config",
        output_root=tmp_path / "output",
        log_root=tmp_path / "logs",
        input_root=tmp_path / "input",
    )


def test_locate_worker_developer_mode_needs_leap_mappings_root(tmp_path):
    context = _developer_context(tmp_path, repository_roots={})
    with pytest.raises(MappingChainError, match="leap_mappings"):
        locate_worker(context)


def test_locate_worker_developer_mode_resolves_module_invocation(tmp_path):
    mappings_root = tmp_path / "leap_mappings"
    mappings_root.mkdir()
    context = _developer_context(tmp_path, repository_roots={"leap_mappings": mappings_root})

    command, cwd = locate_worker(context)

    assert command == [sys.executable, "-m", "codebase.portable_mapping_chain"]
    assert cwd == mappings_root


def test_locate_worker_portable_mode_needs_bundled_exe(tmp_path):
    context = _portable_context(tmp_path)
    with pytest.raises(MappingChainError, match="mapping-chain"):
        locate_worker(context)


def test_run_mapping_chain_surfaces_worker_error(tmp_path, monkeypatch):
    context = _developer_context(
        tmp_path, repository_roots={"leap_mappings": tmp_path}
    )

    class _FakeCompleted:
        returncode = 1
        stdout = json.dumps({"error": "boom"})
        stderr = ""

    monkeypatch.setattr(
        "codebase.portable_release.mapping_chain_client.subprocess.run",
        lambda *args, **kwargs: _FakeCompleted(),
    )

    with pytest.raises(MappingChainError, match="boom"):
        run_mapping_chain(context, {"economy": "12_NZ"})


def test_run_mapping_chain_parses_successful_result(tmp_path, monkeypatch):
    context = _developer_context(
        tmp_path, repository_roots={"leap_mappings": tmp_path}
    )

    class _FakeCompleted:
        returncode = 0
        stdout = json.dumps({"comparison_data_path": "x.csv", "comparison_rows": 5})
        stderr = ""

    monkeypatch.setattr(
        "codebase.portable_release.mapping_chain_client.subprocess.run",
        lambda *args, **kwargs: _FakeCompleted(),
    )

    result = run_mapping_chain(context, {"economy": "12_NZ"})

    assert result["comparison_rows"] == 5


@pytest.mark.skipif(
    not (LEAP_MAPPINGS_ROOT / "codebase" / "portable_mapping_chain.py").is_file(),
    reason="requires a sibling leap_mappings checkout with the worker module",
)
def test_run_mapping_chain_real_worker_process_round_trip(tmp_path):
    """Exercises the real subprocess and JSON protocol, not the chain logic.

    A deliberately incomplete job should come back as a MappingChainError
    carrying the worker's own KeyError text, proving stdin/stdout JSON and
    process launch work end to end without paying for the ~3 minute full
    12_NZ chain run (covered by leap_mappings' own
    tests/test_portable_mapping_chain.py).
    """
    context = _developer_context(
        tmp_path, repository_roots={"leap_mappings": LEAP_MAPPINGS_ROOT}
    )

    with pytest.raises(MappingChainError, match="economy"):
        run_mapping_chain(context, {})
