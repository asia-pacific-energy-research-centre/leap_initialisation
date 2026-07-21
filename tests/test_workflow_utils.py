"""Smoke tests for codebase/utilities/workflow_utils.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
import os
import tempfile

import pandas as pd
import pytest

# Ensure repo root is on the path regardless of how pytest is invoked.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from codebase.utilities.workflow_utils import (
    REPO_ROOT,
    _normalize_economy,
    _normalize_year_columns,
    _resolve,
    clear_csv_cache,
    load_esto_csv,
    load_ninth_outlook_csv,
    _DEFAULT_NINTH_PATH,
    _DEFAULT_ESTO_PATH,
)


class TestResolve(unittest.TestCase):
    def test_absolute_path_returned_unchanged(self):
        p = Path("C:/some/absolute/path") if sys.platform == "win32" else Path("/some/absolute/path")
        result = _resolve(p)
        self.assertTrue(result.is_absolute())
        self.assertEqual(result, p)

    def test_relative_path_is_under_repo_root(self):
        result = _resolve("data/example.csv")
        self.assertTrue(result.is_absolute())
        self.assertEqual(result, REPO_ROOT / "data" / "example.csv")

    def test_backslashes_normalised(self):
        result = _resolve("data\\example.csv")
        self.assertEqual(result, REPO_ROOT / "data" / "example.csv")

    def test_repo_root_exists(self):
        self.assertTrue(REPO_ROOT.exists(), f"REPO_ROOT does not exist: {REPO_ROOT}")
        self.assertTrue((REPO_ROOT / "codebase").is_dir())


class TestNormalizeEconomy(unittest.TestCase):
    def test_compact_form_gets_underscore(self):
        self.assertEqual(_normalize_economy("01AUS"), "01_AUS")
        self.assertEqual(_normalize_economy("20USA"), "20_USA")

    def test_lowercase_is_uppercased(self):
        self.assertEqual(_normalize_economy("01aus"), "01_AUS")
        self.assertEqual(_normalize_economy("20usa"), "20_USA")

    def test_already_canonical_is_unchanged(self):
        self.assertEqual(_normalize_economy("01_AUS"), "01_AUS")
        self.assertEqual(_normalize_economy("20_USA"), "20_USA")

    def test_none_and_empty(self):
        result = _normalize_economy(None)
        self.assertIsInstance(result, str)
        result_empty = _normalize_economy("")
        self.assertIsInstance(result_empty, str)

    def test_short_code_not_modified(self):
        # A 2-digit code without enough characters should not get an underscore
        result = _normalize_economy("01")
        self.assertIsInstance(result, str)


class TestNormalizeYearColumns(unittest.TestCase):
    def test_string_years_become_ints(self):
        df = pd.DataFrame({"economy": ["A"], "2020": [1.0], "2021": [2.0]})
        result = _normalize_year_columns(df)
        self.assertIn(2020, result.columns)
        self.assertIn(2021, result.columns)
        self.assertIn("economy", result.columns)
        self.assertNotIn("2020", result.columns)

    def test_already_int_years_unchanged(self):
        df = pd.DataFrame({"economy": ["A"], 2020: [1.0]})
        result = _normalize_year_columns(df)
        self.assertIn(2020, result.columns)

    def test_non_year_columns_unchanged(self):
        df = pd.DataFrame({"economy": ["A"], "flows": ["x"], "2022": [3.0]})
        result = _normalize_year_columns(df)
        self.assertIn("economy", result.columns)
        self.assertIn("flows", result.columns)
        self.assertIn(2022, result.columns)

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = _normalize_year_columns(df)
        self.assertTrue(result.empty)


class TestCsvCache(unittest.TestCase):
    """Use tiny temporary CSVs so cache behavior is tested without data loads."""

    def setUp(self):
        clear_csv_cache()
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.temporary_path = Path(self._temporary_directory.name)

    def tearDown(self):
        clear_csv_cache()
        self._temporary_directory.cleanup()

    @staticmethod
    def _write_csv(path: Path, value: int) -> None:
        path.write_text(f"value\n{value}\n", encoding="utf-8")

    def test_explicit_relative_path_resolves_from_repo_root(self):
        source = _REPO_ROOT / "tests" / "_workflow_utils_cache_test.csv"
        self.addCleanup(lambda: source.unlink(missing_ok=True))
        self._write_csv(source, 1)

        loaded = load_esto_csv("tests\\_workflow_utils_cache_test.csv")

        self.assertEqual(loaded.loc[0, "value"], 1)

    def test_unchanged_source_returns_same_cached_object(self):
        source = self.temporary_path / "source.csv"
        self._write_csv(source, 1)

        first = load_ninth_outlook_csv(source)
        second = load_ninth_outlook_csv(source)

        self.assertIs(first, second)

    def test_changed_source_reloads_automatically(self):
        source = self.temporary_path / "source.csv"
        self._write_csv(source, 1)
        first = load_esto_csv(source)

        self._write_csv(source, 22)
        stat = source.stat()
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
        second = load_esto_csv(source)

        self.assertIsNot(first, second)
        self.assertEqual(second.loc[0, "value"], 22)

    def test_targeted_and_full_cache_clear(self):
        first_source = self.temporary_path / "first.csv"
        second_source = self.temporary_path / "second.csv"
        self._write_csv(first_source, 1)
        self._write_csv(second_source, 2)
        first = load_esto_csv(first_source)
        second = load_esto_csv(second_source)

        clear_csv_cache(first_source)
        self.assertIsNot(first, load_esto_csv(first_source))
        self.assertIs(second, load_esto_csv(second_source))

        clear_csv_cache()
        self.assertIsNot(second, load_esto_csv(second_source))

    def test_column_projections_cache_separately_and_clear_together(self):
        source = self.temporary_path / "source.csv"
        source.write_text("a,b,c\n1,2,3\n", encoding="utf-8")

        first_projection = load_ninth_outlook_csv(source, usecols=["b", "a"])
        same_projection = load_ninth_outlook_csv(source, usecols=["a", "b"])
        second_projection = load_ninth_outlook_csv(source, usecols=["c"])

        self.assertIs(first_projection, same_projection)
        self.assertIsNot(first_projection, second_projection)
        self.assertEqual(first_projection.columns.tolist(), ["a", "b"])
        self.assertEqual(second_projection.columns.tolist(), ["c"])

        clear_csv_cache(source)
        self.assertIsNot(first_projection, load_ninth_outlook_csv(source, usecols=["a", "b"]))
        self.assertIsNot(second_projection, load_ninth_outlook_csv(source, usecols=["c"]))

    def test_changed_source_reloads_all_cached_column_projections(self):
        source = self.temporary_path / "source.csv"
        source.write_text("a,b\n1,2\n", encoding="utf-8")
        first_a = load_esto_csv(source, usecols=["a"])
        first_b = load_esto_csv(source, usecols=["b"])

        source.write_text("a,b\n3,4\n", encoding="utf-8")
        stat = source.stat()
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
        second_a = load_esto_csv(source, usecols=["a"])
        second_b = load_esto_csv(source, usecols=["b"])

        self.assertIsNot(first_a, second_a)
        self.assertIsNot(first_b, second_b)
        self.assertEqual(second_a.loc[0, "a"], 3)
        self.assertEqual(second_b.loc[0, "b"], 4)


_NINTH_MISSING = not _DEFAULT_NINTH_PATH.exists()
_ESTO_MISSING = not _DEFAULT_ESTO_PATH.exists()


@pytest.mark.skipif(_NINTH_MISSING, reason="9th Outlook CSV not present in test environment")
class TestLoadNinthOutlookCsv(unittest.TestCase):
    def test_returns_nonempty_dataframe(self):
        df = load_ninth_outlook_csv()
        self.assertIsInstance(df, pd.DataFrame)
        self.assertGreater(len(df), 0)

    def test_cached_call_returns_same_object(self):
        df1 = load_ninth_outlook_csv()
        df2 = load_ninth_outlook_csv()
        self.assertIs(df1, df2)


@pytest.mark.skipif(_ESTO_MISSING, reason="ESTO CSV not present in test environment")
class TestLoadEstoCsv(unittest.TestCase):
    def test_returns_nonempty_dataframe(self):
        df = load_esto_csv()
        self.assertIsInstance(df, pd.DataFrame)
        self.assertGreater(len(df), 0)

    def test_cached_call_returns_same_object(self):
        df1 = load_esto_csv()
        df2 = load_esto_csv()
        self.assertIs(df1, df2)


if __name__ == "__main__":
    unittest.main()
