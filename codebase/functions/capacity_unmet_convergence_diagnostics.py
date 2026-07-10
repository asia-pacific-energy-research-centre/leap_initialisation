#%%
# Summary: modeller-facing diagnostics for capacity-unmet convergence runs.

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from codebase.supply_reconciliation_config import (
    CAPACITY_UNMET_STATE_PATH,
    RESULTS_RUNTIME_DIR,
)
from codebase.supply_reconciliation_history import (
    load_convergence_csv,
)
from codebase.utilities.workflow_utils import _resolve


#%%
######### FUNCTIONS #########
def _default_convergence_csv_path() -> Path:
    return _resolve(RESULTS_RUNTIME_DIR) / "capacity_unmet_convergence.csv"


def _read_state(state_path: Path | str = CAPACITY_UNMET_STATE_PATH) -> dict[str, object]:
    path = _resolve(state_path)
    if not path.exists():
        raise FileNotFoundError(f"Capacity-unmet state file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"Could not read capacity-unmet state file '{path}': {exc}") from exc


def _to_float(value: object) -> float:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return 0.0
    return float(numeric)


def _safe_run_id_for_filename(run_id: str) -> str:
    token = str(run_id or "").strip()
    return token if token else "legacy_blank_run_id"


def _run_ids_from_convergence(convergence: pd.DataFrame) -> list[str]:
    if convergence.empty or "run_id" not in convergence.columns:
        return []
    run_ids: list[str] = []
    for value in convergence["run_id"].astype(str).tolist():
        run_id = value.strip()
        if run_id and run_id not in run_ids:
            run_ids.append(run_id)
    return run_ids


def _latest_run_id(convergence: pd.DataFrame, state: dict[str, object]) -> str:
    run_ids = _run_ids_from_convergence(convergence)
    if run_ids:
        return run_ids[-1]
    passes = state.get("passes")
    if isinstance(passes, list):
        for pass_summary in reversed(passes):
            if isinstance(pass_summary, dict):
                run_id = str(pass_summary.get("run_id") or "").strip()
                if run_id:
                    return run_id
    return ""


def _latest_two_run_ids(convergence: pd.DataFrame, state: dict[str, object]) -> tuple[str, str]:
    state_run_ids: list[str] = []
    passes = state.get("passes")
    if isinstance(passes, list):
        for pass_summary in passes:
            if not isinstance(pass_summary, dict):
                continue
            run_id = str(pass_summary.get("run_id") or "").strip()
            if run_id and run_id not in state_run_ids:
                state_run_ids.append(run_id)
    run_ids = [run_id for run_id in _run_ids_from_convergence(convergence) if run_id in state_run_ids]
    if len(run_ids) >= 2:
        return run_ids[-2], run_ids[-1]
    if len(state_run_ids) >= 2:
        return state_run_ids[-2], state_run_ids[-1]
    raise ValueError("Need at least two run ids to compare capacity-unmet runs.")


def _filter_passes_for_run(passes: list[dict], run_id: str) -> list[dict]:
    if run_id:
        return [p for p in passes if str(p.get("run_id") or "").strip() == run_id]
    return [p for p in passes if not str(p.get("run_id") or "").strip()]


def _filter_convergence_for_run(convergence: pd.DataFrame, run_id: str) -> pd.DataFrame:
    if convergence.empty:
        return convergence.copy()
    run_values = convergence["run_id"].astype(str).str.strip()
    return convergence[run_values == str(run_id or "").strip()].copy()


def _gap_total(pass_summary: dict) -> float:
    return _to_float(
        pass_summary.get("positive_import_gap_total")
        or pass_summary.get("unmet_proxy_total")
        or 0.0
    )


def _sum_rows_by_fuel(rows: list[dict], value_column: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows or []:
        fuel = str(row.get("esto_product") or "").strip()
        if not fuel:
            continue
        out[fuel] = out.get(fuel, 0.0) + _to_float(row.get(value_column))
    return out


def _allocation_by_fuel_and_lever(passes: list[dict]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for pass_summary in passes:
        for row in pass_summary.get("allocation_rows", []) or []:
            fuel = str(row.get("esto_product") or "").strip()
            if not fuel:
                continue
            allocation_type = str(row.get("allocation_type") or "transformation").strip()
            if allocation_type == "primary_production":
                lever = "primary_production"
            else:
                lever = "transformation_capacity"
            out.setdefault(fuel, {
                "primary_production": 0.0,
                "transformation_capacity": 0.0,
                "imports_fallback": 0.0,
            })
            out[fuel][lever] += _to_float(row.get("allocated_output_uplift"))
        for row in pass_summary.get("unresolved_positive_rows", []) or []:
            fuel = str(row.get("esto_product") or "").strip()
            if not fuel:
                continue
            out.setdefault(fuel, {
                "primary_production": 0.0,
                "transformation_capacity": 0.0,
                "imports_fallback": 0.0,
            })
            out[fuel]["imports_fallback"] += _to_float(row.get("unresolved_output_uplift"))
    return out


def _build_per_fuel_table(passes: list[dict]) -> pd.DataFrame:
    if not passes:
        return pd.DataFrame()
    start_gaps = _sum_rows_by_fuel(passes[0].get("positive_gap_rows", []) or [], "positive_gap")
    end_gaps = _sum_rows_by_fuel(passes[-1].get("positive_gap_rows", []) or [], "positive_gap")
    allocations = _allocation_by_fuel_and_lever(passes)
    clipped: dict[str, float] = {}
    unresolved_fuels = set()
    for pass_summary in passes:
        for row in pass_summary.get("clipping_rows", []) or []:
            fuel = str(row.get("esto_product") or "").strip()
            if fuel:
                clipped[fuel] = clipped.get(fuel, 0.0) + _to_float(row.get("clipped_output_uplift"))
    for row in passes[-1].get("unresolved_positive_rows", []) or []:
        fuel = str(row.get("esto_product") or "").strip()
        if fuel:
            unresolved_fuels.add(fuel)

    fuels = sorted(set(start_gaps) | set(end_gaps) | set(allocations) | set(clipped) | unresolved_fuels)
    rows: list[dict[str, object]] = []
    for fuel in fuels:
        lever_values = allocations.get(fuel, {})
        start_gap = start_gaps.get(fuel, 0.0)
        end_gap = end_gaps.get(fuel, 0.0)
        rows.append(
            {
                "esto_product": fuel,
                "gap_at_run_start": start_gap,
                "gap_at_run_end": end_gap,
                "gap_delta": end_gap - start_gap,
                "allocated_primary_production": lever_values.get("primary_production", 0.0),
                "allocated_transformation_capacity": lever_values.get("transformation_capacity", 0.0),
                "allocated_imports_fallback": lever_values.get("imports_fallback", 0.0),
                "clipped_amount": clipped.get(fuel, 0.0),
                "still_unresolved": fuel in unresolved_fuels,
            }
        )
    return pd.DataFrame(rows)


def _build_run_summary(passes: list[dict], run_convergence: pd.DataFrame, run_id: str) -> dict[str, object]:
    if passes:
        first_gap = _gap_total(passes[0])
        final_gap = _gap_total(passes[-1])
    elif not run_convergence.empty:
        first = run_convergence.iloc[0]
        last = run_convergence.iloc[-1]
        first_gap = _to_float(first.get("gap_at_first_pass") or first.get("gap_at_current_pass"))
        final_gap = _to_float(last.get("gap_at_current_pass"))
    else:
        first_gap = 0.0
        final_gap = 0.0
    if first_gap > 0.0:
        closure_pct = (first_gap - final_gap) / first_gap * 100.0
    else:
        closure_pct = 100.0 if final_gap <= 0.0 else 0.0
    per_fuel = _build_per_fuel_table(passes)
    trend = ""
    if not run_convergence.empty and "trend" in run_convergence.columns:
        trend = str(run_convergence.iloc[-1].get("trend") or "")
    return {
        "run_id": run_id,
        "passes_executed": len(passes) if passes else len(run_convergence),
        "first_gap": first_gap,
        "final_gap": final_gap,
        "closure_pct": round(float(closure_pct), 4),
        "trend": trend or "unknown",
        "allocated_primary_production": float(per_fuel.get("allocated_primary_production", pd.Series(dtype=float)).sum()),
        "allocated_transformation_capacity": float(per_fuel.get("allocated_transformation_capacity", pd.Series(dtype=float)).sum()),
        "allocated_imports_fallback": float(per_fuel.get("allocated_imports_fallback", pd.Series(dtype=float)).sum()),
        "total_clipped": float(per_fuel.get("clipped_amount", pd.Series(dtype=float)).sum()),
    }


def build_capacity_unmet_run_diagnostics(
    run_id: str | None = None,
    *,
    state_path: Path | str = CAPACITY_UNMET_STATE_PATH,
    convergence_csv_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    write_csv: bool = True,
    print_summary: bool = True,
) -> dict[str, object]:
    """Build and optionally write diagnostics for one capacity-unmet run."""
    state = _read_state(state_path)
    convergence_path = _resolve(convergence_csv_path) if convergence_csv_path else _default_convergence_csv_path()
    convergence = load_convergence_csv(convergence_path)
    passes_raw = state.get("passes", [])
    all_passes = passes_raw if isinstance(passes_raw, list) else []
    resolved_run_id = str(run_id or _latest_run_id(convergence, state)).strip()
    passes = _filter_passes_for_run(all_passes, resolved_run_id)
    if not passes and run_id is None and resolved_run_id:
        resolved_run_id = ""
        passes = _filter_passes_for_run(all_passes, resolved_run_id)

    run_convergence = _filter_convergence_for_run(convergence, resolved_run_id)
    if not passes and run_convergence.empty:
        raise ValueError(f"No capacity-unmet diagnostics found for run_id={resolved_run_id!r}.")
    per_fuel = _build_per_fuel_table(passes)
    movers = per_fuel.copy()
    if not movers.empty:
        movers["abs_gap_delta"] = movers["gap_delta"].abs()
        movers = movers.sort_values(["abs_gap_delta", "esto_product"], ascending=[False, True])
    summary = _build_run_summary(passes, run_convergence, resolved_run_id)

    csv_path: Path | None = None
    if write_csv:
        out_dir = _resolve(output_dir) if output_dir else _resolve(RESULTS_RUNTIME_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / f"capacity_unmet_run_diagnostics_{_safe_run_id_for_filename(resolved_run_id)}.csv"
        per_fuel.to_csv(csv_path, index=False)

    if print_summary:
        display_run_id = resolved_run_id or "<legacy blank run_id>"
        print(f"[CAPACITY_UNMET_DIAGNOSTICS] Run {display_run_id}")
        print(
            "  passes={passes_executed}, first_gap={first_gap:.3f}, final_gap={final_gap:.3f}, "
            "closure={closure_pct:.2f}%, trend={trend}".format(**summary)
        )
        print(
            "  allocation: primary={allocated_primary_production:.3f}, "
            "transformation={allocated_transformation_capacity:.3f}, "
            "imports_fallback={allocated_imports_fallback:.3f}, clipped={total_clipped:.3f}".format(**summary)
        )
        if csv_path:
            print(f"  per-fuel CSV: {csv_path}")

    return {
        "run_id": resolved_run_id,
        "summary": summary,
        "per_fuel": per_fuel,
        "movers": movers,
        "csv_path": csv_path,
    }


def compare_capacity_unmet_runs(
    run_id_a: str | None = None,
    run_id_b: str | None = None,
    *,
    state_path: Path | str = CAPACITY_UNMET_STATE_PATH,
    convergence_csv_path: Path | str | None = None,
    print_summary: bool = True,
) -> dict[str, object]:
    """Compare two capacity-unmet runs, defaulting to the latest two run ids."""
    state = _read_state(state_path)
    convergence_path = _resolve(convergence_csv_path) if convergence_csv_path else _default_convergence_csv_path()
    convergence = load_convergence_csv(convergence_path)
    if not run_id_a or not run_id_b:
        latest_a, latest_b = _latest_two_run_ids(convergence, state)
        run_id_a = run_id_a or latest_a
        run_id_b = run_id_b or latest_b

    diag_a = build_capacity_unmet_run_diagnostics(
        run_id_a,
        state_path=state_path,
        convergence_csv_path=convergence_path,
        write_csv=False,
        print_summary=False,
    )
    diag_b = build_capacity_unmet_run_diagnostics(
        run_id_b,
        state_path=state_path,
        convergence_csv_path=convergence_path,
        write_csv=False,
        print_summary=False,
    )

    conv_a = _filter_convergence_for_run(convergence, str(run_id_a))
    conv_b = _filter_convergence_for_run(convergence, str(run_id_b))
    trajectory = pd.DataFrame({
        "pass_count": pd.to_numeric(conv_a.get("pass_count", pd.Series(dtype=object)), errors="coerce"),
        f"{run_id_a}_gap": pd.to_numeric(conv_a.get("gap_at_current_pass", pd.Series(dtype=object)), errors="coerce"),
    })
    trajectory_b = pd.DataFrame({
        "pass_count": pd.to_numeric(conv_b.get("pass_count", pd.Series(dtype=object)), errors="coerce"),
        f"{run_id_b}_gap": pd.to_numeric(conv_b.get("gap_at_current_pass", pd.Series(dtype=object)), errors="coerce"),
    })
    trajectory = trajectory.merge(trajectory_b, on="pass_count", how="outer").sort_values("pass_count")

    unresolved_a = set(diag_a["per_fuel"].loc[diag_a["per_fuel"]["still_unresolved"], "esto_product"])
    unresolved_b = set(diag_b["per_fuel"].loc[diag_b["per_fuel"]["still_unresolved"], "esto_product"])
    per_fuel_a = diag_a["per_fuel"][["esto_product", "gap_at_run_end"]].rename(
        columns={"gap_at_run_end": "end_gap_a"}
    )
    per_fuel_b = diag_b["per_fuel"][["esto_product", "gap_at_run_end"]].rename(
        columns={"gap_at_run_end": "end_gap_b"}
    )
    end_gap_delta = per_fuel_a.merge(per_fuel_b, on="esto_product", how="outer").fillna(0.0)
    end_gap_delta["end_gap_delta_b_minus_a"] = end_gap_delta["end_gap_b"] - end_gap_delta["end_gap_a"]
    end_gap_delta["abs_end_gap_delta"] = end_gap_delta["end_gap_delta_b_minus_a"].abs()
    end_gap_delta = end_gap_delta.sort_values(["abs_end_gap_delta", "esto_product"], ascending=[False, True])

    mode_values_a = set((conv_a.get("mode", pd.Series(dtype=object)).astype(str) + "|" + conv_a.get("iteration_run_mode", pd.Series(dtype=object)).astype(str)).tolist())
    mode_values_b = set((conv_b.get("mode", pd.Series(dtype=object)).astype(str) + "|" + conv_b.get("iteration_run_mode", pd.Series(dtype=object)).astype(str)).tolist())
    mode_mismatch = mode_values_a != mode_values_b

    summary = {
        "run_id_a": run_id_a,
        "run_id_b": run_id_b,
        "closure_pct_delta_b_minus_a": _to_float(diag_b["summary"]["closure_pct"]) - _to_float(diag_a["summary"]["closure_pct"]),
        "pass_count_delta_b_minus_a": int(diag_b["summary"]["passes_executed"]) - int(diag_a["summary"]["passes_executed"]),
        "resolved_in_b": sorted(unresolved_a - unresolved_b),
        "newly_unresolved_in_b": sorted(unresolved_b - unresolved_a),
        "unresolved_in_both": sorted(unresolved_a & unresolved_b),
        "mode_mismatch": mode_mismatch,
    }

    if print_summary:
        print(f"[CAPACITY_UNMET_COMPARISON] {run_id_a} -> {run_id_b}")
        print(
            "  closure delta={closure_pct_delta_b_minus_a:.2f} percentage points, "
            "pass delta={pass_count_delta_b_minus_a}".format(**summary)
        )
        if mode_mismatch:
            print("  WARNING: runs used different mode / iteration_run_mode values.")
        print(
            f"  resolved in B={len(summary['resolved_in_b'])}, "
            f"newly unresolved in B={len(summary['newly_unresolved_in_b'])}, "
            f"unresolved in both={len(summary['unresolved_in_both'])}"
        )

    return {
        "summary": summary,
        "gap_trajectory": trajectory,
        "end_gap_delta": end_gap_delta,
        "run_a": diag_a,
        "run_b": diag_b,
    }


#%%
