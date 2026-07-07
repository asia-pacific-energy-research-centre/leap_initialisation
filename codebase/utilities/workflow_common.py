from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

import pandas as pd

from codebase.functions.leap_core import (
    connect_to_leap,
    create_branches_from_export_file,
    fill_branches_from_export_file,
)
from codebase.functions.analysis_input_write_dispatcher import (
    dispatch_analysis_input_write,
)
from codebase.utilities import fuel_catalog_preflight

AGGREGATE_ECONOMY_LABELS = {"00_APEC", "ALL_ECONOMIES", "ALL"}
REPO_ROOT = Path(__file__).resolve().parents[2]


_TIMING_HISTORY_KEEP = 20


# ---------------------------------------------------------------------------
# Deferred-error registry (THROW_ERROR_AFTER_RUN)
# ---------------------------------------------------------------------------
# Long unattended multi-economy/multi-scenario runs (e.g. an overnight
# baseline-seed run across 21 economies x 3 scenarios) should not be aborted
# partway through by a single economy's data problem. When THROW_ERROR_AFTER_RUN
# is enabled, call sites that would normally `raise` should instead call
# `defer_or_raise()`: it prints a loud [WARN] immediately (so a human or agent
# monitoring the log can judge whether the deferred issue is fatal to the
# output) and records the exception, letting the run continue. The top-level
# entry point (supply_reconciliation_workflow.run_with_config) calls
# `raise_deferred_errors()` once ALL economies and scenarios have finished, so
# the run still fails loudly overall -- just not before producing output.
#
# When THROW_ERROR_AFTER_RUN is False (the default), defer_or_raise() raises
# immediately, matching prior behavior exactly.
THROW_ERROR_AFTER_RUN = False
_DEFERRED_ERRORS: list[tuple[str, Exception]] = []


def clear_deferred_errors() -> None:
    """Reset the deferred-error registry. Call once at the start of a run."""
    _DEFERRED_ERRORS.clear()


def get_deferred_errors() -> list[tuple[str, Exception]]:
    """Return the (context, exception) pairs recorded so far this run."""
    return list(_DEFERRED_ERRORS)


def defer_or_raise(exc: Exception, *, context: str) -> None:
    """Raise ``exc`` immediately, unless THROW_ERROR_AFTER_RUN is enabled.

    When deferred, prints a `[WARN]` with ``context`` and the exception so the
    problem is visible in logs at the time it happened, then records it for
    `raise_deferred_errors()` to surface once the full run completes.
    """
    if not THROW_ERROR_AFTER_RUN:
        raise exc
    print(
        f"[WARN] Deferred error ({context}) — continuing because "
        f"THROW_ERROR_AFTER_RUN=True. Review this before trusting the output: "
        f"{exc!r}"
    )
    _DEFERRED_ERRORS.append((context, exc))


def raise_deferred_errors() -> None:
    """Raise an aggregated error if any were deferred this run; otherwise no-op.

    Call once after ALL economies and ALL scenarios have finished processing.
    """
    if not _DEFERRED_ERRORS:
        return
    summary = "; ".join(f"[{context}] {exc!r}" for context, exc in _DEFERRED_ERRORS)
    count = len(_DEFERRED_ERRORS)
    raise RuntimeError(
        f"{count} error(s) were deferred via THROW_ERROR_AFTER_RUN and the run "
        f"completed anyway. Review outputs for the affected economies/scenarios "
        f"before trusting them. Deferred errors: {summary}"
    ) from _DEFERRED_ERRORS[0][1]


def _detect_git_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "nocommit"
    except Exception:
        return "nocommit"


def _encode_history_stem(
    stem: str,
    started_at: datetime,
    n_economies: int | None,
    n_scenarios: int | None,
    run_type: str,
    commit: str,
) -> str:
    stamp = started_at.strftime("%Y%m%d_%H%M%S")
    econ_seg = f"e{n_economies}" if n_economies is not None else "eX"
    scen_seg = f"s{n_scenarios}" if n_scenarios is not None else "sX"
    return f"{stem}_{stamp}_{econ_seg}_{scen_seg}_{run_type}_{commit}"


