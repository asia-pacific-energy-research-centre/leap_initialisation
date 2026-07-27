"""Tests for the consolidated canonical-ID matching primitive and its consumers.

Covers the shared template-ID lookup extracted from
``enrich_seed_ids_from_template`` (baseline_seed_validation), the results-saver
ID resolution + aggregate-demand retain/drop filter that now delegates to it,
the ``validate_seed_files`` seed-file report, and the
``_build_source_diagnostics`` consumer contract for nonzero missing-ID rows.
"""

from pathlib import Path

import pandas as pd

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

def _saver_resolver():
    from codebase.functions.supply_results_saver import (
        _resolve_ids_and_filter_unmatched_export_rows,
    )

    return _resolve_ids_and_filter_unmatched_export_rows


def test_only_temporary_balance_roots_are_excluded_from_fatal_missing_id_gate() -> None:
    from codebase.functions.supply_results_saver import (
        _filter_blocking_nonzero_missing_id_rows,
    )

    rows = pd.DataFrame(
        [
            {"Branch Path": "Stock Changes\\Primary\\Gas", "2022": 1.0},
            {
                "Branch Path": "Statistical Differences\\Primary\\Gas",
                "2022": -2.0,
            },
            {"Branch Path": "Resources\\Primary\\Unknown", "2022": 3.0},
        ]
    )

    blocking = _filter_blocking_nonzero_missing_id_rows(rows)

    assert blocking["Branch Path"].tolist() == [
        "Resources\\Primary\\Unknown"
    ]


def _source_data() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _template_row("Resources\\Primary\\Gas", "Imports"),
            _template_row(
                "Demand\\All demand aggregated\\Gas",
                branch_id=300,
                variable_id=400,
            ),
        ]
    )


def test_saver_exact_match_stamps_all_ids() -> None:
    resolve = _saver_resolver()
    df = pd.DataFrame([_seed_row("Resources\\Primary\\Gas", "Imports", years={"2022": 5.0})])

    out, unmatched = resolve(df, source_data=_source_data(), source_path=Path("template.xlsx"))

    assert out[["BranchID", "VariableID", "ScenarioID", "RegionID"]].iloc[0].tolist() == [
        100,
        200,
        2,
        1,
    ]
    assert unmatched.empty


def test_saver_branch_variable_match_with_unknown_scenario_is_not_unmatched() -> None:
    # The old two-pass merge recovered such rows via a Branch+Variable fallback;
    # per-column matching must keep recovering BranchID/VariableID for them.
    resolve = _saver_resolver()
    df = pd.DataFrame(
        [
            _seed_row(
                "Resources\\Primary\\Gas",
                "Imports",
                scenario="Mystery",
                years={"2022": 5.0},
            )
        ]
    )

    out, unmatched = resolve(df, source_data=_source_data(), source_path=Path("template.xlsx"))

    assert int(out["BranchID"].iloc[0]) == 100
    assert int(out["VariableID"].iloc[0]) == 200
    assert unmatched.empty


def test_saver_zero_only_aggregate_demand_placeholder_is_dropped() -> None:
    resolve = _saver_resolver()
    df = pd.DataFrame(
        [
            _seed_row(
                "Demand\\All demand aggregated\\Unobtanium",
                years={"2022": 0.0, "2023": 0.0},
            )
        ]
    )

    out, unmatched = resolve(df, source_data=_source_data(), source_path=Path("template.xlsx"))

    assert out.empty
    assert unmatched.empty


def test_saver_nonzero_aggregate_demand_placeholder_is_retained_with_minus_one() -> None:
    resolve = _saver_resolver()
    df = pd.DataFrame(
        [
            _seed_row(
                "Demand\\All demand aggregated\\Unobtanium",
                years={"2022": 0.0, "2023": 7.5},
            )
        ]
    )

    out, unmatched = resolve(df, source_data=_source_data(), source_path=Path("template.xlsx"))

    assert len(out) == 1
    assert int(out["BranchID"].iloc[0]) == -1
    assert list(unmatched.columns) == ["Branch Path", "Variable", "Scenario", "Region", "reason"]
    assert unmatched["reason"].tolist() == ["no_verification_export_id_match"]
    assert unmatched["Branch Path"].tolist() == ["Demand\\All demand aggregated\\Unobtanium"]


def test_saver_drops_zero_only_unmatched_transformation_row() -> None:
    resolve = _saver_resolver()
    branch = "Transformation\\Gas works plants\\Processes\\Gas works plants\\Auxiliary Fuels\\Anthracite"

    zero_out, zero_unmatched = resolve(
        pd.DataFrame([_seed_row(branch, "Auxiliary Fuel Use", years={"2022": 0.0})]),
        source_data=_source_data(),
        source_path=Path("template.xlsx"),
    )
    assert zero_out.empty
    assert zero_unmatched.empty

    nonzero_out, nonzero_unmatched = resolve(
        pd.DataFrame([_seed_row(branch, "Auxiliary Fuel Use", years={"2022": 0.5})]),
        source_data=_source_data(),
        source_path=Path("template.xlsx"),
    )
    assert nonzero_out["BranchID"].tolist() == [-1]
    assert nonzero_unmatched["reason"].tolist() == ["no_verification_export_id_match"]


