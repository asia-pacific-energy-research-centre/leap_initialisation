"""
Generic patch utility: replace rows for a chosen module in all
leap_import_baseline_seed_* files without re-running the full workflow.

──────────────────────────────────────────────────────────────────────────────
JUPYTER / INTERACTIVE USE
──────────────────────────────────────────────────────────────────────────────
Edit the two variables in the "RUN SETTINGS" block below, then run:

    run_patch(MODULE, ECONOMIES)

Examples
    run_patch("oil_refineries")              # all economies, auto from ESTO
    run_patch("oil_refineries", ["20_USA"])  # single economy
    run_patch("transformation")              # all transformation sectors
    run_patch("transfers")                   # patch from existing workbooks
    run_patch("supply")
    run_patch("aggregated_demand")
    run_patch("power_interim")

Available modules (auto = regenerated from ESTO; file = read from workbooks):
    oil_refineries, lng, hydrogen, gas_processing, coal_transformation,
    petrochemical, charcoal, biofuels, nonspecified_transformation,
    transformation (all of the above at once)
    supply, transfers, power_interim, aggregated_demand, losses_own_use

Also runnable from `supply_reconciliation_workflow.py` via run_with_config():
set ACTIVE_PRESET = _PRESET_PATCH_BASELINE_SEEDS (see that file's RUN PRESETS
section) and edit PATCH_MODULE / PATCH_ECONOMIES there.

──────────────────────────────────────────────────────────────────────────────
COMMAND-LINE USE
──────────────────────────────────────────────────────────────────────────────
    python -m codebase.functions.patch_baseline_seeds --auto oil_refineries
    python -m codebase.functions.patch_baseline_seeds --module supply
    python -m codebase.functions.patch_baseline_seeds --auto oil_refineries --economies 20_USA 01_AUS
    python -m codebase.functions.patch_baseline_seeds --list
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════
# RUN SETTINGS  ← edit these two lines and call run_patch() in a notebook
# ═══════════════════════════════════════════════════════════════════════════
MODULE = "oil_refineries"   # module to patch (see list above)
ECONOMIES = None            # None = all economies, or e.g. ["20_USA", "01_AUS"]
# ═══════════════════════════════════════════════════════════════════════════

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.functions.baseline_seed_validation import (
    SOURCE_WORKFLOW_COLUMN,
    prepare_seed_rows_for_write,
    resolve_logical_duplicates,
    load_template_rows,
)

BASELINE_SEED_DIR = REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation"
WORKBOOKS_DIR = BASELINE_SEED_DIR / "workbooks"
ARCHIVE_DIR = BASELINE_SEED_DIR / "archive"
FULL_MODEL_EXPORT_PATH = REPO_ROOT / "data" / "full model export.xlsx"

_ECON_RE = re.compile(r"\d{2}_[A-Z]{2,3}")


def _deduplicate_rows_safely(df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate logical keys without choosing between genuine expressions."""
    resolved, duplicate_groups = resolve_logical_duplicates(df)
    conflicts = (
        duplicate_groups[duplicate_groups["blocking"].fillna(False)]
        if "blocking" in duplicate_groups.columns
        else duplicate_groups.iloc[0:0]
    )
    if not conflicts.empty:
        preview = "; ".join(
            " | ".join(str(row.get(column, "")) for column in (
                "Branch Path", "Variable", "Scenario", "Region"
            ))
            for _, row in conflicts.head(5).iterrows()
        )
        raise ValueError(
            "Conflicting duplicate expressions require owning-module "
            f"regeneration; refusing to guess: {preview}"
        )
    return resolved


def _assert_atomic_canonical_share_groups(
    data: pd.DataFrame,
    template_path: Path = FULL_MODEL_EXPORT_PATH,
) -> None:
    """Reject patches that represent only part of a canonical share group."""
    share_variables = {"Output Share", "Process Share", "Feedstock Fuel Share"}
    shares = data[data.get("Variable", pd.Series("", index=data.index)).astype(str).str.strip().isin(share_variables)].copy()
    if shares.empty:
        return
    template = load_template_rows(template_path)
    template = template[template["Variable"].astype(str).str.strip().isin(share_variables)].copy()
    shares["__parent"] = shares["Branch Path"].astype(str).str.rsplit("\\", n=1).str[0]
    template["__parent"] = template["Branch Path"].astype(str).str.rsplit("\\", n=1).str[0]
    failures: list[str] = []
    for key, group in shares.groupby(["__parent", "Variable", "Scenario", "Region"], dropna=False, sort=True):
        parent, variable, scenario, _region = (str(value).strip() for value in key)
        expected_rows = template[
            template["__parent"].astype(str).str.strip().str.lower().eq(parent.lower())
            & template["Variable"].astype(str).str.strip().str.lower().eq(variable.lower())
            & template["Scenario"].astype(str).str.strip().str.lower().eq(scenario.lower())
        ]
        expected = {str(value).strip().lower() for value in expected_rows["Branch Path"]}
        present = {str(value).strip().lower() for value in group["Branch Path"]}
        if not expected or present != expected:
            failures.append(
                f"{parent} | {variable} | {scenario}: "
                f"missing={sorted(expected - present)}; extra={sorted(present - expected)}"
            )
    if failures:
        raise ValueError(
            "Partial canonical share-group patch is forbidden: " + "; ".join(failures[:10])
        )