def _parse_history_filename(filename: str) -> dict:
    """Parse metadata encoded in a history filename."""
    stem = filename[:-4] if filename.endswith(".csv") else filename
    pattern = r"^(.+)_(\d{8})_(\d{6})_(e\d+|eX)_(s\d+|sX)_([^_]+)_([a-f0-9]{7}|nocommit)$"
    m = re.match(pattern, stem)
    if not m:
        return {}
    econ_seg, scen_seg = m.group(4), m.group(5)
    return {
        "base_stem": m.group(1),
        "started_at": f"{m.group(2)}_{m.group(3)}",
        "n_economies": int(econ_seg[1:]) if econ_seg != "eX" else None,
        "n_scenarios": int(scen_seg[1:]) if scen_seg != "sX" else None,
        "run_type": m.group(6),
        "commit": m.group(7),
    }


def format_duration(seconds: float) -> str:
    """Return a compact human-readable duration string."""
    total_seconds = max(float(seconds), 0.0)
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    secs = total_seconds - (hours * 3600) - (minutes * 60)
    return f"{hours}h {minutes}m {secs:.1f}s"


class WorkflowTimer:
    """Small stage timer for notebook-safe workflow scripts."""

    def __init__(
        self,
        workflow_name: str,
        *,
        enabled: bool = True,
        print_each: bool = True,
    ) -> None:
        self.workflow_name = str(workflow_name).strip() or "workflow"
        self.enabled = bool(enabled)
        self.print_each = bool(print_each)
        self.started_at = datetime.now()
        self._last_at = self.started_at
        self._start_perf = time.perf_counter()
        self._last_perf = self._start_perf
        self._records: list[dict[str, object]] = []
        self._commit: str = _detect_git_commit(REPO_ROOT)
        self._n_economies: int | None = None
        self._n_scenarios: int | None = None
        self._run_type: str = "full"

    def set_metadata(
        self,
        *,
        economies: list | None = None,
        scenarios: list | None = None,
        run_type: str | None = None,
    ) -> None:
        """Record economy/scenario counts and run type for history filtering."""
        if economies is not None:
            self._n_economies = len(list(economies))
        if scenarios is not None:
            self._n_scenarios = len(list(scenarios))
        if run_type is not None:
            self._run_type = str(run_type)

    @property
    def records(self) -> list[dict[str, object]]:
        return list(self._records)

    def lap(self, stage: str, *, status: str = "success") -> dict[str, object]:
        """Record elapsed time since the previous lap."""
        if not self.enabled:
            return {}
        now_perf = time.perf_counter()
        now = datetime.now()
        duration = now_perf - self._last_perf
        stage_started_at = self._last_at
        self._last_perf = now_perf
        self._last_at = now
        record = {
            "workflow": self.workflow_name,
            "stage_order": len(self._records) + 1,
            "stage": str(stage).strip() or "stage",
            "status": str(status).strip() or "success",
            "started_at": stage_started_at.isoformat(timespec="seconds"),
            "ended_at": now.isoformat(timespec="seconds"),
            "duration_seconds": round(duration, 3),
            "duration_formatted": format_duration(duration),
        }
        self._records.append(record)
        if self.print_each:
            print(
                "[TIMING] "
                f"{self.workflow_name} | {record['stage']} | "
                f"{record['duration_formatted']}"
            )
        return record

    def finish(self, *, status: str = "success") -> dict[str, object]:
        """Record total workflow runtime."""
        if not self.enabled:
            return {}
        now = datetime.now()
        duration = time.perf_counter() - self._start_perf
        record = {
            "workflow": self.workflow_name,
            "stage_order": len(self._records) + 1,
            "stage": "total",
            "status": str(status).strip() or "success",
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "ended_at": now.isoformat(timespec="seconds"),
            "duration_seconds": round(duration, 3),
            "duration_formatted": format_duration(duration),
        }
        self._records.append(record)
        if self.print_each:
            print(
                "[TIMING] "
                f"{self.workflow_name} | total | {record['duration_formatted']}"
            )
        return record

    def write_csv(self, path: Path | str) -> Path | None:
        """Write timing records to CSV and return the path."""
        if not self.enabled or not self._records:
            return None
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(self._records)
        df.to_csv(output_path, index=False)
        history_dir = output_path.parent / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        history_stem = _encode_history_stem(
            output_path.stem, self.started_at,
            self._n_economies, self._n_scenarios,
            self._run_type, self._commit,
        )
        history_path = history_dir / f"{history_stem}{output_path.suffix}"
        df.to_csv(history_path, index=False)
        old_files = sorted(history_dir.glob(f"{output_path.stem}_*{output_path.suffix}"))
        for old_file in old_files[:-_TIMING_HISTORY_KEEP]:
            try:
                old_file.unlink()
            except Exception:
                pass
        if self.print_each:
            print(f"[TIMING] {self.workflow_name} timing written to {output_path}")
        return output_path


