"""One rule for "is the reset on", shared by every site that gates or reports it.

``reset_is_effective`` exists because docs/work_queue.md [17] happened twice in
two different shapes:

* ``857b6e4`` closed *wrapper value != consumer value* - the preset said one
  thing and the module that acted on it held another;
* ``c5401a5`` opened *consumer value != what the run does* - the consumers
  genuinely hold ``True``, but the reset is refused in workbook mode, so a
  report that reads the flag alone announces a reset that never happens.

Two call sites reporting reset state from two separate notions of "on" is how
the first one went unnoticed for weeks. These tests pin the single rule and the
fail-closed behaviour that makes it safe for a destructive operation.
"""

import ast
from pathlib import Path

import pytest

from codebase.functions.analysis_input_write_dispatcher import reset_is_effective

REPO = Path(__file__).resolve().parents[1]
# Several codebase/*.py files carry a UTF-8 BOM; read as utf-8-sig or ast skips them.
PREFLIGHT_SRC = (REPO / "codebase" / "functions" / "supply_preflight.py").read_text(
    encoding="utf-8-sig"
)
SAVER_SRC = (REPO / "codebase" / "functions" / "supply_results_saver.py").read_text(
    encoding="utf-8-sig"
)
TABLES_SRC = (REPO / "codebase" / "functions" / "supply_reconciliation_tables.py").read_text(
    encoding="utf-8-sig"
)


def test_flag_false_is_never_effective(monkeypatch):
    monkeypatch.setattr(
        "codebase.functions.analysis_input_write_dispatcher.is_workbook_mode",
        lambda: False,
    )
    assert reset_is_effective(False) is False


def test_flag_true_is_effective_only_outside_workbook_mode(monkeypatch):
    import codebase.functions.analysis_input_write_dispatcher as d

    monkeypatch.setattr(d, "is_workbook_mode", lambda: False)
    assert reset_is_effective(True) is True
    monkeypatch.setattr(d, "is_workbook_mode", lambda: True)
    assert reset_is_effective(True) is False


@pytest.mark.parametrize(
    "value",
    [
        "<inconsistent across consumers: ['False', 'True']>",
        "True",
        "False",
        None,
        1,
        0,
        [],
        object(),
    ],
)
def test_ambiguous_input_fails_closed(monkeypatch, value):
    """A destructive operation must never be enabled by an unclear signal.

    ``bool("<inconsistent ...>")`` is ``True``; a naive gate would run the wipe
    precisely when the config state is confused. Note ``1``/``0`` are refused
    too - an int is not a resolved flag, and silently coercing one would let a
    stray truthy value re-arm the wipe.
    """
    monkeypatch.setattr(
        "codebase.functions.analysis_input_write_dispatcher.is_workbook_mode",
        lambda: False,
    )
    assert reset_is_effective(value) is False


def test_predicate_takes_the_flag_as_an_argument():
    """It must not read a module global - that is the [17] defect itself."""
    src = (
        REPO / "codebase" / "functions" / "analysis_input_write_dispatcher.py"
    ).read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "reset_is_effective"
    )
    assert [a.arg for a in fn.args.args] == ["run_reset_flag"]
    loaded = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    assert "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT" not in loaded, (
        "reset_is_effective reads the flag as a global; it must receive it from the "
        "caller or it re-creates the mirrored-globals defect it exists to prevent"
    )


@pytest.mark.parametrize("label", ["supply_preflight", "supply_results_saver"])
def test_both_sites_route_through_the_shared_predicate(label):
    src = {"supply_preflight": PREFLIGHT_SRC, "supply_results_saver": SAVER_SRC}[label]
    assert "reset_is_effective(" in src, (
        f"{label} no longer calls reset_is_effective; two notions of 'is the reset on' "
        "will drift, which is how docs/work_queue.md [17] went unnoticed"
    )


def test_sector_scope_narrows_the_reconciliation_mask():
    """The reset must apply its module scope to both reset representations."""
    start = TABLES_SRC.index("def reset_supply_and_transformation_import_export_to_zero")
    end = TABLES_SRC.index("reconciliation_zero_columns", start)
    body = TABLES_SRC[start:end]
    mask_lines = [ln for ln in body.splitlines() if "mask &=" in ln]
    assert mask_lines, "reset mask construction not found"
    assert any("sector" in ln for ln in mask_lines), (
        "sector_set must narrow the reconciliation mask as well as process records"
    )


def test_aggregate_sentinel_reset_uses_explicit_fallback_resolver():
    """Aggregates have no area template, so reset scope must use its fallback."""
    start = TABLES_SRC.index("def reset_supply_and_transformation_import_export_to_zero")
    body = TABLES_SRC[start:start + 6000]
    assert "resolve_leap_export_template_or_fallback" in body, (
        "aggregate reset scope must route through the explicit fallback resolver"
    )