# ---------------------------------------------------------------------------
# Module registry
# ---------------------------------------------------------------------------
@dataclass
class ModuleConfig:
    strip_prefixes: list[str]
    workbook_glob: str | None = None        # glob under WORKBOOKS_DIR; * replaces {econ}
    auto_sector_keys: list[str] | None = None  # keys in ANALYSIS_REGISTRY
    workbook_dir: Path | None = None        # override WORKBOOKS_DIR when set


def _tf(*titles: str) -> list[str]:
    return [f"Transformation\\{t}" for t in titles]


MODULE_REGISTRY: dict[str, ModuleConfig] = {
    # ── auto-regen from ESTO (transformation sectors) ──────────────────────
    "oil_refineries": ModuleConfig(
        strip_prefixes=_tf("Oil Refining"),
        auto_sector_keys=["oil_refineries"],
    ),
    "lng": ModuleConfig(
        strip_prefixes=_tf("NG Liquefaction"),
        auto_sector_keys=["lng"],
    ),
    "hydrogen": ModuleConfig(
        strip_prefixes=_tf("Hydrogen transformation"),
        auto_sector_keys=["hydrogen_transformation"],
    ),
    "gas_processing": ModuleConfig(
        strip_prefixes=_tf("Gas works plants", "Natural gas blending plants",
                           "Gas to liquids plants"),
        auto_sector_keys=["gas_works"],
    ),
    "coal_transformation": ModuleConfig(
        strip_prefixes=_tf("Coke ovens", "Blast furnaces", "Patent fuel plants",
                           "BKB and PB plants", "Liquefaction coal to oil"),
        auto_sector_keys=["coal_coke_ovens", "coal_blast_furnaces",
                          "coal_patent_fuel_plants", "coal_bkb_pb_plants",
                          "coal_liquefaction"],
    ),
    "petrochemical": ModuleConfig(
        strip_prefixes=_tf("Petrochemical industry"),
        auto_sector_keys=["petrochemical_industry"],
    ),
    "charcoal": ModuleConfig(
        strip_prefixes=_tf("Charcoal processing"),
        auto_sector_keys=["charcoal_processing"],
    ),
    "biofuels": ModuleConfig(
        strip_prefixes=_tf("Biofuels processing"),
        auto_sector_keys=["biofuels_processing"],
    ),
    "nonspecified_transformation": ModuleConfig(
        strip_prefixes=_tf("Non specified transformation"),
        auto_sector_keys=["nonspecified_transformation"],
    ),
    "transformation": ModuleConfig(          # all transformation sectors at once
        strip_prefixes=["Transformation\\"],
        auto_sector_keys=["__all__"],
    ),
    # ── patch from existing workbooks (run the workflow first) ─────────────
    "supply": ModuleConfig(
        strip_prefixes=["Resources\\"],
        workbook_glob="supply_leap_imports_{econ}*.xlsx",
    ),
    "transfers": ModuleConfig(
        strip_prefixes=_tf("Upstream liquids transfers", "Transfers unallocated"),
        workbook_glob="transfer_leap_imports_{econ}*.xlsx",
    ),
    "power_interim": ModuleConfig(
        strip_prefixes=_tf("Electricity interim", "CHP interim", "Heat plant interim"),
        workbook_glob="electricity_heat_interim_{econ}*.xlsx",
    ),
    "aggregated_demand": ModuleConfig(
        strip_prefixes=["Demand\\"],
        workbook_glob="aggregated_demand_{econ}*.xlsx",
    ),
    "losses_own_use": ModuleConfig(
        strip_prefixes=[],   # derived from source rows at runtime
        workbook_glob="other_loss_own_use_proxy_{econ}*.xlsx",
        workbook_dir=BASELINE_SEED_DIR,
    ),
}


# ---------------------------------------------------------------------------
# LEAP file I/O helpers
# ---------------------------------------------------------------------------
def _find_header_row(raw: pd.DataFrame) -> tuple[list, pd.DataFrame]:
    for idx in range(min(8, len(raw))):
        vals = [str(v).strip().lower() for v in raw.iloc[idx].tolist()
                if str(v) not in ("nan", "")]
        if "branch path" in vals and "variable" in vals:
            header = raw.iloc[idx].tolist()
            data = raw.iloc[idx + 1:].copy()
            data.columns = header
            return header, data.dropna(how="all").reset_index(drop=True)
    raise ValueError("LEAP header row (Branch Path + Variable) not found")


