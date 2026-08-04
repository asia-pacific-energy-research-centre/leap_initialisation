"""
Build limited-year LEAP balance comparisons with ESTO and the 9th Outlook.

This first diagnostic stage is read-only. It reports LEAP minus source values
on the shared ESTO flow/product axis and flags comparisons that would need an
allocation rule before a later update workflow could act on them.
"""

from __future__ import annotations

import json
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from codebase.configuration import workflow_config as workflow_cfg
from codebase.mappings.canonical_mapping import ConfigTableRef
from codebase.utilities.leap_balance_export_resolver import (
    BalanceExportSheet,
    list_balance_export_sheets,
    require_level2_balance_export_detail,
    resolve_balance_export_workbook,
    select_balance_export_sheets,
)
from codebase.utilities.leap_results_dashboard_utils import (
    _expand_esto_flow_code_selector,
    pull_base_year_value,
)
from codebase.functions.transformation_analysis_utils import MAJOR_SECTOR_CONFIG


REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_workspace_sibling_repo(repo_name: str) -> Path:
    """Find a workspace sibling from either a normal checkout or nested worktree."""
    candidates = [REPO_ROOT.parent / repo_name]
    for ancestor in REPO_ROOT.parents:
        if ancestor.name == "leap_initialisation":
            candidates.append(ancestor.parent / repo_name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


LEAP_MAPPINGS_REPO_ROOT = _find_workspace_sibling_repo("leap_mappings")
OUTLOOK_MAPPINGS_MASTER_PATH = (
    LEAP_MAPPINGS_REPO_ROOT / "config" / "outlook_mappings_master.xlsx"
)
DEFAULT_EXPORTS_ROOT = REPO_ROOT / "data" / "leap balances exports"
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "outputs"
    / "leap_exports"
    / "supply_reconciliation"
    / "supporting_files"
    / "baseline_seed_balance_diagnostics"
)
DEFAULT_KNOWN_ISSUES_PATH = REPO_ROOT / "config" / "leap_results_balance_known_issues.json"
DEFAULT_TEMPLATE_SHEET = "EBal|2060"
DEFAULT_BASE_YEAR = 2022
DEFAULT_TOLERANCE_PJ = 1e-6
DEFAULT_ROUNDING_TOLERANCE_PERCENT = 0.01
DEFAULT_MAPPING_PAIRS_PATH: ConfigTableRef = (
    OUTLOOK_MAPPINGS_MASTER_PATH,
    "ninth_pairs_to_esto_pairs",
)
DEFAULT_CODEBOOK_PATH = OUTLOOK_MAPPINGS_MASTER_PATH
DEFAULT_SHEET_MAP_PATH = REPO_ROOT / "config" / "runtime_tables" / "leap_results_sheet_map.csv"
DEFAULT_BACKUP_MAPPINGS_PATH = REPO_ROOT / "config" / "backup_leap_mappings.xlsx"
DEFAULT_EXPLICIT_MAPPINGS_PATH = REPO_ROOT / "config" / "leap_results_explicit_mappings.csv"
DEFAULT_EXPLICIT_REASSIGNMENTS_PATH = (
    REPO_ROOT / "config" / "runtime_tables" / "leap_explicit_reassignments.csv"
)
DEFAULT_SYNTHETIC_REFERENCE_ROWS_PATH = (
    REPO_ROOT / "config" / "runtime_tables" / "synthetic_reference_rows.csv"
)
DEFAULT_BALANCE_VARIABLE_RULES_PATH = (
    REPO_ROOT / "config" / "runtime_tables" / "balance_error_signal_rules.csv"
)
DEFAULT_BASE_TABLE_PATH = workflow_cfg.get_energy_source_config().esto_base_table_path
DEFAULT_PROJECTION_TABLE_PATH = REPO_ROOT / "data" / "merged_file_energy_ALL_20251106.csv"
OTHER_SECTOR_WITH_NONENERGY_COMPARATOR_FLOW = (
    "16.03-16.05,17 Other sector including non-energy (all demand aggregate)"
)

DIFFERENCE_OUTPUT_COLUMNS = [
    "economy",
    "scenario",
    "year",
    "esto_flow",
    "esto_product",
    "leap_sector_names",
    "leap_fuel_names",
    "comparison_branch_path",
    "ninth_sector_codes",
    "ninth_fuel_codes",
    "reference_source",
    "leap_value_pj",
    "source_value_pj",
    "difference_pj",
    "absolute_difference_pj",
    "difference_percent",
    "correction_to_match_source_pj",
    "status",
    "is_mismatch",
    "comparison_grain",
    "leap_component_count",
    "ninth_pair_count",
    "ninth_pair_max_esto_claimants",
    "projection_allocation_complete",
    "projection_target_pair_count",
    "projection_matched_pair_count",
    "projection_allocation_methods",
    "projection_share_sources",
    "update_allocation_required",
    "update_allocation_reason",
    "transformation_auxiliary_comparison_status",
    "sheet",
    "measure",
    "fuel_label",
]

REVIEW_ADDED_COLUMNS = [
    "leap_balance_row",
    "leap_balance_fuel",
    "material_for_review",
    "balance_variable_role",
    "allowed_to_change",
    "error_signal_name",
    "balance_variable_rule_reason",
    "balance_contract_issue",
    "requires_issue_review",
    "update_signal_eligible",
    "placeholder_scope",
    "placeholder_scope_reason",
    "preliminary_owner",
    "primary_classification",
    "evidence_note",
    "next_action",
    "no_direct_projection_comparator",
    "affected_by_no_projection_transformation",
    "impact_source_transformation_flows",
]

BALANCE_VARIABLE_RULE_COLUMNS = [
    "economy",
    "scenario",
    "esto_product",
    "esto_flow",
    "balance_variable_role",
    "error_signal_name",
    "reason",
    "enabled",
]

PLACEHOLDER_SECTOR_PATTERN = re.compile(
    r"(?:^|\|)(?:Electricity interim/|CHP interim/|Heat plant interim/)",
    flags=re.IGNORECASE,
)

IGNORED_BALANCE_DIAGNOSTIC_ROWS = frozenset(
    {
        "all demand aggregated",
        "total transformation",
        "total final energy demand",
        "total final energy consumption",
        "unmet requirements",
    }
)

# These processes write 10.01 own-use/loss energy as Auxiliary Fuel Use inside
# the LEAP Transformation module. Coal mines and LNG are deliberately absent:
# their active proxy workflows own 10.01.06 and 10.01.03 respectively under
# Demand\Other loss and own use.
TRANSFORMATION_AUXILIARY_CONFIG_KEYS = (
    "gas_works",
    "coal_coke_ovens",
    "coal_blast_furnaces",
    "oil_refineries",
)

# These are the transformation processes currently confirmed to be created
# from baseline seed/carry-forward logic when the projection has no active
# transformation comparator. Keep this explicit so zero-valued projection
# cells in electricity/CHP allocation workflows are not misclassified.
SEED_OR_CARRY_FORWARD_TRANSFORMATION_FLOW_PREFIXES = (
    "09.08.01 Coke ovens",
    "09.08.02 Blast furnaces",
)


def _resolve(path: Path | str) -> Path:
    """Resolve a notebook-friendly path against this repository."""
    normalized = str(path).replace("\\", "/")
    candidate = Path(normalized)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _resolve_config_table_ref(
    value: ConfigTableRef,
) -> ConfigTableRef:
    """Resolve a path or ``(workbook, sheet)`` mapping-table reference."""
    if isinstance(value, tuple):
        return (_resolve(value[0]), str(value[1]))
    return _resolve(value)


def _clean_token(value: object) -> str:
    if value is None or value is pd.NA:
        return ""
    return str(value).strip()


def _normalize_diagnostic_label(value: object) -> str:
    """Return a case-insensitive label key with stable whitespace."""
    return " ".join(_clean_token(value).casefold().split())


def _first_present_label(row: pd.Series, columns: Sequence[str]) -> str:
    """Return the first populated label from a diagnostic row."""
    for column in columns:
        value = _clean_token(row.get(column, ""))
        if value:
            return value
    return ""


def _ignored_mapping_issue_reason(row: pd.Series) -> str:
    """Explain why an extraction issue is intentionally outside this diagnostic."""
    fuel_label = _first_present_label(
        row,
        (
            "mapping_key_fuel",
            "leap_product_name",
            "leap_product",
            "raw_leap_fuel_name",
        ),
    )
    if _normalize_diagnostic_label(fuel_label) == "total":
        return "aggregate Total fuel column is derived and is not mapped directly"

    sector_label = _first_present_label(
        row,
        (
            "mapping_key_sector",
            "leap_flow_name",
            "leap_flow",
            "leap_sector_name_full_path",
        ),
    )
    if (
        _normalize_diagnostic_label(sector_label).replace("\\", "/")
        == "transmission and distribution/electricity"
        and _normalize_diagnostic_label(fuel_label) == "electricity"
    ):
        return (
            "structural Electricity child mirrors the Transmission and "
            "Distribution parent and must not be mapped separately"
        )
    sector_root = re.split(r"[/\\]", sector_label, maxsplit=1)[0]
    if _normalize_diagnostic_label(sector_root) in IGNORED_BALANCE_DIAGNOSTIC_ROWS:
        return f"{sector_root} is an excluded aggregate or diagnostic-only balance row"
    return ""


