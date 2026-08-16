"""Tests for the consolidated canonical-ID matching primitive and its consumers.

Covers the shared template-ID lookup extracted from
``enrich_seed_ids_from_template`` (baseline_seed_validation), the results-saver
ID resolution + aggregate-demand retain/drop filter that now delegates to it,
the ``validate_seed_files`` seed-file report, and the
``_build_source_diagnostics`` consumer contract for nonzero missing-ID rows.
"""

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions.baseline_seed_validation import (
    apply_template_ids,
    build_template_id_lookup,
    enrich_seed_ids_from_template,
)


def _template_row(
    branch: str,
    variable: str = "Activity Level",
    *,
    branch_id: int = 100,
    variable_id: int = 200,
    scenario: str = "Reference",
    scenario_id: int = 2,
    region: str = "Australia",
    region_id: int = 1,
) -> dict[str, object]:
    return {
        "BranchID": branch_id,
        "VariableID": variable_id,
        "ScenarioID": scenario_id,
        "RegionID": region_id,
        "Branch Path": branch,
        "Variable": variable,
        "Scenario": scenario,
        "Region": region,
    }


def _write_template(path: Path, rows: list[dict[str, object]]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Export", index=False, startrow=2)


def _seed_row(
    branch: str,
    variable: str = "Activity Level",
    *,
    scenario: str = "Reference",
    region: str = "Australia",
    years: dict[str, float] | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "Branch Path": branch,
        "Variable": variable,
        "Scenario": scenario,
        "Region": region,
    }
    row.update(years or {})
    return row


# ---------------------------------------------------------------------------
# Shared primitive: build_template_id_lookup / apply_template_ids
# ---------------------------------------------------------------------------

def test_lookup_builder_accepts_dataframe_and_path(tmp_path: Path) -> None:
    rows = [_template_row("Resources\\Primary\\Gas", "Imports")]
    template_path = tmp_path / "template.xlsx"
    _write_template(template_path, rows)

    from_path = build_template_id_lookup(template_path)
    from_frame = build_template_id_lookup(pd.DataFrame(rows))

    for lookup in (from_path, from_frame):
        assert lookup.branch_ids == {"resources\\primary\\gas": 100}
        assert lookup.variable_ids == {("resources\\primary\\gas", "imports"): 200}
        assert lookup.scenario_ids == {"reference": 2}
        assert lookup.region_ids == {"australia": 1}
        assert lookup.sole_region_id == 1
        assert lookup.canonical_paths == {
            "resources\\primary\\gas": "Resources\\Primary\\Gas"
        }


def test_apply_template_ids_matches_enrich_wrapper(tmp_path: Path) -> None:
    template_path = tmp_path / "template.xlsx"
    _write_template(template_path, [_template_row("Resources\\Primary\\Gas", "Imports")])
    seed = pd.DataFrame([_seed_row("resources\\primary\\GAS", "Imports")])

    via_wrapper = enrich_seed_ids_from_template(seed, template_path)
    via_split = apply_template_ids(seed, build_template_id_lookup(template_path))

    id_cols = ["BranchID", "VariableID", "ScenarioID", "RegionID"]
    pd.testing.assert_frame_equal(via_wrapper[id_cols], via_split[id_cols])
    # Case-insensitive match resolves to canonical template casing.
    assert via_split["Branch Path"].iloc[0] == "Resources\\Primary\\Gas"
    assert via_split[id_cols].iloc[0].tolist() == [100, 200, 2, 1]


def test_apply_template_ids_sole_region_fallback_and_unknown_scenario() -> None:
    lookup = build_template_id_lookup(
        pd.DataFrame([_template_row("Resources\\Primary\\Gas", "Imports")])
    )
    seed = pd.DataFrame(
        [_seed_row("Resources\\Primary\\Gas", "Imports", scenario="Mystery", region="Elsewhere")]
    )

    result = apply_template_ids(seed, lookup)

    assert int(result["BranchID"].iloc[0]) == 100
    assert int(result["VariableID"].iloc[0]) == 200
    assert int(result["ScenarioID"].iloc[0]) == -1
    # Sole template RegionID is valid for renamed economy regions.
    assert int(result["RegionID"].iloc[0]) == 1


def test_alias_exception_rescue_survives_split(tmp_path: Path) -> None:
    # LEAP spells the fuel "Black liqour"; the mapping sheets use "Black liquor".
    lookup = build_template_id_lookup(
        pd.DataFrame(
            [_template_row("Demand\\Industry\\Black liquor", branch_id=555, variable_id=77)]
        )
    )
    seed = pd.DataFrame([_seed_row("Demand\\Industry\\Black liqour")])

    result = apply_template_ids(seed, lookup)

    assert int(result["BranchID"].iloc[0]) == 555
    assert int(result["VariableID"].iloc[0]) == 77
    assert result["Branch Path"].iloc[0] == "Demand\\Industry\\Black liquor"


# ---------------------------------------------------------------------------
# Results saver: ID resolution + aggregate-demand retain/drop filter
# ---------------------------------------------------------------------------

def test_build_source_diagnostics_reads_first_year_column() -> None:
    from codebase.supply_reconciliation.preflight import _build_source_diagnostics

    nonzero_missing = pd.DataFrame(
        [
            {
                "Branch Path": "Demand\\All demand aggregated\\Unobtanium",
                "Variable": "Activity Level",
                "Scenario": "Reference",
                "Region": "Australia",
                "2022": 7.5,
            }
        ]
    )

    diagnostics = _build_source_diagnostics(nonzero_missing_id_rows=nonzero_missing)

    assert len(diagnostics) == 1
    row = diagnostics.iloc[0]
    assert row["issue_type"] == "missing_full_model_export_branch"
    assert row["branch_path"] == "Demand\\All demand aggregated\\Unobtanium"
    assert row["year"] == "2022"
    assert row["value"] == 7.5


# ---------------------------------------------------------------------------
# Seed-file validation report (D)
# ---------------------------------------------------------------------------

def _write_seed_workbook(path: Path, rows: list[dict[str, object]]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="LEAP", index=False)


def test_validate_seed_files_flags_bad_ids_and_unknown_paths(tmp_path: Path) -> None:
    from codebase.functions import patch_baseline_seeds

    template_path = tmp_path / "template.xlsx"
    _write_template(template_path, [_template_row("Resources\\Primary\\Gas", "Imports")])

    good = _template_row("Resources\\Primary\\Gas", "Imports")
    bad_branch_id = dict(good, BranchID=999)
    unknown = dict(good, **{"Branch Path": "Resources\\Primary\\Unobtanium"})
    ignored_prefix = dict(good, **{"Branch Path": "Transformation\\Skipped\\Gas"})
    ignored_fuel = dict(good, **{"Branch Path": "Demand\\Something\\SkipFuel"})

    seed_dir = tmp_path / "seeds"
    seed_dir.mkdir()
    _write_seed_workbook(
        seed_dir / "leap_import_baseline_seed_01_TST.xlsx",
        [good, bad_branch_id, unknown, ignored_prefix, ignored_fuel],
    )

    total_bad = patch_baseline_seeds.validate_seed_files(
        seed_dir=seed_dir,
        template_path=template_path,
        ignore_prefixes=frozenset({"Transformation\\Skipped\\"}),
        ignore_fuel_names=frozenset({"SkipFuel"}),
    )

    # One bad BranchID + one unknown path; ignored rows are skipped silently.
    assert total_bad == 2


def test_validate_seed_files_case_insensitive_path_match(tmp_path: Path) -> None:
    from codebase.functions import patch_baseline_seeds

    template_path = tmp_path / "template.xlsx"
    _write_template(template_path, [_template_row("Resources\\Primary\\Natural Gas", "Imports")])

    row = _template_row("Resources\\Primary\\Natural gas", "Imports")
    seed_dir = tmp_path / "seeds"
    seed_dir.mkdir()
    _write_seed_workbook(seed_dir / "leap_import_baseline_seed_02_TST.xlsx", [row])

    total_bad = patch_baseline_seeds.validate_seed_files(
        seed_dir=seed_dir,
        template_path=template_path,
        ignore_prefixes=frozenset(),
        ignore_fuel_names=frozenset(),
    )

    assert total_bad == 0


def test_validate_seed_files_allows_all_zero_optional_roots(tmp_path: Path) -> None:
    from codebase.functions import patch_baseline_seeds

    template_path = tmp_path / "template.xlsx"
    _write_template(template_path, [_template_row("Resources\\Primary\\Gas", "Imports")])
    rows = [
        dict(
            _template_row("Resources\\Primary\\Gas", "Imports"),
            BranchID=-1,
            VariableID=-1,
            **{
                "Branch Path": "Stock Changes\\Primary\\Gas",
                "Variable": "Stock Changes",
                "Expression": "0",
            },
        ),
        dict(
            _template_row("Resources\\Primary\\Gas", "Imports"),
            BranchID=-1,
            VariableID=-1,
            **{
                "Branch Path": "Statistical Differences\\Primary\\Gas",
                "Variable": "Statistical Differences",
                "Expression": "Data(2023,0)",
            },
        ),
    ]
    seed_dir = tmp_path / "seeds"
    seed_dir.mkdir()
    _write_seed_workbook(seed_dir / "leap_import_baseline_seed_01_TST.xlsx", rows)

    total_bad = patch_baseline_seeds.validate_seed_files(
        seed_dir=seed_dir,
        template_path=template_path,
        ignore_prefixes=frozenset(),
        ignore_fuel_names=frozenset(),
    )

    assert total_bad == 0


def test_validate_seed_files_reports_documented_branch_exception(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from codebase.functions import patch_baseline_seeds

    template_path = tmp_path / "template.xlsx"
    _write_template(template_path, [_template_row("Resources\\Primary\\Gas", "Imports")])

    rows = []
    for exception_path in patch_baseline_seeds.load_validation_exception_branch_notes():
        row = _template_row(exception_path, "Activity Level")
        row["BranchID"] = -1
        row["VariableID"] = -1
        row["Expression"] = "Data(2022,0.01)"
        rows.append(row)

    seed_dir = tmp_path / "seeds"
    seed_dir.mkdir()
    _write_seed_workbook(seed_dir / "leap_import_baseline_seed_03_TST.xlsx", rows)

    total_bad = patch_baseline_seeds.validate_seed_files(
        seed_dir=seed_dir,
        template_path=template_path,
        ignore_prefixes=frozenset(),
        ignore_fuel_names=frozenset(),
    )

    assert total_bad == 0
    output = capsys.readouterr().out
    assert "[EXCEPTION]" in output
    assert "documented missing branch row(s)" in output
    assert "Other recovered gases" in output
    assert "Bio jet kerosene" in output
    assert "[OK] All non-excepted seed file rows match the template." in output


def test_validate_seed_files_checks_only_explicit_seed_paths(tmp_path: Path) -> None:
    from codebase.functions import patch_baseline_seeds

    template_path = tmp_path / "template.xlsx"
    _write_template(template_path, [_template_row("Resources\\Primary\\Gas", "Imports")])

    seed_dir = tmp_path / "seeds"
    seed_dir.mkdir()
    selected_seed = seed_dir / "leap_import_baseline_seed_01_AUS_20260804.xlsx"
    stale_seed = seed_dir / "leap_import_baseline_seed_01_AUS_20260715.xlsx"
    _write_seed_workbook(selected_seed, [_template_row("Resources\\Primary\\Gas", "Imports")])
    _write_seed_workbook(
        stale_seed,
        [dict(_template_row("Resources\\Primary\\Gas", "Imports"), BranchID=999)],
    )

    total_bad = patch_baseline_seeds.validate_seed_files(
        seed_dir=seed_dir,
        seed_paths=[selected_seed],
        template_path=template_path,
        ignore_prefixes=frozenset(),
        ignore_fuel_names=frozenset(),
    )

    assert total_bad == 0


def test_validate_seed_files_reports_missing_template_for_seed_economy(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from codebase.functions import patch_baseline_seeds

    seed_path = tmp_path / "leap_import_baseline_seed_03_CDA_20260804.xlsx"
    _write_seed_workbook(
        seed_path,
        [_template_row("Resources\\Primary\\Gas", "Imports")],
    )

    def _missing_template(economy: object) -> Path:
        raise FileNotFoundError(f"No LEAP export template for economy {economy!r}.")

    monkeypatch.setattr(
        patch_baseline_seeds.leap_export_template_resolver,
        "resolve_leap_export_template",
        _missing_template,
    )

    total_bad = patch_baseline_seeds.validate_seed_files(
        seed_paths=[seed_path],
        ignore_prefixes=frozenset(),
        ignore_fuel_names=frozenset(),
    )
    output = capsys.readouterr().out

    assert total_bad == 0
    assert "no usable LEAP export template for economy 03_CDA" in output
    assert seed_path.name in output
    assert "leap_export_template 20_USA.xlsx" not in output
    assert "No seed files were validated" in output
    assert "[OK]" not in output


def test_latest_seed_files_by_economy_selects_newest_stamp(tmp_path: Path) -> None:
    from codebase.functions import patch_baseline_seeds

    older = tmp_path / "leap_import_baseline_seed_20_USA_20260731.xlsx"
    newest = tmp_path / "leap_import_baseline_seed_20_USA_20260804.xlsx"
    other = tmp_path / "leap_import_baseline_seed_01_AUS_20260803.xlsx"
    for path in (newest, other, older):
        path.touch()

    selected = patch_baseline_seeds._latest_seed_files_by_economy(tmp_path)

    assert selected == {"20_USA": newest, "01_AUS": other}


def test_run_patch_validates_only_successfully_patched_seed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from codebase.functions import patch_baseline_seeds

    selected_seed = tmp_path / "leap_import_baseline_seed_20_USA_20260804.xlsx"
    selected_seed.touch()
    monkeypatch.setattr(patch_baseline_seeds, "BASELINE_SEED_DIR", tmp_path)
    monkeypatch.setattr(
        patch_baseline_seeds,
        "_collect_from_workbooks",
        lambda cfg, economies, files=None: {
            "20_USA": pd.DataFrame([{"Branch Path": "Transformation\\Oil Refining"}])
        },
    )
    patched_paths: list[Path] = []
    monkeypatch.setattr(
        patch_baseline_seeds,
        "_patch_one",
        lambda seed_path, new_df, prefixes, source_workflow, economy: patched_paths.append(seed_path),
    )
    validated_paths: list[Path] = []

    def _record_validation(*, seed_paths, **kwargs) -> int:
        validated_paths.extend(seed_paths)
        return 0

    monkeypatch.setattr(patch_baseline_seeds, "validate_seed_files", _record_validation)

    patch_baseline_seeds._run_patch_locked(
        "oil_refineries",
        ["20_USA"],
        False,
        patch_baseline_seeds.MODULE_REGISTRY["oil_refineries"],
    )

    assert patched_paths == [selected_seed]
    assert validated_paths == [selected_seed]


def test_validate_seed_files_rejects_nonzero_optional_root(tmp_path: Path) -> None:
    from codebase.functions import patch_baseline_seeds

    template_path = tmp_path / "template.xlsx"
    _write_template(
        template_path,
        [_template_row("Resources\\Primary\\Gas", "Imports")],
    )
    row = dict(
        _template_row("Resources\\Primary\\Gas", "Imports"),
        BranchID=-1,
        VariableID=-1,
        **{
            "Branch Path": "Stock Changes\\Primary\\Gas",
            "Variable": "Stock Changes",
            "Expression": "Data(2023,1)",
        },
    )
    seed_dir = tmp_path / "seeds"
    seed_dir.mkdir()
    _write_seed_workbook(
        seed_dir / "leap_import_baseline_seed_01_TST.xlsx",
        [row],
    )

    total_bad = patch_baseline_seeds.validate_seed_files(
        seed_dir=seed_dir,
        template_path=template_path,
        ignore_prefixes=frozenset(),
        ignore_fuel_names=frozenset(),
    )

    assert total_bad == 1
