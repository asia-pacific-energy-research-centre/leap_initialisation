from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from codebase.supply_reconciliation_config import *  # noqa: F401,F403
from codebase.utilities.workflow_utils import _resolve


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


def rollback_last_capacity_unmet_pass(
    state_path: Path | str = CAPACITY_UNMET_STATE_PATH,
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
