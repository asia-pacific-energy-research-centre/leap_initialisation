"""Focused tests for the release manifest, launcher settings, and run provenance."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from codebase.portable_release import validation
from codebase.portable_release.manifest import (
    ReleaseManifestError,
    load_release_manifest,
    parse_release_manifest,
    path_safety_problems,
    validate_release_manifest,
)
from codebase.portable_release.provenance import (
    describe_file,
    finish_run_manifest,
    new_run_manifest,
    sha256_file,
)
from codebase.portable_release.runtime import RuntimeContext, portable_context
from codebase.portable_release.settings import (
    DeveloperSettingsError,
    load_developer_settings,
    render_settings_template,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_MANIFEST = REPO_ROOT / "config" / "portable_release_manifest.toml"

VALID_MANIFEST = textwrap.dedent(
    """
    schema_version = 1

    [release]
    name = "leap-review-tools"
    version = "0.1.0"
    description = "Test manifest."

    [runtime]
    python = ">=3.11,<3.14"
    packages = ["pandas", "openpyxl"]

    [repositories.leap_initialisation]
    commit = "0123456789abcdef0123456789abcdef01234567"
    stage_dir = "leap_initialisation"
    paths = ["codebase/__init__.py"]

    [[config_assets]]
    repository = "leap_initialisation"
    path = "config/example.json"
    dest = "example.json"
    role = "example"

    [[commands]]
    name = "balance-review"
    summary = "Build a balance-review workbook."
    input_mode = "existing_diagnostic_artifacts"
    outputs = "One workbook."

      [[commands.inputs]]
      key = "economy"
      kind = "file"
      description = "Economy code."
    """
)


def _parse(overrides: str = "") -> object:
    return parse_release_manifest(VALID_MANIFEST + overrides)


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


def test_valid_manifest_parses() -> None:
    manifest = _parse()
    assert manifest.name == "leap-review-tools"
    assert manifest.version == "0.1.0"
    assert manifest.package_stem == "leap-review-tools-0.1.0"
    assert manifest.repositories["leap_initialisation"].paths == ("codebase/__init__.py",)
    assert manifest.command("balance-review").inputs[0].key == "economy"
    assert manifest.sys_path_stage_dirs() == ("leap_initialisation",)


def test_unknown_schema_version_is_rejected() -> None:
    with pytest.raises(ReleaseManifestError, match="Unsupported schema_version"):
        parse_release_manifest("schema_version = 99\n")


def test_missing_required_key_is_reported_with_its_location() -> None:
    text = VALID_MANIFEST.replace('stage_dir = "leap_initialisation"', "")
    with pytest.raises(ReleaseManifestError, match="repositories.leap_initialisation.*stage_dir"):
        parse_release_manifest(text)


def test_unknown_command_raises_with_the_available_list() -> None:
    manifest = _parse()
    with pytest.raises(KeyError, match="Available commands: balance-review"):
        manifest.command("no-such-command")


def test_strip_prefix_relocates_staged_paths() -> None:
    manifest = parse_release_manifest(
        VALID_MANIFEST.replace(
            'paths = ["codebase/__init__.py"]',
            'strip_prefix = "codebase"\npaths = ["codebase/thing.py"]',
        )
    )
    spec = manifest.repositories["leap_initialisation"]
    assert spec.staged_relative_path("codebase/thing.py").as_posix() == (
        "leap_initialisation/thing.py"
    )


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("codebase/../../secrets.py", "escapes the repository root"),
        ("/etc/passwd", "must be relative"),
        ("C:/Windows/system32.py", "drive letter"),
        ("codebase\\functions\\x.py", "forward slashes"),
        (".git/config", "private, generated, or cache"),
        (".claude/settings.json", "private, generated, or cache"),
        (".codex/notes.md", "private, generated, or cache"),
        ("node_modules/pkg/index.js", "private, generated, or cache"),
        ("outputs/leap_exports/big.csv", "private, generated, or cache"),
        ("data/merged_file_energy_ALL_20251106.csv", "private, generated, or cache"),
        ("codebase/__pycache__/x.pyc", "private, generated, or cache"),
        ("docs/archive/old.md", "private, generated, or cache"),
    ],
)
def test_unsafe_paths_are_rejected(path: str, expected: str) -> None:
    problems = path_safety_problems(path, context="test")
    assert problems, f"expected {path!r} to be rejected"
    assert any(expected in problem for problem in problems)


def test_ordinary_repository_path_is_accepted() -> None:
    assert path_safety_problems("codebase/functions/thing.py", context="test") == []


# ---------------------------------------------------------------------------
# Manifest validation (declarative only; no Git access)
# ---------------------------------------------------------------------------


def _validate(manifest_text: str, **kwargs: object) -> object:
    manifest = parse_release_manifest(manifest_text)
    return validate_release_manifest(
        manifest,
        {"leap_initialisation": REPO_ROOT},
        check_git=False,
        **kwargs,  # type: ignore[arg-type]
    )


def test_declarative_validation_passes_for_a_good_manifest() -> None:
    report = _validate(VALID_MANIFEST, known_command_names=["balance-review"])
    assert report.ok, report.errors


def test_abbreviated_commit_is_rejected() -> None:
    report = _validate(VALID_MANIFEST.replace("0123456789abcdef0123456789abcdef01234567", "0123456"))
    assert any("40-character SHA" in error for error in report.errors)


def test_non_semantic_version_is_rejected() -> None:
    report = _validate(VALID_MANIFEST.replace('version = "0.1.0"', 'version = "v1"'))
    assert any("semantic version" in error for error in report.errors)


def test_non_python_source_path_is_rejected() -> None:
    report = _validate(
        VALID_MANIFEST.replace(
            'paths = ["codebase/__init__.py"]',
            'paths = ["config/outlook_mappings_master.xlsx"]',
        )
    )
    assert any("whole modules only" in error for error in report.errors)


def test_command_without_an_implementation_is_rejected() -> None:
    report = _validate(VALID_MANIFEST, known_command_names=["dashboard"])
    assert any("has no implementation" in error for error in report.errors)


def test_implemented_but_undeclared_command_is_warned_about() -> None:
    report = _validate(
        VALID_MANIFEST,
        known_command_names=["balance-review", "dashboard"],
    )
    assert report.ok, report.errors
    assert any("unavailable in the release" in warning for warning in report.warnings)


def test_duplicate_config_destination_is_rejected() -> None:
    duplicate = textwrap.dedent(
        """
        [[config_assets]]
        repository = "leap_initialisation"
        path = "config/other.json"
        dest = "example.json"
        role = "other"
        """
    )
    report = _validate(VALID_MANIFEST + duplicate)
    assert any("collides with" in error for error in report.errors)


def test_missing_repository_root_is_reported() -> None:
    manifest = parse_release_manifest(VALID_MANIFEST)
    report = validate_release_manifest(manifest, {}, check_git=False)
    assert any("no repository root was supplied" in error for error in report.errors)


# ---------------------------------------------------------------------------
# The manifest this repository actually ships
# ---------------------------------------------------------------------------


def test_shipped_manifest_is_valid_against_its_pinned_commits() -> None:
    from codebase.portable_release.build_release import (
        resolve_repository_roots,
        validate_only,
    )
    from codebase.portable_release.commands import IMPLEMENTED_COMMANDS

    if not SHIPPED_MANIFEST.is_file():
        pytest.skip("The release manifest has not been authored yet.")
    manifest = load_release_manifest(SHIPPED_MANIFEST)
    try:
        roots = resolve_repository_roots(manifest)
    except Exception as exc:  # pragma: no cover - depends on the local workspace
        pytest.skip(f"Sibling repositories are not available here: {exc}")
    for key, root in roots.items():
        if not (Path(root) / ".git").exists():
            pytest.skip(f"{key} is not a Git checkout at {root}")
    report = validate_release_manifest(
        manifest,
        roots,
        known_command_names=IMPLEMENTED_COMMANDS,
    )
    assert report.ok, report.as_text()
    assert report.checked_source_files >= len(manifest.repositories)


# ---------------------------------------------------------------------------
# Developer settings
# ---------------------------------------------------------------------------


def test_settings_template_round_trips(tmp_path: Path) -> None:
    text = render_settings_template(
        {
            "leap_initialisation": Path("C:/repos/leap_initialisation"),
            "leap_mappings": Path("C:/repos/leap_mappings"),
            "leap_dashboard": Path("C:/repos/leap_dashboard"),
        },
        workspace=Path("C:/work/leap_review_tools"),
    )
    settings_path = tmp_path / "developer_settings.toml"
    settings_path.write_text(text, encoding="utf-8")
    settings = load_developer_settings(settings_path)
    assert settings.repositories["leap_mappings"] == Path("C:/repos/leap_mappings")
    assert settings.output_root == Path("C:/work/leap_review_tools/output")


def test_missing_settings_file_explains_how_to_create_one(tmp_path: Path) -> None:
    with pytest.raises(DeveloperSettingsError, match="write_example_settings"):
        load_developer_settings(tmp_path / "absent.toml")


def test_settings_reject_a_relative_repository_path(tmp_path: Path) -> None:
    settings_path = tmp_path / "developer_settings.toml"
    settings_path.write_text(
        textwrap.dedent(
            """
            [repositories]
            leap_initialisation = "../leap_initialisation"
            leap_mappings = "C:/repos/leap_mappings"
            leap_dashboard = "C:/repos/leap_dashboard"
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(DeveloperSettingsError, match="must be an absolute path"):
        load_developer_settings(settings_path)