def _wide_to_expression(data: pd.DataFrame) -> pd.DataFrame:
    """Convert year-column wide format to a single Expression column."""
    year_cols = [c for c in data.columns
                 if isinstance(c, (int, float)) and 1900 < float(c) < 2200]
    if not year_cols:
        year_cols = [c for c in data.columns
                     if str(c).strip().isdigit() and 1900 < int(str(c)) < 2200]
    if not year_cols:
        return data  # already expression format

    def _expr(row: pd.Series) -> str:
        pairs = []
        for yc in sorted(year_cols, key=float):
            v = row.get(yc)
            if v is not None and str(v) not in ("nan", "NaT", "None", ""):
                try:
                    pairs.append(f"{int(float(yc))},{float(v):.6g}")
                except (ValueError, TypeError):
                    pass
        return f"Data({', '.join(pairs)})" if pairs else ""

    out = data.drop(columns=year_cols).copy()
    out["Expression"] = data.apply(_expr, axis=1)
    return out


def _read_leap_workbook(path: Path) -> pd.DataFrame:
    for sheet in ("LEAP", 0):
        try:
            raw = pd.read_excel(path, sheet_name=sheet, header=None)
            _, data = _find_header_row(raw)
            return _wide_to_expression(data)
        except Exception:
            continue
    raise ValueError(f"Could not read LEAP data from {path.name}")


def _econ_token(filename: str) -> str | None:
    m = _ECON_RE.search(filename)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# Template validation and ID lookup
# ---------------------------------------------------------------------------
_ID_COLS = ("BranchID", "VariableID", "ScenarioID", "RegionID")

# Branch path prefixes known to be zero-energy or otherwise safely absent from
# the template.  Rows under these prefixes are skipped by validate_seed_files.
VALIDATION_IGNORE_PREFIXES: frozenset[str] = frozenset({
    "Transformation\\Biofuels processing\\",  # confirmed zero energy in ESTO
})

# 9th-edition aggregate fuel category names that are not real LEAP branches.
# Any path whose final segment matches one of these is skipped in validation.
VALIDATION_IGNORE_FUEL_NAMES: frozenset[str] = frozenset({
    # 9th-edition aggregate category labels — not real LEAP branches in any sector.
    "Biomass", "Coal", "Gas", "Others",
    "Municipal solid waste non and renewable",
    # "Solar" is NOT here: unallocated solar codes (12_solar, 12_solar_unallocated)
    # are remapped to "Solar nonspecified" at source in _safe_power_interim_display_label.
})

_TEMPLATE_ID_LOOKUP_CACHE: dict | None = None


def _build_id_lookup(
    path: Path = FULL_MODEL_EXPORT_PATH,
) -> dict[str, dict]:
    """Build Branch-Path/Variable/Scenario/Region → ID mappings from the template.

    Returns a dict with keys 'branch', 'variable', 'scenario', 'region'.
    Each value is a dict mapping the string key to its integer ID.
    Only non-(-1) IDs are stored; missing entries should fall back to -1.
    """
    global _TEMPLATE_ID_LOOKUP_CACHE
    if _TEMPLATE_ID_LOOKUP_CACHE is not None:
        return _TEMPLATE_ID_LOOKUP_CACHE

    raw = pd.read_excel(path, sheet_name="Export", header=None)
    _, data = _find_header_row(raw)

    def _int_id(val: object) -> int | None:
        try:
            i = int(float(val))  # type: ignore[arg-type]
            return i if i != -1 else None
        except (TypeError, ValueError):
            return None

    branch: dict[str, int] = {}
    branch_lower: dict[str, int] = {}
    variable: dict[tuple[str, str], int] = {}
    scenario: dict[str, int] = {}
    region: dict[str, int] = {}

    for _, row in data.iterrows():
        bp = str(row.get("Branch Path", "") or "").strip()
        if bp and bp not in branch:
            v = _int_id(row.get("BranchID"))
            if v is not None:
                branch[bp] = v
                branch_lower[bp.lower()] = v

        var = str(row.get("Variable", "") or "").strip()
        variable_key = (bp.lower(), var)
        if bp and var and variable_key not in variable:
            v = _int_id(row.get("VariableID"))
            if v is not None:
                variable[variable_key] = v

        scen = str(row.get("Scenario", "") or "").strip()
        if scen and scen not in scenario:
            v = _int_id(row.get("ScenarioID"))
            if v is not None:
                scenario[scen] = v

        reg = str(row.get("Region", "") or "").strip()
        if reg and reg not in region:
            v = _int_id(row.get("RegionID"))
            if v is not None:
                region[reg] = v

    _TEMPLATE_ID_LOOKUP_CACHE = {
        "branch": branch,
        "branch_lower": branch_lower,
        "variable": variable,
        "scenario": scenario,
        "region": region,
    }
    return _TEMPLATE_ID_LOOKUP_CACHE


