from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

# All public config constants (sentinels, paths, CAPACITY_UNMET_* dicts, etc.)
from codebase.supply_reconciliation_config import *  # noqa: F401,F403
from codebase.supply_reconciliation_config import (  # private names excluded by *
    _ModuleCapRule,
    _resolve_module_cap_rule,
)
from codebase.utilities.workflow_utils import _resolve
from codebase.functions import supply_data_pipeline
from codebase.supply_reconciliation_utils import (
    _build_label_to_esto_product_lookup,
    _normalize_label_for_lookup,
    _normalize_esto_product_for_match,
    _sort_output_frame_for_csv,
    _iter_year_value_items,
)
from codebase.supply_reconciliation_history import (
    _state_token,
    _capacity_addition_state_key,
    _output_addition_state_key,
    _resolve_capacity_unmet_pass_mode,
    _read_capacity_unmet_state,
    _write_capacity_unmet_state,
)

# ---------------------------------------------------------------------------
# Mutable runtime globals — written by the pass functions, read by
# workflow.py's _lookup_runtime_* helpers via module-attribute access.
# ---------------------------------------------------------------------------
_CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS: dict[str, float] = {}
_CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS: dict[str, float] = {}
_CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS: dict[str, float] = {}
_CAPACITY_UNMET_RUNTIME_PASS_SUMMARY: dict[str, object] | None = None


# ---------------------------------------------------------------------------
# Convergence tracking
# ---------------------------------------------------------------------------

def _compute_convergence_metrics(passes: list[dict]) -> dict[str, object]:
    """Compute gap-closure metrics from the pass history list stored in state."""
    if not passes:
        return {"pass_count": 0, "trend": "unknown"}

    pass_count = len(passes)

    def _gap(p: dict) -> float:
        return float(
            p.get("positive_import_gap_total")
            or p.get("unmet_proxy_total")
            or 0.0
        )

    def _allocated(p: dict) -> float:
        return float(
            p.get("allocated_transformation_output_total")
            or p.get("allocated_output_total")
            or 0.0
        ) + float(p.get("allocated_primary_output_total") or 0.0)

    gap_series = [_gap(p) for p in passes]
    allocated_series = [_allocated(p) for p in passes]
    first_gap = gap_series[0]
    current_gap = gap_series[-1]

    if first_gap > 0.0:
        gap_closure_pct = (first_gap - current_gap) / first_gap * 100.0
    else:
        gap_closure_pct = 100.0 if current_gap <= 0.0 else 0.0

    if len(gap_series) >= 2:
        delta = gap_series[-1] - gap_series[-2]
        if delta < -1e-6:
            trend = "converging"
        elif delta > 1e-6:
            trend = "diverging"
        else:
            trend = "stable"
    else:
        trend = "unknown"

    unresolved_fuels: set[str] = set()
    for row in passes[-1].get("unresolved_positive_rows", []):
        fuel = str(row.get("esto_product") or "").strip()
        if fuel:
            unresolved_fuels.add(fuel)

    return {
        "pass_count": int(pass_count),
        "gap_at_first_pass": float(first_gap),
        "gap_at_current_pass": float(current_gap),
        "gap_closure_pct": round(float(gap_closure_pct), 4),
        "gap_delta_last_pass": float(gap_series[-1] - gap_series[-2]) if len(gap_series) >= 2 else 0.0,
        "gap_series": [round(g, 6) for g in gap_series],
        "allocated_series": [round(a, 6) for a in allocated_series],
        "allocated_cumulative": round(float(sum(allocated_series)), 6),
        "clipped_total_current": float(passes[-1].get("clipped_output_total", 0.0)),
        "unresolved_count_current": int(len(passes[-1].get("unresolved_positive_rows", []))),
        "unresolved_fuels_current": sorted(unresolved_fuels),
        "trend": trend,
    }


def _write_convergence_csv(
    *,
    pass_summary: dict[str, object],
    convergence: dict[str, object],
    output_path: Path | str | None = None,
) -> Path | None:
    """Append one convergence row to the running CSV at output_path."""
    if output_path is None:
        output_path = _resolve(RESULTS_RUNTIME_DIR) / "capacity_unmet_convergence.csv"
    path = _resolve(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp_utc": str(pass_summary.get("timestamp_utc", "")),
        "mode": str(pass_summary.get("mode", "")),
        "iteration_run_mode": str(pass_summary.get("iteration_run_mode", "")),
        "pass_count": int(convergence.get("pass_count", 0)),
        "gap_at_first_pass": float(convergence.get("gap_at_first_pass", 0.0)),
        "gap_at_current_pass": float(convergence.get("gap_at_current_pass", 0.0)),
        "gap_closure_pct": float(convergence.get("gap_closure_pct", 0.0)),
        "gap_delta_last_pass": float(convergence.get("gap_delta_last_pass", 0.0)),
        "allocated_cumulative": float(convergence.get("allocated_cumulative", 0.0)),
        "clipped_total_current": float(convergence.get("clipped_total_current", 0.0)),
        "unresolved_count_current": int(convergence.get("unresolved_count_current", 0)),
        "trend": str(convergence.get("trend", "unknown")),
        "unresolved_fuels_current": "; ".join(convergence.get("unresolved_fuels_current", [])),
    }
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
# State parsing helper
# ---------------------------------------------------------------------------

def _parse_runtime_capacity_additions_from_state(
    additions: dict[str, object] | None,
) -> dict[str, float]:
    """Normalize state capacity-addition payload into key->float map."""
    out: dict[str, float] = {}
    if not isinstance(additions, dict):
        return out
    for key, value in additions.items():
        numeric = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric):
            continue
        value_float = float(numeric)
        if abs(value_float) <= 0.0:
            continue
        out[str(key)] = value_float
    return out


# ---------------------------------------------------------------------------
# Product classification helpers
# ---------------------------------------------------------------------------

def _is_primary_esto_product(esto_product: str) -> bool:
    """Return True when ESTO product is classified as primary supply."""
    token = str(esto_product or "").strip()
    classification = supply_data_pipeline.ESTO_PRODUCT_CLASSIFICATION.get(token)
    if classification in {"primary", "secondary"}:
        return classification == "primary"
    return True


def _is_production_only_product(esto_product: str) -> bool:
    """Return True when only indigenous production (not transformation) may close a gap.

    Products in CAPACITY_UNMET_PRODUCTION_ONLY_PRODUCTS skip the transformation
    capacity lever entirely.  Any gap not covered by production headroom goes
    straight to import fallback so that e.g. LNG regasification is never given
    additional capacity just to fill a natural-gas shortfall.
    """
    allowlist = globals().get("CAPACITY_UNMET_PRODUCTION_ONLY_PRODUCTS", set())
    if not isinstance(allowlist, (set, list, tuple)):
        return False
    token = str(esto_product or "").strip().lower()
    return any(str(item or "").strip().lower() == token for item in allowlist)


# ---------------------------------------------------------------------------
# Cap / limit lookup helpers
# ---------------------------------------------------------------------------

def _lookup_module_capacity_upper_limit(
    *,
    economy: str,
    scenario: str,
    module: str,
) -> _ModuleCapRule | float | None:
    """Return raw cap rule or float for a module; caller resolves sentinels via _resolve_module_cap_rule."""
    root = CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS
    if not isinstance(root, dict):
        return None
    economy_payload = root.get(str(economy))
    if not isinstance(economy_payload, dict):
        economy_payload = root.get(_state_token(economy))
    if not isinstance(economy_payload, dict):
        lower_lookup = {
            _state_token(key): value
            for key, value in root.items()
            if isinstance(value, dict)
        }
        economy_payload = lower_lookup.get(_state_token(economy))
    if not isinstance(economy_payload, dict):
        return None

    scenario_payload = economy_payload.get(str(scenario))
    if not isinstance(scenario_payload, dict):
        scenario_payload = economy_payload.get(_state_token(scenario))
    if not isinstance(scenario_payload, dict):
        lower_lookup = {
            _state_token(key): value
            for key, value in economy_payload.items()
            if isinstance(value, dict)
        }
        scenario_payload = lower_lookup.get(_state_token(scenario))
    if not isinstance(scenario_payload, dict):
        return None

    value = scenario_payload.get(str(module))
    if value is None:
        lower_lookup = {
            _state_token(key): val
            for key, val in scenario_payload.items()
            if val is not None
        }
        value = lower_lookup.get(_state_token(module))
    if value is None:
        return None
    if isinstance(value, _ModuleCapRule):
        return value
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return max(float(numeric), 0.0)


