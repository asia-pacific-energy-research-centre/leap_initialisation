"""Characterization tests for the reconciliation module-split state backchannel.

Phase 4 (`docs/prompts/phase_4_monolith_decomposition_execution.md`) split
``codebase/supply_reconciliation_workflow.py`` into sibling modules but kept
them coupled through module-level globals.  Four mechanisms push wrapper state
outward - three hand-maintained, one derived:

* ``_sync_extracted_runtime_state()`` - 4 runtime accumulators onto ``_sra``,
  plus 5 config names onto ``_srt``/``_sra``/``_srh``/``_srs``;
* ``_sync_results_saver_overrides()`` - a hand-maintained list of ~37 names
  onto ``codebase/functions/supply_results_saver.py``;
* ``_refresh_extracted_runtime_state()`` - the accumulators back;
* ``_broadcast_preset_overrides()`` - every key of every ``_PRESET_*`` dict,
  minus ``_PRESET_BROADCAST_PINS``, onto every loaded ``codebase`` module that
  already defines the name.  Derived from the presets rather than listed, so
  it cannot go stale when a preset key is added; added under
  ``docs/work_queue.md`` [17] to fix the omission the tests below characterize.

The failure mode these tests exist to catch: a name that an extracted module
reads as a module global, and that the wrapper rebinds, but that nobody added
to the forwarding list.  The override is then silently dropped - production
diverges from what the notebook preset (or a test monkeypatch) asked for, and
the test suite stays green.  Same shape as the ``073c489`` routing bypass in
``docs/work_queue.md`` [7].

Criterion for "forwardable setting" (the judgement call, test 2)
---------------------------------------------------------------
A name N is a forwardable setting for extracted module T when **all** hold:

1. **The wrapper rebinds N.**  Statically determined from three places, which
   between them are every way the wrapper overrides a setting:
   a. N is a key of any ``_PRESET_*`` dict (these are applied wholesale by
      ``globals().update(ACTIVE_PRESET)`` at wrapper module scope);
   b. N is assigned at wrapper module scope *and* also exists in
      ``codebase/supply_reconciliation_config.py`` (i.e. the wrapper is
      shadowing a config default);
   c. N is assigned inside a wrapper function via ``globals()["N"] = ...``.
2. **T reads N as a module global.**  N is loaded somewhere in T's AST and is
   never a store target anywhere in T - so it can only have arrived via
   ``from codebase.supply_reconciliation_config import *``, i.e. it is T's own
   private copy of a config default.
3. **N is not in the allowlist** below.

Then N must be delivered to T - either by appearing in the forwarding list that
targets T, or by being a broadcast preset key.  The lists are read out of the
wrapper's source by AST and the preset keys off the imported module, not
duplicated here, so a rename on either side is caught.

Source is read with ``encoding="utf-8-sig"`` throughout: several
``codebase/*.py`` files carry a UTF-8 BOM that makes naive ``ast.parse``
tooling fail or silently skip them.

These tests import the reconciliation modules but never call ``run_with_config()``
or any other entry point that acquires economy run locks or writes to
``outputs/``; they are safe to run alongside a live fleet run.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import codebase.supply_reconciliation_allocation as _sra
import codebase.supply_reconciliation_config as _config
import codebase.supply_reconciliation_history as _srh
import codebase.supply_reconciliation_workflow as _wrapper
import codebase.functions.supply_reconciliation_tables as _srt
import codebase.functions.supply_results_saver as _srs

REPO_ROOT = Path(__file__).resolve().parents[1]

WRAPPER_PATH = REPO_ROOT / "codebase" / "supply_reconciliation_workflow.py"

# Modules that receive config pushes from `_sync_extracted_runtime_state`, in
# the order the wrapper pushes them.  `_srs` additionally receives the larger
# `_sync_results_saver_overrides` list.
CONFIG_PUSH_TARGETS = {
    "_srt": (_srt, REPO_ROOT / "codebase" / "functions" / "supply_reconciliation_tables.py"),
    "_sra": (_sra, REPO_ROOT / "codebase" / "supply_reconciliation_allocation.py"),
    "_srh": (_srh, REPO_ROOT / "codebase" / "supply_reconciliation_history.py"),
    "_srs": (_srs, REPO_ROOT / "codebase" / "functions" / "supply_results_saver.py"),
}

RUNTIME_ACCUMULATORS = (
    "_CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS",
    "_CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS",
    "_CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS",
    "_CAPACITY_UNMET_RUNTIME_PASS_SUMMARY",
)

# Names that satisfy the criterion but are known-acceptable exclusions.  Every
# entry needs a reason; adding one must be a deliberate act, so that a genuinely
# new omission cannot hide behind an unexplained skip.
FORWARDING_ALLOWLIST = {
    # Repo-root path resolution.  Assigned at wrapper module scope from the same
    # `_resolve()` pattern the extracted modules use, so both sides compute the
    # identical value; it is not a run-scoped setting and is never overridden.
    "REPO_ROOT",
    # Rebound by `refresh_output_paths_for_pass_mode()` *inside the config
    # module itself*, then broadcast to every loaded codebase module by
    # `_broadcast_config_overrides()`.  It reaches the extracted modules through
    # that path, not through the hand-maintained list.
    "RUN_OUTPUT_LABEL",
}

# FINDING (2026-07-21), FIXED in the same day's [17] sequence.  These names are
# set by `_PRESET_BASELINE_SEED` / `_PRESET_RESULTS_UPDATE` on the wrapper - the
# preset literals are even annotated "# overrides config default" - and are read
# as module globals by `supply_results_saver` inside
# `run_results_linked_transformation_supply_workflow`, but they were absent from
# `_sync_results_saver_overrides`'s list, so the saver used the *config default*.
# `_broadcast_preset_overrides()` now delivers them.  The two that differ from
# the default under the active preset are held back by
# `_PRESET_BROADCAST_PINS` until the isolated behaviour commit, so the mechanism
# fix provably changes no output:
#   RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT  wrapper True / saver False
#   ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT             wrapper True / saver False
# FINDING (2026-07-21), FIXED.  `TRANSFORMATION_SUPPLY_CACHE_PATH` sat in
# `_sync_results_saver_overrides`'s list but was defined nowhere in `codebase/`
# (only `TRANSFORMATION_SUPPLY_CACHE_ENABLED` exists).  Every push is guarded by
# `if name in globals()`, so a dead entry is a silent no-op rather than an error
# - which is exactly why the list can rot unnoticed.  The entry is gone, and
# `test_saver_override_name_exists_on_wrapper_and_target` below now fails
# outright on any new one rather than carrying a pinned exemption.

# What remains undelivered once `_broadcast_preset_overrides()` is accounted
# for: exactly the names deliberately withheld in `_PRESET_BROADCAST_PINS`, and
# only for the modules that read them.  Sourced from the wrapper so that
# removing a pin (the behaviour commit) shows up here as a single change rather
# than needing this baseline edited to match.
KNOWN_UNFORWARDED = {
    "_srs": set(_wrapper._PRESET_BROADCAST_PINS),
    "_srt": set(),
    "_sra": set(),
    "_srh": set(),
}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _parse(path: Path) -> ast.Module:
    """Parse a codebase module, tolerating the UTF-8 BOM several of them carry."""
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _string_list_assigned_in(func: ast.FunctionDef, variable: str) -> list[str]:
    """Return the string literals of `variable = [...]` inside `func`."""
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if variable not in targets:
            continue
        assert isinstance(node.value, ast.List), (
            f"{func.name}: expected {variable} to be a list literal"
        )
        values = []
        for element in node.value.elts:
            assert isinstance(element, ast.Constant) and isinstance(element.value, str), (
                f"{func.name}: {variable} must contain only string literals"
            )
            values.append(element.value)
        return values
    raise AssertionError(f"{func.name}: no assignment to {variable!r} found")


def _function_named(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in {WRAPPER_PATH.name}")


def _loaded_names(tree: ast.Module) -> set[str]:
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }


def _stored_names(tree: ast.Module) -> set[str]:
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }


def _module_level_bindings(tree: ast.Module) -> set[str]:
    bound: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name != "*":
                    bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                bound |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(
            node.target, ast.Name
        ):
            bound.add(node.target.id)
    return bound


def _globals_subscript_stores(tree: ast.Module) -> set[str]:
    """Names assigned via `globals()["NAME"] = ...` anywhere in the module."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store)):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "globals"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            found.add(node.slice.value)
    return found


