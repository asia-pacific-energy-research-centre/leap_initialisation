"""Regression guards for cross-module attribute access bugs.

These tests document the contract between caller modules (which use
`module.attr` dot-access) and the modules that must actually own those
attributes.  A failure here means either (a) the function was moved/removed
without updating the caller, or (b) a caller was written against the wrong
module name — the class of bug caught in 2026-07-01.
"""
from __future__ import annotations

import ast
import builtins
import importlib
import inspect
import pathlib
import symtable

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _attr(module_path: str, name: str):
    """Return the attribute from a dotted module path, or raise ImportError."""
    mod = importlib.import_module(module_path)
    return getattr(mod, name)


def _has(module_path: str, name: str) -> bool:
    try:
        mod = importlib.import_module(module_path)
        return hasattr(mod, name)
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# supply_export_rows — owns coerce_value_by_year (NOT supply_data_pipeline)
# ---------------------------------------------------------------------------

def test_coerce_value_by_year_lives_in_supply_export_rows() -> None:
    """coerce_value_by_year must be importable from supply_export_rows."""
    fn = _attr("codebase.functions.supply_export_rows", "coerce_value_by_year")
    assert callable(fn)


def test_coerce_value_by_year_not_in_supply_data_pipeline() -> None:
    """supply_data_pipeline must NOT expose coerce_value_by_year.

    If this ever becomes True it means the function was re-added to the wrong
    module — check that callers still import it from supply_export_rows.
    """
    assert not _has("codebase.functions.supply_data_pipeline", "coerce_value_by_year"), (
        "coerce_value_by_year appeared in supply_data_pipeline — callers in "
        "supply_leap_io and supply_reconciliation_utils import it from "
        "supply_export_rows; update those imports if you move the function."
    )


def test_coerce_value_by_year_scalar_broadcast() -> None:
    """Smoke-test the function logic: scalar → uniform year dict."""
    from codebase.functions.supply_export_rows import coerce_value_by_year
    result = coerce_value_by_year(5.0, 2022, 2024)
    assert result == {2022: 5.0, 2023: 5.0, 2024: 5.0}


def test_coerce_value_by_year_dict_passthrough() -> None:
    from codebase.functions.supply_export_rows import coerce_value_by_year
    result = coerce_value_by_year({2022: 1.0, 2025: 3.0}, 2022, 2025)
    assert result[2022] == pytest.approx(1.0)
    assert result[2025] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# esto_data_utils — owns get_economy_list (NOT supply_data_pipeline)
# ---------------------------------------------------------------------------

def test_get_economy_list_lives_in_esto_data_utils() -> None:
    """get_economy_list must be importable from esto_data_utils."""
    fn = _attr("codebase.functions.esto_data_utils", "get_economy_list")
    assert callable(fn)


def test_get_economy_list_not_in_supply_data_pipeline() -> None:
    """supply_data_pipeline must NOT expose get_economy_list."""
    assert not _has("codebase.functions.supply_data_pipeline", "get_economy_list"), (
        "get_economy_list appeared in supply_data_pipeline — callers in "
        "supply_reconciliation_tables import it from esto_data_utils; update "
        "those imports if you move the function."
    )


# ---------------------------------------------------------------------------
# supply_data_pipeline — attributes that ARE legitimately owned there
# (regression guard: if one of these disappears a caller will break)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("attr", [
    "EXPORT_BASE_YEAR",
    "EXPORT_FINAL_YEAR",
    "PROJECTION_YEAR_RANGE",
    "PROJECTION_START_YEAR",
    "SUPPLY_PROJECTION_LOOKUP",
    "ECONOMIES_TO_ANALYZE",
    "EXPORT_FILENAME_TEMPLATE",
    "EXPORT_REGION",
    "EXPORT_DIR",
    "CODE_TO_NAME_PATHS",
    "SUPPLY_MEASURES",
    "prepare_supply_assets",
    "generate_supply_exports",
    "normalize_economy_key",
    "ESTO_PRODUCT_CLASSIFICATION",
    "FLOW_CODES_BY_DATASET",
    "build_supply_value_by_year",
    "resolve_dataset",
    "format_scenario_label_for_filename",
    "run_supply_leap_import",
])
def test_supply_data_pipeline_owns_attr(attr: str) -> None:
    """Each attribute used via supply_data_pipeline.X must exist there."""
    assert _has("codebase.functions.supply_data_pipeline", attr), (
        f"supply_data_pipeline.{attr} is missing — callers expect it there"
    )