def _fill_ids_from_template(df: pd.DataFrame, lookup: dict[str, dict]) -> None:
    """Fill IDs using branch-specific template keys."""
    branch_text = df.get("Branch Path", pd.Series("", index=df.index)).astype(str).str.strip()
    variable_text = df.get("Variable", pd.Series("", index=df.index)).astype(str).str.strip()
    scenario_text = df.get("Scenario", pd.Series("", index=df.index)).astype(str).str.strip()
    region_text = df.get("Region", pd.Series("", index=df.index)).astype(str).str.strip()
    df["BranchID"] = branch_text.str.lower().map(lookup["branch_lower"]).fillna(-1).astype(int)
    variable_keys = pd.Series(list(zip(branch_text.str.lower(), variable_text)), index=df.index)
    df["VariableID"] = variable_keys.map(lookup["variable"]).fillna(-1).astype(int)
    df["ScenarioID"] = scenario_text.map(lookup["scenario"]).fillna(-1).astype(int)
    df["RegionID"] = region_text.map(lookup["region"]).fillna(1).astype(int)


def _load_template_valid_ids(
    path: Path = FULL_MODEL_EXPORT_PATH,
) -> dict[str, set]:
    """Return valid non-(-1) values for each ID column and the full Branch Path set."""
    lookup = _build_id_lookup(path)
    return {
        "Branch Path": set(lookup["branch"].keys()),
        "BranchID": set(lookup["branch"].values()),
        "VariableID": set(lookup["variable"].values()),
        "ScenarioID": set(lookup["scenario"].values()),
        "RegionID": set(lookup["region"].values()),
    }


def validate_seed_files(
    seed_dir: Path = BASELINE_SEED_DIR,
    template_path: Path = FULL_MODEL_EXPORT_PATH,
    ignore_prefixes: frozenset[str] = VALIDATION_IGNORE_PREFIXES,
    ignore_fuel_names: frozenset[str] = VALIDATION_IGNORE_FUEL_NAMES,
) -> int:
    """Check all seed files against the template; return number of invalid rows found."""
    if not template_path.exists():
        print(f"[WARN] Template not found, skipping validation: {template_path}")
        return 0

    valid = _load_template_valid_ids(template_path)
    id_lookup = _build_id_lookup(template_path)
    valid_paths = valid["Branch Path"]
    # Case-insensitive lookup: lowercase key → canonical path from template.
    # LEAP branch names sometimes differ only in capitalisation from what the
    # code-to-name mapping produces (e.g. "Natural Gas" vs "Natural gas").
    # Treat these as matching so they don't generate spurious validation noise.
    valid_paths_lower: dict[str, str] = {p.lower(): p for p in valid_paths}

    seed_files = sorted(seed_dir.glob("leap_import_baseline_seed_*.xlsx"))
    if not seed_files:
        return 0

    total_bad = 0
    for seed_path in seed_files:
        try:
            raw = pd.read_excel(seed_path, sheet_name="LEAP", header=None)
            _, data = _find_header_row(raw)
        except Exception as exc:
            print(f"  [WARN] Could not read {seed_path.name}: {exc}")
            continue

        bad_rows: list[str] = []
        for _, row in data.iterrows():
            bp = str(row.get("Branch Path", "") or "")
            if not bp or bp.lower() in ("nan", "area:", ""):
                continue
            if any(bp.startswith(p) for p in ignore_prefixes):
                continue
            if bp.split("\\")[-1] in ignore_fuel_names:
                continue

            # Case-insensitive match: resolve to canonical template path if found.
            canonical_bp = valid_paths_lower.get(bp.lower())
            if canonical_bp is None:
                bad_rows.append(f"  unknown path: {bp}")
                continue
            # Use canonical path for ID column checks.
            bp = canonical_bp

            variable = str(row.get("Variable", "") or "").strip()
            scenario = str(row.get("Scenario", "") or "").strip()
            region = str(row.get("Region", "") or "").strip()
            expected_ids = {
                "BranchID": id_lookup["branch_lower"].get(bp.lower()),
                "VariableID": id_lookup["variable"].get((bp.lower(), variable)),
                "ScenarioID": id_lookup["scenario"].get(scenario),
                "RegionID": id_lookup["region"].get(region, 1),
            }
            for col in _ID_COLS:
                if col not in data.columns:
                    continue
                try:
                    val = int(float(row[col]))
                except (TypeError, ValueError):
                    continue
                expected = expected_ids.get(col)
                if expected is not None and val != int(expected):
                    bad_rows.append(
                        f"  bad {col}={val}, expected {int(expected)} on: {bp}"
                    )

        if bad_rows:
            print(f"\n[INVALID] {seed_path.name} — {len(bad_rows)} issue(s):")
            for msg in bad_rows[:20]:
                print(msg)
            if len(bad_rows) > 20:
                print(f"  ... and {len(bad_rows) - 20} more")
            total_bad += len(bad_rows)

    if total_bad == 0:
        print("[OK] All seed file rows match the template.")
    else:
        print(f"\n[WARN] {total_bad} invalid row(s) found across seed files.")
    return total_bad