# ---------------------------------------------------------------------------
# Derived facts (computed once)
# ---------------------------------------------------------------------------

_WRAPPER_TREE = _parse(WRAPPER_PATH)

SAVER_OVERRIDE_NAMES = _string_list_assigned_in(
    _function_named(_WRAPPER_TREE, "_sync_results_saver_overrides"), "names"
)
SYNC_RUNTIME_NAMES = _string_list_assigned_in(
    _function_named(_WRAPPER_TREE, "_sync_extracted_runtime_state"), "runtime_names"
)
SYNC_CONFIG_NAMES = _string_list_assigned_in(
    _function_named(_WRAPPER_TREE, "_sync_extracted_runtime_state"), "config_names"
)


def _preset_keys() -> set[str]:
    keys: set[str] = set()
    for name, value in vars(_wrapper).items():
        if name.startswith("_PRESET_") and isinstance(value, dict):
            keys |= set(value)
    return keys


def _wrapper_rebound_settings() -> set[str]:
    """Names the wrapper rebinds - criterion (1) in the module docstring."""
    config_names = {name for name in vars(_config) if not name.startswith("__")}
    shadowed = _module_level_bindings(_WRAPPER_TREE) & config_names
    return _preset_keys() | shadowed | _globals_subscript_stores(_WRAPPER_TREE)


