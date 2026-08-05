"""Tests for codebase.portable_release.mapping_chain_client."""

from __future__ import annotations

import io
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


class _FakeProcess:
    """Stands in for the worker process, yielding stdout a line at a time.

    The client reads the worker's stdout as a stream rather than capturing it
    whole, so a fake has to be iterable to exercise the code that matters.
    """

    def __init__(self, lines: list[str], returncode: int) -> None:
        self.stdin = io.StringIO()
        self.stdout = iter(f"{line}\n" for line in lines)
        self._returncode = returncode

    def wait(self) -> int:
        return self._returncode

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def _fake_worker(monkeypatch, lines: list[str], *, returncode: int = 0) -> None:
    monkeypatch.setattr(
        "codebase.portable_release.mapping_chain_client.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(lines, returncode),
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
    _fake_worker(monkeypatch, [json.dumps({"error": "boom"})], returncode=1)
    context = _developer_context(
        tmp_path, repository_roots={"leap_mappings": tmp_path}
    )

    with pytest.raises(MappingChainError, match="boom"):
        run_mapping_chain(context, {"economy": "12_NZ", "work_dir": str(tmp_path / "w")})


def test_run_mapping_chain_parses_successful_result(tmp_path, monkeypatch):
    _fake_worker(
        monkeypatch,
        [json.dumps({"comparison_data_path": "x.csv", "comparison_rows": 5})],
    )
    context = _developer_context(
        tmp_path, repository_roots={"leap_mappings": tmp_path}
    )

    result = run_mapping_chain(
        context, {"economy": "12_NZ", "work_dir": str(tmp_path / "w")}
    )

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


# ---------------------------------------------------------------------------
# Progress streaming
# ---------------------------------------------------------------------------


def test_worker_steps_are_reported_while_the_run_is_still_going(tmp_path, monkeypatch):
    """The reason for reading the pipe a line at a time.

    Each of these steps takes minutes. Capturing the worker's output whole and
    reporting afterwards would leave the console silent for the entire run,
    which is what made a working run indistinguishable from a hung one.
    """
    from codebase.portable_release import progress

    seen: list[str] = []
    _fake_worker(
        monkeypatch,
        [
            "@@step parse_export",
            "  Parsing 0804 TGT.xlsx ...",
            "@@step convert",
            "@@step compare",
            json.dumps({"comparison_rows": 12}),
        ],
    )
    context = _developer_context(tmp_path, repository_roots={"leap_mappings": tmp_path})

    reporter = progress.ProgressReporter(
        command="probe",
        steps=[progress.Step("parse_export", "Reading")],
        store=None,
        stream=io.StringIO(),
    )
    monkeypatch.setattr(reporter, "begin", seen.append)

    with progress.active(reporter):
        result = run_mapping_chain(
            context, {"economy": "12_NZ", "work_dir": str(tmp_path / "w")}
        )

    assert seen == ["parse_export", "convert", "compare"]
    assert result["comparison_rows"] == 12


def test_progress_lines_are_never_mistaken_for_the_result(tmp_path, monkeypatch):
    """The result is the last line that is not a progress announcement."""
    _fake_worker(
        monkeypatch,
        [json.dumps({"comparison_rows": 7}), "@@step compare"],
    )
    context = _developer_context(tmp_path, repository_roots={"leap_mappings": tmp_path})
    result = run_mapping_chain(
        context, {"economy": "12_NZ", "work_dir": str(tmp_path / "w")}
    )
    assert result["comparison_rows"] == 7


def test_the_worker_log_is_kept_for_support(tmp_path, monkeypatch):
    """Its output used to be discarded, taking the diagnosis with it."""
    from codebase.portable_release.mapping_chain_client import WORKER_LOG_NAME

    _fake_worker(
        monkeypatch,
        ["  Parsing 0804 TGT.xlsx ...", json.dumps({"comparison_rows": 1})],
    )
    context = _developer_context(tmp_path, repository_roots={"leap_mappings": tmp_path})
    work_dir = tmp_path / "w"
    run_mapping_chain(context, {"economy": "12_NZ", "work_dir": str(work_dir)})

    log = (work_dir / WORKER_LOG_NAME).read_text(encoding="utf-8")
    assert "Parsing 0804 TGT.xlsx" in log


def test_a_worker_that_says_nothing_is_reported_as_such(tmp_path, monkeypatch):
    """Progress lines alone are not a result."""
    _fake_worker(monkeypatch, ["@@step parse_export"], returncode=1)
    context = _developer_context(tmp_path, repository_roots={"leap_mappings": tmp_path})
    with pytest.raises(MappingChainError, match="produced no output"):
        run_mapping_chain(context, {"economy": "12_NZ", "work_dir": str(tmp_path / "w")})