# ---------------------------------------------------------------------------
# Source row collection
# ---------------------------------------------------------------------------
def _collect_from_workbooks(cfg: ModuleConfig,
                             economy_filter: list[str] | None) -> dict[str, pd.DataFrame]:
    src_dir = cfg.workbook_dir or WORKBOOKS_DIR
    if not src_dir.exists():
        print(f"[WARN] Workbook dir not found: {src_dir}")
        return {}
    if not cfg.workbook_glob:
        print("[WARN] No workbook_glob configured for this module.")
        return {}

    pattern = cfg.workbook_glob.replace("{econ}", "*")
    files = list(src_dir.glob(pattern))
    if not files:
        print(f"[WARN] No files matching '{pattern}' in {src_dir}")
        return {}

    by_econ: dict[str, list[pd.DataFrame]] = {}
    for f in files:
        tok = _econ_token(f.stem)
        if not tok or (economy_filter and tok not in economy_filter):
            continue
        try:
            by_econ.setdefault(tok, []).append(_read_leap_workbook(f))
        except Exception as exc:
            print(f"[WARN] Skipping {f.name}: {exc}")

    result: dict[str, pd.DataFrame] = {}
    for tok, frames in by_econ.items():
        df = pd.concat(frames, ignore_index=True)
        result[tok] = _deduplicate_rows_safely(df)
    return result


def _collect_auto_regen(cfg: ModuleConfig,
                         economy_filter: list[str] | None) -> dict[str, pd.DataFrame]:
    from codebase.functions import transformation_analysis_utils as core
    from codebase import transformation_workflow
    from codebase.functions.supply_data_pipeline import get_region_for_economy

    sector_keys = cfg.auto_sector_keys or []
    if "__all__" in sector_keys:
        run_list = transformation_workflow.ANALYSIS_REGISTRY
    else:
        run_list = [(sk, cb, en) for sk, cb, en in transformation_workflow.ANALYSIS_REGISTRY
                    if sk in sector_keys]

    if not run_list:
        print(f"[WARN] No ANALYSIS_REGISTRY entries for: {sector_keys}")
        return {}

    # Override ECONOMIES_TO_ANALYZE so the analysis runs per-economy rather than
    # just for the APEC aggregate (which is what workflow_config defaults to).
    # If a filter is given, use those economies; otherwise use [] which causes
    # get_economy_list() to return all economies present in the ESTO data.
    _orig_economies = list(core.ECONOMIES_TO_ANALYZE)
    core.ECONOMIES_TO_ANALYZE[:] = economy_filter if economy_filter else []

    records: list[dict] = []
    core.reset_dropped_fuel_log()
    core.reset_analyzed_sector_titles()
    try:
        for sector_key, callback, enabled in run_list:
            core.run_analysis_for_sector(enabled, sector_key, callback, records)
    finally:
        core.ECONOMIES_TO_ANALYZE[:] = _orig_economies
    if not records:
        print("[WARN] No process records returned.")
        return {}

    catalog_df = _load_catalog()
    scenarios = list(core.SCENARIOS_TO_EXPORT)
    base_year, final_year = core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR
    in_scope_titles = {
        str(core.map_code_label(core.resolve_sector_config(sk).get("title", ""),
                                core.code_to_name_mapping))
        for sk, _, _ in run_list
    }
    scenario_cfgs = {s: core.get_scenario_export_config(s, default_base_year=base_year,
                                                         default_final_year=final_year)
                     for s in scenarios}
    combined_base, combined_final = core.compute_combined_year_range(
        base_year, final_year, scenario_cfgs)

    all_economies = sorted({str(r.get("economy") or "").strip() for r in records
                            if str(r.get("economy") or "").strip()})
    result: dict[str, pd.DataFrame] = {}
    for economy in all_economies:
        tok = economy.replace(" ", "_").replace("/", "-")
        if economy_filter and tok not in economy_filter:
            continue
        econ_records = [r for r in records if str(r.get("economy") or "").strip() == economy]
        region = get_region_for_economy(economy)

        log_rows: list[dict] = []
        for scenario in scenarios:
            log_rows.extend(core.build_transformation_log_rows(
                econ_records, scenario, region, base_year, final_year,
                core.code_to_name_mapping, scenario_config=scenario_cfgs[scenario],
            ))
        if not log_rows:
            continue

        if not catalog_df.empty:
            zero = core.build_aux_fuel_zero_rows(
                log_rows, catalog_df, scenarios, base_year, final_year,
                in_scope_sector_titles=in_scope_titles,
            )
            if zero:
                log_rows = zero + log_rows

        export_df, _ = core.build_export_from_log_rows(
            log_rows, ", ".join(scenarios), region, combined_base, combined_final)
        if export_df is None or export_df.empty:
            continue
        result[tok] = core.build_expression_export_df(export_df)

    return result