def _module_globals_read_by(tree: ast.Module) -> set[str]:
    """Names a module reads but never binds - criterion (2)."""
    return _loaded_names(tree) - _stored_names(tree) - _module_level_bindings(tree)


def _unforwarded_for(alias: str) -> set[str]:
    module, path = CONFIG_PUSH_TARGETS[alias]
    forwarded = set(SYNC_CONFIG_NAMES)
    if alias == "_srs":
        forwarded |= set(SAVER_OVERRIDE_NAMES)
    # `_broadcast_preset_overrides()` reaches every loaded codebase module that
    # defines the name, so it covers all four targets at once.
    forwarded |= set(_wrapper._preset_override_names())
    candidates = _wrapper_rebound_settings() - FORWARDING_ALLOWLIST
    return (candidates & _module_globals_read_by(_parse(path))) - forwarded


# ---------------------------------------------------------------------------
# 1. Every forwarded name exists on both sides
# ---------------------------------------------------------------------------


def test_saver_override_list_is_nonempty_and_unique():
    """Guard the AST extraction itself: a silently-empty list would void test 1."""
    assert len(SAVER_OVERRIDE_NAMES) >= 30
    assert len(set(SAVER_OVERRIDE_NAMES)) == len(SAVER_OVERRIDE_NAMES), (
        "duplicate entries in _sync_results_saver_overrides"
    )
    assert SYNC_RUNTIME_NAMES == list(RUNTIME_ACCUMULATORS)
    assert SYNC_CONFIG_NAMES, "_sync_extracted_runtime_state config_names is empty"


@pytest.mark.parametrize("name", SAVER_OVERRIDE_NAMES)
def test_saver_override_name_exists_on_wrapper_and_target(name):
    assert hasattr(_wrapper, name), (
        f"{name!r} is forwarded to supply_results_saver but does not exist on "
        "supply_reconciliation_workflow - stale entry or typo"
    )
    assert hasattr(_srs, name), (
        f"{name!r} is forwarded to supply_results_saver but the module has no such "
        "name; the setattr creates a global nothing reads"
    )


@pytest.mark.parametrize("name", SYNC_CONFIG_NAMES)
def test_synced_config_name_exists_on_wrapper_and_all_targets(name):
    assert hasattr(_wrapper, name), f"{name!r} missing from the workflow wrapper"
    for alias, (module, _path) in CONFIG_PUSH_TARGETS.items():
        assert hasattr(module, name), (
            f"{name!r} is pushed onto {alias} ({module.__name__}) but that module "
            "does not define it"
        )


@pytest.mark.parametrize("name", SYNC_RUNTIME_NAMES)
def test_synced_runtime_name_exists_on_wrapper_and_allocation(name):
    assert hasattr(_wrapper, name), f"{name!r} missing from the workflow wrapper"
    assert hasattr(_sra, name), (
        f"{name!r} is pushed onto supply_reconciliation_allocation but that module "
        "does not define it"
    )


