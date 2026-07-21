"""The supply/transformation zero-reset must not run without its refill pass.

``reset_supply_and_transformation_import_export_to_zero`` is the *wipe* half of
a wipe-then-fill pair. The fill half is the LEAP API import pass - the
``... or RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT`` clauses in
``run_results_linked_leap_import`` and the forced Current Accounts fill in
``supply_leap_io``. The API is decommissioned
(``tests/test_leap_api_decommissioned.py``) and production runs in workbook
mode, so the fill never executes.

Running the wipe alone does not stage a refill, it deletes data. Measured on a
single-economy A/B for docs/work_queue.md [17]: enabling the reset in workbook
mode zeroed 40 ``Exports`` rows totalling **1,111,593 PJ** of Australian
coal, LNG and crude exports, with nothing repopulating them. The seed workbook
was byte-identical, which is why the loss is silent - it only appears in the
LEAP import workbook.

These tests pin the two properties that make that impossible to reintroduce:
the reset's column list really is the trade columns (so a wipe is destructive),
and nothing between the reset and the export write recomputes them.
"""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SAVER = REPO / "codebase" / "functions" / "supply_results_saver.py"
TABLES = REPO / "codebase" / "functions" / "supply_reconciliation_tables.py"

# Several codebase/*.py files carry a UTF-8 BOM; utf-8-sig or ast silently skips them.
SAVER_SRC = SAVER.read_text(encoding="utf-8-sig")
TABLES_SRC = TABLES.read_text(encoding="utf-8-sig")


def _reset_guard_node():
    """The `if` statement in the saver that gates the reset call."""
    tree = ast.parse(SAVER_SRC, filename=str(SAVER))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT" not in names:
            continue
        # The gating branch, not the `include_current_accounts=` expression.
        if isinstance(node.test, ast.BoolOp) or "include_leap_import" in names:
            return node
    return None


def test_reset_is_gated_on_the_leap_import_pass():
    """The wipe may only run when the fill will run."""
    node = _reset_guard_node()
    assert node is not None, (
        "no `if` gating RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT found in "
        "supply_results_saver - the reset must not be reachable unguarded"
    )
    names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
    assert "include_leap_import" in names, (
        "the reset guard no longer references include_leap_import. Without the LEAP "
        "import fill pass the reset deletes real Import/Export values rather than "
        "staging them - see docs/work_queue.md [17]."
    )


def test_skip_is_announced_not_silent():
    """A toggles line reading True beside a reset that did not run is what hid [17]."""
    assert "The reset is " in SAVER_SRC and "SKIPPED" in SAVER_SRC, (
        "the skipped-reset branch must print a warning; silently ignoring a True "
        "toggle recreates the invisible defect [17] was raised for"
    )


def test_reset_zeroes_trade_columns_so_a_lone_wipe_is_destructive():
    """Pins *why* the gate matters: these columns feed Resources\\...\\Exports."""
    tree = ast.parse(TABLES_SRC, filename=str(TABLES))
    literal = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if "reconciliation_zero_columns" in targets and isinstance(node.value, ast.List):
                literal = [
                    e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
                break
    assert literal, "reconciliation_zero_columns literal not found"
    for column in ("projected_exports", "adjusted_exports", "supply_exports_residual"):
        assert column in literal, (
            f"{column!r} no longer zeroed by the reset; the [17] analysis of what a "
            "lone wipe destroys is stale and must be re-measured"
        )


@pytest.mark.parametrize(
    "column", ["projected_exports", "adjusted_exports", "uncapped_adjusted_exports"]
)
def test_nothing_recomputes_the_zeroed_trade_columns_after_the_reset(column):
    """There is no refill stage in workbook mode - the reason the wipe is fatal.

    If a genuine workbook-mode refill is ever added, this test should fail and be
    replaced by one asserting the refill runs. It failing is the signal to
    re-open the gate above, not to delete the assertion.
    """
    marker = "def run_results_linked_transformation_supply_workflow"
    start = SAVER_SRC.index(marker)
    reset_at = SAVER_SRC.index("RESET_SCOPE_ECONOMIES if RESET_SCOPE_ECONOMIES", start)
    after_reset = SAVER_SRC[reset_at:]
    assert f'"{column}"' not in after_reset and f"'{column}'" not in after_reset, (
        f"{column} is referenced after the reset call; if that is a refill, the "
        "workbook-mode gate can be revisited - see docs/work_queue.md [17]"
    )