def _load_catalog() -> pd.DataFrame:
    from codebase.supply_reconciliation_workflow import _extract_catalog_rows_from_full_model_export
    rows = _extract_catalog_rows_from_full_model_export(source_path=FULL_MODEL_EXPORT_PATH)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ---------------------------------------------------------------------------
# Source workflow runner
# ---------------------------------------------------------------------------
def _run_source_workflow(module: str, economies: list[str] | None) -> None:
    """Re-run the upstream workflow that generates the source workbooks for a module.

    Only applies to workbook-based modules.  Auto-regen modules regenerate their
    data inline via _collect_auto_regen and do not need a pre-step.

    Writes workbooks to WORKBOOKS_DIR so _collect_from_workbooks can find them.
    """
    print(f"[INFO] Running source workflow for '{module}' before patching...")

    if module == "power_interim":
        from codebase import electricity_heat_interim_workflow as _w
        from codebase.functions import transformation_analysis_utils as _core
        # When no economies are specified, run per-economy (not the 00_APEC aggregate
        # which is what core.ECONOMIES_TO_ANALYZE defaults to in workflow_config).
        econ_list = economies or sorted(
            e for e in _core.ninth_data["economy"].unique()
            if not str(e).startswith("00_")
        )
        _w.assemble_electricity_heat_interim_workbook(
            economies=econ_list,
            export_output_dir=WORKBOOKS_DIR,
        )

    elif module == "transfers":
        from codebase import transfers_workflow as _w
        _w.assemble_transfer_workbook(
            economies=economies,
            export_output_dir=WORKBOOKS_DIR,
        )

    elif module == "supply":
        # supply_workflow.assemble_supply_workbooks writes to its own EXPORT_OUTPUT_DIR
        # (outputs/leap_exports/) which differs from WORKBOOKS_DIR.  Wire this up once
        # the supply workflow supports a configurable export_output_dir.
        print(
            f"[WARN] No source workflow wired for '{module}' yet — "
            "run supply_workflow.assemble_supply_workbooks() manually first."
        )

    elif module == "aggregated_demand":
        from codebase.aggregated_demand_workflow import (
            save_aggregated_demand_as_leap_workbook,
            LEAP_SCENARIOS,
            PROJECTION_DATA_PATH,
            FUEL_MAPPINGS_PATH,
            BASE_YEAR,
            PROJECTION_END_YEAR,
            DEFAULT_EXPORT_REGION,
        )
        from codebase.functions import transformation_analysis_utils as _core
        econ_list = economies or sorted(
            e for e in _core.ninth_data["economy"].unique()
            if not str(e).startswith("00_")
        )
        for economy in econ_list:
            out_path = WORKBOOKS_DIR / f"aggregated_demand_{economy}.xlsx"
            print(f"[INFO] Building aggregated demand workbook: {economy}")
            save_aggregated_demand_as_leap_workbook(
                economy=economy,
                output_path=out_path,
                scenarios=list(LEAP_SCENARIOS),
                region=DEFAULT_EXPORT_REGION,
                base_year=BASE_YEAR,
                final_year=PROJECTION_END_YEAR,
                data_path=PROJECTION_DATA_PATH,
                fuel_mappings_path=FUEL_MAPPINGS_PATH,
            )

    elif module == "losses_own_use":
        # assemble_proxy_workbook takes a single economy= kwarg; needs a loop.
        # Wire this up once confirmed.
        print(
            f"[WARN] No source workflow wired for '{module}' yet — "
            "run other_loss_own_use_proxy_workflow.assemble_proxy_workbook() manually first."
        )

    else:
        print(f"[INFO] No source workflow registered for '{module}'; skipping.")


# ---------------------------------------------------------------------------
# Patching
# ---------------------------------------------------------------------------
def _derive_prefixes(df: pd.DataFrame, bp_col: str = "Branch Path") -> list[str]:
    prefixes: set[str] = set()
    for bp in df[bp_col].dropna().astype(str).unique():
        parts = bp.split("\\")
        prefixes.add(f"{parts[0]}\\{parts[1]}\\" if len(parts) >= 2 else f"{parts[0]}\\")
    return sorted(prefixes)


