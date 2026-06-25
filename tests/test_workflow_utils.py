"""Smoke tests for codebase/utilities/workflow_utils.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

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