def _partition_mapping_issues(
    mapping_issues: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split actionable mapping issues from explicitly ignored aggregate rows."""
    if mapping_issues is None or mapping_issues.empty:
        empty = pd.DataFrame(columns=getattr(mapping_issues, "columns", []))
        return empty.copy(), empty.copy()

    work = mapping_issues.copy()
    reasons = work.apply(_ignored_mapping_issue_reason, axis=1)
    ignored_mask = reasons.ne("")
    active = work.loc[~ignored_mask].reset_index(drop=True)
    ignored = work.loc[ignored_mask].copy()
    ignored.insert(0, "diagnostic_record_type", "mapping_issue")
    ignored.insert(
        1,
        "diagnostic_disposition_reason",
        reasons.loc[ignored_mask].to_numpy(),
    )
    return active, ignored.reset_index(drop=True)


def _partition_comparison_rows(
    differences: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Remove user-selected aggregate rows while retaining an explicit audit."""
    if differences is None or differences.empty:
        empty = pd.DataFrame(columns=getattr(differences, "columns", []))
        return empty.copy(), empty.copy()

    work = differences.copy()
    row_labels = work.apply(
        lambda row: _first_present_label(
            row,
            ("leap_balance_row", "leap_sector_names", "esto_flow"),
        ),
        axis=1,
    )
    normalized = row_labels.map(_normalize_diagnostic_label)
    ignored_mask = normalized.isin(IGNORED_BALANCE_DIAGNOSTIC_ROWS)
    active = work.loc[~ignored_mask].reset_index(drop=True)
    ignored = work.loc[ignored_mask].copy()
    ignored.insert(0, "diagnostic_record_type", "comparison_row")
    ignored.insert(
        1,
        "diagnostic_disposition_reason",
        [
            f"{label} is an excluded aggregate or diagnostic-only balance row"
            for label in row_labels.loc[ignored_mask]
        ],
    )
    return active, ignored.reset_index(drop=True)


def _all_demand_subtotal_comparator_flows(
    mapping_status: pd.DataFrame,
) -> set[str]:
    """Return mapped ESTO flows beneath the export-only demand parent row."""
    if mapping_status is None or mapping_status.empty:
        return set()
    path_columns = [
        column
        for column in [
            "leap_sector_name_full_path",
            "mapped_leap_sector_name",
            "mapping_key_sector",
            "leap_sector_name",
        ]
        if column in mapping_status.columns
    ]
    if not path_columns or "esto_flow" not in mapping_status.columns:
        return set()
    child_mask = pd.Series(False, index=mapping_status.index)
    for path_column in path_columns:
        paths = (
            mapping_status[path_column]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.replace("\\", "/", regex=False)
        )
        child_mask |= paths.str.lower().str.startswith("all demand aggregated/")
    child_rows = mapping_status.loc[child_mask]
    return {
        _clean_token(flow)
        for flow in child_rows["esto_flow"]
        if _clean_token(flow)
    }


def _include_nonenergy_in_other_sector_comparator_mapping(
    esto_mapping: pd.DataFrame,
) -> pd.DataFrame:
    r"""Align the diagnostic's Other-sector comparator with the seed branch.

    ``Demand\All demand aggregated\Other sector`` deliberately contains ESTO
    flows 16.03-16.05 plus flow 17 non-energy use. The maintained canonical
    mapping retains the ordinary Other-sector selector because it serves wider
    mapping purposes; this diagnostic-only copy needs the combined selector so
    its Correct Source Values compare the same scope written to LEAP.
    """
    out = esto_mapping.copy()
    path_column = "leap_sector_name_full_path"
    if path_column not in out.columns or "esto_flow" not in out.columns:
        return out
    normalized_paths = (
        out[path_column]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.replace("\\", "/", regex=False)
        .map(_normalize_diagnostic_label)
    )
    other_sector = normalized_paths.eq("all demand aggregated/other sector")
    out.loc[other_sector, "esto_flow"] = OTHER_SECTOR_WITH_NONENERGY_COMPARATOR_FLOW
    return out


def load_balance_variable_rules(
    path: Path | str = DEFAULT_BALANCE_VARIABLE_RULES_PATH,
) -> pd.DataFrame:
    """Load the explicit balance-variable/error-signal contract."""
    rules = pd.read_csv(_resolve(path))
    missing = sorted(set(BALANCE_VARIABLE_RULE_COLUMNS) - set(rules.columns))
    if missing:
        raise KeyError(f"Balance-variable rules are missing columns: {missing}")
    enabled = rules["enabled"].fillna(False).astype(str).str.lower().isin(
        {"true", "1", "yes"}
    )
    return rules[enabled].reset_index(drop=True)


def classify_balance_variable(
    *,
    economy: object,
    scenario: object,
    esto_product: object,
    esto_flow: object,
    rules: pd.DataFrame,
) -> dict[str, str]:
    """Resolve the most-specific rule, defaulting unlisted flows to protected."""
    values = {
        "economy": _clean_token(economy),
        "scenario": _clean_token(scenario).lower(),
        "esto_product": _clean_token(esto_product),
        "esto_flow": _clean_token(esto_flow),
    }
    matches: list[tuple[int, int, pd.Series]] = []
    for index, rule in rules.iterrows():
        specificity = 0
        matched = True
        for column, value in values.items():
            rule_value = _clean_token(rule.get(column))
            if column == "scenario":
                rule_value = rule_value.lower()
            if rule_value == "*":
                continue
            if rule_value != value:
                matched = False
                break
            specificity += 1
        if matched:
            matches.append((specificity, int(index), rule))
    if not matches:
        return {
            "balance_variable_role": "protected",
            "error_signal_name": "",
            "balance_variable_rule_reason": (
                "No allowed-change rule applies; differences are protected by default."
            ),
        }
    _, _, selected = sorted(matches, key=lambda item: (-item[0], item[1]))[0]
    return {
        "balance_variable_role": _clean_token(
            selected.get("balance_variable_role")
        ),
        "error_signal_name": _clean_token(selected.get("error_signal_name")),
        "balance_variable_rule_reason": _clean_token(selected.get("reason")),
    }


def _split_pipe_tokens(value: object) -> list[str]:
    return [token.strip() for token in _clean_token(value).split("|") if token.strip()]


def _unique_pipe(values: Iterable[object]) -> str:
    tokens: set[str] = set()
    for value in values:
        tokens.update(_split_pipe_tokens(value))
    return "|".join(sorted(tokens))


def _iter_paired_tokens(left: object, right: object) -> list[tuple[str, str]]:
    """Expand paired mapping tokens without hiding non-one-to-one cardinality."""
    left_tokens = _split_pipe_tokens(left)
    right_tokens = _split_pipe_tokens(right)
    if not left_tokens or not right_tokens:
        return []
    if len(left_tokens) == len(right_tokens):
        return list(dict.fromkeys(zip(left_tokens, right_tokens)))
    if len(left_tokens) == 1:
        return [(left_tokens[0], token) for token in right_tokens]
    if len(right_tokens) == 1:
        return [(token, right_tokens[0]) for token in left_tokens]
    return [(left_token, right_token) for left_token in left_tokens for right_token in right_tokens]


def _count_mapping_pairs(frame: pd.DataFrame, left_col: str, right_col: str) -> int:
    pairs: set[tuple[str, str]] = set()
    if frame.empty:
        return 0
    for row in frame[[left_col, right_col]].itertuples(index=False, name=None):
        pairs.update(_iter_paired_tokens(row[0], row[1]))
    return len(pairs)


def _compact_economy_code(economy: str) -> str:
    return _clean_token(economy).replace("_", "")


def _normalize_scenarios(scenarios: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    for scenario in scenarios:
        label = _clean_token(scenario)
        if label.lower() not in {"reference", "target"}:
            raise ValueError(
                f"Unsupported scenario {scenario!r}. Step 1 accepts Reference and Target."
            )
        canonical = label.title()
        if canonical not in normalized:
            normalized.append(canonical)
    if not normalized:
        raise ValueError("At least one of Reference or Target is required.")
    return normalized


def _validate_years(years: Sequence[int], *, base_year: int) -> list[int]:
    normalized = sorted({int(year) for year in years})
    if not normalized:
        raise ValueError("At least one diagnostic year is required.")
    historical = [year for year in normalized if year < int(base_year)]
    if historical:
        raise ValueError(
            "Step 1 currently supports the ESTO base year and later 9th Outlook "
            f"projection years. Pre-base historical years are not yet supported: {historical}."
        )
    return normalized


def _read_direct_workbook_scope(
    workbook_path: Path | str,
    *,
    base_year: int,
    years: Sequence[int] | None = None,
    scenarios: Sequence[str] | None = None,
) -> tuple[Path, list[int], list[str], list[BalanceExportSheet]]:
    """Read and optionally narrow the scope of one explicit balance workbook."""
    path = _resolve(workbook_path)
    if not path.exists():
        raise FileNotFoundError(f"Direct LEAP balance workbook does not exist: {path}")

    available = list_balance_export_sheets(path)
    selected_years = (
        _validate_years(years, base_year=base_year)
        if years is not None
        else _validate_years(
            [sheet.year for sheet in available],
            base_year=base_year,
        )
    )
    requested_scenarios = (
        _normalize_scenarios(scenarios)
        if scenarios is not None
        else _normalize_scenarios([sheet.scenario for sheet in available])
    )
    available_scenarios = {sheet.scenario for sheet in available}
    selected_scenarios = [
        scenario
        for scenario in requested_scenarios
        if scenario in available_scenarios
    ]
    if not selected_scenarios:
        raise ValueError(
            f"None of the requested scenarios are available in {path}: "
            f"{requested_scenarios}"
        )
    selected = select_balance_export_sheets(
        path,
        years=selected_years,
        scenarios=selected_scenarios,
    )
    if not selected:
        raise ValueError(
            f"No requested scenario/year balance sheets were found in {path}."
        )
    units = sorted({sheet.units.lower() for sheet in selected})
    supported_units = {"petajoule", "thousand petajoule"}
    unsupported_units = sorted(set(units) - supported_units)
    if unsupported_units:
        raise ValueError(
            "Direct LEAP balance diagnostics currently require Petajoule or "
            "Thousand Petajoule workbook metadata; "
            f"found unsupported units {unsupported_units} in {path}."
        )
    actual_years = _validate_years(
        [sheet.year for sheet in selected],
        base_year=base_year,
    )
    actual_scenarios = _normalize_scenarios(
        [sheet.scenario for sheet in selected]
    )
    return path, actual_years, actual_scenarios, selected


def _load_optional_json(path: Path | str | None) -> dict[str, Any]:
    if path is None:
        return {}
    resolved = _resolve(path)
    if not resolved.exists():
        return {}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"Could not read JSON configuration {resolved}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {resolved}.")
    return payload


@contextmanager
def _temporary_balance_runtime_paths(
    *,
    codebook_path: Path,
    sheet_map_path: Path,
    exports_root: Path,
):
    """Route shared loader globals for a worktree run and restore them."""
    from codebase.mappings import canonical_loaders
    from codebase.utilities import master_config

    master_snapshot = {
        "OUTLOOK_MAPPINGS_MASTER_PATH": master_config.OUTLOOK_MAPPINGS_MASTER_PATH,
        "RUNTIME_TABLE_DIR": master_config.RUNTIME_TABLE_DIR,
    }
    canonical_workbook_snapshot = canonical_loaders.CANONICAL_WORKBOOK_PATH
    resolver_defaults = dict(resolve_balance_export_workbook.__kwdefaults__ or {})
    master_config.OUTLOOK_MAPPINGS_MASTER_PATH = codebook_path
    master_config.RUNTIME_TABLE_DIR = sheet_map_path.parent
    canonical_loaders.CANONICAL_WORKBOOK_PATH = codebook_path
    if resolve_balance_export_workbook.__kwdefaults__ is not None:
        resolve_balance_export_workbook.__kwdefaults__["exports_root"] = exports_root

    from codebase.utilities.leap_results_dashboard_balance import (
        build_balance_comparison_esto_axis,
        convert_leap_balances_to_esto_long_table,
    )
    from codebase.utilities import energy_balance_template_extractor

    extractor_snapshot = {
        "LEAP_MAPPINGS_REPO_ROOT": energy_balance_template_extractor.LEAP_MAPPINGS_REPO_ROOT,
        "SUBTOTAL_MISMATCH_EXCEPTIONS_PATH": (
            energy_balance_template_extractor.SUBTOTAL_MISMATCH_EXCEPTIONS_PATH
        ),
        "_SUBTOTAL_MISMATCH_EXCEPTION_SETS": (
            energy_balance_template_extractor._SUBTOTAL_MISMATCH_EXCEPTION_SETS
        ),
        "_DUPLICATE_MAPPING_EXCEPTION_SETS": (
            energy_balance_template_extractor._DUPLICATE_MAPPING_EXCEPTION_SETS
        ),
    }
    energy_balance_template_extractor.LEAP_MAPPINGS_REPO_ROOT = LEAP_MAPPINGS_REPO_ROOT
    energy_balance_template_extractor.SUBTOTAL_MISMATCH_EXCEPTIONS_PATH = (
        LEAP_MAPPINGS_REPO_ROOT / "config" / "mapping_issue_exception_sets.xlsx"
    )
    energy_balance_template_extractor._SUBTOTAL_MISMATCH_EXCEPTION_SETS = None
    energy_balance_template_extractor._DUPLICATE_MAPPING_EXCEPTION_SETS = None
    try:
        yield build_balance_comparison_esto_axis, convert_leap_balances_to_esto_long_table
    finally:
        master_config.OUTLOOK_MAPPINGS_MASTER_PATH = master_snapshot[
            "OUTLOOK_MAPPINGS_MASTER_PATH"
        ]
        master_config.RUNTIME_TABLE_DIR = master_snapshot["RUNTIME_TABLE_DIR"]
        canonical_loaders.CANONICAL_WORKBOOK_PATH = canonical_workbook_snapshot
        if resolve_balance_export_workbook.__kwdefaults__ is not None:
            resolve_balance_export_workbook.__kwdefaults__.clear()
            resolve_balance_export_workbook.__kwdefaults__.update(resolver_defaults)
        for name, value in extractor_snapshot.items():
            setattr(energy_balance_template_extractor, name, value)


def _scope_rows_to_diagnostic_window(
    frame: pd.DataFrame,
    *,
    years: Sequence[int],
    scenarios: Sequence[str],
) -> pd.DataFrame:
    """Limit supporting diagnostics to the same small review window."""
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame.copy()
    scoped = frame.copy()
    if "year" in scoped.columns:
        numeric_year = pd.to_numeric(scoped["year"], errors="coerce")
        scoped = scoped[numeric_year.isin({int(year) for year in years})].copy()
    if "scenario" in scoped.columns:
        wanted = {scenario.lower() for scenario in _normalize_scenarios(scenarios)}
        scoped = scoped[
            scoped["scenario"].fillna("").astype(str).str.strip().str.lower().isin(wanted)
        ].copy()
    return scoped.reset_index(drop=True)


def _preliminary_owner(esto_flow: object) -> str:
    """Return the likely workflow owner from the ESTO flow family."""
    flow = _clean_token(esto_flow)
    if flow.startswith(("01 ", "02 ", "03 ", "04 ", "05 ", "06 ", "07 ")):
        return "supply"
    if flow.startswith("08"):
        return "transfers"
    if flow.startswith("09"):
        return "transformation"
    if flow.startswith("10"):
        return "other_loss_and_own_use"
    if flow.startswith(("12 ", "13 ", "14 ", "15 ", "16 ", "17 ")):
        return "aggregated_demand"
    return "mapping_or_diagnostic"


def build_balance_review_table(
    differences: pd.DataFrame,
    *,
    material_threshold_pj: float = 1.0,
    balance_variable_rules: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Classify differences using the explicit allowed balance-variable contract."""
    review = differences.copy()
    for column in DIFFERENCE_OUTPUT_COLUMNS:
        if column not in review.columns:
            review[column] = pd.NA
    review["leap_balance_row"] = review["leap_sector_names"].fillna("")
    review["leap_balance_fuel"] = review["leap_fuel_names"].fillna("")
    review["material_for_review"] = (
        pd.to_numeric(review["absolute_difference_pj"], errors="coerce")
        .fillna(0.0)
        .ge(float(material_threshold_pj))
    )
    rules = (
        load_balance_variable_rules()
        if balance_variable_rules is None
        else balance_variable_rules.copy()
    )
    variable_classifications = [
        classify_balance_variable(
            economy=row.get("economy"),
            scenario=row.get("scenario"),
            esto_product=row.get("esto_product"),
            esto_flow=row.get("esto_flow"),
            rules=rules,
        )
        for row in review.to_dict("records")
    ]
    review["balance_variable_role"] = [
        row["balance_variable_role"] for row in variable_classifications
    ]
    review["allowed_to_change"] = review["balance_variable_role"].eq("error_signal")
    review["error_signal_name"] = [
        row["error_signal_name"] for row in variable_classifications
    ]
    review["balance_variable_rule_reason"] = [
        row["balance_variable_rule_reason"] for row in variable_classifications
    ]
    review["balance_contract_issue"] = ""
    review["requires_issue_review"] = False
    review["update_signal_eligible"] = False
    review["placeholder_scope"] = (
        review["leap_sector_names"]
        .fillna("")
        .astype(str)
        .str.contains(PLACEHOLDER_SECTOR_PATTERN, regex=True)
    )
    review["placeholder_scope_reason"] = ""
    review.loc[review["placeholder_scope"], "placeholder_scope_reason"] = (
        "Interim/placeholder activity may need a combined placeholder-and-replacement "
        "comparison boundary; it is not automatically excluded."
    )
    review["preliminary_owner"] = review["esto_flow"].map(_preliminary_owner)
    review["primary_classification"] = ""
    review["evidence_note"] = ""
    review["next_action"] = ""

    discrepancy_mask = review["status"].ne("match")
    unavailable = discrepancy_mask & review["status"].isin(
        {"reference_unavailable", "missing_in_reference", "missing_in_leap"}
    )
    allocation_required = discrepancy_mask & review[
        "update_allocation_required"
    ].fillna(False).astype(bool)
    error_signal_difference = (
        discrepancy_mask
        & ~unavailable
        & ~allocation_required
        & review["balance_variable_role"].eq("error_signal")
    )
    derived_difference = (
        discrepancy_mask
        & ~unavailable
        & ~allocation_required
        & review["balance_variable_role"].eq("derived_check")
    )
    protected_difference = (
        discrepancy_mask
        & ~unavailable
        & ~allocation_required
        & review["balance_variable_role"].eq("protected")
    )

    review.loc[unavailable, "balance_contract_issue"] = (
        "comparison_unavailable_or_mapping_issue"
    )
    review.loc[allocation_required, "balance_contract_issue"] = (
        "mapping_allocation_rule_required"
    )
    review.loc[error_signal_difference, "balance_contract_issue"] = (
        "expected_error_signal_difference"
    )
    review.loc[derived_difference, "balance_contract_issue"] = (
        "derived_balance_difference"
    )
    review.loc[protected_difference, "balance_contract_issue"] = (
        "protected_flow_difference"
    )
    review.loc[
        unavailable | allocation_required | derived_difference | protected_difference,
        "requires_issue_review",
    ] = True
    review.loc[error_signal_difference, "update_signal_eligible"] = True

    review.loc[discrepancy_mask, "primary_classification"] = "unresolved"
    review.loc[error_signal_difference, "primary_classification"] = (
        "expected_error_signal"
    )
    review.loc[derived_difference, "primary_classification"] = (
        "derived_balance_difference"
    )
    review.loc[protected_difference, "primary_classification"] = (
        "protected_flow_difference"
    )
    review.loc[discrepancy_mask, "evidence_note"] = (
        "Classified against the allowed balance-variable contract."
    )
    review.loc[error_signal_difference, "evidence_note"] = (
        "Imports are the configured balancing error signal for this fuel."
    )
    review.loc[error_signal_difference, "next_action"] = (
        "Use this difference as updater input, subject to allocator and mapping checks."
    )
    review.loc[
        protected_difference | derived_difference,
        "evidence_note",
    ] = (
        "This variable is not configured as an allowed balancing signal. Investigate "
        "the baseline seed, LEAP balancing rules, or the variable contract."
    )
    review.loc[
        protected_difference | derived_difference,
        "next_action",
    ] = (
        "Raise an issue; do not convert this row directly into a numeric update."
    )
    review.loc[unavailable | allocation_required, "next_action"] = (
        "Resolve comparison coverage or allocation grain before using this row."
    )

    total_final_boundary = (
        discrepancy_mask
        & review["esto_flow"].fillna("").eq("13 Total final energy consumption")
        & review["leap_sector_names"]
        .fillna("")
        .str.lower()
        .eq("total final energy consumption")
    )
    review.loc[total_final_boundary, "primary_classification"] = "diagnostic_bug"
    review.loc[total_final_boundary, "balance_contract_issue"] = (
        "diagnostic_comparison_boundary_bug"
    )
    review.loc[total_final_boundary, "requires_issue_review"] = True
    review.loc[total_final_boundary, "update_signal_eligible"] = False
    review.loc[total_final_boundary, "preliminary_owner"] = "mapping_or_diagnostic"
    review.loc[total_final_boundary, "evidence_note"] = (
        "LEAP Total Final Energy Demand includes the separate Other loss and own "
        "use demand branch, so it is not a direct ESTO flow-13 comparator."
    )
    review.loc[total_final_boundary, "next_action"] = (
        "Define a rollup-aware comparison boundary; do not update seed rows from "
        "this aggregate difference."
    )

    missing_rollup = (
        review["status"].eq("reference_unavailable")
        & review["esto_flow"].fillna("").str.contains(
            r"\(including own use\)",
            regex=True,
        )
    )
    review.loc[
        missing_rollup,
        "primary_classification",
    ] = "mapping_grain_or_allocation_required"
    review.loc[missing_rollup, "preliminary_owner"] = "mapping_or_diagnostic"
    review.loc[missing_rollup, "evidence_note"] = (
        "The named ESTO comparison row is a synthetic own-use boundary rollup, "
        "not a literal row in the raw ESTO table."
    )
    review.loc[missing_rollup, "next_action"] = (
        "Apply the maintained rollup components before numerical comparison."
    )

    leap_nonzero = (
        pd.to_numeric(review["leap_value_pj"], errors="coerce")
        .fillna(0.0)
        .abs()
        .gt(DEFAULT_TOLERANCE_PJ)
    )
    source_missing_or_zero = (
        pd.to_numeric(review["source_value_pj"], errors="coerce")
        .fillna(0.0)
        .abs()
        .le(DEFAULT_TOLERANCE_PJ)
    )
    auxiliary_without_process = review[
        "transformation_auxiliary_comparison_status"
    ].fillna("").eq("auxiliary_present_without_process_comparator")
    confirmed_seed_process = (
        review["esto_flow"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.startswith(SEED_OR_CARRY_FORWARD_TRANSFORMATION_FLOW_PREFIXES)
    )
    review["no_direct_projection_comparator"] = (
        confirmed_seed_process
        & leap_nonzero
        & ~review["reference_source"].fillna("").eq("ESTO")
        & (
            review["status"].eq("reference_unavailable")
            | source_missing_or_zero
            | auxiliary_without_process
        )
    )
    no_projection_comparator = review["no_direct_projection_comparator"]
    review.loc[
        no_projection_comparator, "primary_classification"
    ] = "seed_or_carry_forward_process"
    review.loc[
        no_projection_comparator, "balance_contract_issue"
    ] = "no_direct_projection_comparator"
    review.loc[no_projection_comparator, "requires_issue_review"] = True
    review.loc[no_projection_comparator, "update_signal_eligible"] = False
    review.loc[no_projection_comparator, "evidence_note"] = (
        "No active direct 9th projection transformation comparator is available. "
        "The LEAP process balance is therefore generated from a seed or "
        "carry-forward rule for review purposes."
    )
    review.loc[no_projection_comparator, "next_action"] = (
        "Leave the process efficiency and auxiliary values unchanged unless a "
        "reviewed projection comparator or replacement rule is supplied."
    )

    review["affected_by_no_projection_transformation"] = False
    review["impact_source_transformation_flows"] = ""
    impact_keys = review.loc[
        no_projection_comparator,
        ["economy", "scenario", "year", "esto_product", "esto_flow"],
    ].copy()
    if not impact_keys.empty:
        impact_summary = (
            impact_keys.groupby(
                ["economy", "scenario", "year", "esto_product"],
                dropna=False,
            )["esto_flow"]
            .agg(lambda values: " | ".join(sorted({_clean_token(value) for value in values})))
            .rename("impact_source_transformation_flows")
            .reset_index()
        )
        supply_rows = review["esto_flow"].isin(
            {"01 Production", "02 Imports", "03 Exports"}
        )
        review = review.merge(
            impact_summary,
            on=["economy", "scenario", "year", "esto_product"],
            how="left",
            suffixes=("", "_impact"),
        )
        impact_column = "impact_source_transformation_flows_impact"
        review.loc[
            supply_rows & review[impact_column].fillna("").ne(""),
            "affected_by_no_projection_transformation",
        ] = True
        review.loc[
            review[impact_column].fillna("").ne(""),
            "impact_source_transformation_flows",
        ] = review.loc[
            review[impact_column].fillna("").ne(""),
            impact_column,
        ]
        review = review.drop(columns=impact_column)

    return review[[*DIFFERENCE_OUTPUT_COLUMNS, *REVIEW_ADDED_COLUMNS]].reset_index(
        drop=True
    )


def build_balance_diagnostic_counts(
    differences: pd.DataFrame,
    mapping_issues: pd.DataFrame,
) -> dict[str, int]:
    """Return the separate review counts required before prioritisation."""
    statuses = differences.get("status", pd.Series(dtype=str)).fillna("").astype(str)
    issue_reasons = mapping_issues.get("reason", pd.Series(dtype=str)).fillna("").astype(str)
    issue_severity = (
        mapping_issues.get("severity", pd.Series(dtype=str)).fillna("").astype(str)
    )
    direct_mask = differences.get(
        "comparison_grain",
        pd.Series("", index=differences.index, dtype=str),
    ).eq("direct_leap_to_esto_pair")
    unsafe_mask = differences.get(
        "update_allocation_required",
        pd.Series(False, index=differences.index, dtype=bool),
    ).fillna(False).astype(bool)
    return {
        "value_mismatches": int(statuses.eq("value_mismatch").sum()),
        "rows_missing_from_leap": int(statuses.eq("missing_in_leap").sum()),
        "rows_missing_from_comparator": int(
            statuses.isin(["reference_unavailable", "missing_in_source"]).sum()
        ),
        "unmapped_rows": int(issue_reasons.eq("missing_esto_pair").sum()),
        "total_balance_check_failures": int(
            (
                issue_reasons.eq("total_balance_mapping_check")
                & issue_severity.eq("error")
            ).sum()
        ),
        "direct_one_to_one_comparisons": int(direct_mask.sum()),
        "aggregate_or_shared_unsafe_comparisons": int(unsafe_mask.sum()),
    }


def _write_esto_axis_extraction_mapping_workbook(
    *,
    output_path: Path,
    codebook_path: Path,
) -> Path:
    """Write the strict LEAP->ESTO subset needed by the Step 1 extractor.

    The ESTO-axis diagnostic does not consume ``leap_combined_ninth`` during
    extraction. Future-year source values are joined later through the separate
    canonical ninth_pairs_to_esto_pairs bridge. Keeping a header-only ninth
    sheet prevents unrelated LEAP->9th validation findings from blocking this
    read-only ESTO-axis report without marking those findings as accepted.
    """
    from codebase.utilities.master_config import read_config_table

    esto_mapping = read_config_table(
        codebook_path,
        sheet_name="leap_combined_esto",
        dtype=str,
    )
    esto_mapping = _include_nonenergy_in_other_sector_comparator_mapping(
        esto_mapping
    )
    rollup_rules = read_config_table(
        codebook_path,
        sheet_name="leap_rollup_rules",
        dtype=str,
    )
    required_rollup_columns = {
        "input_leap_sector_name_full_path",
        "rolled_leap_sector_name_full_path",
        "ROLLUP_MODE",
        "include",
    }
    if required_rollup_columns.issubset(rollup_rules.columns):
        include = (
            rollup_rules["include"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.casefold()
            .isin({"1", "true", "yes", "y", "on", "t"})
        )
        expanding = (
            rollup_rules["ROLLUP_MODE"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.casefold()
            .eq("expanding")
        )
        transfer_rules = rollup_rules.loc[
            include
            & expanding
            & rollup_rules["rolled_leap_sector_name_full_path"]
            .fillna("")
            .astype(str)
            .map(_normalize_diagnostic_label)
            .eq("transfers")
        ]
        transfer_mapping = esto_mapping.loc[
            esto_mapping["leap_sector_name_full_path"]
            .fillna("")
            .astype(str)
            .map(_normalize_diagnostic_label)
            .eq("transfers")
        ]
        aliases: list[pd.DataFrame] = []
        for component in transfer_rules[
            "input_leap_sector_name_full_path"
        ].dropna().astype(str):
            component = component.strip()
            if not component:
                continue
            alias = transfer_mapping.copy()
            # Level 2 balance exports expose these rows as a parent and an
            # identically named indented child, so the extractor's full key is
            # Component/Component.
            alias["leap_sector_name_full_path"] = f"{component}/{component}"
            # The maintained mapping correctly labels ESTO 08 Transfers as a
            # subtotal. Unlike ordinary subtotals, however, its product rows
            # contain the real comparison values. The direct diagnostic must
            # therefore pull them rather than replacing them with NA.
            if "esto_pair_is_subtotal" in alias.columns:
                alias["esto_pair_is_subtotal"] = "False"
            alias["subtotal_mismatch_is_ok"] = "True"
            aliases.append(alias)
        if aliases:
            esto_mapping = pd.concat(
                [esto_mapping, *aliases],
                ignore_index=True,
                sort=False,
            ).drop_duplicates(
                subset=[
                    "leap_sector_name_full_path",
                    "raw_leap_fuel_name",
                    "esto_flow",
                    "esto_product",
                ],
                keep="first",
            )

    # Some Level 2 exports shorten the child process label from
    # NG Liquefaction to Liquefaction. The maintained electricity mapping is
    # currently recorded against the repeated parent/child label, while the
    # same workbook already maps natural gas and LNG under the shortened child.
    # Add the equivalent extraction alias without changing the canonical file.
    lng_repeated = esto_mapping[
        esto_mapping["leap_sector_name_full_path"]
        .fillna("")
        .astype(str)
        .map(_normalize_diagnostic_label)
        .eq("ng liquefaction/ng liquefaction")
    ].copy()
    if not lng_repeated.empty:
        lng_repeated["leap_sector_name_full_path"] = (
            "NG Liquefaction/Liquefaction"
        )
        esto_mapping = pd.concat(
            [esto_mapping, lng_repeated],
            ignore_index=True,
            sort=False,
        ).drop_duplicates(
            subset=[
                "leap_sector_name_full_path",
                "raw_leap_fuel_name",
                "esto_flow",
                "esto_product",
            ],
            keep="first",
        )
    ninth_columns = read_config_table(
        codebook_path,
        sheet_name="leap_combined_ninth",
        dtype=str,
    ).columns
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path) as writer:
        esto_mapping.to_excel(writer, sheet_name="leap_combined_esto", index=False)
        pd.DataFrame(columns=ninth_columns).to_excel(
            writer,
            sheet_name="leap_combined_ninth",
            index=False,
        )
    return output_path


def _build_mapping_metadata(
    mapping_status: pd.DataFrame,
    leap_long: pd.DataFrame | None,
    *,
    include_comparison_branch_path: bool,
) -> pd.DataFrame:
    """Return one mapping/cardinality record per displayed comparison row."""
    key_columns = ["sheet", "measure", "fuel_label"]
    if include_comparison_branch_path:
        key_columns.append("comparison_branch_path")
    metadata_columns = [
        *key_columns,
        "esto_flow",
        "esto_product",
        "ninth_sector_codes",
        "ninth_fuel_codes",
        "ninth_pair_count",
        "ninth_pair_max_esto_claimants",
        "leap_sector_names",
        "leap_fuel_names",
        "leap_component_count",
    ]
    if mapping_status is None or mapping_status.empty:
        return pd.DataFrame(columns=metadata_columns)

    status = mapping_status.copy()
    if include_comparison_branch_path and "comparison_branch_path" not in status.columns:
        status["comparison_branch_path"] = status.get(
            "leap_sector_name_full_path",
            pd.Series("", index=status.index),
        )
    for column in [
        *key_columns,
        "esto_flow",
        "esto_product",
        "sector_code_9th",
        "ninth_fuel_code",
    ]:
        if column not in status.columns:
            status[column] = ""
        status[column] = status[column].fillna("").astype(str).str.strip()

    ninth_pair_claimants: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for row in status[
        ["esto_flow", "esto_product", "sector_code_9th", "ninth_fuel_code"]
    ].itertuples(index=False, name=None):
        esto_pairs = _iter_paired_tokens(row[0], row[1])
        ninth_pairs = _iter_paired_tokens(row[2], row[3])
        for ninth_pair in ninth_pairs:
            ninth_pair_claimants.setdefault(ninth_pair, set()).update(esto_pairs)

    records: list[dict[str, Any]] = []
    for key, group in status.groupby(key_columns, dropna=False, sort=False):
        group_ninth_pairs: set[tuple[str, str]] = set()
        for row in group[["sector_code_9th", "ninth_fuel_code"]].itertuples(
            index=False,
            name=None,
        ):
            group_ninth_pairs.update(_iter_paired_tokens(row[0], row[1]))
        records.append(
            {
                "sheet": key[0],
                "measure": key[1],
                "fuel_label": key[2],
                **(
                    {"comparison_branch_path": key[3]}
                    if include_comparison_branch_path
                    else {}
                ),
                "esto_flow": _unique_pipe(group["esto_flow"]),
                "esto_product": _unique_pipe(group["esto_product"]),
                "ninth_sector_codes": _unique_pipe(group["sector_code_9th"]),
                "ninth_fuel_codes": _unique_pipe(group["ninth_fuel_code"]),
                "ninth_pair_count": _count_mapping_pairs(
                    group,
                    "sector_code_9th",
                    "ninth_fuel_code",
                ),
                "ninth_pair_max_esto_claimants": max(
                    (
                        len(ninth_pair_claimants.get(pair, set()))
                        for pair in group_ninth_pairs
                    ),
                    default=0,
                ),
            }
        )
    metadata = pd.DataFrame(records)

    if leap_long is None or leap_long.empty:
        metadata["leap_sector_names"] = ""
        metadata["leap_fuel_names"] = ""
        metadata["leap_component_count"] = 0
        return metadata[metadata_columns]

    leap = leap_long.copy()
    if "sheet" not in leap.columns and "sheet_name" in leap.columns:
        leap["sheet"] = leap["sheet_name"]
    if include_comparison_branch_path and "comparison_branch_path" not in leap.columns:
        leap["comparison_branch_path"] = leap.get(
            "leap_sector_name_full_path",
            pd.Series("", index=leap.index),
        )
    for column in [*key_columns, "leap_sector_name", "leap_fuel_name", "leap_sector", "leap_fuel"]:
        if column not in leap.columns:
            leap[column] = ""
        leap[column] = leap[column].fillna("").astype(str).str.strip()

    component_records: list[dict[str, Any]] = []
    for key, group in leap.groupby(key_columns, dropna=False, sort=False):
        sector_column = "leap_sector_name" if group["leap_sector_name"].ne("").any() else "leap_sector"
        fuel_column = "leap_fuel_name" if group["leap_fuel_name"].ne("").any() else "leap_fuel"
        component_records.append(
            {
                "sheet": key[0],
                "measure": key[1],
                "fuel_label": key[2],
                **(
                    {"comparison_branch_path": key[3]}
                    if include_comparison_branch_path
                    else {}
                ),
                "leap_sector_names": _unique_pipe(group[sector_column]),
                "leap_fuel_names": _unique_pipe(group[fuel_column]),
                "leap_component_count": _count_mapping_pairs(
                    group,
                    sector_column,
                    fuel_column,
                ),
            }
        )
    components = pd.DataFrame(component_records)
    metadata = metadata.merge(components, on=key_columns, how="left")
    metadata["leap_sector_names"] = metadata["leap_sector_names"].fillna("")
    metadata["leap_fuel_names"] = metadata["leap_fuel_names"].fillna("")
    metadata["leap_component_count"] = (
        pd.to_numeric(metadata["leap_component_count"], errors="coerce").fillna(0).astype(int)
    )
    return metadata[metadata_columns]


def _projection_pair_records(mapping_status: pd.DataFrame) -> pd.DataFrame:
    """Expand displayed comparison keys to distinct ESTO target pairs."""
    columns = ["sheet", "measure", "fuel_label", "esto_flow", "esto_product"]
    if mapping_status is None or mapping_status.empty:
        return pd.DataFrame(columns=columns)
    status = mapping_status.copy()
    if "sheet" not in status.columns and "sheet_name" in status.columns:
        status["sheet"] = status["sheet_name"]
    for column in columns:
        if column not in status.columns:
            status[column] = ""
        status[column] = status[column].fillna("").astype(str).str.strip()

    records: list[dict[str, str]] = []
    for row in status[columns].itertuples(index=False, name=None):
        for esto_flow, esto_product in _iter_paired_tokens(row[3], row[4]):
            records.append(
                {
                    "sheet": row[0],
                    "measure": row[1],
                    "fuel_label": row[2],
                    "esto_flow": esto_flow,
                    "esto_product": esto_product,
                }
            )
    if not records:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(records).drop_duplicates().reset_index(drop=True)


def apply_canonical_projection_comparators(
    *,
    comparison_long: pd.DataFrame,
    mapping_status: pd.DataFrame,
    projection_tables: pd.DataFrame,
    allocation_provenance: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replace raw 9th projection claims with allocated ESTO-pair values.

    ``projection_tables`` contains one row per scenario/economy/ESTO pair and
    year columns. ``allocation_provenance`` is optional review detail from the
    same canonical allocation. Only complete displayed comparison groups are
    replaced; incomplete groups retain their original value and stay subject
    to the conservative raw-cardinality gate.
    """
    status_columns = [
        "scenario",
        "sheet",
        "measure",
        "fuel_label",
        "year",
        "projection_allocation_complete",
        "projection_target_pair_count",
        "projection_matched_pair_count",
        "projection_allocation_methods",
        "projection_share_sources",
    ]
    if (
        comparison_long is None
        or comparison_long.empty
        or projection_tables is None
        or projection_tables.empty
    ):
        return comparison_long.copy(), pd.DataFrame(columns=status_columns)

    keys = ["scenario", "sheet", "measure", "fuel_label", "year"]
    targets = comparison_long.copy()
    for column in ["scenario", "sheet", "measure", "fuel_label", "source"]:
        if column not in targets.columns:
            targets[column] = ""
        targets[column] = targets[column].fillna("").astype(str).str.strip()
    targets["scenario"] = targets["scenario"].str.title()
    targets["year"] = pd.to_numeric(targets["year"], errors="coerce").astype("Int64")
    targets = targets[
        targets["source"].str.lower().eq("projection") & targets["year"].notna()
    ][keys].drop_duplicates()
    if targets.empty:
        return comparison_long.copy(), pd.DataFrame(columns=status_columns)

    pair_records = _projection_pair_records(mapping_status)
    if pair_records.empty:
        return comparison_long.copy(), pd.DataFrame(columns=status_columns)
    expanded = targets.merge(
        pair_records,
        on=["sheet", "measure", "fuel_label"],
        how="left",
    )
    expanded = expanded[
        expanded["esto_flow"].fillna("").astype(str).str.strip().ne("")
        & expanded["esto_product"].fillna("").astype(str).str.strip().ne("")
    ].drop_duplicates()
    if expanded.empty:
        return comparison_long.copy(), pd.DataFrame(columns=status_columns)

    projection = projection_tables.copy()
    projection["scenario"] = (
        projection.get("scenario", "").fillna("").astype(str).str.strip().str.title()
    )
    for column in ["esto_flow", "esto_product"]:
        projection[column] = projection.get(column, "").fillna("").astype(str).str.strip()
    year_columns = [
        column
        for column in projection.columns
        if str(column).isdigit()
    ]
    if not year_columns:
        return comparison_long.copy(), pd.DataFrame(columns=status_columns)
    projection_long = projection.melt(
        id_vars=["scenario", "esto_flow", "esto_product"],
        value_vars=year_columns,
        var_name="year",
        value_name="_allocated_projection_value",
    )
    projection_long["year"] = pd.to_numeric(
        projection_long["year"], errors="coerce"
    ).astype("Int64")
    projection_long["_allocated_projection_value"] = pd.to_numeric(
        projection_long["_allocated_projection_value"], errors="coerce"
    )
    projection_long = (
        projection_long.groupby(
            ["scenario", "esto_flow", "esto_product", "year"],
            as_index=False,
            dropna=False,
        )["_allocated_projection_value"]
        .sum(min_count=1)
    )
    # Canonical projection allocation is stored at detailed ESTO flows, while
    # a visible LEAP balance row may map to an honest parent/range selector
    # such as ``14 Industry sector`` or ``16.01-16.02 Buildings``. Materialize
    # only the requested rollup aliases so each detailed ESTO product receives
    # its allocated share instead of comparing one leaf with the entire 9th
    # fuel aggregate.
    requested_pairs = expanded[["esto_flow", "esto_product"]].drop_duplicates()
    existing_pairs = set(
        projection_long[["esto_flow", "esto_product"]].itertuples(
            index=False,
            name=None,
        )
    )
    projection_flow_codes = (
        projection_long["esto_flow"]
        .astype(str)
        .str.extract(r"^(\d+(?:\.\d+)*)", expand=False)
        .fillna("")
    )
    rollup_aliases: list[pd.DataFrame] = []
    for requested_flow, requested_product in requested_pairs.itertuples(
        index=False,
        name=None,
    ):
        pair = (_clean_token(requested_flow), _clean_token(requested_product))
        if not all(pair) or pair in existing_pairs:
            continue
        component_codes = _expand_esto_flow_code_selector(pair[0])
        if not component_codes:
            continue
        product_mask = projection_long["esto_product"].eq(pair[1])
        component_masks: list[pd.Series] = []
        for component_code in component_codes:
            exact_mask = product_mask & projection_flow_codes.eq(component_code)
            component_masks.append(
                exact_mask
                if bool(exact_mask.any())
                else (
                    product_mask
                    & projection_flow_codes.str.startswith(component_code + ".")
                )
            )
        if not component_masks:
            continue
        rollup_mask = component_masks[0].copy()
        for component_mask in component_masks[1:]:
            rollup_mask |= component_mask
        components = projection_long.loc[rollup_mask]
        if components.empty:
            continue
        alias = (
            components.groupby(
                ["scenario", "year"],
                as_index=False,
                dropna=False,
            )["_allocated_projection_value"]
            .sum(min_count=1)
        )
        alias["esto_flow"] = pair[0]
        alias["esto_product"] = pair[1]
        rollup_aliases.append(alias)
    if rollup_aliases:
        projection_long = pd.concat(
            [projection_long, *rollup_aliases],
            ignore_index=True,
            sort=False,
        )

    expanded = expanded.merge(
        projection_long,
        on=["scenario", "esto_flow", "esto_product", "year"],
        how="left",
        indicator="_projection_merge",
    )
    expanded["_pair_key"] = (
        expanded["esto_flow"].astype(str) + "\x1f" + expanded["esto_product"].astype(str)
    )
    pair_counts = (
        expanded.groupby(keys, dropna=False, as_index=False)
        .agg(
            projection_target_pair_count=("_pair_key", "nunique"),
            projection_matched_pair_count=(
                "_projection_merge",
                lambda values: int((values == "both").sum()),
            ),
            _allocated_projection_value=(
                "_allocated_projection_value",
                lambda values: values.sum(min_count=1),
            ),
        )
    )
    pair_counts["projection_allocation_complete"] = (
        pair_counts["projection_target_pair_count"].gt(0)
        & pair_counts["projection_matched_pair_count"].eq(
            pair_counts["projection_target_pair_count"]
        )
    )

    provenance_summary = pd.DataFrame(
        columns=[*keys, "projection_allocation_methods", "projection_share_sources"]
    )
    if allocation_provenance is not None and not allocation_provenance.empty:
        provenance = allocation_provenance.copy()
        provenance["scenario"] = (
            provenance.get("scenario", "")
            .fillna("")
            .astype(str)
            .str.strip()
            .str.title()
        )
        provenance["year"] = pd.to_numeric(
            provenance.get("year"), errors="coerce"
        ).astype("Int64")
        for column in [
            "esto_flow",
            "esto_product",
            "allocation_method",
            "share_source",
        ]:
            provenance[column] = (
                provenance.get(column, "").fillna("").astype(str).str.strip()
            )
        provenance_join = expanded[
            [*keys, "esto_flow", "esto_product"]
        ].drop_duplicates().merge(
            provenance[
                [
                    "scenario",
                    "year",
                    "esto_flow",
                    "esto_product",
                    "allocation_method",
                    "share_source",
                ]
            ],
            on=["scenario", "year", "esto_flow", "esto_product"],
            how="left",
        )
        provenance_summary = (
            provenance_join.groupby(keys, as_index=False, dropna=False)
            .agg(
                projection_allocation_methods=(
                    "allocation_method",
                    _unique_pipe,
                ),
                projection_share_sources=("share_source", _unique_pipe),
            )
        )

    status = pair_counts.merge(provenance_summary, on=keys, how="left")
    status["projection_allocation_methods"] = (
        status["projection_allocation_methods"].fillna("")
    )
    status["projection_share_sources"] = status["projection_share_sources"].fillna("")

    replacement = status[
        [*keys, "projection_allocation_complete", "_allocated_projection_value"]
    ]
    output = comparison_long.copy()
    for column in ["scenario", "sheet", "measure", "fuel_label", "source"]:
        if column not in output.columns:
            output[column] = ""
        output[column] = output[column].fillna("").astype(str).str.strip()
    output["scenario"] = output["scenario"].str.title()
    output["year"] = pd.to_numeric(output["year"], errors="coerce").astype("Int64")
    output = output.merge(replacement, on=keys, how="left")
    replace_mask = (
        output["source"].str.lower().eq("projection")
        & output["projection_allocation_complete"].fillna(False).astype(bool)
    )
    output.loc[replace_mask, "value"] = output.loc[
        replace_mask, "_allocated_projection_value"
    ]
    output = output.drop(
        columns=["projection_allocation_complete", "_allocated_projection_value"]
    )
    return output, status[status_columns].reset_index(drop=True)


def build_canonical_projection_inputs(
    *,
    base_df: pd.DataFrame,
    ninth_df: pd.DataFrame,
    mapping_pairs_path: ConfigTableRef,
    base_year: int,
    projection_years: Sequence[int],
    scenarios: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build allocated ESTO projections once per selected 9th scenario."""
    if not projection_years:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    from codebase.functions.ninth_projection_mapping import (
        build_esto_projection_table,
    )

    projection_parts: list[pd.DataFrame] = []
    diagnostic_parts: list[pd.DataFrame] = []
    provenance_parts: list[pd.DataFrame] = []
    resolved_mapping = _resolve_config_table_ref(mapping_pairs_path)
    for scenario in _normalize_scenarios(scenarios):
        projection, allocation_diagnostics, provenance = build_esto_projection_table(
            ninth_data=ninth_df,
            esto_data=base_df,
            mapping_path=resolved_mapping,
            base_year=int(base_year),
            projection_years=projection_years,
            scenario=scenario.lower(),
            sign_stable_flows="all",
            strict_conservation=False,
            return_allocation_provenance=True,
        )
        for frame in (projection, allocation_diagnostics, provenance):
            if frame is not None and not frame.empty:
                frame["scenario"] = scenario
        if projection is not None and not projection.empty:
            projection_parts.append(projection)
        if allocation_diagnostics is not None and not allocation_diagnostics.empty:
            diagnostic_parts.append(allocation_diagnostics)
        if provenance is not None and not provenance.empty:
            provenance_parts.append(provenance)
    return (
        pd.concat(projection_parts, ignore_index=True, sort=False)
        if projection_parts
        else pd.DataFrame(),
        pd.concat(diagnostic_parts, ignore_index=True, sort=False)
        if diagnostic_parts
        else pd.DataFrame(),
        pd.concat(provenance_parts, ignore_index=True, sort=False)
        if provenance_parts
        else pd.DataFrame(),
    )


def _add_single_lng_child_projection_alias(
    *,
    projection_tables: pd.DataFrame,
    mapping_status: pd.DataFrame,
) -> pd.DataFrame:
    """Alias parent LNG projections when one visible child owns the module."""
    if projection_tables is None or projection_tables.empty:
        return projection_tables.copy()
    if mapping_status is None or mapping_status.empty:
        return projection_tables.copy()

    lng_config = MAJOR_SECTOR_CONFIG["lng"]
    child_flows = {
        _clean_token(lng_config.get("esto_flow_code_liquefaction", "")),
        _clean_token(lng_config.get("esto_flow_code_regasification", "")),
    }
    child_flows.discard("")
    present_flows: set[str] = set()
    for value in mapping_status.get("esto_flow", pd.Series(dtype=str)):
        present_flows.update(_split_pipe_tokens(value))
    selected_children = sorted(child_flows & present_flows)
    if len(selected_children) != 1:
        return projection_tables.copy()

    parent_flow = "09.06.02 Liquefaction/regasification plants"
    out = projection_tables.copy()
    parent_rows = out[
        out["esto_flow"].fillna("").astype(str).str.strip().eq(parent_flow)
    ].copy()
    if parent_rows.empty:
        return out
    parent_rows["esto_flow"] = selected_children[0]
    out = pd.concat([out, parent_rows], ignore_index=True, sort=False)
    dedupe_columns = [
        column
        for column in ["scenario", "esto_flow", "esto_product"]
        if column in out.columns
    ]
    return out.drop_duplicates(
        subset=dedupe_columns,
        keep="first",
    ).reset_index(drop=True)


def _add_direct_lng_projection_fallback(
    *,
    projection_tables: pd.DataFrame,
    ninth_df: pd.DataFrame,
    mapping_status: pd.DataFrame,
    mapping_pairs_path: ConfigTableRef,
    economy: str,
    projection_years: Sequence[int],
    scenarios: Sequence[str],
) -> pd.DataFrame:
    """Add exact LNG rows when share allocation has no historical base profile."""
    if ninth_df is None or ninth_df.empty or not projection_years:
        return projection_tables.copy()

    lng_config = MAJOR_SECTOR_CONFIG["lng"]
    child_flows = {
        _clean_token(lng_config.get("esto_flow_code_liquefaction", "")),
        _clean_token(lng_config.get("esto_flow_code_regasification", "")),
    }
    child_flows.discard("")
    present_flows: set[str] = set()
    for value in mapping_status.get("esto_flow", pd.Series(dtype=str)):
        present_flows.update(_split_pipe_tokens(value))
    selected_children = sorted(child_flows & present_flows)
    if len(selected_children) != 1:
        return projection_tables.copy()

    from codebase.functions.ninth_projection_mapping import add_ninth_pair_columns
    from codebase.utilities.master_config import read_config_table

    mapping_ref = _resolve_config_table_ref(mapping_pairs_path)
    if isinstance(mapping_ref, tuple):
        mapping_df = read_config_table(
            mapping_ref[0],
            sheet_name=mapping_ref[1],
            dtype=str,
        ).fillna("")
    else:
        mapping_df = read_config_table(mapping_ref, dtype=str).fillna("")
    ninth_sector = _clean_token(lng_config["transformation_sub2"][0])
    parent_flow = "09.06.02 Liquefaction/regasification plants"
    pair_map = mapping_df[
        mapping_df["ninth_sector"].fillna("").astype(str).str.strip().eq(ninth_sector)
        & mapping_df["esto_flow"].fillna("").astype(str).str.strip().eq(parent_flow)
    ][["ninth_fuel", "esto_product"]].drop_duplicates()
    if pair_map.empty:
        return projection_tables.copy()

    source = ninth_df.copy()
    if "economy" in source.columns:
        source = source[
            source["economy"]
            .fillna("")
            .astype(str)
            .str.replace("_", "", regex=False)
            .str.upper()
            .eq(_clean_token(economy).replace("_", "").upper())
        ].copy()
    source = source[
        source.get("sub2sectors", pd.Series("", index=source.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .eq(ninth_sector)
    ].copy()
    if source.empty:
        return projection_tables.copy()
    source = add_ninth_pair_columns(source)
    source = source.merge(pair_map, on="ninth_fuel", how="inner")
    if source.empty:
        return projection_tables.copy()

    scenario_values = {value.lower() for value in _normalize_scenarios(scenarios)}
    source = source[
        source["scenarios"].fillna("").astype(str).str.strip().str.lower().isin(
            scenario_values
        )
    ].copy()
    if source.empty:
        return projection_tables.copy()
    source["scenario"] = source["scenarios"].astype(str).str.strip().str.title()
    year_columns = [
        column
        for year in projection_years
        for column in source.columns
        if str(column) == str(int(year))
    ]
    if not year_columns:
        return projection_tables.copy()
    for column in year_columns:
        source[column] = pd.to_numeric(source[column], errors="coerce")

    fallback = (
        source.groupby(["scenario", "esto_product"], as_index=False, dropna=False)[
            year_columns
        ]
        .sum(min_count=1)
    )
    fallback["economy_key"] = _clean_token(economy).replace("_", "").upper()
    fallback["esto_flow"] = selected_children[0]
    ordered = [
        "economy_key",
        "scenario",
        "esto_flow",
        "esto_product",
        *year_columns,
    ]
    out = pd.concat(
        [projection_tables, fallback[ordered]],
        ignore_index=True,
        sort=False,
    )
    return out.drop_duplicates(
        subset=["scenario", "esto_flow", "esto_product"],
        keep="first",
    ).reset_index(drop=True)


def _comparison_grain(row: pd.Series) -> str:
    leap_count = int(row.get("leap_component_count", 0) or 0)
    ninth_count = int(row.get("ninth_pair_count", 0) or 0)
    ninth_claimants = int(row.get("ninth_pair_max_esto_claimants", 0) or 0)
    source = _clean_token(row.get("reference_source", "")).lower()
    if source == "9th outlook":
        if bool(row.get("projection_allocation_complete", False)):
            return "canonical_allocated_ninth_to_esto_pair"
        if ninth_claimants > 1 and leap_count > 1:
            return "aggregate_many_leap_via_shared_ninth_pair"
        if ninth_claimants > 1:
            return "aggregate_shared_ninth_pair_across_esto_rows"
        if leap_count > 1 and ninth_count > 1:
            return "aggregate_many_leap_to_many_ninth"
        if leap_count > 1:
            return "aggregate_many_leap_to_one_ninth"
        if ninth_count > 1:
            return "aggregate_one_leap_to_many_ninth"
        return "direct_leap_to_ninth_via_esto_pair"
    if leap_count > 1:
        return "aggregate_many_leap_to_one_esto"
    return "direct_leap_to_esto_pair"


def _allocation_reason(row: pd.Series) -> str:
    reasons: list[str] = []
    if int(row.get("leap_component_count", 0) or 0) > 1:
        reasons.append("multiple_leap_components_share_the_esto_pair")
    projection_allocation_complete = bool(
        row.get("projection_allocation_complete", False)
    )
    if (
        _clean_token(row.get("reference_source", "")).lower() == "9th outlook"
        and not projection_allocation_complete
        and int(row.get("ninth_pair_count", 0) or 0) > 1
    ):
        reasons.append("esto_pair_sums_multiple_ninth_pairs")
    if (
        _clean_token(row.get("reference_source", "")).lower() == "9th outlook"
        and not projection_allocation_complete
        and int(row.get("ninth_pair_max_esto_claimants", 0) or 0) > 1
    ):
        reasons.append("ninth_pair_is_shared_by_multiple_esto_pairs")
    return ";".join(reasons)


def _transformation_auxiliary_rules() -> list[dict[str, object]]:
    """Return the active LEAP transformation-module own-use boundaries."""
    rules: list[dict[str, object]] = []
    for config_key in TRANSFORMATION_AUXILIARY_CONFIG_KEYS:
        config = MAJOR_SECTOR_CONFIG[config_key]
        transformation_flows = list(
            config.get("transformation_flow_codes", [])
        )
        if config_key in {"coal_coke_ovens", "coal_blast_furnaces"}:
            transformation_flows.extend(
                f"{flow} (including own use)"
                for flow in tuple(transformation_flows)
            )
        rules.append(
            {
                "config_key": config_key,
                "transformation_flows": transformation_flows,
                "auxiliary_flows": list(config.get("loss_flow_codes", [])),
            }
        )

    return [
        rule
        for rule in rules
        if rule["transformation_flows"] and rule["auxiliary_flows"]
    ]


def _base_auxiliary_values_long(
    *,
    base_df: pd.DataFrame | None,
    economy: str,
    auxiliary_flows: Sequence[str],
) -> pd.DataFrame:
    """Extract raw ESTO own-use values for one transformation boundary."""
    columns = ["esto_product", "year", "_auxiliary_value_pj"]
    if base_df is None or base_df.empty:
        return pd.DataFrame(columns=columns)
    required = {"economy", "flows", "products"}
    missing = sorted(required - set(base_df.columns))
    if missing:
        raise KeyError(f"base_df is missing transformation comparison columns: {missing}")

    year_columns = {
        int(str(column)): column
        for column in base_df.columns
        if str(column).strip().isdigit()
    }
    scoped = base_df.copy()
    scoped["_economy_key"] = (
        scoped["economy"]
        .fillna("")
        .astype(str)
        .str.replace("_", "", regex=False)
        .str.upper()
    )
    scoped = scoped[
        scoped["_economy_key"].eq(_clean_token(economy).replace("_", "").upper())
        & scoped["flows"].fillna("").astype(str).str.strip().isin(auxiliary_flows)
    ].copy()
    if "is_subtotal" in scoped.columns:
        subtotal = (
            scoped["is_subtotal"]
            .fillna(False)
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"true", "1", "yes"})
        )
        scoped = scoped[~subtotal].copy()

    records: list[dict[str, object]] = []
    for _, row in scoped.iterrows():
        for year, column in year_columns.items():
            value = pd.to_numeric(
                pd.Series([row.get(column)]), errors="coerce"
            ).iloc[0]
            if pd.notna(value):
                records.append(
                    {
                        "esto_product": _clean_token(row.get("products", "")),
                        "year": int(year),
                        "_auxiliary_value_pj": float(value),
                    }
                )
    if not records:
        return pd.DataFrame(columns=columns)
    return (
        pd.DataFrame(records)
        .groupby(["esto_product", "year"], as_index=False)[
            "_auxiliary_value_pj"
        ]
        .sum()
    )


def _projection_auxiliary_values_long(
    *,
    projection_tables: pd.DataFrame | None,
    auxiliary_flows: Sequence[str],
) -> pd.DataFrame:
    """Extract allocated 9th own-use values for one transformation boundary."""
    columns = ["scenario", "esto_product", "year", "_auxiliary_value_pj"]
    if projection_tables is None or projection_tables.empty:
        return pd.DataFrame(columns=columns)
    required = {"scenario", "esto_flow", "esto_product"}
    missing = sorted(required - set(projection_tables.columns))
    if missing:
        raise KeyError(
            f"projection_tables is missing transformation comparison columns: {missing}"
        )

    year_columns = [
        column for column in projection_tables.columns if str(column).isdigit()
    ]
    scoped = projection_tables[
        projection_tables["esto_flow"]
        .fillna("")
        .astype(str)
        .str.strip()
        .isin(auxiliary_flows)
    ].copy()
    if scoped.empty or not year_columns:
        return pd.DataFrame(columns=columns)
    scoped["scenario"] = (
        scoped["scenario"].fillna("").astype(str).str.strip().str.title()
    )
    scoped["esto_product"] = (
        scoped["esto_product"].fillna("").astype(str).str.strip()
    )
    long = scoped.melt(
        id_vars=["scenario", "esto_product"],
        value_vars=year_columns,
        var_name="year",
        value_name="_auxiliary_value_pj",
    )
    long["year"] = pd.to_numeric(long["year"], errors="coerce").astype("Int64")
    long["_auxiliary_value_pj"] = pd.to_numeric(
        long["_auxiliary_value_pj"], errors="coerce"
    )
    return (
        long.groupby(
            ["scenario", "esto_product", "year"],
            as_index=False,
            dropna=False,
        )["_auxiliary_value_pj"]
        .sum(min_count=1)
    )


def _add_auxiliary_values_for_active_process(
    *,
    wide: pd.DataFrame,
    value_column: str,
    auxiliary_values: pd.DataFrame,
    transformation_flows: Sequence[str],
    join_columns: Sequence[str],
    tolerance_pj: float,
) -> pd.DataFrame:
    """Add own-use only when exactly one configured process comparator is active."""
    if auxiliary_values.empty:
        return wide
    out = wide.copy()
    scoped = out[
        out["esto_flow"].isin(transformation_flows) & out[value_column].notna()
    ].copy()
    if scoped.empty:
        return out

    activity = (
        scoped.assign(_absolute_direct=scoped[value_column].abs())
        .groupby([*join_columns, "esto_flow"], as_index=False, dropna=False)[
            "_absolute_direct"
        ]
        .sum()
    )
    active = activity[activity["_absolute_direct"].gt(float(tolerance_pj))]
    active_counts = (
        active.groupby(list(join_columns), dropna=False)["esto_flow"]
        .nunique()
        .rename("_active_process_count")
        .reset_index()
    )
    active = active.merge(active_counts, on=list(join_columns), how="left")
    active = active[active["_active_process_count"].eq(1)][
        [*join_columns, "esto_flow"]
    ].rename(columns={"esto_flow": "_active_transformation_flow"})

    out = out.merge(active, on=list(join_columns), how="left")
    out = out.merge(auxiliary_values, on=[*join_columns, "esto_product"], how="left")
    target = (
        out["esto_flow"].eq(out["_active_transformation_flow"])
        & out["_auxiliary_value_pj"].notna()
    )
    out.loc[target, value_column] = (
        out.loc[target, value_column].fillna(0.0)
        + out.loc[target, "_auxiliary_value_pj"]
    )
    out.loc[
        target, "transformation_auxiliary_comparison_status"
    ] = "combined_with_active_process_comparator"

    auxiliary_present = (
        out["esto_flow"].isin(transformation_flows)
        & out["_auxiliary_value_pj"].fillna(0.0).abs().gt(float(tolerance_pj))
        & out["_active_transformation_flow"].isna()
    )
    out.loc[
        auxiliary_present, "transformation_auxiliary_comparison_status"
    ] = "auxiliary_present_without_process_comparator"
    return out.drop(
        columns=["_active_transformation_flow", "_auxiliary_value_pj"]
    )


def _add_transformation_auxiliary_own_use_to_references(
    *,
    wide: pd.DataFrame,
    base_df: pd.DataFrame | None,
    projection_tables: pd.DataFrame | None,
    economy: str,
    tolerance_pj: float,
) -> pd.DataFrame:
    """Align source comparators with LEAP's net transformation-module boundary."""
    out = wide.copy()
    out["transformation_auxiliary_comparison_status"] = ""
    for rule in _transformation_auxiliary_rules():
        transformation_flows = list(rule["transformation_flows"])
        auxiliary_flows = list(rule["auxiliary_flows"])
        base_auxiliary = _base_auxiliary_values_long(
            base_df=base_df,
            economy=economy,
            auxiliary_flows=auxiliary_flows,
        )
        out = _add_auxiliary_values_for_active_process(
            wide=out,
            value_column="base",
            auxiliary_values=base_auxiliary,
            transformation_flows=transformation_flows,
            join_columns=["year"],
            tolerance_pj=tolerance_pj,
        )
        projection_auxiliary = _projection_auxiliary_values_long(
            projection_tables=projection_tables,
            auxiliary_flows=auxiliary_flows,
        )
        out = _add_auxiliary_values_for_active_process(
            wide=out,
            value_column="projection",
            auxiliary_values=projection_auxiliary,
            transformation_flows=transformation_flows,
            join_columns=["scenario", "year"],
            tolerance_pj=tolerance_pj,
        )
    return out


def build_leap_source_difference_table(
    *,
    comparison_long: pd.DataFrame,
    mapping_status: pd.DataFrame,
    leap_long: pd.DataFrame | None = None,
    projection_allocation_status: pd.DataFrame | None = None,
    reassignment_status: pd.DataFrame | None = None,
    base_df: pd.DataFrame | None = None,
    projection_tables: pd.DataFrame | None = None,
    economy: str,
    years: Sequence[int],
    scenarios: Sequence[str],
    base_year: int = DEFAULT_BASE_YEAR,
    tolerance_pj: float = DEFAULT_TOLERANCE_PJ,
) -> pd.DataFrame:
    """Build the narrow Step 1 LEAP-versus-source diagnostic table."""
    required = {"scenario", "sheet", "measure", "fuel_label", "source", "year", "value"}
    missing = sorted(required - set(comparison_long.columns))
    if missing:
        raise KeyError(f"comparison_long is missing required columns: {missing}")

    selected_years = {int(year) for year in years}
    selected_scenarios = {scenario.lower() for scenario in _normalize_scenarios(scenarios)}
    working = comparison_long.copy()
    working["scenario"] = working["scenario"].fillna("").astype(str).str.strip().str.title()
    working["year"] = pd.to_numeric(working["year"], errors="coerce").astype("Int64")
    working["value"] = pd.to_numeric(working["value"], errors="coerce")
    working["source"] = working["source"].fillna("").astype(str).str.strip().str.lower()
    working = working[
        working["year"].isin(selected_years)
        & working["scenario"].str.lower().isin(selected_scenarios)
        & working["source"].isin({"leap", "base", "projection"})
    ].copy()
    if working.empty:
        return pd.DataFrame(columns=DIFFERENCE_OUTPUT_COLUMNS)

    include_comparison_branch_path = "comparison_branch_path" in working.columns
    if not include_comparison_branch_path:
        working["comparison_branch_path"] = ""
    working["comparison_branch_path"] = (
        working["comparison_branch_path"].fillna("").astype(str).str.strip()
    )
    key_columns = [
        "scenario",
        "sheet",
        "measure",
        "fuel_label",
        "comparison_branch_path",
        "year",
    ]
    grouped = (
        working.groupby([*key_columns, "source"], dropna=False, as_index=False)["value"]
        .sum(min_count=1)
    )
    wide = grouped.pivot_table(
        index=key_columns,
        columns="source",
        values="value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    for column in ["leap", "base", "projection"]:
        if column not in wide.columns:
            wide[column] = pd.NA
        wide[column] = pd.to_numeric(wide[column], errors="coerce")

    metadata = _build_mapping_metadata(
        mapping_status,
        leap_long,
        include_comparison_branch_path=include_comparison_branch_path,
    )
    metadata_join_columns = ["sheet", "measure", "fuel_label"]
    if include_comparison_branch_path:
        metadata_join_columns.append("comparison_branch_path")
    wide = wide.merge(
        metadata,
        on=metadata_join_columns,
        how="left",
    )
    def _distinct_esto_pair_count(group: pd.DataFrame) -> int:
        return len(
            {
                pair
                for row in group[["esto_flow", "esto_product"]].itertuples(
                    index=False,
                    name=None,
                )
                for pair in _iter_paired_tokens(row[0], row[1])
            }
        )

    comparison_pair_counts = (
        wide.groupby(
            ["scenario", "sheet", "measure", "fuel_label", "year"],
            dropna=False,
        )
        .apply(_distinct_esto_pair_count)
    )
    comparison_keys = pd.MultiIndex.from_frame(
        wide[["scenario", "sheet", "measure", "fuel_label", "year"]]
    )
    single_diagnostic_target = pd.Series(
        comparison_keys.map(comparison_pair_counts).to_numpy() == 1,
        index=wide.index,
    )
    wide["_visible_cell_key"] = [
        (
            f"leap::{_clean_token(row.leap_sector_names)}::"
            f"{_clean_token(row.leap_fuel_names)}"
            if _clean_token(row.leap_sector_names)
            or _clean_token(row.leap_fuel_names)
            else (
                f"diagnostic::{_clean_token(row.sheet)}::"
                f"{_clean_token(row.measure)}::{_clean_token(row.fuel_label)}"
            )
        )
        for row in wide[
            [
                "leap_sector_names",
                "leap_fuel_names",
                "sheet",
                "measure",
                "fuel_label",
            ]
        ].itertuples(index=False)
    ]
    visible_pair_counts = (
        wide.groupby(
            ["scenario", "_visible_cell_key", "year"],
            dropna=False,
        )
        .apply(_distinct_esto_pair_count)
    )
    visible_keys = pd.MultiIndex.from_frame(
        wide[["scenario", "_visible_cell_key", "year"]]
    )
    single_visible_target = pd.Series(
        visible_keys.map(visible_pair_counts).to_numpy() == 1,
        index=wide.index,
    )
    single_target = single_diagnostic_target & single_visible_target
    if base_df is not None and not base_df.empty:
        missing_base = (
            wide["base"].isna()
            & wide["year"].eq(int(base_year))
            & single_target
            & wide["esto_flow"].fillna("").astype(str).str.strip().ne("")
            & wide["esto_product"].fillna("").astype(str).str.strip().ne("")
        )
        if bool(missing_base.any()):
            wide.loc[missing_base, "base"] = [
                pull_base_year_value(
                    base_df,
                    base_year=int(base_year),
                    economy_code=_compact_economy_code(economy),
                    esto_flow=_clean_token(row.esto_flow),
                    esto_product=_clean_token(row.esto_product),
                )
                for row in wide.loc[
                    missing_base,
                    ["esto_flow", "esto_product"],
                ].itertuples(index=False)
            ]
    if reassignment_status is not None and not reassignment_status.empty:
        reassigned = reassignment_status.copy()
        for column in [
            "dataset",
            "source_esto_flow",
            "source_esto_product",
        ]:
            if column not in reassigned.columns:
                reassigned[column] = ""
            reassigned[column] = (
                reassigned[column].fillna("").astype(str).str.strip()
            )
        if "matched_rows" not in reassigned.columns:
            reassigned["matched_rows"] = 0
        reassigned["matched_rows"] = pd.to_numeric(
            reassigned["matched_rows"], errors="coerce"
        ).fillna(0)
        reassigned_zero_pairs = set(
            reassigned.loc[
                reassigned["dataset"].eq("base_df")
                & reassigned["matched_rows"].gt(0)
                & reassigned["source_esto_flow"].ne("")
                & reassigned["source_esto_product"].ne(""),
                ["source_esto_flow", "source_esto_product"],
            ].itertuples(index=False, name=None)
        )
        reassigned_zero = (
            wide["base"].isna()
            & wide["year"].eq(int(base_year))
            & single_target
            & wide[["esto_flow", "esto_product"]].apply(
                lambda row: tuple(row) in reassigned_zero_pairs,
                axis=1,
            )
        )
        wide.loc[reassigned_zero, "base"] = 0.0
    wide = _add_transformation_auxiliary_own_use_to_references(
        wide=wide,
        base_df=base_df,
        projection_tables=projection_tables,
        economy=economy,
        tolerance_pj=tolerance_pj,
    )

    has_base = wide["base"].notna()
    has_projection = wide["projection"].notna()
    wide["reference_source"] = ""
    wide.loc[has_base & ~has_projection, "reference_source"] = "ESTO"
    wide.loc[has_projection & ~has_base, "reference_source"] = "9th Outlook"
    wide.loc[has_base & has_projection, "reference_source"] = "ambiguous"
    wide["source_value_pj"] = wide["base"].combine_first(wide["projection"])
    wide["leap_value_pj"] = wide["leap"]
    # Aggregated demand is written to LEAP as positive energy demand. ESTO and
    # 9th balance tables retain international bunkers as negative withdrawals.
    # Compare magnitudes at this demand boundary so an exact match is not
    # reported as an artificial two-times-value error.
    comparison_branch_path = (
        wide["comparison_branch_path"].fillna("").astype(str).str.strip().str.casefold()
    )
    international_demand = (
        (
            wide["sheet"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.casefold()
            .eq("international transport")
            | wide["leap_sector_names"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.casefold()
            .eq("international transport")
            | comparison_branch_path.str.endswith("international transport")
        )
        & wide["esto_flow"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.startswith(("04", "05"))
    )
    wide.loc[international_demand, "source_value_pj"] = wide.loc[
        international_demand, "source_value_pj"
    ].abs()

    # LEAP's Statistical Differences control uses the opposite sign from the
    # ESTO/9th statistical-discrepancy balance row. Match the supply-export
    # convention here so a correct LEAP balance is not reported as a
    # two-times-value preview mismatch.
    statistical_differences = (
        wide["esto_flow"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.startswith("11 Statistical discrepancy")
    )
    wide.loc[statistical_differences, "source_value_pj"] = -wide.loc[
        statistical_differences, "source_value_pj"
    ]

    both_present = wide["leap_value_pj"].notna() & wide["source_value_pj"].notna()
    wide["difference_pj"] = wide["leap_value_pj"] - wide["source_value_pj"]
    wide["absolute_difference_pj"] = wide["difference_pj"].abs()
    wide["correction_to_match_source_pj"] = -wide["difference_pj"]
    nonzero_reference = wide["source_value_pj"].abs().gt(float(tolerance_pj))
    wide["difference_percent"] = pd.NA
    wide.loc[both_present & nonzero_reference, "difference_percent"] = (
        wide.loc[both_present & nonzero_reference, "difference_pj"]
        / wide.loc[both_present & nonzero_reference, "source_value_pj"]
        * 100.0
    )

    wide["status"] = "reference_unavailable"
    wide.loc[wide["leap_value_pj"].isna() & wide["source_value_pj"].notna(), "status"] = "missing_in_leap"
    wide.loc[
        both_present
        & (
            wide["absolute_difference_pj"].le(float(tolerance_pj))
            | wide["difference_percent"].abs().le(
                DEFAULT_ROUNDING_TOLERANCE_PERCENT
            )
        ),
        "status",
    ] = "match"
    wide.loc[
        both_present
        & wide["absolute_difference_pj"].gt(float(tolerance_pj))
        & ~wide["difference_percent"].abs().le(
            DEFAULT_ROUNDING_TOLERANCE_PERCENT
        ),
        "status",
    ] = "value_mismatch"
    wide.loc[has_base & has_projection, "status"] = "ambiguous_reference"
    wide["is_mismatch"] = wide["status"].isin({"value_mismatch", "missing_in_leap"})

    allocation_keys = ["scenario", "sheet", "measure", "fuel_label", "year"]
    if (
        projection_allocation_status is not None
        and not projection_allocation_status.empty
    ):
        allocation_status = projection_allocation_status.copy()
        allocation_status["scenario"] = (
            allocation_status["scenario"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.title()
        )
        allocation_status["year"] = pd.to_numeric(
            allocation_status["year"], errors="coerce"
        ).astype("Int64")
        wide = wide.merge(
            allocation_status,
            on=allocation_keys,
            how="left",
        )
    for column in [
        "esto_flow",
        "esto_product",
        "ninth_sector_codes",
        "ninth_fuel_codes",
        "leap_sector_names",
        "leap_fuel_names",
    ]:
        wide[column] = wide.get(column, "").fillna("").astype(str)
    for column in [
        "leap_component_count",
        "ninth_pair_count",
        "ninth_pair_max_esto_claimants",
    ]:
        wide[column] = pd.to_numeric(wide.get(column, 0), errors="coerce").fillna(0).astype(int)
    if "projection_allocation_complete" not in wide.columns:
        wide["projection_allocation_complete"] = False
    wide["projection_allocation_complete"] = wide[
        "projection_allocation_complete"
    ].fillna(False).astype(bool)
    for column in [
        "projection_target_pair_count",
        "projection_matched_pair_count",
    ]:
        if column not in wide.columns:
            wide[column] = 0
        wide[column] = (
            pd.to_numeric(wide[column], errors="coerce")
            .fillna(0)
            .astype(int)
        )
    for column in [
        "projection_allocation_methods",
        "projection_share_sources",
    ]:
        if column not in wide.columns:
            wide[column] = ""
        wide[column] = wide[column].fillna("").astype(str)

    wide["economy"] = _clean_token(economy)
    wide["comparison_grain"] = wide.apply(_comparison_grain, axis=1)
    wide["update_allocation_reason"] = wide.apply(_allocation_reason, axis=1)
    wide["update_allocation_required"] = wide["update_allocation_reason"].ne("")

    status_order = {
        "value_mismatch": 0,
        "missing_in_leap": 1,
        "ambiguous_reference": 2,
        "reference_unavailable": 3,
        "match": 4,
    }
    wide["_status_order"] = wide["status"].map(status_order).fillna(99)
    wide = wide.sort_values(
        ["_status_order", "absolute_difference_pj", "scenario", "year", "esto_flow", "esto_product"],
        ascending=[True, False, True, True, True, True],
        na_position="last",
        kind="mergesort",
    ).drop(columns=["_status_order", "leap", "base", "projection"])
    return wide[DIFFERENCE_OUTPUT_COLUMNS].reset_index(drop=True)


def _override_direct_demand_sources(
    difference_table: pd.DataFrame,
    ninth_df: pd.DataFrame,
    economy: str,
    base_year: int,
    tolerance_pj: float,
    mapping_pairs_path: ConfigTableRef,
) -> pd.DataFrame:
    """Override two aggregate-demand comparators with direct mapped 9th detail."""
    if difference_table.empty or ninth_df is None or ninth_df.empty:
        return difference_table
    out = difference_table.copy()
    out["_direct_group"] = out["comparison_branch_path"].fillna("").astype(str).str.casefold().map(
        {
            "all demand aggregated/industry": "industry",
            "all demand aggregated/transport non road": "transport_non_road",
        }
    )
    targets = out.loc[
        out["_direct_group"].notna()
        & out["scenario"].astype(str).str.casefold().eq("target")
        & pd.to_numeric(out["year"], errors="coerce").gt(int(base_year))
    ].copy()
    if targets.empty:
        return difference_table
    scoped = ninth_df.loc[
        ninth_df["economy"].fillna("").astype(str).map(_compact_economy_code).eq(_compact_economy_code(economy))
        & ninth_df["scenarios"].fillna("").astype(str).str.casefold().eq("target")
    ].copy()
    if scoped.empty:
        return difference_table
    from codebase.functions.ninth_projection_mapping import add_ninth_pair_columns

    scoped = add_ninth_pair_columns(scoped)
    year_columns = [column for column in scoped.columns if str(column).isdigit()]
    if not year_columns:
        return difference_table
    from codebase.utilities.master_config import read_config_table

    mapping_ref = _resolve_config_table_ref(mapping_pairs_path)
    rollup_rules = read_config_table(
        mapping_ref[0], sheet_name="ninth_rollup_rules", dtype=str
    ).fillna("")
    active_non_road_rules = rollup_rules.loc[
        rollup_rules["rolled_ninth_sector"].eq(
            "15_01,15_03-15_06 Transport non-road"
        )
        & rollup_rules["rollup_context"].eq(
            "transport_non_road_comparison"
        )
        & rollup_rules["include"].astype(str).str.strip().str.lower().isin(
            {"1", "true", "yes", "y", "t"}
        ),
        "input_ninth_sector",
    ]
    non_road_component_sectors = set(
        active_non_road_rules.astype(str).str.strip().loc[
            active_non_road_rules.astype(str).str.strip().ne("")
        ]
    )
    sector_masks = {
        "industry": scoped["ninth_sector"].eq("14_industry_sector"),
        # The component rules are at the 9th ``sub1sectors`` level.  The
        # derived ``ninth_sector`` is deliberately more specific (for example
        # 15_01_01_passenger), so it cannot be compared to these parents.
        "transport_non_road": scoped["sub1sectors"].isin(
            non_road_component_sectors
        )
        # CSV-backed 9th inputs commonly carry this as the string "False".
        # ``astype(bool)`` treats every non-empty string as true and would
        # therefore discard all non-road component rows.
        & ~scoped["subtotal_results"]
        .fillna(False)
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"1", "true", "yes", "y", "t"}),
    }
    direct_source = pd.concat(
        [
            scoped.loc[mask, year_columns].assign(
                _direct_group=group_name,
                ninth_fuel_code=scoped.loc[mask, "ninth_fuel"],
            )
            for group_name, mask in sector_masks.items()
            if bool(mask.any())
        ],
        ignore_index=True,
    )
    if direct_source.empty:
        return difference_table
    direct_values = direct_source.melt(
        id_vars=["_direct_group", "ninth_fuel_code"],
        value_vars=year_columns,
        var_name="year",
        value_name="source_value_pj",
    )
    direct_values["year"] = pd.to_numeric(direct_values["year"], errors="coerce").astype("Int64")
    direct_values["source_value_pj"] = pd.to_numeric(direct_values["source_value_pj"], errors="coerce")
    direct_values = direct_values.groupby(
        ["_direct_group", "ninth_fuel_code", "year"], as_index=False, dropna=False
    )["source_value_pj"].sum(min_count=1)

    mapping = read_config_table(
        mapping_ref[0], sheet_name=mapping_ref[1], dtype=str
    ).fillna("")
    mapping = mapping.loc[
        mapping["ninth_sector"].eq("14_industry_sector")
        | mapping["esto_flow"].eq("15.01,15.03-15.06 Transport non-road"),
        ["ninth_sector", "ninth_fuel", "esto_flow", "esto_product"],
    ].rename(columns={"ninth_fuel": "ninth_fuel_code"})
    mapping["_direct_group"] = mapping["ninth_sector"].eq("14_industry_sector").map(
        {True: "industry", False: "transport_non_road"}
    )
    candidates = targets.reset_index(names="_difference_row")[
        [
            "_difference_row",
            "_direct_group",
            "esto_flow",
            "esto_product",
            "year",
            "source_value_pj",
        ]
    ].merge(
        mapping, on=["_direct_group", "esto_flow", "esto_product"], how="left"
    ).merge(direct_values, on=["_direct_group", "ninth_fuel_code", "year"], how="left")
    candidates = candidates.rename(columns={"source_value_pj_x": "_share_weight", "source_value_pj_y": "_direct_total"})
    allocation_keys = ["_direct_group", "ninth_fuel_code", "year"]
    candidates["_weight_total"] = candidates.groupby(allocation_keys, dropna=False)["_share_weight"].transform("sum")
    candidates["_target_count"] = candidates.groupby(allocation_keys, dropna=False)["_difference_row"].transform("count")
    candidates["source_value_pj"] = candidates["_direct_total"] * (
        candidates["_share_weight"] / candidates["_weight_total"]
    )
    fallback = candidates["_direct_total"].notna() & candidates["_weight_total"].le(float(tolerance_pj))
    candidates.loc[fallback, "source_value_pj"] = (
        candidates.loc[fallback, "_direct_total"]
        / candidates.loc[fallback, "_target_count"]
    )
    replacements = candidates.groupby("_difference_row", as_index=False)["source_value_pj"].sum(min_count=1)
    replacements = replacements.rename(columns={"source_value_pj": "_direct_source_value_pj"})
    out = out.reset_index(names="_difference_row").merge(replacements, on="_difference_row", how="left")
    replaced = out["_direct_source_value_pj"].notna() & out["_direct_group"].notna()
    out.loc[replaced, "source_value_pj"] = out.loc[replaced, "_direct_source_value_pj"]
    out.loc[replaced, "reference_source"] = "9th Outlook (direct demand detail)"
    both = out["leap_value_pj"].notna() & out["source_value_pj"].notna()
    out["difference_pj"] = out["leap_value_pj"] - out["source_value_pj"]
    out["absolute_difference_pj"] = out["difference_pj"].abs()
    out["correction_to_match_source_pj"] = -out["difference_pj"]
    out["difference_percent"] = pd.NA
    nonzero = both & out["source_value_pj"].abs().gt(float(tolerance_pj))
    out.loc[nonzero, "difference_percent"] = (
        out.loc[nonzero, "difference_pj"] / out.loc[nonzero, "source_value_pj"] * 100.0
    )
    match = both & (
        out["absolute_difference_pj"].le(float(tolerance_pj))
        | out["difference_percent"].abs().le(DEFAULT_ROUNDING_TOLERANCE_PERCENT)
    )
    out.loc[match, "status"] = "match"
    out.loc[both & ~match, "status"] = "value_mismatch"
    out["is_mismatch"] = out["status"].isin({"value_mismatch", "missing_in_leap"})
    return out.drop(columns=["_difference_row", "_direct_group", "_direct_source_value_pj"])


def run_economy_balance_diagnostic(
    *,
    economy: str,
    years: Sequence[int] | None,
    scenarios: Sequence[str] | None = ("Reference", "Target"),
    base_year: int = DEFAULT_BASE_YEAR,
    exports_root: Path | str = DEFAULT_EXPORTS_ROOT,
    workbook_path: Path | str | None = None,
    ref_date_id: str | None = None,
    tgt_date_id: str | None = None,
    template_sheet: str = DEFAULT_TEMPLATE_SHEET,
    tolerance_pj: float = DEFAULT_TOLERANCE_PJ,
    mapping_pairs_path: Any = DEFAULT_MAPPING_PAIRS_PATH,
    codebook_path: Path | str = DEFAULT_CODEBOOK_PATH,
    sheet_map_path: Path | str = DEFAULT_SHEET_MAP_PATH,
    backup_mappings_path: Path | str = DEFAULT_BACKUP_MAPPINGS_PATH,
    explicit_mappings_path: Path | str = DEFAULT_EXPLICIT_MAPPINGS_PATH,
    explicit_reassignments_path: Path | str = DEFAULT_EXPLICIT_REASSIGNMENTS_PATH,
    synthetic_reference_rows_path: Path | str = DEFAULT_SYNTHETIC_REFERENCE_ROWS_PATH,
    esto_table_path: Path | str = DEFAULT_BASE_TABLE_PATH,
    projection_table_path: Path | str = DEFAULT_PROJECTION_TABLE_PATH,
    known_issues_path: Path | str | None = DEFAULT_KNOWN_ISSUES_PATH,
) -> dict[str, Any]:
    """Run the read-only Step 1 diagnostic for one economy."""
    resolved_codebook_path = _resolve(codebook_path)
    resolved_sheet_map_path = _resolve(sheet_map_path)

    if workbook_path is not None:
        (
            direct_path,
            selected_years,
            selected_scenarios,
            selected_balance_sheets,
        ) = _read_direct_workbook_scope(
            workbook_path,
            base_year=base_year,
            years=years,
            scenarios=scenarios,
        )
        ref_path = direct_path if "Reference" in selected_scenarios else None
        tgt_path = direct_path if "Target" in selected_scenarios else None
    else:
        if years is None or scenarios is None:
            raise ValueError(
                "years and scenarios are required when no direct workbook_path is supplied."
            )
        selected_years = _validate_years(years, base_year=base_year)
        selected_scenarios = _normalize_scenarios(scenarios)
        ref_path = (
            resolve_balance_export_workbook(
                economy=economy,
                scenario="REF",
                date_id=ref_date_id,
                exports_root=exports_root,
            )
            if "Reference" in selected_scenarios
            else None
        )
        tgt_path = (
            resolve_balance_export_workbook(
                economy=economy,
                scenario="TGT",
                date_id=tgt_date_id,
                exports_root=exports_root,
            )
            if "Target" in selected_scenarios
            else None
        )
        selected_balance_sheets = []
        if ref_path is not None:
            selected_balance_sheets.extend(
                select_balance_export_sheets(
                    ref_path,
                    years=selected_years,
                    scenarios=["Reference"],
                )
            )
        if tgt_path is not None:
            selected_balance_sheets.extend(
                select_balance_export_sheets(
                    tgt_path,
                    years=selected_years,
                    scenarios=["Target"],
                )
            )
    ref_sheet_names = [
        sheet.sheet_name
        for sheet in selected_balance_sheets
        if sheet.scenario_code == "REF"
    ]
    tgt_sheet_names = [
        sheet.sheet_name
        for sheet in selected_balance_sheets
        if sheet.scenario_code == "TGT"
    ]
    projection_years = [year for year in selected_years if year > int(base_year)]
    scenario_map = {scenario: scenario.lower() for scenario in selected_scenarios}

    workbook_paths = [path for path in (ref_path, tgt_path) if path is not None]
    detail_inspections = require_level2_balance_export_detail(workbook_paths)
    known_issues = _load_optional_json(known_issues_path)

    with _temporary_balance_runtime_paths(
        codebook_path=resolved_codebook_path,
        sheet_map_path=resolved_sheet_map_path,
        exports_root=_resolve(exports_root),
    ) as (build_balance_comparison_esto_axis, convert_leap_balances_to_esto_long_table):
        # Windows can briefly retain the generated mapping workbook after
        # pandas/openpyxl finishes reading it. Cleanup failure must not discard
        # a completed diagnostic conversion.
        with tempfile.TemporaryDirectory(
            prefix="leap_balance_esto_mapping_",
            ignore_cleanup_errors=True,
        ) as temp_dir:
            extraction_mapping_path = _write_esto_axis_extraction_mapping_workbook(
                output_path=Path(temp_dir) / "esto_axis_extraction_mappings.xlsx",
                codebook_path=resolved_codebook_path,
            )
            conversion = convert_leap_balances_to_esto_long_table(
                ref_workbook_path=ref_path,
                tgt_workbook_path=tgt_path,
                template_sheet=template_sheet,
                mapping_pairs_path=extraction_mapping_path,
                codebook_path=resolved_codebook_path,
                known_issues=known_issues,
                projection_economy=economy,
                max_output_year=max(selected_years),
                ref_sheet_name_filter=ref_sheet_names or None,
                tgt_sheet_name_filter=tgt_sheet_names or None,
                explicit_pair_mappings_only=True,
                allow_descendant_mapping_expansion=False,
            )
        comparison = build_balance_comparison_esto_axis(
            leap_long=conversion["leap_long"],
            mapping_status=conversion["mapping_status"],
            base_year=int(base_year),
            projection_years=projection_years,
            base_economy=_compact_economy_code(economy),
            projection_economy=economy,
            scenario_map=scenario_map,
            sheet_map_path=resolved_sheet_map_path,
            backup_mappings_path=backup_mappings_path,
            codebook_path=resolved_codebook_path,
            canonical_pairs_path=mapping_pairs_path,
            explicit_mappings_path=explicit_mappings_path,
            explicit_reassignments_path=explicit_reassignments_path,
            synthetic_reference_rows_path=synthetic_reference_rows_path,
            esto_table_path=esto_table_path,
            projection_table_path=projection_table_path,
            chart_navigation_guide_path=None,
            balance_mapping_workbook_path=resolved_codebook_path,
            known_issues=known_issues,
            base_subtotal_comparator_flows=_all_demand_subtotal_comparator_flows(
                conversion["mapping_status"]
            ),
        )
    canonical_projection, projection_allocation_diagnostics, allocation_provenance = (
        build_canonical_projection_inputs(
            base_df=comparison.get("base_df", pd.DataFrame()),
            ninth_df=comparison.get("ninth_df", pd.DataFrame()),
            mapping_pairs_path=mapping_pairs_path,
            base_year=int(base_year),
            projection_years=projection_years,
            scenarios=selected_scenarios,
        )
    )
    canonical_projection = _add_single_lng_child_projection_alias(
        projection_tables=canonical_projection,
        mapping_status=comparison["mapping_status"],
    )
    canonical_projection = _add_direct_lng_projection_fallback(
        projection_tables=canonical_projection,
        ninth_df=comparison.get("ninth_df", pd.DataFrame()),
        mapping_status=comparison["mapping_status"],
        mapping_pairs_path=mapping_pairs_path,
        economy=economy,
        projection_years=projection_years,
        scenarios=selected_scenarios,
    )
    comparison_long_raw = comparison["comparison_long"]
    allocated_comparison_long, projection_allocation_status = (
        apply_canonical_projection_comparators(
            comparison_long=comparison_long_raw,
            mapping_status=comparison["mapping_status"],
            projection_tables=canonical_projection,
            allocation_provenance=allocation_provenance,
        )
    )
    comparison["comparison_long_raw"] = comparison_long_raw
    comparison["comparison_long"] = allocated_comparison_long
    comparison["canonical_projection"] = canonical_projection
    comparison["projection_allocation_status"] = projection_allocation_status
    comparison["projection_allocation_diagnostics"] = (
        projection_allocation_diagnostics
    )
    comparison["projection_allocation_provenance"] = allocation_provenance
    difference_table = build_leap_source_difference_table(
        comparison_long=allocated_comparison_long,
        mapping_status=comparison["mapping_status"],
        leap_long=conversion["leap_long"],
        projection_allocation_status=projection_allocation_status,
        reassignment_status=comparison.get("reassignment_status"),
        base_df=comparison.get("base_df"),
        projection_tables=canonical_projection,
        economy=economy,
        years=selected_years,
        scenarios=selected_scenarios,
        base_year=int(base_year),
        tolerance_pj=tolerance_pj,
    )
    difference_table = _override_direct_demand_sources(
        difference_table=difference_table,
        ninth_df=comparison.get("ninth_df", pd.DataFrame()),
        economy=economy,
        base_year=int(base_year),
        tolerance_pj=tolerance_pj,
        mapping_pairs_path=mapping_pairs_path,
    )
    difference_table, ignored_comparison_rows = _partition_comparison_rows(
        difference_table
    )
    scoped_mapping_issues = _scope_rows_to_diagnostic_window(
        conversion.get("issues", pd.DataFrame()),
        years=selected_years,
        scenarios=selected_scenarios,
    )
    mapping_issues, ignored_mapping_issues = _partition_mapping_issues(
        scoped_mapping_issues
    )
    ignored_rows = pd.concat(
        [ignored_comparison_rows, ignored_mapping_issues],
        ignore_index=True,
        sort=False,
    )
    total_balance_checks = _scope_rows_to_diagnostic_window(
        conversion.get("total_balance_checks", pd.DataFrame()),
        years=selected_years,
        scenarios=selected_scenarios,
    )
    matching_diagnostics = _scope_rows_to_diagnostic_window(
        conversion.get("matching_diagnostics", pd.DataFrame()),
        years=selected_years,
        scenarios=selected_scenarios,
    )
    return {
        "economy": economy,
        "years": selected_years,
        "scenarios": selected_scenarios,
        "ref_workbook_path": ref_path,
        "tgt_workbook_path": tgt_path,
        "selected_balance_sheets": selected_balance_sheets,
        "detail_inspections": detail_inspections,
        "difference_table": difference_table,
        "mapping_issues": mapping_issues,
        "ignored_rows": ignored_rows,
        "total_balance_checks": total_balance_checks,
        "matching_diagnostics": matching_diagnostics,
        "projection_allocation_status": projection_allocation_status,
        "projection_allocation_diagnostics": projection_allocation_diagnostics,
        "projection_allocation_provenance": allocation_provenance,
        "conversion": conversion,
        "comparison": comparison,
    }


def run_baseline_seed_balance_diagnostics(
    *,
    economies: Sequence[str],
    years: Sequence[int] | None,
    scenarios: Sequence[str] | None = ("Reference", "Target"),
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    exports_root: Path | str = DEFAULT_EXPORTS_ROOT,
    date_ids_by_economy: dict[str, dict[str, str | None]] | None = None,
    workbook_paths_by_economy: dict[str, Path | str] | None = None,
    base_year: int = DEFAULT_BASE_YEAR,
    tolerance_pj: float = DEFAULT_TOLERANCE_PJ,
    balance_variable_rules_path: Path | str = DEFAULT_BALANCE_VARIABLE_RULES_PATH,
    **diagnostic_paths: Any,
) -> dict[str, Any]:
    """Run Step 1 for several economies and write one combined CSV table."""
    economy_list = [_clean_token(economy) for economy in economies if _clean_token(economy)]
    if not economy_list:
        raise ValueError("At least one economy is required.")
    resolved_output_dir = _resolve(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[str, Any]] = {}
    difference_parts: list[pd.DataFrame] = []
    issue_parts: list[pd.DataFrame] = []
    ignored_parts: list[pd.DataFrame] = []
    for economy in economy_list:
        date_ids = (date_ids_by_economy or {}).get(economy, {})
        direct_workbook_path = (workbook_paths_by_economy or {}).get(economy)
        result = run_economy_balance_diagnostic(
            economy=economy,
            years=years,
            scenarios=scenarios,
            base_year=base_year,
            exports_root=exports_root,
            workbook_path=direct_workbook_path,
            ref_date_id=date_ids.get("REF"),
            tgt_date_id=date_ids.get("TGT"),
            tolerance_pj=tolerance_pj,
            **diagnostic_paths,
        )
        results[economy] = result
        difference_parts.append(result["difference_table"])
        issues = result["mapping_issues"].copy()
        if not issues.empty:
            if "economy" not in issues.columns:
                issues["economy"] = economy
            issue_parts.append(issues)
        ignored = result.get("ignored_rows", pd.DataFrame()).copy()
        if not ignored.empty:
            if "economy" not in ignored.columns:
                ignored["economy"] = economy
            ignored_parts.append(ignored)

    differences = (
        pd.concat(difference_parts, ignore_index=True, sort=False)
        if difference_parts
        else pd.DataFrame(columns=DIFFERENCE_OUTPUT_COLUMNS)
    )
    differences_path = resolved_output_dir / "leap_balance_source_differences.csv"
    differences.to_csv(differences_path, index=False)

    mapping_issues = pd.concat(issue_parts, ignore_index=True, sort=False) if issue_parts else pd.DataFrame()
    mapping_issues_path: Path | None = None
    if not mapping_issues.empty:
        mapping_issues_path = resolved_output_dir / "leap_balance_mapping_issues.csv"
        mapping_issues.to_csv(mapping_issues_path, index=False)

    ignored_rows = (
        pd.concat(ignored_parts, ignore_index=True, sort=False)
        if ignored_parts
        else pd.DataFrame()
    )
    ignored_rows_path: Path | None = None
    if not ignored_rows.empty:
        ignored_rows_path = resolved_output_dir / "leap_balance_ignored_rows.csv"
        ignored_rows.to_csv(ignored_rows_path, index=False)

    review = build_balance_review_table(
        differences,
        balance_variable_rules=load_balance_variable_rules(
            balance_variable_rules_path
        ),
    )
    review_path = resolved_output_dir / "leap_balance_source_review.csv"
    review.to_csv(review_path, index=False)
    diagnostic_counts = build_balance_diagnostic_counts(differences, mapping_issues)

    mismatch_count = int(differences["is_mismatch"].fillna(False).astype(bool).sum())
    allocation_count = int(
        differences["update_allocation_required"].fillna(False).astype(bool).sum()
    )
    print(
        "[INFO] baseline-seed balance diagnostic: "
        f"{len(differences):,} comparison rows, {mismatch_count:,} mismatches, "
        f"{allocation_count:,} rows needing a future allocation rule."
    )
    print(f"[INFO] Wrote {differences_path}")
    print(f"[INFO] Wrote {review_path}")
    if mapping_issues_path is not None:
        print(f"[INFO] Wrote {mapping_issues_path}")
    if ignored_rows_path is not None:
        print(f"[INFO] Wrote {ignored_rows_path}")

    return {
        "differences": differences,
        "differences_path": differences_path,
        "review": review,
        "review_path": review_path,
        "mapping_issues": mapping_issues,
        "mapping_issues_path": mapping_issues_path,
        "ignored_rows": ignored_rows,
        "ignored_rows_path": ignored_rows_path,
        "economy_results": results,
        "summary": {
            "comparison_rows": int(len(differences)),
            "mismatch_rows": mismatch_count,
            "future_allocation_rule_rows": allocation_count,
            "mapping_issue_rows": int(len(mapping_issues)),
            "ignored_rows": int(len(ignored_rows)),
            **diagnostic_counts,
        },
    }