def test_settings_report_missing_repository_keys(tmp_path: Path) -> None:
    settings_path = tmp_path / "developer_settings.toml"
    settings_path.write_text(
        '[repositories]\nleap_initialisation = "C:/repos/leap_initialisation"\n',
        encoding="utf-8",
    )
    with pytest.raises(DeveloperSettingsError, match="leap_mappings"):
        load_developer_settings(settings_path)


def test_example_settings_file_in_config_is_loadable() -> None:
    example = REPO_ROOT / "config" / "leap_review_tools_settings.example.toml"
    settings = load_developer_settings(example)
    assert set(settings.repositories) == {
        "leap_initialisation",
        "leap_mappings",
        "leap_dashboard",
    }


# ---------------------------------------------------------------------------
# Run provenance
# ---------------------------------------------------------------------------


def test_describe_file_records_size_and_hash(tmp_path: Path) -> None:
    target = tmp_path / "thing.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    record = describe_file(target, role="input:thing")
    assert record.exists
    assert record.size_bytes == target.stat().st_size
    assert record.sha256 == sha256_file(target)


def test_describe_file_tolerates_a_missing_file(tmp_path: Path) -> None:
    record = describe_file(tmp_path / "absent.csv", role="input:absent")
    assert record.exists is False
    assert record.sha256 is None