# ---------------------------------------------------------------------------
# 2. No silently-unforwarded setting  (the important one)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("alias", sorted(CONFIG_PUSH_TARGETS))
def test_known_unforwarded_settings_do_not_grow(alias):
    """Pin the current omissions so a *new* one fails loudly.

    This is the working safety net (D4.1 option (c)).  It is deliberately a
    passing test with a pinned baseline rather than a bare assertion of
    emptiness, because the existing omissions are a FINDING to be fixed under
    the Phase 4 staged sequence, not in the characterization commit.
    """
    unforwarded = _unforwarded_for(alias)
    expected = KNOWN_UNFORWARDED[alias]
    new = unforwarded - expected
    assert not new, (
        f"{alias}: {sorted(new)} are rebound by supply_reconciliation_workflow and "
        f"read as module globals by {CONFIG_PUSH_TARGETS[alias][0].__name__}, but are "
        "not in any forwarding list. Add them to _sync_results_saver_overrides / "
        "_sync_extracted_runtime_state, or to FORWARDING_ALLOWLIST with a reason."
    )
    stale = expected - unforwarded
    assert not stale, (
        f"{alias}: {sorted(stale)} are recorded in KNOWN_UNFORWARDED but are now "
        "forwarded (or no longer read). Remove them from the baseline."
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The delivery mechanism is fixed, but "
        "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT and "
        "ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT are still withheld by "
        "_PRESET_BROADCAST_PINS so the mechanism commits change no output. "
        "Emptying the pin set (docs/work_queue.md [17], behaviour commit) turns "
        "this green"
    ),
)
def test_no_wrapper_setting_is_read_unforwarded():
    """The end state the forwarding list is supposed to guarantee."""
    offenders = {
        alias: sorted(_unforwarded_for(alias)) for alias in sorted(CONFIG_PUSH_TARGETS)
    }
    assert not any(offenders.values()), offenders


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The active preset sets RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT "
        "and ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT on the wrapper (both annotated "
        "'# overrides config default'), and _broadcast_preset_overrides() can now "
        "deliver them, but both are withheld by _PRESET_BROADCAST_PINS until the "
        "isolated behaviour commit, so supply_results_saver still holds the config "
        "default"
    ),
)
@pytest.mark.parametrize(
    "name",
    [
        "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT",
        "ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT",
    ],
)
def test_preset_overridden_flags_reach_the_saver(name):
    """The same defect stated in values rather than names.

    Both flags gate real behaviour inside
    ``run_results_linked_transformation_supply_workflow`` (the zero-reset before
    filling, and the other-demand zeroing workbooks).
    """
    _wrapper._sync_results_saver_overrides()
    assert getattr(_srs, name) == getattr(_wrapper, name)


def test_pinned_preset_names_are_still_read_by_the_saver():
    """A pin is only meaningful while something reads the name.

    If `supply_results_saver` stopped reading a pinned flag, the pin would be
    silently protecting nothing and the behaviour commit would be a no-op.
    """
    saver_reads = _module_globals_read_by(_parse(CONFIG_PUSH_TARGETS["_srs"][1]))
    for name in _wrapper._PRESET_BROADCAST_PINS:
        assert name in saver_reads, (
            f"{name!r} is pinned out of the preset broadcast but supply_results_saver "
            "no longer reads it; drop the pin instead of carrying it"
        )


# ---------------------------------------------------------------------------
# 2b. The broadcast mechanism itself
# ---------------------------------------------------------------------------