def _patch_one(
    seed_path: Path,
    new_df: pd.DataFrame,
    prefixes: list[str],
    source_workflow: str = "patch_baseline_seeds",
) -> None:
    _assert_atomic_canonical_share_groups(new_df, FULL_MODEL_EXPORT_PATH)
    raw = pd.read_excel(seed_path, sheet_name="LEAP", header=None)
    _, data = _find_header_row(raw)

    bp_col = next((c for c in data.columns if str(c).strip().lower() == "branch path"), None)
    if bp_col is None:
        print(f"  [WARN] No 'Branch Path' column in {seed_path.name}; skipping.")
        return

    active = prefixes or _derive_prefixes(new_df, bp_col)

    def _hits(val: str) -> bool:
        return any(val.startswith(p) for p in active)

    strip_mask = data[bp_col].astype(str).apply(_hits)
    n_removed = int(strip_mask.sum())
    cleaned = data[~strip_mask].copy()

    for col in cleaned.columns:
        if col not in new_df.columns:
            new_df[col] = pd.NA
    if FULL_MODEL_EXPORT_PATH.exists():
        _fill_ids_from_template(new_df, _build_id_lookup())
    else:
        for id_col, default in [("BranchID", -1), ("VariableID", -1),
                                 ("ScenarioID", -1), ("RegionID", 1)]:
            if id_col in cleaned.columns:
                new_df[id_col] = default

    new_aligned = new_df.reindex(columns=cleaned.columns)
    if active:
        new_aligned = new_aligned[new_aligned[bp_col].astype(str).apply(_hits)]

    # Drop rows for known aggregate fuel names that aren't real LEAP branches.
    ignore_mask = new_aligned[bp_col].astype(str).apply(
        lambda p: p.split("\\")[-1] in VALIDATION_IGNORE_FUEL_NAMES
    )
    if ignore_mask.any():
        new_aligned = new_aligned[~ignore_mask].copy()

    cleaned[SOURCE_WORKFLOW_COLUMN] = "retained_baseline_seed_rows"
    new_aligned[SOURCE_WORKFLOW_COLUMN] = source_workflow
    combined = pd.concat([cleaned, new_aligned], ignore_index=True)

    branch_paths = combined[bp_col].fillna("").astype(str)
    documented_exclusion_mask = branch_paths.map(
        lambda path: path.split("\\")[-1] in VALIDATION_IGNORE_FUEL_NAMES
        or any(path.startswith(prefix) for prefix in VALIDATION_IGNORE_PREFIXES)
    )
    diagnostics_dir = seed_path.parent / "supporting_files" / "baseline_seed_validation"
    diagnostic_stem = f"{seed_path.stem}_patch_{source_workflow}"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    combined[documented_exclusion_mask].to_csv(
        diagnostics_dir / f"{diagnostic_stem}_documented_exclusions.csv",
        index=False,
    )
    combined = combined[~documented_exclusion_mask].copy()

    from codebase.functions import transformation_record_builder as record_builder

    required_years_by_scenario: dict[str, list[int]] = {}
    for scenario in sorted({str(value).strip() for value in combined["Scenario"] if str(value).strip()}):
        scenario_config = record_builder.get_scenario_export_config(scenario)
        start_year, end_year = record_builder.resolve_scenario_year_range(
            record_builder.EXPORT_BASE_YEAR,
            record_builder.EXPORT_FINAL_YEAR,
            scenario_config,
        )
        if scenario.lower() not in {"current account", "current accounts"}:
            start_year = max(int(start_year), int(record_builder.EXPORT_BASE_YEAR) + 1)
        required_years_by_scenario[scenario] = list(range(int(start_year), int(end_year) + 1))

    validation = prepare_seed_rows_for_write(
        combined,
        template_path=FULL_MODEL_EXPORT_PATH,
        diagnostics_dir=diagnostics_dir,
        diagnostic_stem=diagnostic_stem,
        required_years_by_scenario=required_years_by_scenario,
    )
    combined = validation.resolved_rows.drop(
        columns=[SOURCE_WORKFLOW_COLUMN], errors="ignore"
    )

    cols = list(combined.columns)
    preamble = {c: pd.NA for c in cols}
    preamble[bp_col] = "Area:"
    if "Scenario" in cols:
        preamble["Scenario"] = "Ver:"
    if "Region" in cols:
        preamble["Region"] = "2"

    full_df = pd.concat([
        pd.DataFrame([preamble]),
        pd.DataFrame([{c: pd.NA for c in cols}]),
        pd.DataFrame([cols], columns=cols),
        combined,
    ], ignore_index=True)

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(seed_path, ARCHIVE_DIR / f"{seed_path.stem}_pre_patch_{stamp}{seed_path.suffix}")

    with pd.ExcelWriter(seed_path, engine="openpyxl") as writer:
        full_df.to_excel(writer, sheet_name="LEAP", index=False, header=False)
        full_df.to_excel(writer, sheet_name="FOR_VIEWING", index=False, header=False)

    print(f"  removed {n_removed}, added {len(new_aligned)} rows -> {seed_path.name}")


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def run_patch(
    module: str,
    economies: list[str] | None = None,
    run_workflow: bool = True,
) -> None:
    """
    Patch baseline seed files for the given module.

    Parameters
    ----------
    module : str
        Name from MODULE_REGISTRY (e.g. "oil_refineries", "supply").
    economies : list[str] | None
        Economy tokens to limit scope (e.g. ["20_USA", "01_AUS"]).
        None = all economies.
    run_workflow : bool
        If True (default), re-run the upstream source workflow before patching
        so that workbook-based modules always patch from fresh data.
        Set False to patch from whatever workbooks are already on disk.
    """
    if module not in MODULE_REGISTRY:
        print(f"[ERROR] Unknown module '{module}'. Available: {sorted(MODULE_REGISTRY)}")
        return

    global _TEMPLATE_ID_LOOKUP_CACHE
    _TEMPLATE_ID_LOOKUP_CACHE = None  # rebuild from template on each run_patch call

    cfg = MODULE_REGISTRY[module]
    if run_workflow and not cfg.auto_sector_keys:
        _run_source_workflow(module, economies)
    is_auto = bool(cfg.auto_sector_keys)
    print(f"=== Patch: {module} ({'auto-regen' if is_auto else 'from workbooks'}) ===")

    source_by_econ = (
        _collect_auto_regen(cfg, economies)
        if is_auto
        else _collect_from_workbooks(cfg, economies)
    )
    if not source_by_econ:
        print("[ERROR] No source rows collected. Nothing to patch.")
        return

    print(f"Economies with source rows: {sorted(source_by_econ)}")

    seed_files = {
        _econ_token(p.stem): p
        for p in BASELINE_SEED_DIR.glob("leap_import_baseline_seed_*.xlsx")
        if _econ_token(p.stem)
    }

    failed: list[str] = []
    for tok, new_df in sorted(source_by_econ.items()):
        seed_path = seed_files.get(tok)
        if not seed_path:
            print(f"  [{tok}] no baseline seed found; skipping.")
            continue
        print(f"  [{tok}] {seed_path.name}")
        try:
            _patch_one(seed_path, new_df, cfg.strip_prefixes, source_workflow=module)
        except PermissionError:
            print(f"  [{tok}] SKIPPED — file is locked (close it in Excel and re-run for this economy).")
            failed.append(tok)
        except Exception as exc:
            print(f"  [{tok}] ERROR — {exc}")
            failed.append(tok)

    if failed:
        print(f"\nFailed economies (re-run with --economies {' '.join(failed)}): {failed}")
    print("Done.")
    print("\nValidating seed files against template...")
    validate_seed_files()