def _lookup_production_upper_limit(
    *,
    economy: str,
    scenario: str,
    esto_product: str,
    baseline_production: float = 0.0,
) -> float | None:
    """Return optional product-level production cap for balanced iterative mode.

    Values may be raw floats or production-cap sentinels
    (KEEP_PRODUCTION_AT_BASE_YEAR, INCREASE_PRODUCTION_BY_PCT, etc.).
    When a sentinel is used, ``baseline_production`` (the current constrained
    production for this economy/product/year) is used as the reference level.
    """
    root = CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS
    if not isinstance(root, dict):
        return None
    economy_payload = root.get(str(economy))
    if not isinstance(economy_payload, dict):
        economy_payload = root.get(_state_token(economy))
    if not isinstance(economy_payload, dict):
        lower_lookup = {
            _state_token(key): value
            for key, value in root.items()
            if isinstance(value, dict)
        }
        economy_payload = lower_lookup.get(_state_token(economy))
    if not isinstance(economy_payload, dict):
        return None

    scenario_payload = economy_payload.get(str(scenario))
    if not isinstance(scenario_payload, dict):
        scenario_payload = economy_payload.get(_state_token(scenario))
    if not isinstance(scenario_payload, dict):
        lower_lookup = {
            _state_token(key): value
            for key, value in economy_payload.items()
            if isinstance(value, dict)
        }
        scenario_payload = lower_lookup.get(_state_token(scenario))
    if not isinstance(scenario_payload, dict):
        return None

    value = scenario_payload.get(str(esto_product))
    if value is None:
        lower_lookup = {
            _normalize_esto_product_for_match(key): val
            for key, val in scenario_payload.items()
            if val is not None
        }
        value = lower_lookup.get(_normalize_esto_product_for_match(esto_product))
    if value is None:
        return None
    # Accept production-cap sentinels (reuse _resolve_module_cap_rule with
    # baseline_production as the reference level).
    if isinstance(value, _ModuleCapRule):
        return _resolve_module_cap_rule(value, float(baseline_production))
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return max(float(numeric), 0.0)


# ---------------------------------------------------------------------------
# Process catalog lookup builders
# ---------------------------------------------------------------------------

def _build_module_baseline_output_lookup(process_catalog: pd.DataFrame) -> dict[tuple[str, str, int], float]:
    """Return normalized lookup of baseline module output totals by economy/module/year."""
    if process_catalog is None or process_catalog.empty:
        return {}
    grouped = (
        process_catalog.groupby(["economy", "module", "year"], as_index=False)["module_total_output"]
        .sum(min_count=1)
    )
    out: dict[tuple[str, str, int], float] = {}
    for _, row in grouped.iterrows():
        year_value = pd.to_numeric(row.get("year"), errors="coerce")
        if pd.isna(year_value):
            continue
        output_value = pd.to_numeric(row.get("module_total_output"), errors="coerce")
        output_float = 0.0 if pd.isna(output_value) else max(float(output_value), 0.0)
        key = (
            _state_token(row.get("economy")),
            _state_token(row.get("module")),
            int(year_value),
        )
        out[key] = output_float
    return out


def _build_module_added_output_lookup(
    additions: dict[str, float],
) -> dict[tuple[str, str, str, int], float]:
    """Aggregate process-level capacity additions to module-year totals."""
    out: dict[tuple[str, str, str, int], float] = {}
    if not isinstance(additions, dict):
        return out
    for key, value in additions.items():
        parts = str(key or "").split("|")
        if len(parts) != 6:
            continue
        economy, scenario, module, _process, _instance, year_text = parts
        year_value = pd.to_numeric(year_text, errors="coerce")
        if pd.isna(year_value):
            continue
        amount = pd.to_numeric(value, errors="coerce")
        if pd.isna(amount):
            continue
        out_key = (_state_token(economy), _state_token(scenario), _state_token(module), int(year_value))
        out[out_key] = out.get(out_key, 0.0) + max(float(amount), 0.0)
    return out


# ---------------------------------------------------------------------------
# Unresolved-positive policy helpers
# ---------------------------------------------------------------------------

def _normalize_esto_product_token(value: object) -> str:
    """Normalize ESTO product token for case-insensitive matching."""
    return str(value or "").strip().lower()


def _resolve_unresolved_positive_policy() -> str:
    """Return unresolved-positive policy token with validation."""
    policy = str(CAPACITY_UNMET_UNRESOLVED_POSITIVE_POLICY or "").strip().lower() or "fail"
    valid = {"fail", "imports_fallback", "track_only"}
    if policy not in valid:
        raise ValueError(
            "Invalid CAPACITY_UNMET_UNRESOLVED_POSITIVE_POLICY="
            f"{CAPACITY_UNMET_UNRESOLVED_POSITIVE_POLICY!r}. Valid values: {sorted(valid)}"
        )
    return policy


def _is_unresolved_allowlisted(esto_product: object) -> bool:
    """Return True when unresolved fuel is allowlisted for non-fatal handling."""
    allowlist = globals().get("CAPACITY_UNMET_UNRESOLVED_POSITIVE_ALLOWLIST", set())
    if not isinstance(allowlist, (set, list, tuple)):
        return False
    normalized = {_normalize_esto_product_token(item) for item in allowlist}
    return _normalize_esto_product_token(esto_product) in normalized


