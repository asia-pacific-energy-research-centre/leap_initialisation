from __future__ import annotations

import json
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from codebase.supply_reconciliation_config import *  # noqa: F401,F403
from codebase.utilities.workflow_utils import _resolve

CONVERGENCE_CSV_COLUMNS = [
    "run_id",
    "timestamp_utc",
    "mode",
    "iteration_run_mode",
    "pass_count",
    "gap_at_first_pass",
    "gap_at_current_pass",
    "gap_closure_pct",
    "gap_delta_last_pass",
    "allocated_cumulative",
    "clipped_total_current",
    "unresolved_count_current",
    "trend",
    "unresolved_fuels_current",
]


def _state_token(value: object) -> str:
    """Normalize a state key token for case-insensitive comparisons."""
    return str(value or "").strip().lower()


def _capacity_addition_state_key(
    economy: str,
    scenario: str,
    module: str,
    process: str,
    instance: int,
    year: int,
) -> str:
    """Build state key for cumulative process-level capacity additions."""
    return "|".join(
        [
            _state_token(economy),
            _state_token(scenario),
            _state_token(module),
            _state_token(process),
            str(int(instance)),
            str(int(year)),
        ]
    )


def _output_addition_state_key(
    economy: str,
    scenario: str,
    esto_product: str,
    year: int,
) -> str:
    """Build state key for cumulative output additions by product/year."""
    return "|".join(
        [
            _state_token(economy),
            _state_token(scenario),
            _state_token(esto_product),
            str(int(year)),
        ]
    )


def _results_signature_state_key(economy: str, scenario: str) -> str:
    """Build state key for last processed results signatures."""
    return "|".join([_state_token(economy), _state_token(scenario)])


def _capacity_unmet_default_state() -> dict[str, object]:
    """Return empty state payload for iterative unmet-capacity runs."""
    return {
        "version": 1,
        "cumulative_capacity_additions": {},
        "cumulative_output_additions": {},
        "cumulative_primary_additions": {},
        "cumulative_export_adjustments": {},
        "last_results_signatures": {},
        "passes": [],
        "pass_deltas": [],
    }


def _default_convergence_csv_path() -> Path:
    return _resolve(RESULTS_RUNTIME_DIR) / "capacity_unmet_convergence.csv"


def _convergence_manifest_dir(runtime_dir: Path | str | None = None) -> Path:
    """Return the additive manifest directory beside convergence history."""
    base_dir = _resolve(runtime_dir) if runtime_dir is not None else _resolve(RESULTS_RUNTIME_DIR)
    return base_dir / "capacity_unmet_run_manifests"


def _safe_run_id_for_filename(run_id: str) -> str:
    """Make a run id safe for the manifest filename without changing its meaning."""
    return "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in str(run_id).strip()
    ) or "legacy_blank_run_id"