def load_history_summary(
    path: Path | str,
    *,
    n_economies: int | None = None,
    n_scenarios: int | None = None,
    run_type: str = "full",
    current_commit: str | None = None,
) -> pd.DataFrame | None:
    """
    Average past timing runs from the history folder, with outlier removal.

    Filters to runs matching ``run_type``, ``n_economies``, and ``n_scenarios``.
    If any history file exists for the current git commit it restricts to those
    runs only, ignoring older commits (so a major refactor starts a fresh baseline).
    Per-stage IQR outlier removal is applied before averaging (needs >=4 runs).

    Returns a DataFrame with columns: stage, stage_order, avg_duration_seconds,
    avg_duration_formatted, n_runs.  Returns None if no matching history exists.

    To reset timing expectations after a commit that heavily changes runtime,
    delete files from the ``history/`` subdirectory next to the timing CSV.
    """
    path = Path(path)
    history_dir = path.parent / "history"
    if not history_dir.exists():
        return None
    if current_commit is None:
        current_commit = _detect_git_commit(REPO_ROOT)
    all_files = sorted(history_dir.glob(f"{path.stem}_*.csv"))
    candidates: list[tuple[Path, dict]] = []
    for f in all_files:
        meta = _parse_history_filename(f.name)
        if not meta:
            continue
        if meta.get("run_type") != run_type:
            continue
        if n_economies is not None and meta.get("n_economies") != n_economies:
            continue
        if n_scenarios is not None and meta.get("n_scenarios") != n_scenarios:
            continue
        candidates.append((f, meta))
    if not candidates:
        return None
    if current_commit and current_commit != "nocommit":
        commit_matches = [(f, m) for f, m in candidates if m.get("commit") == current_commit]
        if commit_matches:
            candidates = commit_matches
    dfs: list[pd.DataFrame] = []
    for f, meta in candidates:
        try:
            df = pd.read_csv(f)
            df["_commit"] = meta.get("commit", "")
            dfs.append(df)
        except Exception:
            continue
    if not dfs:
        return None
    combined = pd.concat(dfs, ignore_index=True)
    combined = combined[(combined["stage"] != "total") & (combined["status"] == "success")]
    rows: list[dict] = []
    for (stage, order), group in combined.groupby(["stage", "stage_order"]):
        durations = group["duration_seconds"].dropna()
        if len(durations) >= 4:
            q1, q3 = durations.quantile(0.25), durations.quantile(0.75)
            iqr = q3 - q1
            durations = durations[(durations >= q1 - 1.5 * iqr) & (durations <= q3 + 1.5 * iqr)]
        avg = float(durations.mean())
        rows.append({
            "stage_order": int(order),
            "stage": stage,
            "avg_duration_seconds": round(avg, 1),
            "avg_duration_formatted": format_duration(avg),
            "n_runs": len(durations),
        })
    if not rows:
        return None
    return pd.DataFrame(rows).sort_values("stage_order").reset_index(drop=True)