def test_run_manifest_writes_both_forms(tmp_path: Path) -> None:
    manifest = new_run_manifest(
        release_name="leap-review-tools",
        release_version="0.1.0",
        mode="portable",
        command="balance-review",
        settings={"economy": "20_USA"},
    )
    manifest.release_commits = {"leap_initialisation": "0" * 40}
    finish_run_manifest(manifest, status="succeeded")
    paths = manifest.write(tmp_path)

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["mode"] == "portable"
    assert payload["status"] == "succeeded"
    assert payload["settings"]["economy"] == "20_USA"
    assert payload["release_commits"]["leap_initialisation"] == "0" * 40
    text = paths["text"].read_text(encoding="utf-8")
    assert "run manifest" in text
    assert "Release source commits" in text


# ---------------------------------------------------------------------------
# Runtime context
# ---------------------------------------------------------------------------


def test_portable_context_places_everything_inside_the_package(tmp_path: Path) -> None:
    context = portable_context(
        release_name="leap-review-tools",
        release_version="0.1.0",
        package_root=tmp_path,
        code_root=tmp_path / "code",
        sys_path_stage_dirs=["leap_initialisation"],
        config_assets={},
        release_commits={"leap_initialisation": "0" * 40},
    )
    assert context.output_root == tmp_path / "output"
    assert context.config_root == tmp_path / "config"
    assert context.sys_path_roots == (tmp_path / "code" / "leap_initialisation",)
    # __post_init__ creates the writable folders a run needs.
    assert context.output_root.is_dir()
    assert context.log_root.is_dir()