def _save_unresolved_positive_report(
    *,
    mode: str,
    unresolved_rows: list[dict[str, object]],
) -> tuple[Path, Path]:
    """Persist unresolved-positive diagnostics to CSV and JSON artifacts."""
    output_root = _resolve(RESULTS_CHECKS_DIR)
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / f"{mode}_unresolved_positive_residuals.csv"
    json_path = output_root / f"{mode}_unresolved_positive_residuals.json"
    frame = pd.DataFrame(unresolved_rows)
    _sort_output_frame_for_csv(frame).to_csv(csv_path, index=False)
    payload = {
        "mode": mode,
        "count": int(len(unresolved_rows)),
        "rows": unresolved_rows,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return csv_path, json_path


def _is_no_eligible_transformation_producer_case(row: dict[str, object]) -> bool:
    """Return True when unresolved row reflects lack of transformation producer mapping."""
    reason = str(row.get("reason") or "").strip().lower()
    return "no eligible transformation process outputs this fuel in this year" in reason


def _split_unresolved_rows_by_policy(
    unresolved_rows: list[dict[str, object]],
    *,
    mode: str = "",
) -> tuple[list[dict[str, object]], list[dict[str, object]], str]:
    """Split unresolved rows into fatal vs handled rows according to policy/allowlist."""
    policy = _resolve_unresolved_positive_policy()
    if not unresolved_rows:
        return [], [], policy
    fatal_rows: list[dict[str, object]] = []
    handled_rows: list[dict[str, object]] = []
    for row in unresolved_rows:
        entry = dict(row)
        allowlisted = bool(_is_unresolved_allowlisted(entry.get("esto_product")))
        no_producer_case = _is_no_eligible_transformation_producer_case(entry)
        entry["allowlisted"] = allowlisted
        # Only in balanced mode, always allow imports-fallback behavior for
        # "no eligible producer" rows so LEAP can satisfy via imports.
        if no_producer_case and str(mode).strip().lower() == "capacity_unmet_iterative_balanced":
            entry["policy_applied"] = "imports_fallback_no_producer"
            handled_rows.append(entry)
            continue
        if policy == "fail" and not allowlisted:
            entry["policy_applied"] = "fail"
            fatal_rows.append(entry)
            continue
        entry["policy_applied"] = (
            "imports_fallback_allowlist"
            if policy == "fail" and allowlisted
            else policy
        )
        handled_rows.append(entry)
    return fatal_rows, handled_rows, policy


# ---------------------------------------------------------------------------
# Allocation helpers
# ---------------------------------------------------------------------------

def _build_capacity_process_catalog(
    process_records: list[dict],
) -> tuple[pd.DataFrame, list[str]]:
    """Build per-process output/yield rows keyed by economy/product/year."""
    if not process_records:
        return pd.DataFrame(), []
    label_to_product = _build_label_to_esto_product_lookup()
    rows: list[dict[str, object]] = []
    unmapped_labels: set[str] = set()
    instance_counter: dict[tuple[str, str, str], int] = {}
    for record_index, record in enumerate(process_records):
        economy = str(record.get("economy") or "").strip()
        module = str(record.get("sector_title") or "").strip() or "__unknown_module__"
        process = str(record.get("process_name") or "").strip() or "__unknown_process__"
        if not economy:
            continue
        counter_key = (_state_token(economy), _state_token(module), _state_token(process))
        instance_counter[counter_key] = int(instance_counter.get(counter_key, 0)) + 1
        instance = int(instance_counter[counter_key])

        product_output_by_year: dict[tuple[str, int], float] = {}
        total_output_by_year: dict[int, float] = {}
        for label, year, value in _iter_year_value_items(
            record.get("output_values"),
            BASE_YEAR,
            FINAL_YEAR,
        ):
            numeric = max(float(value), 0.0)
            if numeric <= 0.0:
                continue
            product = (
                label_to_product.get(label)
                or label_to_product.get(label.lower())
                or label_to_product.get(_normalize_label_for_lookup(label))
            )
            if not product:
                unmapped_labels.add(str(label))
                continue
            product_key = str(product)
            product_output_by_year[(product_key, int(year))] = (
                product_output_by_year.get((product_key, int(year)), 0.0) + numeric
            )
            total_output_by_year[int(year)] = total_output_by_year.get(int(year), 0.0) + numeric

        for (product_key, year), product_output in product_output_by_year.items():
            total_output = total_output_by_year.get(int(year), 0.0)
            if total_output <= 0.0:
                continue
            output_yield = float(product_output) / float(total_output)
            if output_yield <= 0.0:
                continue
            rows.append(
                {
                    "record_index": int(record_index),
                    "economy": economy,
                    "module": module,
                    "process": process,
                    "instance": int(instance),
                    "esto_product": product_key,
                    "year": int(year),
                    "product_output": float(product_output),
                    "module_total_output": float(total_output),
                    "yield": float(output_yield),
                }
            )

    if not rows:
        return pd.DataFrame(), sorted(unmapped_labels)
    catalog = pd.DataFrame(rows).sort_values(
        ["economy", "module", "process", "instance", "esto_product", "year"]
    ).reset_index(drop=True)
    return catalog, sorted(unmapped_labels)


def _validate_capacity_priority_coverage(process_catalog: pd.DataFrame) -> None:
    """Raise if any ESTO product is produced by 2+ modules but has no entry in CAPACITY_UNMET_PRIORITY_BY_PRODUCT.

    Products produced by only one module are unambiguous — that module is the implicit default.
    Products produced by multiple modules require an explicit priority ordering so the
    allocation loop doesn't silently depend on sort order.
    """
    if process_catalog.empty:
        return

    modules_by_product: dict[str, set[str]] = {}
    for _, row in process_catalog[["esto_product", "module"]].drop_duplicates().iterrows():
        product = str(row["esto_product"]).strip()
        module = str(row["module"]).strip()
        if not product or not module:
            continue
        modules_by_product.setdefault(product, set()).add(module)

    missing: dict[str, list[str]] = {}
    for product, modules in modules_by_product.items():
        if len(modules) <= 1:
            continue
        if _resolve_capacity_priority_modules(product):
            continue
        missing[product] = sorted(modules)

    if not missing:
        return

    lines = [
        "capacity_unmet_iterative_balanced: the following ESTO products are produced by "
        "multiple transformation modules but have no entry in CAPACITY_UNMET_PRIORITY_BY_PRODUCT.\n"
        "Add them to CAPACITY_UNMET_PRIORITY_BY_PRODUCT with an ordered list of modules so the "
        "allocation is deterministic.\n"
    ]
    for product, modules in sorted(missing.items()):
        module_list = ", ".join(f'"{m}"' for m in modules)
        lines.append(f'  "{product}": [{module_list}],')
    raise ValueError("\n".join(lines))


def _resolve_capacity_priority_modules(esto_product: str) -> list[str]:
    """Return ordered priority module names configured for one ESTO product."""
    candidates = [
        CAPACITY_UNMET_PRIORITY_BY_PRODUCT.get(str(esto_product)),
        CAPACITY_UNMET_PRIORITY_BY_PRODUCT.get(str(esto_product).lower()),
        CAPACITY_UNMET_PRIORITY_BY_PRODUCT.get(_normalize_esto_product_for_match(esto_product)),
    ]
    for item in candidates:
        if isinstance(item, list) and item:
            return [str(value).strip() for value in item if str(value or "").strip()]
    return []


def _rank_capacity_candidates(
    candidate_rows: pd.DataFrame,
    esto_product: str,
) -> list[dict[str, object]]:
    """Return ranked candidate process rows for one fuel/year."""
    if candidate_rows.empty:
        return []
    ordered: list[dict[str, object]] = []
    remaining = candidate_rows.copy()
    remaining["module_key"] = remaining["module"].astype(str).str.strip().str.lower()
    priority_modules = _resolve_capacity_priority_modules(esto_product)
    for module_name in priority_modules:
        module_key = str(module_name).strip().lower()
        if not module_key:
            continue
        matched = remaining[remaining["module_key"] == module_key].copy()
        if matched.empty:
            continue
        matched = matched.sort_values(
            ["product_output", "module_total_output"],
            ascending=False,
        )
        ordered.extend(matched.to_dict("records"))
        remaining = remaining[remaining["module_key"] != module_key].copy()
    if not remaining.empty:
        remaining = remaining.sort_values(
            ["product_output", "module_total_output"],
            ascending=False,
        )
        ordered.extend(remaining.to_dict("records"))
    return ordered


def _collect_observed_trade_from_supply_results(
    *,
    scenario_pairs: list[tuple[str, str]],
    label_to_product: dict[str, str],
    results_dir: Path | str | Iterable[Path | str],
    include_exports: bool,
) -> tuple[pd.DataFrame, dict[str, object], list[dict[str, object]]]:
    """Collect observed imports/exports from the current run's balance-table CSVs."""
    from codebase import supply_reconciliation_workflow as _srw  # lazy — breaks circular import
    return _srw._collect_observed_trade_from_balance_tables(
        scenario_pairs=scenario_pairs,
        results_dir=results_dir,
        include_exports=include_exports,
    )


# ---------------------------------------------------------------------------
# Main allocation algorithms
# ---------------------------------------------------------------------------

def _run_capacity_unmet_iterative_pass(
    *,
    reconciliation_table: pd.DataFrame,
    process_records: list[dict],
    economies: Iterable[str],
    scenarios: Iterable[str],
    resolve_scenario_key: Callable[[pd.DataFrame, str], str],
    results_dir: Path | str | Iterable[Path | str] = CAPACITY_UNMET_RESULTS_DIR,
    state_path: Path | str = CAPACITY_UNMET_STATE_PATH,
    allow_same_results_reuse: bool = CAPACITY_UNMET_ALLOW_SAME_RESULTS_REUSE,
) -> dict[str, object]:
    """Compute one manual unmet-capacity pass and persist cumulative state."""
    global _CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS
    if reconciliation_table.empty:
        raise ValueError("Cannot run capacity_unmet_iterative with empty reconciliation table.")

    process_catalog, unmapped_process_labels = _build_capacity_process_catalog(process_records)
    if process_catalog.empty:
        raise ValueError(
            "capacity_unmet_iterative mode requires transformation process output rows "
            "to infer fuel yields; none were found."
        )
    if unmapped_process_labels:
        preview = ", ".join(unmapped_process_labels[:12])
        print(
            "[WARN] Some transformation output labels could not be mapped to ESTO products "
            f"for capacity_unmet_iterative: {preview}"
        )

    run_mode = _resolve_capacity_unmet_pass_mode()
    state = _read_capacity_unmet_state(state_path=state_path, run_mode=run_mode)
    cumulative_capacity_map = _parse_runtime_capacity_additions_from_state(
        state.get("cumulative_capacity_additions")
    )
    cumulative_output_map = _parse_runtime_capacity_additions_from_state(
        state.get("cumulative_output_additions")
    )
    module_baseline_output_lookup = _build_module_baseline_output_lookup(process_catalog)
    module_added_output_lookup = _build_module_added_output_lookup(cumulative_capacity_map)
    last_signatures = state.get("last_results_signatures")
    if not isinstance(last_signatures, dict):
        last_signatures = {}

    reconciliation = reconciliation_table.copy()
    reconciliation["scenario_key"] = (
        reconciliation["scenario"].astype(str).str.strip().str.lower()
    )
    reconciliation["adjusted_imports"] = pd.to_numeric(
        reconciliation.get("adjusted_imports"), errors="coerce"
    ).fillna(0.0)
    reconciliation["max_transformation_output"] = pd.to_numeric(
        reconciliation.get("max_transformation_output"), errors="coerce"
    )
    reconciliation["constrained_transformation_output"] = pd.to_numeric(
        reconciliation.get("constrained_transformation_output"), errors="coerce"
    ).fillna(0.0)

    scenario_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for economy in [str(item).strip() for item in economies if str(item).strip()]:
        for scenario in [str(item).strip() for item in scenarios if str(item).strip()]:
            scenario_key = _state_token(
                resolve_scenario_key(reconciliation_table, scenario)
            )
            pair = (str(economy), scenario_key)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            scenario_pairs.append(pair)
    if not scenario_pairs:
        raise ValueError("capacity_unmet_iterative mode needs at least one economy/scenario pair.")

    label_to_product = _build_label_to_esto_product_lookup()
    observed_trade, signature_map, unmatched_result_fuels = _collect_observed_trade_from_supply_results(
        scenario_pairs=scenario_pairs,
        label_to_product=label_to_product,
        results_dir=results_dir,
        include_exports=False,
    )

    if (
        not allow_same_results_reuse
        and signature_map
        and last_signatures
        and signature_map == last_signatures
    ):
        print(
            "[WARN] capacity_unmet_iterative mode detected no new LEAP results artifacts since the "
            "previous pass. Continuing with reused results artifacts. "
            "Import workbook into LEAP, recalculate, refresh results tables, then rerun "
            "to use fresh results."
        )

    observed_imports = observed_trade
    if observed_imports.empty:
        raise ValueError(
            "capacity_unmet_iterative mode could not parse any observed imports from supply "
            f"results sheets {CAPACITY_UNMET_IMPORT_SHEETS} in '{_resolve(results_dir)}'."
        )

    requested_scenarios = {scenario for _, scenario in scenario_pairs}
    requested_economies = {economy for economy, _ in scenario_pairs}
    baseline_imports = reconciliation[
        reconciliation["economy"].astype(str).isin(requested_economies)
        & reconciliation["scenario_key"].astype(str).isin(requested_scenarios)
    ][
        [
            "economy",
            "scenario_key",
            "esto_product",
            "year",
            "adjusted_imports",
            "max_transformation_output",
            "constrained_transformation_output",
        ]
    ].copy()
    baseline_imports = baseline_imports.rename(columns={"scenario_key": "scenario"})
    if baseline_imports.empty:
        raise ValueError(
            "capacity_unmet_iterative mode found no reconciliation rows for run economy/scenario scope."
        )

    unmet_table = baseline_imports.merge(
        observed_imports,
        on=["economy", "scenario", "esto_product", "year"],
        how="outer",
    )
    unmet_table["adjusted_imports"] = pd.to_numeric(
        unmet_table.get("adjusted_imports"), errors="coerce"
    ).fillna(0.0)
    unmet_table["observed_imports"] = pd.to_numeric(
        unmet_table.get("observed_imports"), errors="coerce"
    ).fillna(0.0)
    unmet_table["max_transformation_output"] = pd.to_numeric(
        unmet_table.get("max_transformation_output"), errors="coerce"
    )
    unmet_table["constrained_transformation_output"] = pd.to_numeric(
        unmet_table.get("constrained_transformation_output"), errors="coerce"
    ).fillna(0.0)
    unmet_table["unmet_proxy"] = (
        unmet_table["observed_imports"] - unmet_table["adjusted_imports"]
    ).clip(lower=0.0)

    allocation_rows: list[dict[str, object]] = []
    clipping_rows: list[dict[str, object]] = []
    unresolved_rows: list[dict[str, object]] = []
    pass_capacity_additions: dict[str, float] = {}
    pass_output_additions: dict[str, float] = {}

    unmet_candidates = unmet_table[unmet_table["unmet_proxy"] > 0.0].copy()
    unmet_candidates = unmet_candidates.sort_values(
        ["economy", "scenario", "esto_product", "year"]
    )
    for _, row in unmet_candidates.iterrows():
        economy = str(row.get("economy") or "").strip()
        scenario_key = str(row.get("scenario") or "").strip().lower()
        esto_product = str(row.get("esto_product") or "").strip()
        year = int(pd.to_numeric(row.get("year"), errors="coerce"))
        unmet_value = max(float(row.get("unmet_proxy", 0.0)), 0.0)
        if not economy or not scenario_key or not esto_product or unmet_value <= 0.0:
            continue

        output_state_key = _output_addition_state_key(
            economy=economy,
            scenario=scenario_key,
            esto_product=esto_product,
            year=year,
        )
        prior_added_output = float(cumulative_output_map.get(output_state_key, 0.0))
        cap_value = pd.to_numeric(row.get("max_transformation_output"), errors="coerce")
        constrained_value = max(float(row.get("constrained_transformation_output", 0.0)), 0.0)
        if pd.isna(cap_value):
            headroom = float("inf")
        else:
            headroom = max(float(cap_value) - constrained_value - prior_added_output, 0.0)

        if headroom <= 0.0:
            clipping_rows.append(
                {
                    "economy": economy,
                    "scenario": scenario_key,
                    "esto_product": esto_product,
                    "year": int(year),
                    "requested_output_uplift": float(unmet_value),
                    "allocated_output_uplift": 0.0,
                    "clipped_output_uplift": float(unmet_value),
                    "reason": "No remaining cap headroom after constrained output + prior additions.",
                }
            )
            continue

        requested_output = float(unmet_value)
        allocatable_output = min(requested_output, headroom)
        if allocatable_output < requested_output:
            clipping_rows.append(
                {
                    "economy": economy,
                    "scenario": scenario_key,
                    "esto_product": esto_product,
                    "year": int(year),
                    "requested_output_uplift": float(requested_output),
                    "allocated_output_uplift": float(allocatable_output),
                    "clipped_output_uplift": float(requested_output - allocatable_output),
                    "reason": "Requested uplift exceeded max_transformation_output headroom.",
                }
            )
        if allocatable_output <= 0.0:
            continue

        candidates = process_catalog[
            (process_catalog["economy"].astype(str) == economy)
            & (process_catalog["esto_product"].astype(str) == esto_product)
            & (process_catalog["year"].astype(int) == int(year))
        ].copy()
        if candidates.empty:
            unresolved_rows.append(
                {
                    "economy": economy,
                    "scenario": scenario_key,
                    "esto_product": esto_product,
                    "year": int(year),
                    "unresolved_output_uplift": float(allocatable_output),
                    "reason": "No eligible transformation process outputs this fuel in this year.",
                }
            )
            continue

        ranked = _rank_capacity_candidates(candidates, esto_product)
        remaining_output = float(allocatable_output)
        for candidate in ranked:
            if remaining_output <= 0.0:
                break
            module_name = str(candidate.get("module") or "")
            _raw_cap_rule = _lookup_module_capacity_upper_limit(
                economy=economy,
                scenario=scenario_key,
                module=module_name,
            )
            module_headroom = float("inf")
            if _raw_cap_rule is not None:
                baseline_module_output = module_baseline_output_lookup.get(
                    (_state_token(economy), _state_token(module_name), int(year)),
                    0.0,
                )
                prior_module_added = module_added_output_lookup.get(
                    (_state_token(economy), _state_token(scenario_key), _state_token(module_name), int(year)),
                    0.0,
                )
                module_upper_limit = _resolve_module_cap_rule(_raw_cap_rule, baseline_module_output)
                if module_upper_limit is not None:
                    module_headroom = max(
                        float(module_upper_limit) - float(baseline_module_output) - float(prior_module_added),
                        0.0,
                    )
            if module_headroom <= 0.0:
                clipping_rows.append(
                    {
                        "economy": economy,
                        "scenario": scenario_key,
                        "esto_product": esto_product,
                        "year": int(year),
                        "requested_output_uplift": float(remaining_output),
                        "allocated_output_uplift": 0.0,
                        "clipped_output_uplift": float(remaining_output),
                        "reason": (
                            f"Module upper limit reached for '{module_name}'. "
                            "Set CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS to adjust."
                        ),
                    }
                )
                continue
            output_yield = pd.to_numeric(candidate.get("yield"), errors="coerce")
            if pd.isna(output_yield) or float(output_yield) <= 0.0:
                continue
            allocated_output = min(float(remaining_output), float(module_headroom))
            if allocated_output <= 0.0:
                continue
            capacity_increment = float(allocated_output) / float(output_yield)
            cap_key = _capacity_addition_state_key(
                economy=economy,
                scenario=scenario_key,
                module=module_name,
                process=str(candidate.get("process") or ""),
                instance=int(candidate.get("instance") or 1),
                year=year,
            )
            pass_capacity_additions[cap_key] = pass_capacity_additions.get(cap_key, 0.0) + capacity_increment
            module_added_key = (_state_token(economy), _state_token(scenario_key), _state_token(module_name), int(year))
            module_added_output_lookup[module_added_key] = (
                module_added_output_lookup.get(module_added_key, 0.0) + float(capacity_increment)
            )
            pass_output_additions[output_state_key] = pass_output_additions.get(output_state_key, 0.0) + allocated_output
            allocation_rows.append(
                {
                    "economy": economy,
                    "scenario": scenario_key,
                    "esto_product": esto_product,
                    "year": int(year),
                    "module": str(candidate.get("module") or ""),
                    "process": str(candidate.get("process") or ""),
                    "instance": int(candidate.get("instance") or 1),
                    "allocated_output_uplift": float(allocated_output),
                    "yield": float(output_yield),
                    "capacity_increment": float(capacity_increment),
                    "priority_modules": _resolve_capacity_priority_modules(esto_product),
                }
            )
            remaining_output -= allocated_output
        if remaining_output > 1e-9:
            unresolved_rows.append(
                {
                    "economy": economy,
                    "scenario": scenario_key,
                    "esto_product": esto_product,
                    "year": int(year),
                    "unresolved_output_uplift": float(remaining_output),
                    "reason": "Eligible processes found but no positive yield available.",
                }
            )

    fatal_unresolved_rows, handled_unresolved_rows, unresolved_policy = _split_unresolved_rows_by_policy(
        unresolved_rows,
        mode="capacity_unmet_iterative",
    )
    unresolved_csv_path: Path | None = None
    unresolved_json_path: Path | None = None
    if handled_unresolved_rows:
        unresolved_csv_path, unresolved_json_path = _save_unresolved_positive_report(
            mode="capacity_unmet_iterative",
            unresolved_rows=handled_unresolved_rows,
        )
        print(
            "[CAPACITY_UNMET_ITERATIVE][WARN] Unresolved positive residuals handled by policy "
            f"'{unresolved_policy}': {len(handled_unresolved_rows)} "
            f"(csv={unresolved_csv_path}, json={unresolved_json_path})"
        )
    if fatal_unresolved_rows:
        preview = fatal_unresolved_rows[:12]
        raise RuntimeError(
            "capacity_unmet_iterative could not allocate unmet imports to eligible transformation "
            f"processes. Examples: {preview}"
        )

    for key, value in pass_capacity_additions.items():
        cumulative_capacity_map[key] = cumulative_capacity_map.get(key, 0.0) + float(value)
    for key, value in pass_output_additions.items():
        cumulative_output_map[key] = cumulative_output_map.get(key, 0.0) + float(value)

    _CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS = dict(cumulative_capacity_map)
    state["cumulative_capacity_additions"] = cumulative_capacity_map
    state["cumulative_output_additions"] = cumulative_output_map
    state["last_results_signatures"] = signature_map

    unmet_total = float(unmet_candidates["unmet_proxy"].sum()) if not unmet_candidates.empty else 0.0
    allocated_total = float(sum(pass_output_additions.values()))
    clipped_total = float(
        sum(float(item.get("clipped_output_uplift", 0.0)) for item in clipping_rows)
    )
    pass_summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "capacity_unmet_iterative",
        "iteration_run_mode": run_mode,
        "state_path": str(_resolve(state_path)),
        "results_signature_used": signature_map,
        "baseline_import_total": float(unmet_table["adjusted_imports"].sum()),
        "observed_import_total": float(unmet_table["observed_imports"].sum()),
        "unmet_proxy_total": unmet_total,
        "allocated_output_total": allocated_total,
        "clipped_output_total": clipped_total,
        "allocation_rows": allocation_rows,
        "clipping_rows": clipping_rows,
        "unresolved_positive_rows": handled_unresolved_rows,
        "unresolved_positive_policy": unresolved_policy,
        "unresolved_positive_csv": str(unresolved_csv_path) if unresolved_csv_path else "",
        "unresolved_positive_json": str(unresolved_json_path) if unresolved_json_path else "",
        "unmatched_results_fuels": unmatched_result_fuels,
        "next_manual_step": (
            "Import generated workbook into LEAP, recalculate, refresh results tables, then rerun."
        ),
    }
    pass_history = state.get("passes")
    if not isinstance(pass_history, list):
        pass_history = []
    pass_history.append(pass_summary)
    state["passes"] = pass_history[-50:]
    convergence = _compute_convergence_metrics(state["passes"])
    pass_summary["convergence"] = convergence
    convergence_csv = _write_convergence_csv(pass_summary=pass_summary, convergence=convergence)
    pass_delta = {
        "pass_index": len(state["passes"]) - 1,
        "timestamp_utc": pass_summary.get("timestamp_utc", ""),
        "mode": pass_summary.get("mode", ""),
        "pre_pass_signatures": last_signatures,
        "capacity_additions": dict(pass_capacity_additions),
        "output_additions": dict(pass_output_additions),
        "primary_additions": {},
        "export_adjustments": {},
    }
    _delta_history = state.get("pass_deltas")
    if not isinstance(_delta_history, list):
        _delta_history = []
    _delta_history.append(pass_delta)
    state["pass_deltas"] = _delta_history[-50:]
    persisted_path = _write_capacity_unmet_state(state, state_path=state_path)

    print("\n" + "=" * 96)
    print("[CAPACITY_UNMET_ITERATIVE] Pass summary")
    print(f"[CAPACITY_UNMET_ITERATIVE] State file: {persisted_path}")
    print(
        "[CAPACITY_UNMET_ITERATIVE] Baseline imports="
        f"{pass_summary['baseline_import_total']:.3f}, observed imports={pass_summary['observed_import_total']:.3f}, "
        f"unmet proxy={pass_summary['unmet_proxy_total']:.3f}"
    )
    print(
        "[CAPACITY_UNMET_ITERATIVE] Allocated output uplift="
        f"{allocated_total:.3f}, clipped={clipped_total:.3f}, allocations={len(allocation_rows)}"
    )
    if clipping_rows:
        print(f"[CAPACITY_UNMET_ITERATIVE][WARN] Clipped rows: {len(clipping_rows)}")
        for item in clipping_rows[:20]:
            print(
                "  - economy={economy} scenario={scenario} fuel={fuel} year={year} "
                "requested={requested:.3f} clipped={clipped:.3f} reason={reason}".format(
                    economy=item.get("economy"),
                    scenario=item.get("scenario"),
                    fuel=item.get("esto_product"),
                    year=item.get("year"),
                    requested=float(item.get("requested_output_uplift", 0.0)),
                    clipped=float(item.get("clipped_output_uplift", 0.0)),
                    reason=item.get("reason"),
                )
            )
        if len(clipping_rows) > 20:
            print(f"  ... plus {len(clipping_rows) - 20} more clipping rows")
    if unmatched_result_fuels:
        print(
            "[CAPACITY_UNMET_ITERATIVE][WARN] Unmapped Fuel labels in results sheets: "
            f"{len(unmatched_result_fuels)}"
        )
    print(
        "[CAPACITY_UNMET_ITERATIVE] Convergence: "
        f"pass {convergence['pass_count']}, gap={convergence['gap_at_current_pass']:.3f}, "
        f"closure={convergence['gap_closure_pct']:.1f}%, trend={convergence['trend']}"
        + (f", convergence CSV: {convergence_csv}" if convergence_csv else "")
    )
    print(
        "[CAPACITY_UNMET_ITERATIVE] Next step: "
        "Import workbook into LEAP, recalc, refresh results tables, rerun this workflow."
    )
    print("=" * 96 + "\n")
    return pass_summary