# ---------------------------------------------------------------------------
# Whole-codebase static scanner (catches the class, not just enumerated cases)
# ---------------------------------------------------------------------------
#
# The tests above guard the *known* incidents by name.  This scanner catches
# the NEXT one automatically: it AST-parses every first-party source file,
# resolves each `module_alias.attr` dot-access back to the real module object,
# and asserts the attribute actually exists.  This is exactly the check Python
# only performs lazily at runtime — which is why these bugs survive until the
# (very slow) initialisation run hits the code path.

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FIRST_PARTY_PREFIX = "codebase"
# Dead/archived trees that are never executed by the initialisation run.
_EXCLUDE_DIRS = {"archive", "old_workflows", "scrapbook", "examples", "__pycache__"}


def _iter_first_party_files():
    for path in (_REPO_ROOT / "codebase").rglob("*.py"):
        if any(part in _EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


def _try_import(module_path: str):
    try:
        mod = importlib.import_module(module_path)
    except Exception:
        return None
    return mod if inspect.ismodule(mod) else None


def _module_alias_map(tree: ast.AST) -> dict[str, object]:
    """Map local name -> module object for first-party module imports.

    A name bound to more than one distinct module in the same file (e.g. a
    throwaway `_w` rebound inside mutually-exclusive branches) is ambiguous
    and dropped, so the scanner stays false-positive free.
    """
    bindings: dict[str, set] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                target = alias.name if alias.asname else alias.name.split(".")[0]
                if not target.startswith(_FIRST_PARTY_PREFIX):
                    continue
                mod = _try_import(target)
                if mod is not None:
                    bindings.setdefault(bound, set()).add(mod)
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue  # skip relative and `from . import x`
            if not node.module.startswith(_FIRST_PARTY_PREFIX):
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                mod = _try_import(f"{node.module}.{alias.name}")
                if mod is not None:  # only submodule imports; plain names are skipped
                    bindings.setdefault(alias.asname or alias.name, set()).add(mod)
    return {name: next(iter(mods)) for name, mods in bindings.items() if len(mods) == 1}


def _base_and_attrs(node: ast.Attribute):
    """Unwind `a.b.c` into (base_name, ["b", "c"]) or None if base isn't a Name."""
    attrs = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        attrs.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        return cur.id, list(reversed(attrs))
    return None


def _first_missing(module, attrs: list[str]):
    """Walk the attr chain across module objects; return the missing attr or None."""
    cur = module
    for name in attrs:
        if not hasattr(cur, name):
            return getattr(cur, "__name__", str(cur)), name
        nxt = getattr(cur, name)
        if not inspect.ismodule(nxt):
            return None  # reached a value; can't statically verify further
        cur = nxt
    return None


def test_no_cross_module_attribute_misattribution() -> None:
    """No first-party file calls `module.attr` where `attr` is absent on module."""
    violations: list[str] = []
    parse_errors: list[str] = []

    for path in _iter_first_party_files():
        try:
            # utf-8-sig: several core files carry a BOM that trips plain utf-8
            # parsing — skipping them would blind the scanner to the riskiest code.
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except SyntaxError as exc:
            parse_errors.append(f"{path.relative_to(_REPO_ROOT)}: {exc}")
            continue

        alias_map = _module_alias_map(tree)
        if not alias_map:
            continue

        seen: set = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            resolved = _base_and_attrs(node)
            if resolved is None:
                continue
            base, attrs = resolved
            if base not in alias_map:
                continue
            missing = _first_missing(alias_map[base], attrs)
            if missing is None:
                continue
            owner, attr = missing
            key = (str(path), node.lineno, base, tuple(attrs))
            if key in seen:
                continue
            seen.add(key)
            rel = path.relative_to(_REPO_ROOT)
            violations.append(
                f"{rel}:{node.lineno} — {base}.{'.'.join(attrs)} — "
                f"'{attr}' not found on module {owner}"
            )

    assert not parse_errors, (
        "Files failed to parse (scanner coverage gap):\n  " + "\n  ".join(parse_errors)
    )
    assert not violations, (
        "Cross-module attribute misattribution detected — a caller accesses "
        "`module.attr` but `attr` does not live in that module:\n  "
        + "\n  ".join(violations)
    )


# ---------------------------------------------------------------------------
# Bare-name misattribution scanner (the SECOND class the attr scanner misses)
# ---------------------------------------------------------------------------
#
# The scanner above only sees qualified `module.attr` access.  The same refactor
# also produced *unqualified* references — a function calls `some_helper()` or
# reads `SOME_CONSTANT` that was moved to another module (or never defined),
# without importing it.  These are invisible to pyflakes here because these
# modules use `from ... import *`, which makes linters give up on undefined-name
# detection entirely.
#
# This test uses `symtable` (the compiler's own scope analysis, so no home-grown
# false positives) to find names a function resolves as a *module global* that
# do not actually exist in the module's runtime namespace (which includes the
# star-imported names).  It is scoped to the supply/transformation modules where
# this class of bug has occurred; importing them is enough to populate their
# namespaces.

# Modules to scan.  Kept explicit (rather than walking the whole tree) so the
# test stays fast and free of import side effects from script-style modules.
_BARE_NAME_SCAN_MODULES = [
    "codebase.functions.supply_preflight",
    "codebase.functions.supply_leap_io",
    "codebase.functions.supply_results_saver",
    "codebase.functions.supply_data_pipeline",
    "codebase.functions.supply_reconciliation_tables",
    "codebase.functions.supply_demand_mapping",
    "codebase.functions.transformation_record_builder",
    "codebase.functions.transformation_analysis_utils",
    "codebase.supply_reconciliation_balance_tables",
    "codebase.supply_reconciliation_utils",
    "codebase.supply_reconciliation_allocation",
    "codebase.utilities.leap_results_dashboard_balance",
]

# Known-but-deferred findings that require domain judgment to fix (not the
# mechanical import/define fix the others got).  Each entry is (module, name).
# Empty: the previous entries (build_balance_comparison's undefined
# template_groups/hierarchy_sheet_catalog) were removed when that dead,
# superseded function was deleted.  Add entries here only for genuinely deferred
# cases — new findings otherwise fail the test.
_BARE_NAME_ALLOWLIST: set[tuple[str, str]] = set()

_BUILTIN_NAMES = frozenset(dir(builtins))


def _module_available_names(module, top_table: symtable.SymbolTable) -> set[str]:
    """Names resolvable at module scope: runtime namespace + lazily-set globals."""
    available = set(dir(module)) | _BUILTIN_NAMES
    for sym in top_table.get_symbols():
        if sym.is_assigned() or sym.is_imported():
            available.add(sym.get_name())
    return available


def _iter_function_scopes(table: symtable.SymbolTable):
    for child in table.get_children():
        if child.get_type() == "function":
            yield child
        yield from _iter_function_scopes(child)


def _bare_name_violations(module_path: str) -> list[str]:
    module = importlib.import_module(module_path)
    source = pathlib.Path(module.__file__).read_text(encoding="utf-8-sig")
    top = symtable.symtable(source, module.__file__, "exec")
    available = _module_available_names(module, top)

    found: list[str] = []
    seen: set[str] = set()
    for scope in _iter_function_scopes(top):
        for sym in scope.get_symbols():
            name = sym.get_name()
            if not (sym.is_referenced() and sym.is_global()):
                continue
            if name in available or name in seen:
                continue
            if (module_path, name) in _BARE_NAME_ALLOWLIST:
                continue
            seen.add(name)
            found.append(f"{module_path} -> {name} (referenced as a module global but not defined)")
    return found


@pytest.mark.parametrize("module_path", _BARE_NAME_SCAN_MODULES)
def test_no_bare_name_misattribution(module_path: str) -> None:
    """No function references an undefined module global (unqualified misattribution)."""
    violations = _bare_name_violations(module_path)
    assert not violations, (
        "Bare-name misattribution — a function uses a name that resolves to a "
        "module global but is neither defined nor imported in the module:\n  "
        + "\n  ".join(violations)
    )