def emit_completion_beep(
    *,
    success: bool = True,
    style: str = "simple",
    enabled: bool = True,
    count: int = 1,
    frequency_hz: int = 880,
    duration_ms: int = 180,
    pause_seconds: float = 0.12,
) -> None:
    """Emit an audible completion signal (winsound, notebook audio, terminal bell)."""
    if not bool(enabled):
        return

    count = max(int(count), 1)
    frequency = max(int(frequency_hz), 37)
    duration = max(int(duration_ms), 50)
    pause_seconds = max(float(pause_seconds), 0.0)
    if not success:
        count = max(count, 2)
        frequency = max(frequency - 180, 37)
        if style == "chime":
            style = "error"

    if style == "chime":
        tone_plan = [(659, 90), (784, 90), (988, 140)]  # E5, G5, B5
        gap_ms = 40
    elif style == "error":
        tone_plan = [(440, 140), (330, 180)]  # A4 -> E4 (descending)
        gap_ms = 60
    else:
        tone_plan = [(frequency, duration)] * count
        gap_ms = int(pause_seconds * 1000)

    try:
        import winsound  # type: ignore

        for index, (freq_hz, tone_duration_ms) in enumerate(tone_plan):
            try:
                winsound.Beep(max(int(freq_hz), 37), max(int(tone_duration_ms), 50))
            except Exception:
                winsound.MessageBeep()
            if gap_ms > 0 and index < len(tone_plan) - 1:
                time.sleep(gap_ms / 1000.0)
        return
    except Exception:
        pass

    try:
        from IPython import get_ipython  # type: ignore
        from IPython.display import Javascript, display  # type: ignore

        ip = get_ipython()
        shell_name = type(ip).__name__ if ip is not None else ""
        if shell_name == "ZMQInteractiveShell":
            tones_js = ", ".join(
                f"{{freq: {max(int(freq_hz), 37)}, durMs: {max(int(tone_duration_ms), 50)}}}"
                for freq_hz, tone_duration_ms in tone_plan
            )
            js = f"""
            (() => {{
              const AudioCtx = window.AudioContext || window.webkitAudioContext;
              if (!AudioCtx) return;
              const tones = [{tones_js}];
              const gapMs = {int(gap_ms)};
              const playOne = (delayMs, freq, durMs) => {{
                setTimeout(() => {{
                  const ctx = new AudioCtx();
                  const osc = ctx.createOscillator();
                  const gain = ctx.createGain();
                  osc.type = "sine";
                  osc.frequency.value = freq;
                  gain.gain.value = 0.045;
                  osc.connect(gain);
                  gain.connect(ctx.destination);
                  osc.start();
                  osc.stop(ctx.currentTime + (durMs / 1000));
                  osc.onended = () => ctx.close();
                }}, delayMs);
              }};
              let cursor = 0;
              for (const tone of tones) {{
                playOne(cursor, tone.freq, tone.durMs);
                cursor += tone.durMs + gapMs;
              }}
            }})();
            """
            display(Javascript(js))
            return
    except Exception:
        pass

    for index, _ in enumerate(tone_plan):
        print("\a", end="", flush=True)
        if gap_ms > 0 and index < len(tone_plan) - 1:
            time.sleep(gap_ms / 1000.0)
    print("", flush=True)


def archive_config_dir_once_per_day(
    config_dir: Path | None = None,
    archive_root: Path | None = None,
    *,
    today: date | None = None,
) -> Path | None:
    """Archive the config folder once per day, skipping if already archived."""
    config_dir = (config_dir or (REPO_ROOT / "config")).resolve()
    archive_root = (archive_root or (config_dir / ".archive")).resolve()
    date_token = (today or date.today()).strftime("%Y%m%d")
    daily_dir = archive_root / date_token
    daily_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(daily_dir.glob("config_*.zip"))
    if existing:
        return existing[0]

    archive_path = daily_dir / f"config_{date_token}.zip"
    base_dir = config_dir
    skip_dir = archive_root
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in base_dir.rglob("*"):
            if path.is_dir():
                continue
            if skip_dir in path.parents:
                continue
            # Excel lock files (for open workbooks) are temporary and frequently unreadable.
            if path.name.startswith("~$"):
                continue
            rel_path = path.relative_to(base_dir)
            try:
                zf.write(path, arcname=str(rel_path))
            except PermissionError:
                print(f"[WARN] Skipping unreadable config file during archive: {path}")
                continue
    return archive_path