def _run_capacity_unmet_iterative_balanced_pass(
    *,
    reconciliation_table: pd.DataFrame,
    process_records: list[dict],
    economies: Iterable[str],
    scenarios: Iterable[str],
    resolve_scenario_key: Callable[[pd.DataFrame, str], str],
    results_dir: Path | str | Iterable[Path | str] = CAPACITY_UNMET_RESULTS_DIR,
    state_path: Path | str = CAPACITY_UNMET_STATE_PATH,
    allow_same_results_reuse: bool = CAPACITY_UNMET_ALLOW_SAME_RESULTS_REUSE,
) -> dict[str, object]:
    """Compute one iterative pass using observed imports gaps as unmet proxy."""
    global _CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS
    global _CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS
    global _CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS
    if reconciliation_table.empty:
        raise ValueError("Cannot run capacity_unmet_iterative_balanced with empty reconciliation table.")

    process_catalog, unmapped_process_labels = _build_capacity_process_catalog(process_records)
    if process_catalog.empty:
        raise ValueError(
            "capacity_unmet_iterative_balanced mode requires transformation process output rows "
            "to infer fuel yields; none were found."
        )
    if unmapped_process_labels:
        preview = ", ".join(unmapped_process_labels[:12])
        print(
            "[WARN] Some transformation output labels could not be mapped to ESTO products "
            f"for capacity_unmet_iterative_balanced: {preview}"
        )

    _validate_capacity_priority_coverage(process_catalog)

    run_mode = _resolve_capacity_unmet_pass_mode()
    state = _read_capacity_unmet_state(state_path=state_path, run_mode=run_mode)
    cumulative_capacity_map = _parse_runtime_capacity_additions_from_state(
        state.get("cumulative_capacity_additions")
    )
    cumulative_output_map = _parse_runtime_capacity_additions_from_state(
        state.get("cumulative_output_additions")
    )
    cumulative_primary_map = _parse_runtime_capacity_additions_from_state(
        state.get("cumulative_primary_additions")
    )
    cumulative_export_map = _parse_runtime_capacity_additions_from_state(
        state.get("cumulative_export_adjustments")
    )
    module_baseline_output_lookup = _build_module_baseline_output_lookup(process_catalog)
    module_added_output_lookup = _build_module_added_output_lookup(cumulative_capacity_map)
    last_signatures = state.get("last_results_signatures")
    if not isinstance(last_signatures, dict):
        last_signatures = {}

    reconciliation = reconciliation_table.copy()
    reconciliation["scenario_key"] = (
        reconciliation["scenario"].astype(str).str.strip().str.lower()
    )
    reconciliation["adjusted_imports"] = pd.to_numeric(
        reconciliation.get("adjusted_imports"), errors="coerce"
    ).fillna(0.0)
    reconciliation["adjusted_exports"] = pd.to_numeric(
        reconciliation.get("adjusted_exports"), errors="coerce"
    ).fillna(0.0)
    reconciliation["max_transformation_output"] = pd.to_numeric(
        reconciliation.get("max_transformation_output"), errors="coerce"
    )
    reconciliation["constrained_transformation_output"] = pd.to_numeric(
        reconciliation.get("constrained_transformation_output"), errors="coerce"
    ).fillna(0.0)
    reconciliation["max_production"] = pd.to_numeric(
        reconciliation.get("max_production"), errors="coerce"
    )
    reconciliation["constrained_production"] = pd.to_numeric(
        reconciliation.get("constrained_production"), errors="coerce"
    ).fillna(0.0)

    scenario_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for economy in [str(item).strip() for item in economies if str(item).strip()]:
        for scenario in [str(item).strip() for item in scenarios if str(item).strip()]:
            scenario_key = _state_token(
                resolve_scenario_key(reconciliation_table, scenario)
            )
            pair = (str(economy), scenario_key)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            scenario_pairs.append(pair)
    if not scenario_pairs:
        raise ValueError("capacity_unmet_iterative_balanced needs at least one economy/scenario pair.")

    label_to_product = _build_label_to_esto_product_lookup()
    observed_trade, signature_map, unmatched_result_fuels = _collect_observed_trade_from_supply_results(
        scenario_pairs=scenario_pairs,
        label_to_product=label_to_product,
        results_dir=results_dir,
        include_exports=True,
    )
    if (
        not allow_same_results_reuse
        and signature_map
        and last_signatures
        and signature_map == last_signatures
    ):
        print(
            "[WARN] capacity_unmet_iterative_balanced detected no new LEAP results artifacts since the "
            "previous pass. Continuing with reused results artifacts. "
            "Import workbook into LEAP, recalculate, refresh results tables, then rerun "
            "to use fresh results."
        )
    if observed_trade.empty:
        raise ValueError(
            "capacity_unmet_iterative_balanced could not parse imports/exports from supply "
            f"results tables in '{_resolve(results_dir)}'."
        )
    observed_trade["observed_imports"] = pd.to_numeric(
        observed_trade.get("observed_imports"), errors="coerce"
    ).fillna(0.0)
    observed_trade["observed_exports"] = pd.to_numeric(
        observed_trade.get("observed_exports"), errors="coerce"
    ).fillna(0.0)
    observed_trade["observed_net_imports"] = (
        observed_trade["observed_imports"] - observed_trade["observed_exports"]
    )

    requested_scenarios = {scenario for _, scenario in scenario_pairs}
    requested_economies = {economy for economy, _ in scenario_pairs}
    baseline = reconciliation[
        reconciliation["economy"].astype(str).isin(requested_economies)
        & reconciliation["scenario_key"].astype(str).isin(requested_scenarios)
    ][
        [
            "economy",
            "scenario_key",
            "esto_product",
            "year",
            "adjusted_imports",
            "adjusted_exports",
            "max_transformation_output",
            "constrained_transformation_output",
            "max_production",
            "constrained_production",
        ]
    ].copy()
    baseline = baseline.rename(columns={"scenario_key": "scenario"})
    if baseline.empty:
        raise ValueError(
            "capacity_unmet_iterative_balanced found no reconciliation rows for run economy/scenario scope."
        )
    baseline["baseline_net_imports"] = (
        baseline["adjusted_imports"] - baseline["adjusted_exports"]
    )

    delta = baseline.merge(
        observed_trade[
            [
                "economy",
                "scenario",
                "esto_product",
                "year",
                "observed_imports",
                "observed_exports",
                "observed_net_imports",
            ]
        ],
        on=["economy", "scenario", "esto_product", "year"],
        how="left",
    )
    for column in [
        "adjusted_imports",
        "adjusted_exports",
        "baseline_net_imports",
        "observed_imports",
        "observed_exports",
        "observed_net_imports",
        "constrained_transformation_output",
        "constrained_production",
    ]:
        delta[column] = pd.to_numeric(delta.get(column), errors="coerce").fillna(0.0)
    delta["max_transformation_output"] = pd.to_numeric(
        delta.get("max_transformation_output"), errors="coerce"
    )
    delta["max_production"] = pd.to_numeric(delta.get("max_production"), errors="coerce")
    # Imports gap is the unmet proxy:
    # +ve: LEAP needed more imports than expected baseline -> uplift output/capacity.
    # -ve: LEAP needed fewer imports than expected baseline -> route to extra exports.
    delta["imports_gap"] = delta["observed_imports"] - delta["adjusted_imports"]

    positive_rows = delta[delta["imports_gap"] > 0.0].copy().sort_values(
        ["economy", "scenario", "esto_product", "year"]
    )
    negative_rows = delta[delta["imports_gap"] < 0.0].copy().sort_values(
        ["economy", "scenario", "esto_product", "year"]
    )

    allocation_rows: list[dict[str, object]] = []
    clipping_rows: list[dict[str, object]] = []
    unresolved_rows: list[dict[str, object]] = []
    export_rows: list[dict[str, object]] = []
    pass_capacity_additions: dict[str, float] = {}
    pass_output_additions: dict[str, float] = {}
    pass_primary_additions: dict[str, float] = {}
    pass_export_adjustments: dict[str, float] = {}

    for _, row in positive_rows.iterrows():
        economy = str(row.get("economy") or "").strip()
        scenario_key = str(row.get("scenario") or "").strip().lower()
        esto_product = str(row.get("esto_product") or "").strip()
        year = int(pd.to_numeric(row.get("year"), errors="coerce"))
        remaining_output = max(float(row.get("imports_gap", 0.0)), 0.0)
        if not economy or not scenario_key or not esto_product or remaining_output <= 0.0:
            continue

        if _is_primary_esto_product(esto_product):
            primary_key = _output_addition_state_key(
                economy=economy,
                scenario=scenario_key,
                esto_product=esto_product,
                year=year,
            )
            prior_primary = float(cumulative_primary_map.get(primary_key, 0.0))
            max_prod = pd.to_numeric(row.get("max_production"), errors="coerce")
            constrained_prod = max(float(row.get("constrained_production", 0.0)), 0.0)
            configured_max_prod = _lookup_production_upper_limit(
                economy=economy,
                scenario=scenario_key,
                esto_product=esto_product,
                baseline_production=constrained_prod,
            )
            if configured_max_prod is not None:
                if pd.isna(max_prod):
                    max_prod = float(configured_max_prod)
                else:
                    max_prod = min(float(max_prod), float(configured_max_prod))
            if pd.isna(max_prod):
                primary_headroom = float("inf")
            else:
                primary_headroom = max(float(max_prod) - constrained_prod - prior_primary, 0.0)
            primary_alloc = min(remaining_output, primary_headroom)
            if primary_alloc > 0.0:
                pass_primary_additions[primary_key] = pass_primary_additions.get(primary_key, 0.0) + primary_alloc
                allocation_rows.append(
                    {
                        "economy": economy,
                        "scenario": scenario_key,
                        "esto_product": esto_product,
                        "year": int(year),
                        "module": "Resources\\Primary",
                        "process": "Indigenous Production",
                        "instance": 1,
                        "allocated_output_uplift": float(primary_alloc),
                        "yield": 1.0,
                        "capacity_increment": float(primary_alloc),
                        "allocation_type": "primary_production",
                    }
                )
                remaining_output -= primary_alloc
            if primary_headroom < float(row.get("imports_gap", 0.0)):
                clipped = max(float(row.get("imports_gap", 0.0)) - primary_alloc, 0.0)
                if clipped > 0.0:
                    clipping_rows.append(
                        {
                            "economy": economy,
                            "scenario": scenario_key,
                            "esto_product": esto_product,
                            "year": int(year),
                            "requested_output_uplift": float(row.get("imports_gap", 0.0)),
                            "allocated_output_uplift": float(primary_alloc),
                            "clipped_output_uplift": float(clipped),
                            "reason": "Primary production capped by max_production headroom.",
                        }
                    )
        if remaining_output <= 0.0:
            continue

        # Production-only products skip the transformation lever entirely so
        # that e.g. LNG regasification never absorbs a natural-gas gap that
        # should come from the well.  Any residual goes to import fallback via
        # the unresolved_rows path below.
        if _is_production_only_product(esto_product):
            unresolved_rows.append(
                {
                    "economy": economy,
                    "scenario": scenario_key,
                    "esto_product": esto_product,
                    "year": int(year),
                    "unresolved_output_uplift": float(remaining_output),
                    "reason": (
                        "Production-only product: transformation lever skipped "
                        f"(see CAPACITY_UNMET_PRODUCTION_ONLY_PRODUCTS). "
                        f"Remaining gap of {remaining_output:.3f} routed to import fallback."
                    ),
                }
            )
            continue

        output_state_key = _output_addition_state_key(
            economy=economy,
            scenario=scenario_key,
            esto_product=esto_product,
            year=year,
        )
        prior_added_output = float(cumulative_output_map.get(output_state_key, 0.0))
        cap_value = pd.to_numeric(row.get("max_transformation_output"), errors="coerce")
        constrained_value = max(float(row.get("constrained_transformation_output", 0.0)), 0.0)
        if pd.isna(cap_value):
            headroom = float("inf")
        else:
            headroom = max(float(cap_value) - constrained_value - prior_added_output, 0.0)
        allocatable_output = min(remaining_output, headroom)
        if allocatable_output < remaining_output:
            clipping_rows.append(
                {
                    "economy": economy,
                    "scenario": scenario_key,
                    "esto_product": esto_product,
                    "year": int(year),
                    "requested_output_uplift": float(remaining_output),
                    "allocated_output_uplift": float(allocatable_output),
                    "clipped_output_uplift": float(remaining_output - allocatable_output),
                    "reason": "Transformation output capped by max_transformation_output headroom.",
                }
            )
        if allocatable_output <= 0.0:
            if remaining_output > 0.0:
                unresolved_rows.append(
                    {
                        "economy": economy,
                        "scenario": scenario_key,
                        "esto_product": esto_product,
                        "year": int(year),
                        "unresolved_output_uplift": float(remaining_output),
                        "reason": "No remaining transformation headroom after caps.",
                    }
                )
            continue

        candidates = process_catalog[
            (process_catalog["economy"].astype(str) == economy)
            & (process_catalog["esto_product"].astype(str) == esto_product)
            & (process_catalog["year"].astype(int) == int(year))
        ].copy()
        if candidates.empty:
            unresolved_rows.append(
                {
                    "economy": economy,
                    "scenario": scenario_key,
                    "esto_product": esto_product,
                    "year": int(year),
                    "unresolved_output_uplift": float(allocatable_output),
                    "reason": "No eligible transformation process outputs this fuel in this year.",
                }
            )
            continue
        ranked = _rank_capacity_candidates(candidates, esto_product)
        remaining_transform = float(allocatable_output)
        for candidate in ranked:
            if remaining_transform <= 0.0:
                break
            module_name = str(candidate.get("module") or "")
            output_yield = pd.to_numeric(candidate.get("yield"), errors="coerce")
            if pd.isna(output_yield) or float(output_yield) <= 0.0:
                continue
            output_yield_value = float(output_yield)
            cap_key = _capacity_addition_state_key(
                economy=economy,
                scenario=scenario_key,
                module=module_name,
                process=str(candidate.get("process") or ""),
                instance=int(candidate.get("instance") or 1),
                year=year,
            )
            # Use max-style capacity across co-products for a process-year:
            # if this process already got capacity this pass for another fuel, reuse it first.
            existing_pass_capacity = float(pass_capacity_additions.get(cap_key, 0.0))
            reusable_output = min(float(remaining_transform), existing_pass_capacity * output_yield_value)
            if reusable_output > 0.0:
                pass_output_additions[output_state_key] = (
                    pass_output_additions.get(output_state_key, 0.0) + float(reusable_output)
                )
                allocation_rows.append(
                    {
                        "economy": economy,
                        "scenario": scenario_key,
                        "esto_product": esto_product,
                        "year": int(year),
                        "module": str(candidate.get("module") or ""),
                        "process": str(candidate.get("process") or ""),
                        "instance": int(candidate.get("instance") or 1),
                        "allocated_output_uplift": float(reusable_output),
                        "yield": float(output_yield_value),
                        "capacity_increment": 0.0,
                        "priority_modules": _resolve_capacity_priority_modules(esto_product),
                        "allocation_type": "transformation",
                    }
                )
                remaining_transform -= float(reusable_output)
                if remaining_transform <= 0.0:
                    break
            _raw_cap_rule = _lookup_module_capacity_upper_limit(
                economy=economy,
                scenario=scenario_key,
                module=module_name,
            )
            module_headroom = float("inf")
            if _raw_cap_rule is not None:
                baseline_module_output = module_baseline_output_lookup.get(
                    (_state_token(economy), _state_token(module_name), int(year)),
                    0.0,
                )
                prior_module_added = module_added_output_lookup.get(
                    (_state_token(economy), _state_token(scenario_key), _state_token(module_name), int(year)),
                    0.0,
                )
                module_upper_limit = _resolve_module_cap_rule(_raw_cap_rule, baseline_module_output)
                if module_upper_limit is not None:
                    module_headroom = max(
                        float(module_upper_limit) - float(baseline_module_output) - float(prior_module_added),
                        0.0,
                    )
            if module_headroom <= 0.0:
                clipping_rows.append(
                    {
                        "economy": economy,
                        "scenario": scenario_key,
                        "esto_product": esto_product,
                        "year": int(year),
                        "requested_output_uplift": float(remaining_transform),
                        "allocated_output_uplift": 0.0,
                        "clipped_output_uplift": float(remaining_transform),
                        "reason": (
                            f"Module upper limit reached for '{module_name}'. "
                            "Set CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS to adjust."
                        ),
                    }
                )
                continue
            required_capacity_increment = float(remaining_transform) / float(output_yield_value)
            capacity_increment = min(required_capacity_increment, float(module_headroom))
            if capacity_increment <= 0.0:
                continue
            allocated_output = float(capacity_increment) * float(output_yield_value)
            if allocated_output <= 0.0:
                continue
            pass_capacity_additions[cap_key] = existing_pass_capacity + float(capacity_increment)
            module_added_key = (_state_token(economy), _state_token(scenario_key), _state_token(module_name), int(year))
            module_added_output_lookup[module_added_key] = (
                module_added_output_lookup.get(module_added_key, 0.0) + float(capacity_increment)
            )
            pass_output_additions[output_state_key] = pass_output_additions.get(output_state_key, 0.0) + allocated_output
            allocation_rows.append(
                {
                    "economy": economy,
                    "scenario": scenario_key,
                    "esto_product": esto_product,
                    "year": int(year),
                    "module": str(candidate.get("module") or ""),
                    "process": str(candidate.get("process") or ""),
                    "instance": int(candidate.get("instance") or 1),
                    "allocated_output_uplift": float(allocated_output),
                    "yield": float(output_yield_value),
                    "capacity_increment": float(capacity_increment),
                    "priority_modules": _resolve_capacity_priority_modules(esto_product),
                    "allocation_type": "transformation",
                }
            )
            remaining_transform -= allocated_output
        if remaining_transform > 1e-9:
            unresolved_rows.append(
                {
                    "economy": economy,
                    "scenario": scenario_key,
                    "esto_product": esto_product,
                    "year": int(year),
                    "unresolved_output_uplift": float(remaining_transform),
                    "reason": "Eligible processes found but no positive yield available.",
                }
            )

    for _, row in negative_rows.iterrows():
        economy = str(row.get("economy") or "").strip()
        scenario_key = str(row.get("scenario") or "").strip().lower()
        esto_product = str(row.get("esto_product") or "").strip()
        year = int(pd.to_numeric(row.get("year"), errors="coerce"))
        residual = float(row.get("imports_gap", 0.0))
        if not economy or not scenario_key or not esto_product or residual >= 0.0:
            continue
        if CAPACITY_UNMET_PIN_EXPORTS_TO_9TH_PROJECTIONS:
            # In pinned-export mode, do not convert negative import gaps into extra exports.
            # This prevents iterative state from drifting exports away from 9th projections.
            continue
        extra_exports = abs(residual)
        export_key = _output_addition_state_key(
            economy=economy,
            scenario=scenario_key,
            esto_product=esto_product,
            year=year,
        )
        pass_export_adjustments[export_key] = pass_export_adjustments.get(export_key, 0.0) + extra_exports
        export_rows.append(
            {
                "economy": economy,
                "scenario": scenario_key,
                "esto_product": esto_product,
                "year": int(year),
                "extra_exports": float(extra_exports),
                "reason": "Observed imports below baseline; route residual to explicit exports.",
            }
        )

    fatal_unresolved_rows, handled_unresolved_rows, unresolved_policy = _split_unresolved_rows_by_policy(
        unresolved_rows,
        mode="capacity_unmet_iterative_balanced",
    )
    unresolved_csv_path: Path | None = None
    unresolved_json_path: Path | None = None
    if handled_unresolved_rows:
        unresolved_csv_path, unresolved_json_path = _save_unresolved_positive_report(
            mode="capacity_unmet_iterative_balanced",
            unresolved_rows=handled_unresolved_rows,
        )
        print(
            "[CAPACITY_UNMET_ITERATIVE_BALANCED][WARN] Unresolved positive residuals handled by policy "
            f"'{unresolved_policy}': {len(handled_unresolved_rows)} "
            f"(csv={unresolved_csv_path}, json={unresolved_json_path})"
        )
    if fatal_unresolved_rows:
        preview = fatal_unresolved_rows[:12]
        raise RuntimeError(
            "capacity_unmet_iterative_balanced could not allocate positive residuals to "
            f"eligible production/transformation. Examples: {preview}"
        )

    for key, value in pass_capacity_additions.items():
        cumulative_capacity_map[key] = cumulative_capacity_map.get(key, 0.0) + float(value)
    for key, value in pass_output_additions.items():
        cumulative_output_map[key] = cumulative_output_map.get(key, 0.0) + float(value)
    for key, value in pass_primary_additions.items():
        cumulative_primary_map[key] = cumulative_primary_map.get(key, 0.0) + float(value)
    for key, value in pass_export_adjustments.items():
        cumulative_export_map[key] = cumulative_export_map.get(key, 0.0) + float(value)

    _CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS = dict(cumulative_capacity_map)
    _CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS = dict(cumulative_primary_map)
    _CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS = dict(cumulative_export_map)
    state["cumulative_capacity_additions"] = cumulative_capacity_map
    state["cumulative_output_additions"] = cumulative_output_map
    state["cumulative_primary_additions"] = cumulative_primary_map
    state["cumulative_export_adjustments"] = cumulative_export_map
    state["last_results_signatures"] = signature_map

    positive_total = float(positive_rows["imports_gap"].sum()) if not positive_rows.empty else 0.0
    negative_total = float((-negative_rows["imports_gap"]).sum()) if not negative_rows.empty else 0.0
    allocated_transform_total = float(sum(pass_output_additions.values()))
    allocated_primary_total = float(sum(pass_primary_additions.values()))
    extra_export_total = float(sum(pass_export_adjustments.values()))
    clipped_total = float(
        sum(float(item.get("clipped_output_uplift", 0.0)) for item in clipping_rows)
    )
    pass_summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "capacity_unmet_iterative_balanced",
        "iteration_run_mode": run_mode,
        "state_path": str(_resolve(state_path)),
        "results_signature_used": signature_map,
        "baseline_import_total": float(delta["adjusted_imports"].sum()),
        "observed_import_total": float(delta["observed_imports"].sum()),
        "positive_import_gap_total": positive_total,
        "negative_import_gap_total": negative_total,
        "baseline_net_import_total": float(delta["baseline_net_imports"].sum()),
        "observed_net_import_total": float(delta["observed_net_imports"].sum()),
        "positive_residual_total": positive_total,
        "negative_residual_total": negative_total,
        "allocated_transformation_output_total": allocated_transform_total,
        "allocated_primary_output_total": allocated_primary_total,
        "extra_export_total": extra_export_total,
        "clipped_output_total": clipped_total,
        "allocation_rows": allocation_rows,
        "export_rows": export_rows,
        "clipping_rows": clipping_rows,
        "unresolved_positive_rows": handled_unresolved_rows,
        "unresolved_positive_policy": unresolved_policy,
        "unresolved_positive_csv": str(unresolved_csv_path) if unresolved_csv_path else "",
        "unresolved_positive_json": str(unresolved_json_path) if unresolved_json_path else "",
        "unmatched_results_fuels": unmatched_result_fuels,
        "next_manual_step": (
            "Import generated workbook into LEAP, recalculate, refresh results tables, then rerun."
        ),
    }
    pass_history = state.get("passes")
    if not isinstance(pass_history, list):
        pass_history = []
    pass_history.append(pass_summary)
    state["passes"] = pass_history[-50:]
    convergence = _compute_convergence_metrics(state["passes"])
    pass_summary["convergence"] = convergence
    convergence_csv = _write_convergence_csv(pass_summary=pass_summary, convergence=convergence)
    pass_delta = {
        "pass_index": len(state["passes"]) - 1,
        "timestamp_utc": pass_summary.get("timestamp_utc", ""),
        "mode": pass_summary.get("mode", ""),
        "pre_pass_signatures": last_signatures,
        "capacity_additions": dict(pass_capacity_additions),
        "output_additions": dict(pass_output_additions),
        "primary_additions": dict(pass_primary_additions),
        "export_adjustments": dict(pass_export_adjustments),
    }
    _delta_history = state.get("pass_deltas")
    if not isinstance(_delta_history, list):
        _delta_history = []
    _delta_history.append(pass_delta)
    state["pass_deltas"] = _delta_history[-50:]
    persisted_path = _write_capacity_unmet_state(state, state_path=state_path)

    print("\n" + "=" * 96)
    print("[CAPACITY_UNMET_ITERATIVE_BALANCED] Pass summary")
    print(f"[CAPACITY_UNMET_ITERATIVE_BALANCED] State file: {persisted_path}")
    print(
        "[CAPACITY_UNMET_ITERATIVE_BALANCED] Baseline imports="
        f"{pass_summary['baseline_import_total']:.3f}, observed imports={pass_summary['observed_import_total']:.3f}"
    )
    print(
        "[CAPACITY_UNMET_ITERATIVE_BALANCED] Positive imports gap="
        f"{positive_total:.3f}, negative imports gap={negative_total:.3f}"
    )
    print(
        "[CAPACITY_UNMET_ITERATIVE_BALANCED] Allocated transformation="
        f"{allocated_transform_total:.3f}, primary={allocated_primary_total:.3f}, "
        f"extra exports={extra_export_total:.3f}, clipped={clipped_total:.3f}"
    )
    if clipping_rows:
        print(f"[CAPACITY_UNMET_ITERATIVE_BALANCED][WARN] Clipped rows: {len(clipping_rows)}")
    if unmatched_result_fuels:
        print(
            "[CAPACITY_UNMET_ITERATIVE_BALANCED][WARN] Unmapped Fuel labels in results sheets: "
            f"{len(unmatched_result_fuels)}"
        )
    print(
        "[CAPACITY_UNMET_ITERATIVE_BALANCED] Convergence: "
        f"pass {convergence['pass_count']}, gap={convergence['gap_at_current_pass']:.3f}, "
        f"closure={convergence['gap_closure_pct']:.1f}%, trend={convergence['trend']}"
        + (f", convergence CSV: {convergence_csv}" if convergence_csv else "")
    )
    print(
        "[CAPACITY_UNMET_ITERATIVE_BALANCED] Next step: "
        "Import workbook into LEAP, recalc, refresh results tables, rerun this workflow."
    )
    print("=" * 96 + "\n")
    return pass_summary
