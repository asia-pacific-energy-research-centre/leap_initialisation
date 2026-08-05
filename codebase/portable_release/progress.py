"""Step-by-step progress and a time estimate for long-running commands.

A dashboard run takes minutes, and until now it printed nothing between the
command line and the result. A user watching a still console has no way to tell
a working run from a hung one, and the natural response is to close the window
part-way through - which is exactly what we do not want.

Two things fix that, and both are here:

* **Named steps.** Each command declares its steps up front, so the display can
  say "step 3 of 6" rather than emitting an unbounded stream of lines. Steps
  that happen inside the mapping-chain subprocess are reported by the worker
  over the same stdio channel it already uses (see
  :mod:`codebase.portable_release.mapping_chain_client`).

* **An estimate from real runs.** ``logs/run_timings.json`` keeps the last few
  runs of each command, per step. The remaining time is the sum of the recorded
  medians of the steps not yet done, which degrades sensibly: a machine slower
  than the one that seeded the file converges onto its own timings after a run
  or two, and an unrecognised step simply contributes nothing.

The file ships pre-populated so the very first run on a colleague's machine
still shows an estimate. It is written on every run, so a package on a
read-only share must not fail because of it - every write here is best-effort.

Output is deliberately plain: no ANSI, no cursor movement, no progress bars.
The target is a double-clicked ``cmd.exe`` window, where a carriage-return
animation leaves a mess in the scrollback and in any redirected log.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence


#: Runs kept per command. Enough to absorb one unusually slow run without the
#: estimate chasing it, few enough that a machine change is reflected quickly.
HISTORY_LIMIT = 5

TIMINGS_FILENAME = "run_timings.json"


@dataclass(frozen=True)
class Step:
    """One declared step of a command."""

    key: str
    label: str


def format_duration(seconds: float) -> str:
    """Render a duration the way a person would say it."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, remainder = divmod(int(round(seconds)), 60)
    if minutes < 10:
        return f"{minutes}m {remainder:02d}s"
    # Past ten minutes the seconds are noise, but they must round rather than
    # truncate: 16m40s reads as 17 min, not 16.
    return f"{round(seconds / 60.0)} min"


def format_estimate(seconds: float) -> str:
    """Render an estimate, rounded so it does not imply false precision."""
    seconds = max(0.0, float(seconds))
    if seconds < 45:
        return "under a minute"
    minutes = seconds / 60.0
    if minutes < 10:
        return f"about {round(minutes)} minutes"
    return f"about {int(round(minutes / 5.0) * 5)} minutes"


class TimingStore:
    """Recorded per-step durations for each command.

    Shape on disk::

        {"dashboard-from-export": [{"total": 351.2, "steps": {"parse": 48.1}}]}

    Unknown commands and unknown steps are absent rather than zero, so a
    reader can tell "never measured" from "measured as instant".
    """

    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path is not None else None
        self._runs: dict[str, list[dict]] = {}
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt or unreadable timings file costs an estimate, nothing
            # more. It must never stop a run.
            return
        if isinstance(loaded, dict):
            self._runs = {
                str(key): [item for item in value if isinstance(item, dict)]
                for key, value in loaded.items()
                if isinstance(value, list)
            }

    def step_estimate(self, command: str, step_key: str) -> float | None:
        """Median recorded duration of one step, or ``None`` if never seen."""
        values = [
            float(run["steps"][step_key])
            for run in self._runs.get(command, [])
            if isinstance(run.get("steps"), dict)
            and isinstance(run["steps"].get(step_key), (int, float))
        ]
        return statistics.median(values) if values else None

    def total_estimate(self, command: str) -> float | None:
        """Median recorded wall-clock time for the whole command."""
        values = [
            float(run["total"])
            for run in self._runs.get(command, [])
            if isinstance(run.get("total"), (int, float))
        ]
        return statistics.median(values) if values else None

    def run_count(self, command: str) -> int:
        return len(self._runs.get(command, []))

    def record(self, command: str, total: float, steps: dict[str, float]) -> None:
        """Append a run and rewrite the file, keeping the last few runs."""
        if self.path is None:
            return
        history = list(self._runs.get(command, []))
        history.append({"total": round(float(total), 1),
                        "steps": {k: round(float(v), 1) for k, v in steps.items()}})
        self._runs[command] = history[-HISTORY_LIMIT:]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._runs, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except OSError:
            # Read-only package location, or a locked file. The run itself is
            # unaffected; only the next estimate is slightly staler.
            pass