def test_preset_broadcast_delivers_an_unpinned_key_to_every_reader():
    """The mechanism fix, stated independently of any particular flag.

    Rebinding an unpinned preset key on the wrapper - what a notebook edit does
    - must reach every loaded codebase module that reads it, not just the four
    modules named in the hand-maintained lists.
    """
    name = "WRITE_AGGREGATED_DEMAND_WORKBOOK"
    assert name in _wrapper._preset_override_names(), (
        f"{name} is no longer an unpinned preset key; pick another for this test"
    )
    targets = [
        module
        for module in vars(_wrapper).values()
        if getattr(module, "__name__", "").startswith("codebase.")
        and name in vars(module)
    ]
    assert targets, f"no loaded codebase module defines {name}"

    original_wrapper = getattr(_wrapper, name)
    originals = [(module, getattr(module, name)) for module in targets]
    sentinel = not original_wrapper
    try:
        setattr(_wrapper, name, sentinel)
        _wrapper._broadcast_preset_overrides()
        for module in targets:
            assert getattr(module, name) is sentinel, (
                f"a wrapper rebind of {name} did not reach {module.__name__}"
            )
    finally:
        setattr(_wrapper, name, original_wrapper)
        for module, value in originals:
            setattr(module, name, value)


def test_toggles_line_and_reset_reminder_report_the_same_value():
    """The two log lines that disagreed for weeks must now agree by construction.

    ``[INFO] run_with_config toggles:`` printed the wrapper's copy while
    ``[WARN] Reset reminder:`` reported ``supply_preflight``'s - the run log
    said the reset was on for every run in which it was off
    (``docs/work_queue.md`` [17]).  Both now resolve to the consumer value.
    """
    import codebase.functions.supply_preflight as _spf

    name = "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT"
    assert _wrapper._effective_setting(name) == getattr(_spf, name), (
        "the toggles line and the reset reminder would report different values"
    )


def test_preset_delivery_warnings_name_every_withheld_preset():
    """A pinned preset must announce itself; silence is how [17] survived."""
    warned = " ".join(_wrapper._preset_delivery_warnings())
    for name in _wrapper._PRESET_BROADCAST_PINS:
        assert name in warned, (
            f"{name} is withheld from the broadcast but the run prints no warning "
            "saying so"
        )


def test_preset_broadcast_withholds_pinned_names():
    """The pins must actually hold, or the mechanism commits are not inert."""
    originals = {
        name: (getattr(_wrapper, name), getattr(_srs, name))
        for name in _wrapper._PRESET_BROADCAST_PINS
    }
    try:
        for name in _wrapper._PRESET_BROADCAST_PINS:
            setattr(_wrapper, name, "SENTINEL")
        _wrapper._broadcast_preset_overrides()
        for name in _wrapper._PRESET_BROADCAST_PINS:
            assert getattr(_srs, name) != "SENTINEL", (
                f"{name} is pinned but the broadcast delivered it anyway"
            )
    finally:
        for name, (wrapper_value, saver_value) in originals.items():
            setattr(_wrapper, name, wrapper_value)
            setattr(_srs, name, saver_value)


# ---------------------------------------------------------------------------
# 3. Round-trip of the runtime accumulators
# ---------------------------------------------------------------------------


def test_runtime_accumulator_round_trip_preserves_identity():
    before = {name: getattr(_wrapper, name) for name in RUNTIME_ACCUMULATORS}
    try:
        _wrapper._sync_extracted_runtime_state()
        _wrapper._refresh_extracted_runtime_state()
        for name in RUNTIME_ACCUMULATORS:
            assert getattr(_wrapper, name) is before[name], (
                f"{name} was replaced by the sync/refresh round trip"
            )
            assert getattr(_sra, name) is before[name], (
                f"{name} on supply_reconciliation_allocation is not the wrapper object"
            )
    finally:
        for name, value in before.items():
            setattr(_wrapper, name, value)
            setattr(_sra, name, value)


def test_wrapper_mutation_reaches_the_allocation_module():
    name = "_CAPACITY_UNMET_RUNTIME_PASS_SUMMARY"
    original_wrapper = getattr(_wrapper, name)
    original_allocation = getattr(_sra, name)
    sentinel = {"__forwarding_test__": {"pass": 1}}
    try:
        setattr(_wrapper, name, sentinel)
        _wrapper._sync_extracted_runtime_state()
        assert getattr(_sra, name) is sentinel, (
            "a wrapper monkeypatch of the pass summary did not reach "
            "supply_reconciliation_allocation"
        )
        _wrapper._refresh_extracted_runtime_state()
        assert getattr(_wrapper, name) is sentinel
    finally:
        setattr(_wrapper, name, original_wrapper)
        setattr(_sra, name, original_allocation)
