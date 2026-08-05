"""Tests for the progress display and its time estimate.

The behaviour under test is what a user sees while waiting: that a long run
says what it is doing, and that the estimate comes from real runs rather than a
guess baked into the code.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from codebase.portable_release import progress


def _reporter(tmp_path: Path, steps, command="probe"):
    stream = io.StringIO()
    store = progress.TimingStore(tmp_path / progress.TIMINGS_FILENAME)
    reporter = progress.ProgressReporter(
        command=command, steps=steps, store=store, stream=stream
    )
    return reporter, stream, store


STEPS = [
    progress.Step("validate", "Checking your files"),
    progress.Step("convert", "Converting"),
    progress.Step("render", "Drawing the charts"),
]


# ---------------------------------------------------------------------------
# What the user sees
# ---------------------------------------------------------------------------


def test_each_step_is_announced_as_it_starts(tmp_path: Path) -> None:
    reporter, stream, _ = _reporter(tmp_path, STEPS)
    reporter.start("Building the dashboard for 20USA.")
    for key in ("validate", "convert", "render"):
        reporter.begin(key)
    reporter.finish()

    text = stream.getvalue()
    assert "Building the dashboard for 20USA." in text
    assert "[1/3] Checking your files" in text
    assert "[2/3] Converting" in text
    assert "[3/3] Drawing the charts" in text
    assert "Finished in" in text


def test_a_step_is_announced_before_it_runs_not_after(tmp_path: Path) -> None:
    """The whole point: the line appears while the user is waiting.

    A display that only prints a step once it is over tells the user nothing
    during the minutes that matter, which is the bug this replaced.
    """
    reporter, stream, _ = _reporter(tmp_path, STEPS)
    reporter.start()
    reporter.begin("validate")
    assert "Checking your files" in stream.getvalue()


def test_the_display_carries_no_ansi_or_carriage_returns(tmp_path: Path) -> None:
    """It has to read correctly in a double-clicked cmd.exe and in a log file."""
    reporter, stream, _ = _reporter(tmp_path, STEPS)
    reporter.start("Subject.")
    reporter.begin("validate")
    reporter.note("something worth saying")
    reporter.begin("convert")
    reporter.finish()
    text = stream.getvalue()
    assert "\x1b" not in text
    assert "\r" not in text


def test_a_note_does_not_corrupt_the_open_step_line(tmp_path: Path) -> None:
    reporter, stream, _ = _reporter(tmp_path, STEPS)
    reporter.start()
    reporter.begin("validate")
    reporter.note("17,675 rows had no map")
    reporter.begin("convert")
    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    # The note is on its own line, and the step it interrupted still reports.
    assert any("17,675 rows had no map" in line for line in lines)
    assert any("Checking your files done in" in line for line in lines)


def test_an_undeclared_step_is_still_shown(tmp_path: Path) -> None:
    """Drift between the worker and this declaration must not hide a step."""
    reporter, stream, _ = _reporter(tmp_path, STEPS)
    reporter.start()
    reporter.begin("esto_rows")
    assert "Esto rows" in stream.getvalue()


def test_a_broken_stream_does_not_stop_the_run(tmp_path: Path) -> None:
    class Closed(io.StringIO):
        def write(self, _text):  # noqa: ANN001
            raise ValueError("I/O operation on closed file")

    store = progress.TimingStore(tmp_path / progress.TIMINGS_FILENAME)
    reporter = progress.ProgressReporter(
        command="probe", steps=STEPS, store=store, stream=Closed()
    )
    reporter.start("Subject.")
    reporter.begin("validate")
    reporter.finish()  # must not raise


# ---------------------------------------------------------------------------
# The estimate
# ---------------------------------------------------------------------------


def test_the_first_run_records_its_timings(tmp_path: Path) -> None:
    reporter, _, store = _reporter(tmp_path, STEPS)
    reporter.start()
    for key in ("validate", "convert", "render"):
        reporter.begin(key)
    reporter.finish()

    saved = json.loads((tmp_path / progress.TIMINGS_FILENAME).read_text(encoding="utf-8"))
    assert set(saved["probe"][0]["steps"]) == {"validate", "convert", "render"}
    assert saved["probe"][0]["total"] >= 0


def test_a_failed_run_is_not_recorded(tmp_path: Path) -> None:
    """A run that died part-way would drag every later estimate down."""
    reporter, _, _ = _reporter(tmp_path, STEPS)
    reporter.start()
    reporter.begin("validate")
    reporter.finish(ok=False)
    assert not (tmp_path / progress.TIMINGS_FILENAME).exists()


def test_only_the_last_few_runs_are_kept(tmp_path: Path) -> None:
    store = progress.TimingStore(tmp_path / progress.TIMINGS_FILENAME)
    for index in range(progress.HISTORY_LIMIT + 4):
        store.record("probe", total=float(index), steps={"convert": float(index)})
    saved = json.loads((tmp_path / progress.TIMINGS_FILENAME).read_text(encoding="utf-8"))
    assert len(saved["probe"]) == progress.HISTORY_LIMIT
    # The oldest were dropped, not the newest.
    assert saved["probe"][-1]["total"] == float(progress.HISTORY_LIMIT + 3)


def test_the_estimate_is_the_median_of_recorded_runs(tmp_path: Path) -> None:
    store = progress.TimingStore(tmp_path / progress.TIMINGS_FILENAME)
    for total in (100.0, 120.0, 900.0):  # one outlier
        store.record("probe", total=total, steps={"convert": total})
    # The median ignores the outlier; a mean would not.
    assert store.total_estimate("probe") == 120.0
    assert store.step_estimate("probe", "convert") == 120.0


def test_remaining_time_counts_only_the_steps_left(tmp_path: Path) -> None:
    store = progress.TimingStore(tmp_path / progress.TIMINGS_FILENAME)
    store.record(
        "probe",
        total=300.0,
        steps={"validate": 10.0, "convert": 200.0, "render": 90.0},
    )
    reporter = progress.ProgressReporter(
        command="probe", steps=STEPS, store=store, stream=io.StringIO()
    )
    assert reporter._remaining_estimate() == pytest.approx(300.0)
    reporter.start()
    reporter.begin("validate")
    reporter.begin("convert")  # closes validate
    assert reporter._remaining_estimate() == pytest.approx(290.0)


def test_a_never_measured_command_offers_no_estimate(tmp_path: Path) -> None:
    """Silence is right here: a made-up number is worse than none."""
    reporter, stream, _ = _reporter(tmp_path, STEPS, command="never-run")
    reporter.start("Subject.")
    assert "usually takes" not in stream.getvalue()


def test_a_corrupt_timings_file_costs_an_estimate_not_the_run(tmp_path: Path) -> None:
    path = tmp_path / progress.TIMINGS_FILENAME
    path.write_text("{not json", encoding="utf-8")
    store = progress.TimingStore(path)
    assert store.total_estimate("probe") is None
    store.record("probe", total=5.0, steps={})  # recovers by overwriting
    assert store.total_estimate("probe") == 5.0


def test_a_read_only_location_does_not_fail_a_run(tmp_path: Path) -> None:
    """A package on a read-only share still has to run."""
    store = progress.TimingStore(tmp_path / "nested" / progress.TIMINGS_FILENAME)
    directory = tmp_path / "nested"
    directory.mkdir()
    directory.chmod(0o500)
    try:
        store.record("probe", total=1.0, steps={})  # must not raise
    finally:
        directory.chmod(0o700)


def test_no_store_means_no_estimate_and_no_crash(tmp_path: Path) -> None:
    reporter = progress.ProgressReporter(
        command="probe", steps=STEPS, store=None, stream=io.StringIO()
    )
    reporter.start("Subject.")
    reporter.begin("validate")
    reporter.finish()


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "under a minute"), (30, "under a minute"), (100, "about 2 minutes"),
     (350, "about 6 minutes"), (1000, "about 15 minutes")],
)
def test_estimates_are_rounded_not_precise(seconds: int, expected: str) -> None:
    """'about 6 minutes' is honest; '5 minutes 52 seconds' is not."""
    assert progress.format_estimate(seconds) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [(2, "2s"), (48, "48s"), (95, "1m 35s"), (1000, "17 min")],
)
def test_durations_read_the_way_a_person_says_them(seconds: int, expected: str) -> None:
    assert progress.format_duration(seconds) == expected


# ---------------------------------------------------------------------------
# The scoped current reporter
# ---------------------------------------------------------------------------


def test_the_active_reporter_does_not_leak_past_its_command(tmp_path: Path) -> None:
    reporter, _, _ = _reporter(tmp_path, STEPS)
    assert progress.current() is None
    with progress.active(reporter):
        assert progress.current() is reporter
    assert progress.current() is None


def test_the_active_reporter_is_restored_after_a_failure(tmp_path: Path) -> None:
    reporter, _, _ = _reporter(tmp_path, STEPS)
    with pytest.raises(RuntimeError):
        with progress.active(reporter):
            raise RuntimeError("boom")
    assert progress.current() is None


def test_reporting_with_no_active_reporter_is_a_no_op() -> None:
    progress.begin_step("convert")  # must not raise
    progress.note("something")


# ---------------------------------------------------------------------------
# The cross-repository protocol
# ---------------------------------------------------------------------------

WORKER_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "leap_mappings"
    / "codebase"
    / "portable_mapping_chain.py"
)


@pytest.mark.skipif(not WORKER_SOURCE.is_file(), reason="leap_mappings checkout not present")
def test_the_worker_and_the_client_agree_on_the_progress_prefix() -> None:
    """The two live in repositories that cannot import each other.

    Nothing at runtime would notice them drifting apart: a changed prefix
    turns every progress line into an unrecognised payload line, and the
    result JSON stops being the last one - so the run fails with "output was
    not valid JSON" rather than with anything that names the real cause.
    """
    from codebase.portable_release import mapping_chain_client

    source = WORKER_SOURCE.read_text(encoding="utf-8")
    declared = re.search(r'^PROGRESS_PREFIX = "([^"]*)"', source, re.M)
    assert declared, "the worker no longer declares PROGRESS_PREFIX"
    assert declared.group(1) == mapping_chain_client.PROGRESS_PREFIX


@pytest.mark.skipif(not WORKER_SOURCE.is_file(), reason="leap_mappings checkout not present")
def test_every_step_the_worker_announces_is_declared_by_a_command() -> None:
    """Otherwise the display shows a step key instead of a sentence."""
    from codebase.portable_release import commands

    source = WORKER_SOURCE.read_text(encoding="utf-8")
    announced = set(re.findall(r'report_step\("([^"]+)"\)', source))
    declared = {step.key for step in commands._CHAIN_STEPS}
    declared |= {commands._VALIDATE_STEP.key, commands._ESTO_ROWS_STEP.key}
    assert announced <= declared, f"undeclared worker steps: {sorted(announced - declared)}"