def parse_notebook_safe_args(
    parser: argparse.ArgumentParser,
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse CLI args while tolerating Jupyter kernel connection-file flags."""
    if argv is None:
        argv = sys.argv[1:]

    filtered_args: list[str] = []
    skip_next = False
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        if token == "-f":
            skip_next = True
            continue
        if str(token).startswith("--f="):
            continue
        filtered_args.append(str(token))
    return parser.parse_args(filtered_args)


def normalize_economies(economies: str | Iterable[str] | None) -> list[str]:
    """Return a normalized list of economy labels."""
    if economies is None:
        return []
    if isinstance(economies, str):
        text = economies.strip()
        return [text] if text else []
    return [str(value).strip() for value in economies if str(value).strip()]


def resolve_aggregate_economy(
    economies: str | Iterable[str] | None,
    aggregate_label: str | None = None,
    *,
    aggregate_labels: set[str] | None = None,
) -> tuple[bool, str, list[str]]:
    """Return (should_aggregate, aggregate_label, normalized_economies)."""
    normalized = normalize_economies(economies)
    labels = aggregate_labels or AGGREGATE_ECONOMY_LABELS
    if len(normalized) == 1 and normalized[0] in labels:
        return True, normalized[0], normalized
    resolved_label = aggregate_label or "ALL_ECONOMIES"
    return False, resolved_label, normalized

def format_filename_segment(value: str | None) -> str:
    """Return a file-safe string for economy or scenario labels."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
    sanitized = sanitized.strip("_") or text
    if len(sanitized) <= 48:
        return sanitized
    digest = hashlib.sha1(sanitized.encode("utf-8")).hexdigest()[:8]
    prefix = sanitized[:39].rstrip("_-")
    return f"{prefix}_{digest}"


def compact_filename_segment(
    value: str | None,
    *,
    max_length: int = 48,
    hash_length: int = 8,
) -> str:
    """Return a stable, Windows-friendly filename segment.

    If the sanitized value is longer than ``max_length``, keep the front of the
    label and append a short hash suffix so the name stays readable but compact.
    """
    text = format_filename_segment(value)
    if not text or len(text) <= max_length:
        return text
    hash_length = max(4, min(int(hash_length), max_length - 2))
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:hash_length]
    keep = max_length - hash_length - 1
    prefix = max(1, keep)
    return f"{text[:prefix].rstrip('_-')}_{digest}"


def normalize_scenarios(scenarios: str | Iterable[str] | None) -> list[str]:
    """Return a list of scenario labels."""
    if scenarios is None:
        return []
    if isinstance(scenarios, str):
        return [scenarios]
    return list(scenarios)


def normalize_workflow_scenarios(
    scenarios: str | Iterable[str] | None,
    default_scenarios: Sequence[str],
) -> list[str]:
    """Return cleaned scenario names for export/import workflow operations."""
    if scenarios is None:
        scenario_values = list(default_scenarios)
    elif isinstance(scenarios, str):
        scenario_values = [scenarios]
    else:
        scenario_values = list(scenarios)
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in scenario_values:
        scenario_name = str(value).strip()
        if not scenario_name or scenario_name in seen:
            continue
        seen.add(scenario_name)
        cleaned.append(scenario_name)
    return cleaned or list(default_scenarios)


def resolve_import_scenarios(
    scenario_list: Sequence[str],
    import_scenario: str | Sequence[str] | None,
    *,
    current_accounts_labels: set[str] | None = None,
) -> list[str]:
    """Return ordered scenario names to import, excluding current-accounts labels."""
    account_labels = current_accounts_labels or {"current accounts", "current account"}
    available_by_lower = {str(name).strip().lower(): str(name) for name in scenario_list}
    default_scenarios = [
        scenario
        for scenario in scenario_list
        if str(scenario).strip().lower() not in account_labels
    ]
    if import_scenario is None:
        if not default_scenarios:
            raise ValueError(
                f"No non-'Current Accounts' scenarios available for import in {list(scenario_list)}."
            )
        return list(default_scenarios)

    if isinstance(import_scenario, str):
        requested_values = [import_scenario]
    else:
        requested_values = list(import_scenario)

    resolved: list[str] = []
    for value in requested_values:
        scenario_name = str(value).strip()
        if not scenario_name:
            continue
        scenario_key = scenario_name.lower()
        if scenario_key in account_labels:
            continue
        if scenario_key not in available_by_lower:
            raise ValueError(
                f"Import scenario '{scenario_name}' is not in exported scenarios: {list(scenario_list)}"
            )
        matched = available_by_lower[scenario_key]
        if matched not in resolved:
            resolved.append(matched)
    if not resolved:
        if not default_scenarios:
            raise ValueError(
                f"No non-'Current Accounts' scenarios available for import in {list(scenario_list)}."
            )
        return list(default_scenarios)
    return resolved


