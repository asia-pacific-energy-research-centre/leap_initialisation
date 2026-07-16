"""Contract tests keeping docs/check_registry.md honest.

The registry documents drift-prone code, so without a contract it drifts too.
These tests fail when a documented check is renamed/removed, or when the registry
cites a file that no longer exists.

Line numbers in the registry are explicitly navigation aids and are NOT asserted
here -- they drift on every edit. Symbol existence is what matters.

If a check below is renamed or moved, update BOTH the code and
docs/check_registry.md; if one is deliberately retired, delete its row here and
in the registry together.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "check_registry.md"

# Load-bearing checks the registry documents, by family.
# symbol -> module path relative to the repo root.
REGISTERED_CHECKS: dict[str, str] = {
    # F1 - enumeration: gap-fill / reset
    "build_aux_fuel_zero_rows": "codebase/functions/transformation_record_builder.py",
    "add_zero_rows_for_unset_values": "codebase/functions/other_loss_own_use_proxy_utils.py",
    "load_export_key_table": "codebase/functions/other_loss_own_use_proxy_utils.py",
    "build_demand_zeroing_rows": "codebase/aggregated_demand_workflow.py",
    "save_demand_zeroing_workbook": "codebase/aggregated_demand_workflow.py",
    "reset_supply_and_transformation_import_export_to_zero": (
        "codebase/functions/supply_reconciliation_tables.py"
    ),
    # F2 - artifact invariants (the emit boundary)
    "prepare_seed_rows_for_write": "codebase/functions/baseline_seed_validation.py",
    "complete_canonical_share_groups": "codebase/functions/baseline_seed_validation.py",
    "_zero_capacity_is_explicit": "codebase/functions/baseline_seed_validation.py",
    "_validate_process_efficiency_for_capacity": "codebase/functions/baseline_seed_validation.py",
    "resolve_logical_duplicates": "codebase/functions/baseline_seed_validation.py",
    "check_producer_coverage": "codebase/functions/baseline_seed_validation.py",
    "validate_seed_files": "codebase/functions/patch_baseline_seeds.py",
    # F3 - LEAP-import readiness
    "validate_region": "codebase/functions/leap_exports.py",
    "_ensure_export_contains_scenarios": "codebase/refining_workflow.py",
    # F4 - preflight
    "run_preflight_compressed_projection": "codebase/functions/supply_preflight.py",
    "_validate_capacity_priority_coverage": "codebase/supply_reconciliation_allocation.py",
    "ensure_fuel_catalog_current": "codebase/utilities/fuel_catalog_preflight.py",
    # F5 - conservation / numeric
    "build_with_conservation_policy": "codebase/functions/conservation_policy.py",
    "validate_proxy_activity_target_consistency": "codebase/other_loss_own_use_proxy_workflow.py",
    # Shared readers underpinning F1/F2 (header-parsing drift)
    "find_leap_header_row": "codebase/functions/leap_excel_io.py",
    "read_leap_sheet": "codebase/functions/leap_excel_io.py",
}


def _read_source(path: Path) -> str:
    # Several core codebase/*.py files carry a UTF-8 BOM; utf-8-sig or the AST
    # tooling silently skips them.
    return path.read_text(encoding="utf-8-sig")


def _module_level_symbols(path: Path) -> set[str]:
    tree = ast.parse(_read_source(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


@pytest.fixture(scope="module")
def registry_text() -> str:
    return REGISTRY_PATH.read_text(encoding="utf-8")


def test_registry_exists():
    assert REGISTRY_PATH.is_file(), f"missing {REGISTRY_PATH}"


@pytest.mark.parametrize("symbol,module_path", sorted(REGISTERED_CHECKS.items()))
def test_registered_check_still_exists(symbol: str, module_path: str):
    """A documented check must still be defined where the registry says it is."""
    path = REPO_ROOT / module_path
    assert path.is_file(), f"{module_path} is gone; update docs/check_registry.md"
    assert symbol in _module_level_symbols(path), (
        f"'{symbol}' is no longer defined in {module_path}. If it was renamed or "
        "moved, update the code, docs/check_registry.md, and REGISTERED_CHECKS here."
    )


@pytest.mark.parametrize("symbol", sorted(REGISTERED_CHECKS))
def test_registered_check_is_documented(symbol: str, registry_text: str):
    """Every load-bearing check must have a row in the registry."""
    assert symbol in registry_text, (
        f"'{symbol}' is not mentioned in docs/check_registry.md. Add it to the "
        "right family table so the directory stays complete."
    )


# Modules the registry names as *planned* rather than existing. Remove an entry
# once the module lands (the test then starts enforcing that it exists).
PLANNED_MODULES = {
    "export_zero_fill.py",  # F1 consolidation, see prompts/export_zero_fill_consolidation_execution_prompt.md
}


def test_registry_cites_only_real_files(registry_text: str):
    """Every .py path the registry cites must resolve somewhere in the repo."""
    cited = set()
    for span in re.findall(r"`([^`]+)`", registry_text):
        for match in re.finditer(r"([A-Za-z_][\w./]*\.py)", span):
            cited.add(match.group(1))

    missing = []
    for name in sorted(cited):
        if Path(name).name in PLANNED_MODULES:
            continue
        candidate = REPO_ROOT / name
        if candidate.is_file():
            continue
        # Registry cites bare filenames (e.g. `leap_core.py:2304`) - resolve by basename.
        if any(REPO_ROOT.glob(f"codebase/**/{Path(name).name}")):
            continue
        if any(REPO_ROOT.glob(f"tests/**/{Path(name).name}")):
            continue
        missing.append(name)

    assert not missing, (
        "docs/check_registry.md cites files that no longer exist: "
        + ", ".join(missing)
    )


def test_five_families_are_present(registry_text: str):
    """The registry's structure is the point; don't let a family silently vanish."""
    for family in ("F1", "F2", "F3", "F4", "F5"):
        assert re.search(rf"\*\*{family}\*\*", registry_text), f"family {family} missing"


def test_decision_rules_are_present(registry_text: str):
    """Rules A/B/C are what make the registry usable rather than a list."""
    assert "BACKING-CHECK" in registry_text, "rule B's gateability column is missing"
    assert "Boundary vs workflow-local" in registry_text, "rule A is missing"
    assert "Severity policy" in registry_text, "rule C is missing"
