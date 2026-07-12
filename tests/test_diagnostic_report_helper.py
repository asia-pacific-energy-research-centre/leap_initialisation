"""Tests for the shared diagnostic-report writer in supply_results_saver."""

from pathlib import Path

import pandas as pd

from codebase.functions.supply_results_saver import _write_diagnostic_report


def _rows(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Branch Path": f"Resources\\Primary\\Fuel{i:03d}", "column": "Units"} for i in range(n)]
    )


def test_empty_rows_write_nothing_and_print_nothing(tmp_path: Path, capsys) -> None:
    path = tmp_path / "checks" / "report.csv"

    written = _write_diagnostic_report(
        pd.DataFrame(),
        path,
        header="[WARN] header",
        count_label="Mismatches",
        row_formatter=lambda row: str(row.get("Branch Path")),
        more_label="more mismatches",
    )

    assert written is False
    assert not path.exists()
    assert capsys.readouterr().out == ""


def test_report_writes_csv_and_prints_preview_block(tmp_path: Path, capsys) -> None:
    path = tmp_path / "checks" / "report.csv"
    rows = _rows(3)

    written = _write_diagnostic_report(
        rows,
        path,
        header="\n[WARN] Example mismatches detected.",
        count_label="Example mismatches",
        row_formatter=lambda row: f"branch='{row.get('Branch Path')}'",
        more_label="more example mismatches",
    )

    assert written is True
    assert len(pd.read_csv(path)) == 3
    out = capsys.readouterr().out
    assert "\n[WARN] Example mismatches detected.\n" in out
    assert f"[WARN] Example mismatches: 3 (details saved to {path})" in out
    assert "  - branch='Resources\\Primary\\Fuel000'" in out
    assert "plus" not in out  # no tail under the preview limit


def test_report_truncates_preview_and_prints_tail(tmp_path: Path, capsys) -> None:
    path = tmp_path / "report.csv"
    rows = _rows(33)

    _write_diagnostic_report(
        rows,
        path,
        header="[WARN] header",
        count_label="Mismatches",
        row_formatter=lambda row: str(row.get("Branch Path")),
        more_label="more mismatches",
    )

    out = capsys.readouterr().out
    assert out.count("  - ") == 30
    assert "  ... plus 3 more mismatches" in out
    assert len(pd.read_csv(path)) == 33  # CSV keeps every row