def test_saver_retain_drop_follows_activity_level_not_own_row(tmp_path: Path) -> None:
    # A structural row (e.g. Final Energy Intensity = 1) on a missing branch is
    # retained only when the branch's Activity Level row is genuinely nonzero.
    resolve = _saver_resolver()
    branch = "Demand\\All demand aggregated\\Unobtanium"
    df = pd.DataFrame(
        [
            _seed_row(branch, "Activity Level", years={"2022": 7.5}),
            _seed_row(branch, "Final Energy Intensity", years={"2022": 1.0}),
        ]
    )

    out, unmatched = resolve(df, source_data=_source_data(), source_path=Path("template.xlsx"))

    assert len(out) == 2
    assert set(out["BranchID"].tolist()) == {-1}

    zero_df = pd.DataFrame(
        [
            _seed_row(branch, "Activity Level", years={"2022": 0.0}),
            _seed_row(branch, "Final Energy Intensity", years={"2022": 1.0}),
        ]
    )
    out_zero, _ = resolve(zero_df, source_data=_source_data(), source_path=Path("template.xlsx"))
    assert out_zero.empty


def test_saver_alias_rescued_row_is_not_reported_unmatched() -> None:
    resolve = _saver_resolver()
    source = pd.DataFrame(
        [_template_row("Demand\\Industry\\Black liquor", branch_id=555, variable_id=77)]
    )
    df = pd.DataFrame([_seed_row("Demand\\Industry\\Black liqour", years={"2022": 3.0})])

    out, unmatched = resolve(df, source_data=source, source_path=Path("template.xlsx"))

    assert int(out["BranchID"].iloc[0]) == 555
    assert unmatched.empty


def test_saver_missing_source_marks_all_rows_with_reason(tmp_path: Path) -> None:
    resolve = _saver_resolver()
    df = pd.DataFrame([_seed_row("Resources\\Primary\\Gas", "Imports", years={"2022": 5.0})])

    out, unmatched = resolve(
        df, source_data=pd.DataFrame(), source_path=tmp_path / "does_not_exist.xlsx"
    )

    assert out["BranchID"].tolist() == [-1]
    assert unmatched["reason"].tolist() == ["verification_export_missing"]

    existing = tmp_path / "empty.xlsx"
    _write_template(existing, [_template_row("Resources\\Primary\\Gas")])
    out2, unmatched2 = resolve(df, source_data=pd.DataFrame(), source_path=existing)
    assert unmatched2["reason"].tolist() == ["verification_export_empty"]


def test_saver_source_missing_required_columns_reason() -> None:
    resolve = _saver_resolver()
    df = pd.DataFrame([_seed_row("Resources\\Primary\\Gas", "Imports", years={"2022": 5.0})])
    bad_source = pd.DataFrame([{"Branch Path": "Resources\\Primary\\Gas"}])

    out, unmatched = resolve(df, source_data=bad_source, source_path=Path("template.xlsx"))

    assert out["BranchID"].tolist() == [-1]
    assert unmatched["reason"].tolist() == ["verification_export_missing_required_columns"]


# ---------------------------------------------------------------------------
# Results saver: per-economy template verification (economy-specific fix,
# work_queue.md "Priority follow-up - make template verification
# economy-specific"). The known-good regression fixture per that doc is the
# real 02_BD "Demand\All demand aggregated\Activity Level" control row
# (BranchID 2336, VariableID 2027); reproduced synthetically here since these
# tests must not depend on real data files.
# ---------------------------------------------------------------------------

def _per_economy_resolver():
    from codebase.functions.supply_results_saver import (
        _resolve_ids_and_filter_unmatched_export_rows_per_economy,
    )

    return _resolve_ids_and_filter_unmatched_export_rows_per_economy


def test_pinned_reference_alone_misses_a_real_non_pinned_economy_branch() -> None:
    # Characterizes the bug: a branch/fuel combination that exists only in
    # 02_BD's own template (BranchID 2336) is reported unmatched when compared
    # against a USA-only pinned reference.
    resolve = _saver_resolver()
    usa_pinned_reference = pd.DataFrame(
        [_template_row("Resources\\Primary\\Gas", "Imports", region="United States")]
    )
    bd_row = pd.DataFrame(
        [
            _seed_row(
                "Demand\\All demand aggregated\\Activity Level",
                "Activity Level",
                region="Brunei Darussalam",
                years={"2022": 7.5},
            )
        ]
    )

    out, unmatched = resolve(bd_row, source_data=usa_pinned_reference, source_path=Path("usa.xlsx"))

    assert int(out["BranchID"].iloc[0]) == -1
    assert unmatched["reason"].tolist() == ["no_verification_export_id_match"]