@dataclass
class ProgressReporter:
    """Prints declared steps as they run, with an estimate of the time left."""

    command: str
    steps: Sequence[Step]
    store: TimingStore | None = None
    stream: object = None
    enabled: bool = True

    _durations: dict[str, float] = field(default_factory=dict, init=False)
    _index: int = field(default=0, init=False)
    _current: Step | None = field(default=None, init=False)
    _started_step: float = field(default=0.0, init=False)
    _started_run: float = field(default=0.0, init=False)
    _line_open: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.stream is None:
            self.stream = sys.stdout

    # -- writing -----------------------------------------------------------

    def _write(self, text: str, *, end: str = "\n") -> None:
        if not self.enabled:
            return
        try:
            print(text, end=end, file=self.stream, flush=True)
        except (OSError, ValueError):
            # A closed or broken stdout must not take the run down with it.
            self.enabled = False

    def note(self, message: str) -> None:
        """Print a message without disturbing an open step line."""
        if self._line_open:
            self._write("")
            self._line_open = False
        self._write(f"      {message}")

    # -- lifecycle ---------------------------------------------------------

    def start(self, subject: str | None = None) -> None:
        self._started_run = time.monotonic()
        if subject:
            self._write(f"\n{subject}")
        estimate = self._remaining_estimate()
        if estimate is not None:
            runs = self.store.run_count(self.command) if self.store else 0
            basis = (
                f" (based on the last {runs} run{'s' if runs != 1 else ''})"
                if runs
                else ""
            )
            self._write(f"This usually takes {format_estimate(estimate)}{basis}.")
        self._write("")

    def begin(self, step_key: str) -> None:
        """Mark the named step as started, closing off the previous one.

        An unknown key is reported rather than ignored: it means a worker and
        this declaration have drifted apart, and silently dropping the step
        would make the count wrong ("step 3 of 6" arriving twice).
        """
        self._close_open_step()
        step = next((item for item in self.steps if item.key == step_key), None)
        if step is None:
            step = Step(key=step_key, label=step_key.replace("_", " ").capitalize())
        self._current = step
        self._index += 1
        self._started_step = time.monotonic()
        label = f"  [{self._index}/{len(self.steps)}] {step.label}"
        self._write(f"{label:<52}", end="")
        self._line_open = True

    def _close_open_step(self) -> None:
        if self._current is None:
            return
        elapsed = time.monotonic() - self._started_step
        self._durations[self._current.key] = elapsed
        remaining = self._remaining_estimate()
        tail = ""
        if remaining is not None and remaining >= 30:
            tail = f"   ({format_estimate(remaining)} left)"
        if not self._line_open:
            # A note interrupted the line; restate which step finished.
            self._write(f"  ... {self._current.label} done in {format_duration(elapsed)}{tail}")
        else:
            self._write(f"done in {format_duration(elapsed):>7}{tail}")
        self._line_open = False
        self._current = None

    def finish(self, *, ok: bool = True) -> None:
        self._close_open_step()
        if not self._started_run:
            return
        total = time.monotonic() - self._started_run
        if ok and self.store is not None:
            self.store.record(self.command, total, self._durations)
        self._write(f"\nFinished in {format_duration(total)}.")

    # -- estimating --------------------------------------------------------

    def _remaining_estimate(self) -> float | None:
        """Sum of the medians of the steps not yet finished."""
        if self.store is None:
            return None
        done = set(self._durations)
        pending = [step for step in self.steps if step.key not in done]
        if not pending:
            return None
        parts = [self.store.step_estimate(self.command, step.key) for step in pending]
        known = [value for value in parts if value is not None]
        if not known:
            # No per-step history: fall back to the whole-command median, which
            # is only meaningful before any step has finished.
            return self.store.total_estimate(self.command) if not done else None
        return sum(known)


# ---------------------------------------------------------------------------
# The reporter in scope for the current command
# ---------------------------------------------------------------------------
#
# The mapping-chain client reports steps from several frames below the command
# function, and the commands themselves are plain functions rather than methods
# on a run object. Threading a reporter through every signature would touch
# every command and the chain client purely to print. This process runs exactly
# one command at a time, so a scoped module global is the smaller cost - but it
# is set only by `active()` below, never assigned directly, so it cannot leak
# past the command that owns it.

_ACTIVE: ProgressReporter | None = None


def current() -> ProgressReporter | None:
    """Return the reporter for the command in progress, if any."""
    return _ACTIVE


@contextmanager
def active(reporter: ProgressReporter | None) -> Iterator[ProgressReporter | None]:
    """Install *reporter* as the current one for the duration of the block."""
    global _ACTIVE
    previous = _ACTIVE
    _ACTIVE = reporter
    try:
        yield reporter
    finally:
        _ACTIVE = previous


def begin_step(step_key: str) -> None:
    """Report a step against the current reporter, if there is one."""
    reporter = current()
    if reporter is not None:
        reporter.begin(step_key)


def note(message: str) -> None:
    """Add a line of detail under the running step, if anyone is listening."""
    reporter = current()
    if reporter is not None:
        reporter.note(message)