def _format_scenario_segment(
    scenarios: Sequence[str],
    format_segment_fn: Callable[[str], str],
) -> str:
    tokens = [format_segment_fn(segment) for segment in scenarios if segment]
    sanitized = "_".join(token for token in tokens if token)
    return sanitized or "scenarios"


def format_export_filename(
    economy_label: str,
    scenarios: Sequence[str],
    template: str,
    format_segment_fn: Callable[[str], str],
    fallback_template: str | None = None,
) -> str:
    """Return a safe filename for export workbooks."""
    scenario_segment = _format_scenario_segment(scenarios, format_segment_fn)
    economy_segment = format_segment_fn(economy_label)
    try:
        return template.format(economy=economy_segment, scenario=scenario_segment)
    except Exception as exc:
        print(f"Failed to format export filename: {exc}")
        fallback = fallback_template or template
        try:
            return fallback.format(economy=economy_segment, scenario=scenario_segment)
        except Exception:
            return fallback


def build_workflow_export_filename(
    economy_label: str,
    scenarios: str | Iterable[str] | None,
    template: str,
    format_segment_fn: Callable[[str], str] = format_filename_segment,
    fallback_template: str | None = None,
) -> str:
    """Return a filename that includes economy and scenario(s)."""
    scenario_list = normalize_scenarios(scenarios)
    return format_export_filename(
        economy_label,
        scenario_list,
        template,
        format_segment_fn,
        fallback_template=fallback_template,
    )


def read_export_column_values(
    export_path: Path,
    sheet_name: str,
    column: str,
) -> list[str]:
    """Return unique values in a column while preserving order."""
    for header in (2, 0):
        try:
            df = pd.read_excel(
                export_path, sheet_name=sheet_name, header=header, usecols=[column]
            )
        except Exception:
            continue
        if column not in df.columns:
            continue
        seen: list[str] = []
        for value in df[column].dropna().astype(str):
            if value not in seen:
                seen.append(value)
        if seen:
            return seen
    return []


def list_export_scenarios(export_path: Path, sheet_name: str) -> list[str]:
    """Return the Scenario column values in declaration order."""
    return read_export_column_values(export_path, sheet_name, "Scenario")


def validate_export_region(export_path: Path, sheet_name: str, region: str) -> None:
    """Ensure the workbook contains the requested region."""
    regions = read_export_column_values(export_path, sheet_name, "Region")
    if not regions:
        print(f"Warning: 'Region' column missing from {export_path.name}; skipping region check.")
        return
    if region not in regions:
        raise ValueError(
            f"Requested region '{region}' not present in {export_path.name}; available: {regions}"
        )


def diagnose_missing_canonical_branches(
    export_path: Path | str,
    sheet_name: str,
    workflow_name: str,
    full_model_export_path: Path | str | None = None,
    full_model_sheet: str | None = None,
    output_dir: Path | str | None = None,
) -> Path | None:
    """Flag generated branch paths absent from the canonical full model export.

    This is purely informational: the canonical export is used only as a
    validation reference here (never to generate branch paths), and a
    mismatch never raises. Writes a diagnostics CSV when mismatches are
    found and returns its path, or None if there was nothing to flag.
    """
    canonical_path = Path(full_model_export_path or fuel_catalog_preflight.DEFAULT_FULL_MODEL_EXPORT_PATH)
    canonical_sheet = full_model_sheet or fuel_catalog_preflight.DEFAULT_FULL_MODEL_EXPORT_SHEET
    try:
        generated_df = fuel_catalog_preflight._read_branch_variable_rows(export_path, sheet_name=sheet_name)
        canonical_df = fuel_catalog_preflight._read_branch_variable_rows(canonical_path, sheet_name=canonical_sheet)
    except Exception as exc:
        print(f"[WARN] {workflow_name}: canonical-branch diagnostic failed to read workbooks: {exc}")
        return None
    if generated_df.empty:
        return None
    if canonical_df.empty:
        print(
            f"[WARN] {workflow_name}: canonical export at {canonical_path} is missing/empty; "
            "skipping missing-branch diagnostic."
        )
        return None

    canonical_branches = {
        str(value).strip() for value in canonical_df.get("Branch Path", pd.Series(dtype=str)).dropna()
    }
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, row in generated_df.iterrows():
        branch_path = str(row.get("Branch Path", "")).strip()
        if not branch_path or branch_path in canonical_branches:
            continue
        scenario = str(row.get("Scenario", "")).strip()
        key = (branch_path, scenario)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "workflow": workflow_name,
                "generated_branch_path": branch_path,
                "scenario": scenario,
                "variable": str(row.get("Variable", "")).strip(),
                "source_file": Path(export_path).name,
                "reason": "generated branch not found in canonical export (full model export.xlsx)",
            }
        )
    if not rows:
        return None

    out_dir = Path(output_dir) if output_dir else Path(export_path).parent / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"missing_canonical_branches_{workflow_name}.csv"
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(
        f"[WARN] {workflow_name}: {len(rows)} generated branch path(s) not found in canonical "
        f"export; see {out_path}"
    )
    return out_path