def list_modules() -> None:
    """Print all available module names."""
    print(f"{'Module':<30} {'Mode':<10} Strip prefixes")
    print("-" * 80)
    for name, cfg in sorted(MODULE_REGISTRY.items()):
        mode = "auto" if cfg.auto_sector_keys else "file"
        prefixes = ", ".join(cfg.strip_prefixes) or "(derived from source)"
        print(f"{name:<30} {mode:<10} {prefixes}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Patch baseline seed files for a chosen module.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--auto", metavar="MODULE",
                       help="Auto-regenerate from ESTO (transformation sectors)")
    group.add_argument("--module", metavar="MODULE",
                       help="Patch from workbooks already in the workbooks dir")
    group.add_argument("--list", action="store_true", dest="list_mods",
                       help="List available module names and exit")
    parser.add_argument("--economies", nargs="*", metavar="TOKEN",
                        help="Limit to these economy tokens, e.g. 20_USA 01_AUS")
    args = parser.parse_args(argv)

    if args.list_mods:
        list_modules()
        return

    module = args.auto or args.module
    if not module:
        parser.print_help()
        return

    if module not in MODULE_REGISTRY:
        print(f"[ERROR] Unknown module '{module}'.")
        list_modules()
        sys.exit(1)

    cfg = MODULE_REGISTRY[module]
    if args.auto and not cfg.auto_sector_keys:
        print(f"[ERROR] '{module}' has no auto-regen; use --module instead.")
        sys.exit(1)

    run_patch(module, args.economies or None)


if __name__ == "__main__":
    _cli()