def test_per_economy_resolver_uses_each_rows_own_template(monkeypatch) -> None:
    import codebase.functions.supply_results_saver as supply_results_saver

    resolve = _per_economy_resolver()

    usa_pinned_reference = pd.DataFrame(
        [_template_row("Resources\\Primary\\Gas", "Imports", region="United States")]
    )
    aus_template = pd.DataFrame(
        [
            _template_row(
                "Demand\\Industry\\Electricity",
                "Activity Level",
                branch_id=111,
                variable_id=222,
                region="Australia",
            )
        ]
    )
    bd_template = pd.DataFrame(
        [
            _template_row(
                "Demand\\All demand aggregated\\Activity Level",
                "Activity Level",
                branch_id=2336,
                variable_id=2027,
                region="Brunei Darussalam",
            )
        ]
    )
    templates_by_economy = {"01_AUS": (Path("aus.xlsx"), aus_template), "02_BD": (Path("bd.xlsx"), bd_template)}

    def fake_resolve_template(economy_code, *, fallback, **_kwargs):
        if economy_code in templates_by_economy:
            return templates_by_economy[economy_code][0]
        return fallback

    def fake_read_sheet(path, sheet_name):
        for resolved_path, template_df in templates_by_economy.values():
            if Path(path) == resolved_path:
                return pd.DataFrame(), template_df, []
        raise AssertionError(f"unexpected template read: {path}")

    monkeypatch.setattr(
        supply_results_saver.leap_export_template_resolver,
        "resolve_leap_export_template_or_fallback",
        fake_resolve_template,
    )
    monkeypatch.setattr(supply_results_saver, "_read_workbook_sheet_with_header_detection", fake_read_sheet)

    df = pd.DataFrame(
        [
            _seed_row(
                "Demand\\Industry\\Electricity", "Activity Level",
                region="Australia", years={"2022": 5.0},
            ),
            _seed_row(
                "Demand\\All demand aggregated\\Activity Level", "Activity Level",
                region="Brunei Darussalam", years={"2022": 7.5},
            ),
        ]
    )

    out, unmatched = resolve(
        df, fallback_source_data=usa_pinned_reference, fallback_source_path=Path("usa.xlsx")
    )

    assert unmatched.empty
    aus_row = out[out["Region"] == "Australia"].iloc[0]
    bd_row = out[out["Region"] == "Brunei Darussalam"].iloc[0]
    assert (int(aus_row["BranchID"]), int(aus_row["VariableID"])) == (111, 222)
    assert (int(bd_row["BranchID"]), int(bd_row["VariableID"])) == (2336, 2027)


def test_per_economy_resolver_falls_back_for_unrecognised_region() -> None:
    resolve = _per_economy_resolver()
    usa_pinned_reference = pd.DataFrame(
        [_template_row("Resources\\Primary\\Gas", "Imports", region="United States")]
    )
    df = pd.DataFrame(
        [_seed_row("Resources\\Primary\\Gas", "Imports", region="Somewhere Unmapped", years={"2022": 1.0})]
    )

    out, unmatched = resolve(
        df, fallback_source_data=usa_pinned_reference, fallback_source_path=Path("usa.xlsx")
    )

    # Falls back to the pinned reference (matches on Branch/Variable, not Region).
    assert int(out["BranchID"].iloc[0]) == 100
    assert unmatched.empty


def test_per_economy_resolver_falls_back_when_template_resolution_raises(monkeypatch) -> None:
    import codebase.functions.supply_results_saver as supply_results_saver

    resolve = _per_economy_resolver()
    usa_pinned_reference = pd.DataFrame(
        [_template_row("Resources\\Primary\\Gas", "Imports", region="United States")]
    )

    def fake_resolve_template(economy_code, *, fallback, **_kwargs):
        raise FileNotFoundError("no template for economy")

    monkeypatch.setattr(
        supply_results_saver.leap_export_template_resolver,
        "resolve_leap_export_template_or_fallback",
        fake_resolve_template,
    )

    df = pd.DataFrame(
        [_seed_row("Resources\\Primary\\Gas", "Imports", region="Australia", years={"2022": 1.0})]
    )

    out, unmatched = resolve(
        df, fallback_source_data=usa_pinned_reference, fallback_source_path=Path("usa.xlsx")
    )

    assert int(out["BranchID"].iloc[0]) == 100
    assert unmatched.empty


# ---------------------------------------------------------------------------
# Source diagnostics consumer contract (C)
# ---------------------------------------------------------------------------

def test_build_source_diagnostics_reads_first_year_column() -> None:
    from codebase.functions.supply_preflight import _build_source_diagnostics

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


def test_validate_seed_files_allows_temporary_balance_roots(tmp_path: Path) -> None:
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
            },
        ),
        dict(
            _template_row("Resources\\Primary\\Gas", "Imports"),
            BranchID=-1,
            VariableID=-1,
            **{
                "Branch Path": "Statistical Differences\\Primary\\Gas",
                "Variable": "Statistical Differences",
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