def find_latest_export_workbook(
    directory: Path | str,
    prefix: str,
    filename: str | None = None,
) -> Path:
    """Locate a workbook by explicit name or latest matching prefix."""
    directory_path = Path(directory)
    if filename:
        candidate = directory_path / filename
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Specified export missing: {candidate}")
    matches = sorted(directory_path.glob(f"{prefix}*.xlsx"))
    if not matches:
        raise FileNotFoundError(f"No exports detected in {directory_path}")
    return matches[-1]


def import_workbook_to_leap(
    export_path: Path,
    sheet_name: str,
    scenario: str | None,
    region: str | None,
    create_branches: bool = True,
    fill_branches: bool = True,
    include_current_accounts: bool = True,
    default_branch_type: tuple | None = None,
    branch_type_mapping: dict | None = None,
    branch_root: str | None = None,
    branch_path_col: str | None = None,
    raise_on_missing_branch: bool = False,
) -> Path:
    """Connect to LEAP, validate the workbook, and fill branches."""
    available = list_export_scenarios(export_path, sheet_name)
    scenario_choice = scenario or (available[0] if available else None)
    available_lower = {str(name).strip().lower() for name in available}
    current_accounts_available = any(
        label in available_lower for label in {"current accounts", "current account"}
    )
    if scenario_choice and scenario_choice not in available:
        raise ValueError(
            f"Scenario '{scenario_choice}' not found in {export_path.name}; options {available}"
        )
    if region:
        validate_export_region(export_path, sheet_name, region)
    if include_current_accounts and not current_accounts_available:
        print(
            "[INFO] Skipping Current Accounts import for "
            f"{export_path.name}: workbook scenarios are {available}."
        )
        include_current_accounts = False

    def _run_api_write() -> Path:
        leap_conn = connect_to_leap()
        if leap_conn is None:
            raise RuntimeError("Unable to connect to LEAP.")

        fuel_catalog_preflight.run_fuel_catalog_preflight(
            export_path=export_path,
            sheet_name=sheet_name,
            scenario=scenario_choice,
            context="workflow_common.import_workbook_to_leap",
            leap_app=leap_conn,
        )
        if create_branches:
            create_kwargs = {
                "sheet_name": sheet_name,
                "branch_root": branch_root,
                "branch_type_mapping": branch_type_mapping,
                "default_branch_type": default_branch_type,
                "RAISE_ERROR_ON_FAILED_BRANCH_CREATION": raise_on_missing_branch,
            }
            if branch_path_col is not None:
                create_kwargs["branch_path_col"] = branch_path_col
            create_branches_from_export_file(
                leap_conn,
                export_path,
                **create_kwargs,
            )
        if fill_branches:
            fill_branches_from_export_file(
                leap_conn,
                export_path,
                sheet_name=sheet_name,
                scenario=scenario_choice,
                region=region,
                RAISE_ERROR_ON_FAILED_SET=raise_on_missing_branch,
                HANDLE_CURRENT_ACCOUNTS_TOO=include_current_accounts,
                RUN_FUEL_CATALOG_PREFLIGHT=False,
            )
        return export_path

    dispatch_result = dispatch_analysis_input_write(
        export_path=export_path,
        sheet_name=sheet_name,
        scenario=scenario_choice,
        region=region,
        context_label="workflow_common.import_workbook_to_leap",
        run_api_write=_run_api_write,
    )
    if dispatch_result.get("mode") == "api":
        result_path = dispatch_result.get("api_result")
        if isinstance(result_path, Path):
            return result_path
    return export_path
