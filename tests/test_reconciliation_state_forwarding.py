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
import sys
import types
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
# the default under the active preset were held back by `_PRESET_BROADCAST_PINS`
# for the mechanism commits, so those were provably output-inert, and released
# in the isolated behaviour commit that follows:
#   RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT  wrapper True, now delivered
#   ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT             wrapper True, now delivered
# Only `supply_results_saver` gates behaviour on either (the zero-reset before
# filling, and the other-demand zeroing workbooks).  `supply_preflight` reads the
# first for a log line only and forces it False for the results-update preflight;
# `supply_leap_io` reads it inside the decommissioned LEAP API path.  The other
# six modules that hold a copy never load the name - see
# `scripts/check_preset_forwarding.py`, which splits readers from stale copies.
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

# The two flags whose delivery is the substance of [17].  Named here rather than
# read from `_PRESET_BROADCAST_PINS` because that set is now empty: tests that
# iterate the pins would pass vacuously and stop guarding anything.
BEHAVIOUR_FLAGS = (
    "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT",
    "ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT",
)


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


def test_no_wrapper_setting_is_read_unforwarded():
    """The end state the forwarding list is supposed to guarantee."""
    offenders = {
        alias: sorted(_unforwarded_for(alias)) for alias in sorted(CONFIG_PUSH_TARGETS)
    }
    assert not any(offenders.values()), offenders


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


def test_the_two_behaviour_flags_are_still_read_by_the_saver():
    """Delivery is only worth anything while something reads the name.

    These are the two flags whose delivery is the whole point of
    ``docs/work_queue.md`` [17].  If `supply_results_saver` stopped reading one,
    the behaviour commit would silently become a no-op and the seed diff
    recorded against it would no longer mean what it says.
    """
    saver_reads = _module_globals_read_by(_parse(CONFIG_PUSH_TARGETS["_srs"][1]))
    for name in BEHAVIOUR_FLAGS:
        assert name in saver_reads, (
            f"{name!r} is delivered to supply_results_saver but the module no longer "
            "reads it as a module global; [17]'s behaviour commit is now a no-op"
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
    # Enumerate from `sys.modules`, not from the wrapper's own namespace: the
    # broadcast reaches every loaded `codebase` module, which is a superset of
    # the ones the wrapper happens to bind a name for.  Restoring only the
    # latter leaks the sentinel into the rest of the session.
    targets = [
        module
        for module_name, module in list(sys.modules.items())
        if module is not None
        and (module_name == "codebase" or module_name.startswith("codebase."))
        and module is not _wrapper
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


def test_duplicate_wrapper_module_is_not_counted_as_a_consumer():
    """The wrapper must not be mistaken for a consumer of its own settings.

    Production runs this file as a script, so ``__name__`` is ``"__main__"`` and
    a name-based self-check never matches; ``supply_preflight``'s late import
    then loads the same file again under its package name, leaving two live
    copies in one process.  Both apply the preset to themselves, so the second
    copy looked like a consumer holding the preset value - and every withheld
    setting reported ``<inconsistent across consumers: ...>`` instead of its
    real effective value.  Observed in the [17] A/B before-leg log.
    """
    duplicate = types.ModuleType("codebase.supply_reconciliation_workflow__duplicate")
    duplicate.__file__ = _wrapper.__file__
    name = "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT"
    setattr(duplicate, name, "SENTINEL_FROM_DUPLICATE_WRAPPER")
    sys.modules[duplicate.__name__] = duplicate
    try:
        consumers = _wrapper._consumer_values(name)
        assert duplicate.__name__ not in consumers, (
            "a second module object for this same file was counted as a consumer"
        )
        effective = _wrapper._effective_setting(name)
        assert "inconsistent" not in str(effective), (
            f"the duplicate wrapper copy corrupted the effective value: {effective!r}"
        )
    finally:
        del sys.modules[duplicate.__name__]


def test_unhashable_setting_is_not_reported_as_undelivered():
    """A list-valued setting must not be permanently flagged as undelivered.

    ``_effective_setting`` used to collect values in a set and substitute
    ``repr`` for unhashable ones, so ``PATCH_MODULE = []`` became ``"[]"`` and
    never compared equal to the real ``[]``.  Every run printed
    ``[WARN] Preset not in effect: PATCH_MODULE ... (NOT DELIVERED - investigate)``
    for a name that had been delivered correctly - noise on the one line whose
    job is to be believed.
    """
    name = "PATCH_MODULE"
    if name not in _wrapper._preset_override_names() and not hasattr(_wrapper, name):
        pytest.skip(f"{name} is no longer a wrapper setting")
    effective = _wrapper._effective_setting(name)
    assert _wrapper._values_match(effective, getattr(_wrapper, name)), (
        f"{name}: effective {effective!r} does not match wrapper "
        f"{getattr(_wrapper, name)!r}"
    )
    assert not any(
        line.startswith(f"{name}:") for line in _wrapper._preset_delivery_warnings()
    ), f"{name} is still reported as undelivered"


def test_values_match_survives_settings_whose_equality_is_not_a_bool():
    """Reporting must not crash a run on an array-like config value."""

    class _ArrayLike:
        def __eq__(self, other):  # element-wise result, truthiness raises
            raise ValueError("truth value of an array is ambiguous")

    left, right = _ArrayLike(), _ArrayLike()
    assert _wrapper._values_match(left, left) is True
    assert _wrapper._values_match(left, right) in (True, False)


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


def test_no_preset_is_withheld_in_normal_operation():
    """The shipped pin set must be empty, and the run must say so by silence.

    ``_PRESET_BROADCAST_PINS`` is a deliberate lever, not a resting state: a
    name left in it is a preset the operator asked for and the run does not
    apply.  Shipping a non-empty set is how [17] would recur.
    """
    assert _wrapper._PRESET_BROADCAST_PINS == set(), (
        "a preset is being withheld from its consumers on the shipped default; "
        "if that is intended it belongs in docs/work_queue.md, not only in code"
    )
    assert _wrapper._preset_delivery_warnings() == [], (
        "presets are not reaching their consumers: "
        f"{_wrapper._preset_delivery_warnings()}"
    )


def test_preset_broadcast_withholds_a_pinned_name():
    """The withholding lever must still work, or [17] has no one-line revert.

    Exercised with a temporary pin because the shipped set is empty (see the
    test above).  This is the mechanism the behaviour commit would be reverted
    through, so it has to stay alive even while unused.
    """
    name = "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT"
    original_pins = set(_wrapper._PRESET_BROADCAST_PINS)
    original_wrapper = getattr(_wrapper, name)
    original_saver = getattr(_srs, name)
    try:
        _wrapper._PRESET_BROADCAST_PINS = {name}
        setattr(_wrapper, name, "SENTINEL")
        _wrapper._broadcast_preset_overrides()
        assert getattr(_srs, name) != "SENTINEL", (
            f"{name} was pinned but the broadcast delivered it anyway"
        )
        assert any(name in warning for warning in _wrapper._preset_delivery_warnings()), (
            f"{name} is withheld but the run prints no warning saying so"
        )
    finally:
        _wrapper._PRESET_BROADCAST_PINS = original_pins
        setattr(_wrapper, name, original_wrapper)
        setattr(_srs, name, original_saver)


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