def test_preflight_names_every_missing_location(tmp_path: Path) -> None:
    context = RuntimeContext(
        mode="portable",
        release_name="leap-review-tools",
        release_version="0.1.0",
        package_root=tmp_path / "absent-package",
        config_root=tmp_path / "absent-config",
        output_root=tmp_path / "output",
        log_root=tmp_path / "logs",
        input_root=tmp_path / "input",
        config_assets={"dashboard_template": tmp_path / "absent-template.json"},
    )
    problems = context.preflight()
    assert any("package root" in problem for problem in problems)
    assert any("configuration directory" in problem for problem in problems)
    assert any("dashboard_template" in problem for problem in problems)
    with pytest.raises(FileNotFoundError, match="cannot start"):
        context.require_ready()


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [("20_USA", "20_USA"), ("20USA", "20_USA"), (" 20-usa ", "20_USA")],
)
def test_normalize_economy(given: str, expected: str) -> None:
    assert validation.normalize_economy(given) == expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [("tgt", "Target"), ("TGT", "Target"), ("Reference", "Reference"), ("ref", "Reference")],
)
def test_normalize_scenario(given: str, expected: str) -> None:
    assert validation.normalize_scenario(given) == expected


def test_balance_review_validation_explains_a_missing_diagnostics_folder(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "export.xlsx"
    workbook.write_bytes(b"not really a workbook")
    report = validation.validate_balance_review_inputs(
        economy="20_USA",
        scenario="Target",
        year=2022,
        balance_export_workbook=workbook,
        diagnostics_directory=tmp_path / "absent",
    )
    assert not report.ok
    message = report.failure_message()
    assert "diagnostics folder does not exist" in message
    assert "cannot be produced from a LEAP export alone" in message


def test_balance_review_validation_rejects_a_non_xlsx_export(tmp_path: Path) -> None:
    workbook = tmp_path / "export.csv"
    workbook.write_text("nope", encoding="utf-8")
    report = validation.validate_balance_review_inputs(
        economy="20_USA",
        scenario="Target",
        year=2022,
        balance_export_workbook=workbook,
        diagnostics_directory=tmp_path,
    )
    assert any(
        "must be a .xlsx file" in check.detail
        for check in report.failures
    )


def test_balance_review_validation_rejects_an_out_of_range_year(tmp_path: Path) -> None:
    report = validation.validate_balance_review_inputs(
        economy="20_USA",
        scenario="Target",
        year=1899,
        balance_export_workbook=tmp_path / "absent.xlsx",
        diagnostics_directory=tmp_path,
    )
    assert any("outside the supported range" in check.detail for check in report.failures)


def test_balance_review_validation_lists_the_scopes_the_diagnostics_do_cover(
    tmp_path: Path,
) -> None:
    diagnostics = tmp_path / "diagnostics"
    diagnostics.mkdir()
    header = ",".join(
        list(validation.BALANCE_REVIEW_SHARED_COLUMNS)
        + list(validation.BALANCE_REVIEW_REVIEW_ONLY_COLUMNS)
    )
    row = "01_AUS,Reference,2022,01,1.01,x,y,match,0,0,0,Production,Coal,False"
    (diagnostics / "leap_balance_source_review.csv").write_text(
        f"{header}\n{row}\n", encoding="utf-8"
    )
    (diagnostics / "leap_balance_source_differences.csv").write_text(
        f"{','.join(validation.BALANCE_REVIEW_SHARED_COLUMNS)}\n"
        "01_AUS,Reference,2022,01,1.01,x,y,match,0\n",
        encoding="utf-8",
    )
    report = validation.validate_balance_review_inputs(
        economy="20_USA",
        scenario="Target",
        year=2022,
        balance_export_workbook=tmp_path / "absent.xlsx",
        diagnostics_directory=diagnostics,
    )
    failure = report.failure_message()
    assert "no rows for 20_USA / Target / 2022" in failure
    assert "01_AUS/Reference/2022" in failure


def test_balance_review_validation_reports_missing_columns(tmp_path: Path) -> None:
    diagnostics = tmp_path / "diagnostics"
    diagnostics.mkdir()
    (diagnostics / "leap_balance_source_review.csv").write_text(
        "economy,scenario\n20_USA,Target\n", encoding="utf-8"
    )
    (diagnostics / "leap_balance_source_differences.csv").write_text(
        "economy,scenario\n20_USA,Target\n", encoding="utf-8"
    )
    report = validation.validate_balance_review_inputs(
        economy="20_USA",
        scenario="Target",
        year=2022,
        balance_export_workbook=tmp_path / "absent.xlsx",
        diagnostics_directory=diagnostics,
    )
    assert any("missing required columns" in check.detail for check in report.failures)


def test_dashboard_validation_lists_available_economies(tmp_path: Path) -> None:
    comparison = tmp_path / "comparison.csv"
    comparison.write_text(
        ",".join(validation.DASHBOARD_COMPARISON_COLUMNS)
        + "\nesto_leap_ninth,ESTO,02_BD,historical,2022,01,1.01,row1,1.0\n",
        encoding="utf-8",
    )
    rows = tmp_path / "rows.csv"
    rows.write_text("common_row_id\nrow1\n", encoding="utf-8")
    template = tmp_path / "template.json"
    template.write_text(json.dumps({"sector_pages": []}), encoding="utf-8")
    series = tmp_path / "series.json"
    series.write_text(json.dumps({"visible_series": []}), encoding="utf-8")

    report = validation.validate_dashboard_inputs(
        economy="20_USA",
        comparison_data_path=comparison,
        common_rows_path=rows,
        template_path=template,
        series_config_path=series,
    )
    assert not report.ok
    assert "no rows for 20_USA" in report.failure_message()
    assert "02BD" in report.failure_message()


def test_dashboard_validation_passes_for_a_covered_economy(tmp_path: Path) -> None:
    comparison = tmp_path / "comparison.csv"
    comparison.write_text(
        ",".join(validation.DASHBOARD_COMPARISON_COLUMNS)
        + "\nesto_leap_ninth,ESTO,20_USA,historical,2022,01,1.01,row1,1.0\n",
        encoding="utf-8",
    )
    rows = tmp_path / "rows.csv"
    rows.write_text("common_row_id\nrow1\n", encoding="utf-8")
    template = tmp_path / "template.json"
    template.write_text(json.dumps({"sector_pages": []}), encoding="utf-8")
    series = tmp_path / "series.json"
    series.write_text(json.dumps({"visible_series": []}), encoding="utf-8")

    report = validation.validate_dashboard_inputs(
        economy="20_USA",
        comparison_data_path=comparison,
        common_rows_path=rows,
        template_path=template,
        series_config_path=series,
    )
    assert report.ok, report.failure_message()
    assert report.facts["comparison_rows_matching_economy"] == 1


def test_dashboard_validation_reports_broken_json(tmp_path: Path) -> None:
    template = tmp_path / "template.json"
    template.write_text("{not json", encoding="utf-8")
    report = validation.validate_dashboard_inputs(
        economy="20_USA",
        comparison_data_path=None,
        common_rows_path=None,
        template_path=template,
        series_config_path=None,
    )
    assert any("not valid JSON" in check.detail for check in report.failures)