def _file_fingerprint(path: Path | str) -> dict[str, object]:
    """Return a cheap, reproducible file fingerprint used by workflow caches."""
    resolved_path = _resolve(path).resolve()
    if not resolved_path.exists():
        return {"path": str(resolved_path), "exists": False}
    stat = resolved_path.stat()
    return {
        "path": str(resolved_path),
        "exists": True,
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def build_convergence_input_fingerprints(
    input_paths: dict[str, Path | str],
) -> dict[str, dict[str, object]]:
    """Fingerprint named run inputs using the same inexpensive file-state contract."""
    return {
        str(name): _file_fingerprint(path)
        for name, path in sorted(input_paths.items())
    }


def _current_commit7() -> str:
    """Return the checked-out commit token, or a clear value outside a git checkout."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_convergence_run_manifest(
    *,
    run_id: str,
    economies: list[str] | tuple[str, ...],
    scenarios: list[str] | tuple[str, ...],
    mode: str,
    iteration_run_mode: str,
    input_paths: dict[str, Path | str],
    preset_name: str = "",
    runtime_dir: Path | str | None = None,
    input_fingerprints: dict[str, dict[str, object]] | None = None,
    certified: bool = True,
) -> Path:
    """Write an additive provenance manifest for one nonblank convergence run.

    The existing convergence CSV deliberately remains narrow and legacy-readable.
    This sibling artifact records the run scope and inexpensive source signatures
    needed to distinguish input drift from a code/model change.
    """
    run_token = str(run_id).strip()
    if not run_token:
        raise ValueError("A nonblank run_id is required to write a convergence manifest.")
    manifest = {
        "version": 1,
        "run_id": run_token,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit7": _current_commit7(),
        "preset_name": str(preset_name or ""),
        "economies": sorted({str(economy) for economy in economies}),
        "scenarios": sorted({str(scenario) for scenario in scenarios}),
        "mode": str(mode),
        "iteration_run_mode": str(iteration_run_mode),
        "input_fingerprints": input_fingerprints or build_convergence_input_fingerprints(input_paths),
        "certified": bool(certified),
    }
    manifest_dir = _convergence_manifest_dir(runtime_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"capacity_unmet_run_manifest_{_safe_run_id_for_filename(run_token)}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


def load_convergence_run_manifest(
    run_id: str,
    runtime_dir: Path | str | None = None,
) -> dict[str, object] | None:
    """Load one optional run manifest; legacy convergence history has none."""
    path = _convergence_manifest_dir(runtime_dir) / (
        f"capacity_unmet_run_manifest_{_safe_run_id_for_filename(run_id)}.json"
    )
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid convergence manifest payload in {path}.")
    return payload


def compare_convergence_manifest_inputs(
    run_id: str,
    input_paths: dict[str, Path | str],
    runtime_dir: Path | str | None = None,
) -> dict[str, dict[str, object]]:
    """Return changed input fingerprints for a manifest, without mutating history."""
    manifest = load_convergence_run_manifest(run_id, runtime_dir=runtime_dir)
    if manifest is None:
        return {}
    expected = manifest.get("input_fingerprints", {})
    if not isinstance(expected, dict):
        raise ValueError(f"Invalid input_fingerprints for convergence run {run_id!r}.")
    drift: dict[str, dict[str, object]] = {}
    for name, path in input_paths.items():
        previous = expected.get(str(name))
        current = _file_fingerprint(path)
        if previous != current:
            drift[str(name)] = {"recorded": previous, "current": current}
    return drift


def load_convergence_csv(csv_path: Path | str | None = None) -> pd.DataFrame:
    """Load convergence CSV rows, adding blank run_id for legacy files."""
    path = _resolve(csv_path) if csv_path is not None else _default_convergence_csv_path()
    if not path.exists():
        return pd.DataFrame(columns=CONVERGENCE_CSV_COLUMNS)
    df = pd.read_csv(path, dtype=object).fillna("")
    if "run_id" not in df.columns:
        df.insert(0, "run_id", "")
    for column in CONVERGENCE_CSV_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df


def _latest_convergence_run_id(df: pd.DataFrame) -> str:
    """Return the latest nonblank run id, or blank for legacy-only history."""
    if df.empty or "run_id" not in df.columns:
        return ""
    run_ids = [str(value).strip() for value in df["run_id"].tolist()]
    for run_id in reversed(run_ids):
        if run_id:
            return run_id
    return ""


def rollback_last_capacity_unmet_pass(
    state_path: Path | str = CAPACITY_UNMET_STATE_PATH,
    convergence_csv_path: Path | None = None,
) -> dict[str, object]:
    """Remove the most recent iterative pass and undo its cumulative additions.

    How to use
    ----------
    If you ran a pass based on stale or incorrect LEAP results and want to
    pretend that pass never happened:

        from codebase.supply_reconciliation_history import rollback_last_capacity_unmet_pass
        rollback_last_capacity_unmet_pass()   # uses default state path from config

    The function:
    1. Reads the current state JSON.
    2. Subtracts the last pass's delta from the four cumulative maps.
       Keys that reach zero are removed so the file stays clean.
    3. Removes the last entry from both ``passes`` and ``pass_deltas``.
    4. Resets ``last_results_signatures`` to the snapshot saved before that pass
       so the reuse-guard treats the next run as fresh.
    5. Writes the updated state back to disk and returns the new state.

    Limitations
    -----------
    * You can only roll back as far back as ``pass_deltas`` goes (i.e. passes
      recorded before ``pass_deltas`` was introduced cannot be removed this way).
    * If you have already trimmed old deltas via ``trim_capacity_unmet_pass_deltas``
      those passes are permanently locked in.
    * Subtracting floating-point values may leave tiny residuals (< 1e-12).
      These are treated as zero and pruned automatically.
    """
    path = _resolve(state_path)
    if not path.exists():
        raise FileNotFoundError(f"State file not found: {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Could not read state file '{path}': {exc}") from exc

    pass_deltas = state.get("pass_deltas")
    if not isinstance(pass_deltas, list) or not pass_deltas:
        raise ValueError(
            "No pass deltas available to roll back. Passes recorded before the "
            "pass_deltas feature was added cannot be removed this way."
        )

    delta = pass_deltas[-1]

    def _subtract(cumulative: dict, additions: dict) -> dict:
        out = dict(cumulative)
        for key, value in additions.items():
            current = float(out.get(key, 0.0))
            new_value = current - float(value)
            if abs(new_value) < 1e-12:
                out.pop(key, None)
            else:
                out[key] = new_value
        return out

    state["cumulative_capacity_additions"] = _subtract(
        state.get("cumulative_capacity_additions", {}),
        delta.get("capacity_additions", {}),
    )
    state["cumulative_output_additions"] = _subtract(
        state.get("cumulative_output_additions", {}),
        delta.get("output_additions", {}),
    )
    state["cumulative_primary_additions"] = _subtract(
        state.get("cumulative_primary_additions", {}),
        delta.get("primary_additions", {}),
    )
    state["cumulative_export_adjustments"] = _subtract(
        state.get("cumulative_export_adjustments", {}),
        delta.get("export_adjustments", {}),
    )

    # Restore the results signature that was current before this pass so the
    # reuse-guard on the next run doesn't skip loading fresh LEAP results.
    pre_pass_signatures = delta.get("pre_pass_signatures")
    if isinstance(pre_pass_signatures, dict):
        state["last_results_signatures"] = pre_pass_signatures

    passes = state.get("passes")
    if isinstance(passes, list) and passes:
        passes.pop()
    state["passes"] = passes or []
    state["pass_deltas"] = pass_deltas[:-1]

    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(
        f"[ROLLBACK] Removed pass #{delta.get('pass_index', '?')} "
        f"(mode={delta.get('mode', '?')}, timestamp={delta.get('timestamp_utc', '?')}). "
        f"State written to {path}."
    )
    trim_convergence_csv_to_pass(
        pass_number=len(state["passes"]),
        csv_path=convergence_csv_path,
        run_id=str(delta.get("run_id") or ""),
    )
    return state


def trim_capacity_unmet_pass_deltas(
    keep_last: int,
    state_path: Path | str = CAPACITY_UNMET_STATE_PATH,
) -> dict[str, object]:
    """Discard old pass deltas, keeping only the most recent ``keep_last`` entries.

    How to use
    ----------
    Once you are confident that early passes are correct and you no longer need
    the ability to roll them back, trim the delta list to save disk space:

        from codebase.supply_reconciliation_history import trim_capacity_unmet_pass_deltas
        trim_capacity_unmet_pass_deltas(keep_last=5)  # keep last 5 passes reversible

    **Warning — this is irreversible.** Trimmed passes are permanently locked
    into the cumulative totals. You will not be able to undo them via
    ``rollback_last_capacity_unmet_pass`` after trimming.

    To remove all rollback capability entirely (smallest file):

        trim_capacity_unmet_pass_deltas(keep_last=0)

    Parameters
    ----------
    keep_last : int
        Number of most-recent pass deltas to retain. Must be >= 0.
    state_path : Path or str
        Path to the state JSON file (defaults to CAPACITY_UNMET_STATE_PATH).
    """
    if keep_last < 0:
        raise ValueError(f"keep_last must be >= 0, got {keep_last!r}")
    path = _resolve(state_path)
    if not path.exists():
        raise FileNotFoundError(f"State file not found: {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Could not read state file '{path}': {exc}") from exc

    pass_deltas = state.get("pass_deltas")
    if not isinstance(pass_deltas, list):
        pass_deltas = []
    before = len(pass_deltas)
    state["pass_deltas"] = pass_deltas[-keep_last:] if keep_last > 0 else []
    after = len(state["pass_deltas"])
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(
        f"[TRIM] Removed {before - after} old pass delta(s). "
        f"{after} delta(s) remain (last {keep_last} passes are still reversible). "
        f"State written to {path}."
    )
    return state


def _resolve_capacity_unmet_pass_mode(raw_mode: str | None = None) -> str:
    """Return canonical pass mode for iterative unmet-capacity passes."""
    configured = (
        raw_mode
        if raw_mode is not None
        else CAPACITY_UNMET_PASS_MODE
    )
    token = str(configured or "").strip().lower() or "results_update"
    aliases = {
        "baseline_seed": "baseline_seed",
        "seed_baseline": "baseline_seed",
        "first_clean": "baseline_seed",
        "first": "baseline_seed",
        "first_run": "baseline_seed",
        "baseline": "baseline_seed",
        "results_update": "results_update",
        "update_from_results": "results_update",
        "consecutive": "results_update",
        "second": "results_update",
        "second_run": "results_update",
        "leap_balance": "results_update",
    }
    mode = aliases.get(token)
    if mode is None:
        raise ValueError(
            "Invalid CAPACITY_UNMET_PASS_MODE="
            f"{configured!r}. Valid values: ['baseline_seed', 'results_update'] "
            "(old aliases 'first_clean' and 'consecutive' are also accepted)."
        )
    return mode


def _is_capacity_unmet_baseline_seed_pass() -> bool:
    """Return True when iterative unmet workflow should run baseline-only first pass."""
    return _resolve_capacity_unmet_pass_mode() == "baseline_seed"


def _read_capacity_unmet_state(
    state_path: Path | str = CAPACITY_UNMET_STATE_PATH,
    *,
    run_mode: str | None = None,
) -> dict[str, object]:
    """Load iterative capacity state JSON from disk (or reset for baseline_seed mode)."""
    path = _resolve(state_path)
    mode = _resolve_capacity_unmet_pass_mode(run_mode)
    default_state = _capacity_unmet_default_state()
    if mode == "baseline_seed":
        if path.exists() and bool(CAPACITY_UNMET_FIRST_CLEAN_ARCHIVE_EXISTING_STATE):
            archive_dir = _resolve(RESULTS_SINGLE_FILE_ARCHIVE_DIR)
            archive_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            archive_path = archive_dir / f"{path.stem}_{stamp}{path.suffix}"
            try:
                shutil.copy2(path, archive_path)
                print(
                    "[CAPACITY_UNMET] baseline_seed mode: archived existing state to "
                    f"{archive_path}"
                )
            except Exception as exc:
                print(
                    "[WARN] Failed archiving existing capacity unmet state in baseline_seed mode: "
                    f"{exc}"
                )
        print(
            "[CAPACITY_UNMET] baseline_seed mode: ignoring persisted iterative state and "
            "starting from empty cumulative additions."
        )
        return default_state
    if not path.exists():
        return default_state
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(
            f"Failed reading capacity unmet iterative state file '{path}': {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid capacity unmet iterative state payload in '{path}'.")
    for key, default_value in default_state.items():
        value = payload.get(key)
        if isinstance(default_value, dict):
            payload[key] = value if isinstance(value, dict) else {}
        elif isinstance(default_value, list):
            payload[key] = value if isinstance(value, list) else []
        else:
            payload.setdefault(key, default_value)
    return payload


def _write_capacity_unmet_state(
    state: dict[str, object],
    state_path: Path | str = CAPACITY_UNMET_STATE_PATH,
) -> Path:
    """Persist iterative capacity state JSON to disk."""
    path = _resolve(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return path


def _build_results_signature(path) -> dict[str, object]:
    """Return file signature payload used for same-results reuse guard."""
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "name": path.name,
        "size_bytes": int(stat.st_size),
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _lookup_runtime_capacity_additions_for_record(
    *,
    economy: str,
    scenario: str,
    module: str,
    process: str,
    instance: int,
) -> dict[int, float]:
    """Return per-year cumulative exogenous-capacity additions for one process record."""
    import codebase.supply_reconciliation_allocation as _sra  # late import — avoids circular dep
    additions_by_year: dict[int, float] = {}
    scenario_token = _state_token(scenario)
    aliases = {scenario_token}
    if scenario_token in {"current accounts", "current account"}:
        aliases.add("reference")
    for scenario_alias in aliases:
        for year in range(BASE_YEAR, FINAL_YEAR + 1):
            key = _capacity_addition_state_key(
                economy=economy,
                scenario=scenario_alias,
                module=module,
                process=process,
                instance=instance,
                year=year,
            )
            value = _sra._CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS.get(key, 0.0)
            if value <= 0.0:
                continue
            additions_by_year[year] = additions_by_year.get(year, 0.0) + float(value)
    return additions_by_year


def _lookup_runtime_primary_addition(
    *,
    economy: str,
    scenario: str,
    esto_product: str,
    year: int,
) -> float:
    """Return cumulative primary-production addition for one product-year."""
    import codebase.supply_reconciliation_allocation as _sra  # late import — avoids circular dep
    scenario_token = _state_token(scenario)
    aliases = {scenario_token}
    if scenario_token in {"current accounts", "current account"}:
        aliases.add("reference")
    value = 0.0
    for scenario_alias in aliases:
        key = _output_addition_state_key(
            economy=economy,
            scenario=scenario_alias,
            esto_product=esto_product,
            year=year,
        )
        value += float(_sra._CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS.get(key, 0.0))
    return max(value, 0.0)


def trim_convergence_csv_to_pass(
    pass_number: int,
    csv_path: Path | None = None,
    run_id: str | None = None,
) -> None:
    """Remove convergence rows where pass_count exceeds pass_number.

    After rolling back reconciliation passes, call this to strip the stale
    convergence rows that no longer correspond to active passes. When run_id
    is supplied and the CSV has run ids, trimming is scoped to that run.

    Parameters
    ----------
    pass_number : int
        Rows with pass_count <= pass_number are retained; the rest are dropped.
        Passing 0 removes all data rows (leaves the header only).
    csv_path : Path or None
        Path to the CSV.  Defaults to
        RESULTS_RUNTIME_DIR / "capacity_unmet_convergence.csv".
    run_id : str or None
        Optional run id to trim. Legacy rows without run_id are trimmed
        globally for backward compatibility.
    """
    if csv_path is None:
        csv_path = _default_convergence_csv_path()
    path = _resolve(csv_path)
    if not path.exists():
        return
    df = load_convergence_csv(path)
    before = len(df)
    pass_counts = pd.to_numeric(df["pass_count"], errors="coerce").fillna(0).astype(int)
    run_token = str(run_id or "").strip()
    if run_token and "run_id" in df.columns:
        same_run = df["run_id"].astype(str).str.strip() == run_token
        keep_mask = (~same_run) | (pass_counts <= int(pass_number))
    else:
        keep_mask = pass_counts <= int(pass_number)
    df = df[keep_mask].copy()
    after = len(df)
    df.to_csv(path, index=False)
    scope_text = f" for run_id={run_token}" if run_token else ""
    print(
        f"[CONVERGENCE] Trimmed {before - after} row(s){scope_text} with pass_count > {pass_number} "
        f"({after} row(s) remain). Written to {path}."
    )


def remove_convergence_run(
    run_id: str | None = None,
    csv_path: Path | None = None,
) -> None:
    """Remove all convergence-history rows for one deliberately reverted run.

    If run_id is omitted, the latest nonblank run id in the CSV is removed. For
    legacy CSVs without run ids, omitting run_id removes the blank legacy group.
    The file itself is never deleted.
    """
    if csv_path is None:
        csv_path = _default_convergence_csv_path()
    path = _resolve(csv_path)
    if not path.exists():
        print(f"[CONVERGENCE] No convergence CSV found at {path}.")
        return

    df = load_convergence_csv(path)
    if df.empty:
        df.to_csv(path, index=False)
        print(f"[CONVERGENCE] No convergence rows to remove in {path}.")
        return

    resolved_run_id = str(run_id or _latest_convergence_run_id(df)).strip()
    run_values = df["run_id"].astype(str).str.strip()
    remove_mask = run_values == resolved_run_id
    removed = df[remove_mask].copy()
    kept = df[~remove_mask].copy()

    pass_counts = pd.to_numeric(removed.get("pass_count"), errors="coerce").dropna()
    if pass_counts.empty:
        pass_range = "n/a"
    else:
        pass_range = f"{int(pass_counts.min())}-{int(pass_counts.max())}"

    kept.to_csv(path, index=False)
    display_run_id = resolved_run_id or "<legacy blank run_id>"
    print(
        f"[CONVERGENCE] Removed {len(removed)} row(s) for run_id={display_run_id} "
        f"(pass range {pass_range}). {len(kept)} row(s) remain in {path}."
    )


def prune_convergence_history(
    keep_runs: int,
    *,
    csv_path: Path | str | None = None,
    runtime_dir: Path | str | None = None,
    dry_run: bool = True,
) -> dict[str, object]:
    """Prune old named runs only when explicitly requested.

    ``dry_run=True`` is the default: it reports the exact run ids and manifest
    files that would be removed without changing history. Legacy blank-run-id
    rows are retained because their ordering and ownership are ambiguous.
    """
    if keep_runs < 1:
        raise ValueError("keep_runs must be at least 1 so the latest run is never removed.")
    path = _resolve(csv_path) if csv_path is not None else _default_convergence_csv_path()
    if not path.exists():
        return {"dry_run": dry_run, "removed_run_ids": [], "manifest_paths": [], "csv_path": path}

    convergence = load_convergence_csv(path)
    run_ids: list[str] = []
    for value in convergence["run_id"].astype(str).tolist():
        run_id = value.strip()
        if run_id and run_id not in run_ids:
            run_ids.append(run_id)
    removed_run_ids = run_ids[:-keep_runs]
    manifest_dir = _convergence_manifest_dir(runtime_dir or path.parent)
    manifest_paths = [
        manifest_dir / f"capacity_unmet_run_manifest_{_safe_run_id_for_filename(run_id)}.json"
        for run_id in removed_run_ids
    ]
    result = {
        "dry_run": bool(dry_run),
        "removed_run_ids": removed_run_ids,
        "manifest_paths": manifest_paths,
        "csv_path": path,
    }
    if dry_run or not removed_run_ids:
        return result

    remove_mask = convergence["run_id"].astype(str).str.strip().isin(removed_run_ids)
    convergence.loc[~remove_mask].to_csv(path, index=False)
    for manifest_path in manifest_paths:
        if manifest_path.exists():
            manifest_path.unlink()
    print(
        f"[CONVERGENCE] Pruned {len(removed_run_ids)} named run(s); "
        f"kept the latest {keep_runs}. Legacy rows were retained."
    )
    return result


def clear_convergence_csv(
    csv_path: Path | None = None,
) -> None:
    """Truncate the convergence CSV to its header row only.

    Use this when starting a fresh reconciliation run and you want to clear
    all previous convergence history.

    Parameters
    ----------
    csv_path : Path or None
        Path to the CSV.  Defaults to
        RESULTS_RUNTIME_DIR / "capacity_unmet_convergence.csv".
    """
    if csv_path is None:
        csv_path = _resolve(RESULTS_RUNTIME_DIR) / "capacity_unmet_convergence.csv"
    path = _resolve(csv_path)
    if not path.exists():
        return
    df = pd.read_csv(path, nrows=0)
    df.to_csv(path, index=False)
    print(f"[CONVERGENCE] Cleared all data rows from {path} (header retained).")


def _lookup_runtime_export_adjustment(
    *,
    economy: str,
    scenario: str,
    esto_product: str,
    year: int,
) -> float:
    """Return cumulative extra exports adjustment for one product-year."""
    import codebase.supply_reconciliation_allocation as _sra  # late import — avoids circular dep
    scenario_token = _state_token(scenario)
    aliases = {scenario_token}
    if scenario_token in {"current accounts", "current account"}:
        aliases.add("reference")
    value = 0.0
    for scenario_alias in aliases:
        key = _output_addition_state_key(
            economy=economy,
            scenario=scenario_alias,
            esto_product=esto_product,
            year=year,
        )
        value += float(_sra._CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS.get(key, 0.0))
    return max(value, 0.0)
