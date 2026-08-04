"""End-to-end checks on a built portable package.

These tests stage a package from the shipped manifest and then exercise it the
way a colleague's machine would: in a separate interpreter, started with ``-I``
so no user site directory, ``PYTHONPATH``, or environment customisation can
leak in, and with the working directory somewhere unrelated.

What they defend:

* the package's entry point imports **nothing** from the live repositories;
* a real run writes its output, run manifest, and mapping/configuration hashes
  where the package contract says it will;
* editing a configuration file in a copied package changes the next run's
  recorded hash, so a mapping update needs no rebuild but is never invisible;
* an invalid input fails with a plain-language explanation and no output file;
* the package contains no ``.git``, ``.codex``, ``.claude``, junction, cache, or
  large historical output content.

Staging is slow-ish (it shells out to Git for every file), so it happens once
per session.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from codebase.portable_release.build_release import (
    ReleaseBuildError,
    build,
    inspect_package,
    resolve_repository_roots,
)
from codebase.portable_release.manifest import load_release_manifest


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "config" / "portable_release_manifest.toml"

GOLDEN_DIAGNOSTICS_DIR = (
    REPO_ROOT
    / "outputs"
    / "leap_exports"
    / "supply_reconciliation"
    / "supporting_files"
    / "baseline_seed_balance_diagnostics"
    / "results_update_preview_20260803_usa_tgt"
)
GOLDEN_BALANCE_EXPORT = (
    REPO_ROOT / "data" / "leap balances exports" / "20_USA" / "TGT 0308.xlsx"
)

#: Any of these appearing in the isolated run's loaded-module list means the
#: package reached back into a maintainer checkout.
LIVE_REPOSITORY_ROOTS = ("leap_initialisation", "leap_mappings", "leap_dashboard")


def _repositories_available() -> bool:
    if not MANIFEST_PATH.is_file():
        return False
    try:
        roots = resolve_repository_roots(load_release_manifest(MANIFEST_PATH))
    except Exception:
        return False
    return all((Path(root) / ".git").exists() for root in roots.values())


pytestmark = pytest.mark.skipif(
    not _repositories_available(),
    reason="All three repository checkouts are needed to stage a release.",
)


@pytest.fixture(scope="module")
def staged_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Stage a package from the shipped manifest into a temporary build root."""
    build_root = tmp_path_factory.mktemp("release_build")
    report = build(MANIFEST_PATH, build_root=build_root, freeze=False)
    assert report.package_dir is not None
    return report.package_dir


def _run_package(
    package: Path,
    args: list[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    """Run the package's entry point in an isolated interpreter."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}
    }
    return subprocess.run(
        [sys.executable, "-I", str(package / "code" / "entry_point.py"), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd),
        env=environment,
    )


# ---------------------------------------------------------------------------
# Package contents
# ---------------------------------------------------------------------------


def test_package_layout_matches_the_contract(staged_package: Path) -> None:
    for name in ("code", "config", "input", "output", "logs", "licenses"):
        assert (staged_package / name).is_dir(), name
    assert (staged_package / "README.md").is_file()
    assert (staged_package / "release_manifest.json").is_file()


def test_frozen_manifest_pins_every_repository(staged_package: Path) -> None:
    frozen = json.loads((staged_package / "release_manifest.json").read_text(encoding="utf-8"))
    manifest = load_release_manifest(MANIFEST_PATH)
    assert frozen["release"]["version"] == manifest.version
    for key, spec in manifest.repositories.items():
        assert frozen["repositories"][key]["commit"] == spec.commit
        assert len(frozen["repositories"][key]["commit"]) == 40
    assert frozen["built_utc"]


def test_package_has_no_private_or_generated_content(staged_package: Path) -> None:
    inspection = inspect_package(staged_package)
    assert inspection["problems"] == []
    paths = [item["path"] for item in inspection["files"]]
    forbidden = (".git", ".codex", ".claude", "node_modules", "__pycache__", ".venv")
    for path in paths:
        parts = path.split("/")
        assert not any(part in forbidden for part in parts), path
        assert not path.endswith((".pyc", ".log", ".pkl")), path
    # A staged package is source, reviewed configuration, the mapping-chain
    # artifacts (~90 MB), and the ESTO/9th source tables used by
    # balance-review-from-export (~314 MB) - nothing more.
    total = sum(int(item["size_bytes"]) for item in inspection["files"])
    assert total < 450 * 1024 * 1024, f"staged package is unexpectedly large: {total:,} bytes"


def test_builder_rejects_a_package_containing_a_junction(
    staged_package: Path,
    tmp_path: Path,
) -> None:
    tainted = tmp_path / "tainted"
    shutil.copytree(staged_package, tainted)
    (tainted / ".git").mkdir()
    (tainted / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    inspection = inspect_package(tainted)
    assert any(".git" in problem for problem in inspection["problems"])


def test_entry_point_never_scans_its_own_directory(staged_package: Path) -> None:
    """The stage directories must be baked in, not discovered.

    A scan is correct in a staged package and catastrophic in a frozen one,
    where the entry point's directory is PyInstaller's bundle: putting every
    subfolder of it on sys.path shadows standard-library modules with
    third-party package internals.
    """
    source = (staged_package / "code" / "entry_point.py").read_text(encoding="utf-8")
    assert "iterdir()" not in source
    assert 'getattr(sys, "frozen", False)' in source
    manifest = load_release_manifest(MANIFEST_PATH)
    for stage_dir in manifest.sys_path_stage_dirs():
        assert repr(stage_dir) in source


def test_staged_package_passes_its_own_selfcheck(
    staged_package: Path,
    tmp_path: Path,
) -> None:
    result = _run_package(staged_package, ["selfcheck"], cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "result                   : OK" in result.stdout


def test_package_config_is_external_and_editable(staged_package: Path) -> None:
    config_root = staged_package / "config"
    assert (config_root / "dashboard" / "common_esto_dashboard_template.json").is_file()
    assert (config_root / "dashboard" / "series_config.json").is_file()
    assert (config_root / "dashboard" / "code_colors.json").is_file()
    assert (config_root / "mappings" / "all_demand_aggregated_components.json").is_file()


def test_balance_review_from_export_source_tables_are_packaged(
    staged_package: Path,
) -> None:
    data_root = staged_package / "data" / "balance_review"
    assert (data_root / "00APEC_2024_low_with_subtotals.csv").is_file()
    assert (data_root / "merged_file_energy_ALL_20251106.csv").is_file()

    frozen = json.loads(
        (staged_package / "release_manifest.json").read_text(encoding="utf-8")
    )
    assets = {asset["role"]: asset for asset in frozen["data_assets"]}
    assert assets["esto_base_table"]["sha256"]
    assert assets["ninth_projection_table"]["sha256"]


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


def test_entry_point_imports_nothing_from_the_live_repositories(
    staged_package: Path,
    tmp_path: Path,
) -> None:
    # Only the main target's own STAGE_DIRS go on sys.path here, exactly as
    # entry_point.py does at run time. Scanning every directory under code/
    # would also pick up the mapping-chain worker's own `codebase` package
    # (leap_mappings_worker/codebase/...), which must never share a process
    # with the main target's `codebase` package (handover §1) - that they
    # cannot coexist on one sys.path is the isolation this test is meant to
    # prove, not something to route around.
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json, re, sys\n"
        "from pathlib import Path\n"
        "here = Path(sys.argv[1]) / 'code'\n"
        "entry_source = (here / 'entry_point.py').read_text(encoding='utf-8')\n"
        "match = re.search(r'STAGE_DIRS = \\[(.*?)\\]', entry_source)\n"
        "stage_dirs = eval('[' + match.group(1) + ']')\n"
        "for name in reversed(stage_dirs):\n"
        "    sys.path.insert(0, str(here / name))\n"
        "from codebase.portable_release import commands, portable_main, runtime, validation\n"
        "import common_esto_dashboard_portable\n"
        "import mapping_tools.source_branch_preflight\n"
        "loaded = sorted(\n"
        "    getattr(module, '__file__', '') or ''\n"
        "    for module in list(sys.modules.values())\n"
        ")\n"
        "print(json.dumps([path for path in loaded if path]))\n",
        encoding="utf-8",
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}
    }
    result = subprocess.run(
        [sys.executable, "-I", str(probe), str(staged_package)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
        env=environment,
    )
    assert result.returncode == 0, result.stderr

    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    package_prefix = str(staged_package.resolve()).lower()
    offenders = []
    for path in loaded:
        lowered = str(Path(path).resolve()).lower()
        if lowered.startswith(package_prefix):
            continue
        # Anything outside the package must be the interpreter's own stdlib or
        # an installed third-party package, never a repository checkout.
        for repository in LIVE_REPOSITORY_ROOTS:
            if f"github{os.sep}{repository}".lower() in lowered:
                offenders.append(path)
    assert not offenders, "package imported live repository code:\n" + "\n".join(offenders)


def test_info_runs_from_an_unrelated_working_directory(
    staged_package: Path,
    tmp_path: Path,
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = _run_package(staged_package, ["info"], cwd=elsewhere)
    assert result.returncode == 0, result.stderr
    assert "balance-review" in result.stdout
    assert "portable mode" in result.stdout


# ---------------------------------------------------------------------------
# A real run
# ---------------------------------------------------------------------------


golden_inputs = pytest.mark.skipif(
    not (GOLDEN_DIAGNOSTICS_DIR.is_dir() and GOLDEN_BALANCE_EXPORT.is_file()),
    reason="The USA 2022 golden inputs are not present on this machine.",
)


@pytest.fixture(scope="module")
def portable_run(staged_package: Path, tmp_path_factory: pytest.TempPathFactory):
    """Copy the package, run balance-review inside the copy, return both."""
    if not (GOLDEN_DIAGNOSTICS_DIR.is_dir() and GOLDEN_BALANCE_EXPORT.is_file()):
        pytest.skip("The USA 2022 golden inputs are not present on this machine.")
    copy_root = tmp_path_factory.mktemp("colleague") / "leap-review-tools"
    shutil.copytree(staged_package, copy_root)
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    result = _run_package(
        copy_root,
        [
            "balance-review",
            "--economy",
            "20_USA",
            "--scenario",
            "Target",
            "--year",
            "2022",
            "--balance-export-workbook",
            str(GOLDEN_BALANCE_EXPORT),
            "--diagnostics-directory",
            str(GOLDEN_DIAGNOSTICS_DIR),
            "--run-label",
            "smoke",
            "--support-bundle",
        ],
        cwd=elsewhere,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return copy_root, result


@golden_inputs
def test_run_writes_output_inside_the_package(portable_run) -> None:
    copy_root, _ = portable_run
    deliverable_dir = copy_root / "output" / "20_USA" / "balance_review"
    record_dir = deliverable_dir / "run_records" / "smoke"
    assert (deliverable_dir / "balance_review_20_USA_tgt_2022.xlsx").is_file()
    assert (record_dir / "run_manifest.json").is_file()
    assert (record_dir / "run_manifest.txt").is_file()
    assert (record_dir / "validation_report.txt").is_file()
    assert list((copy_root / "logs").glob("balance-review_*.log"))


@golden_inputs
def test_run_manifest_records_release_commits_and_input_hashes(portable_run) -> None:
    copy_root, _ = portable_run
    manifest = json.loads(
        (
            copy_root
            / "output"
            / "20_USA"
            / "balance_review"
            / "run_records"
            / "smoke"
            / "run_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["mode"] == "portable"
    assert manifest["status"] == "succeeded"
    # release_commits has one entry per manifest repository entry, which may
    # outnumber the checkouts in LIVE_REPOSITORY_ROOTS - e.g. the mapping-chain
    # worker's leap_mappings_worker entry (handover §1/§3.3) is a second entry
    # for the same leap_mappings checkout, pinned separately for its own
    # bundle.
    assert set(LIVE_REPOSITORY_ROOTS) <= set(manifest["release_commits"])
    assert all(len(commit) == 40 for commit in manifest["release_commits"].values())
    # Developer-mode-only fields stay empty in a portable run.
    assert manifest["repositories"] == []
    inputs = {record["role"]: record for record in manifest["inputs"]}
    assert inputs["input:balance_export_workbook"]["sha256"]
    assert any(role.startswith("input:diagnostic_artifact") for role in inputs)
    outputs = {record["role"]: record for record in manifest["outputs"]}
    assert outputs["output:balance_review_workbook"]["sha256"]


@golden_inputs
def test_run_reproduces_the_golden_balance_review_values(portable_run) -> None:
    copy_root, _ = portable_run
    manifest = json.loads(
        (
            copy_root
            / "output"
            / "20_USA"
            / "balance_review"
            / "run_records"
            / "smoke"
            / "run_manifest.json"
        ).read_text(encoding="utf-8")
    )
    build_result = manifest["results"]["build_result"]
    assert build_result["sourceShape"] == {"rows": 79, "columns": 49}
    assert build_result["statusCounts"] == {
        "value_mismatch": 180,
        "reference_unavailable": 14,
        "match": 162,
    }
    assert build_result["missingAuditRows"] == 51
    assert build_result["formulaErrorCells"] == []


@golden_inputs
def test_support_bundle_excludes_input_data(portable_run) -> None:
    import zipfile

    copy_root, _ = portable_run
    bundles = list((copy_root / "output").glob("support_bundle_*.zip"))
    assert bundles, "expected a support bundle"
    with zipfile.ZipFile(bundles[0]) as bundle:
        names = bundle.namelist()
    assert "run/run_manifest.json" in names
    assert "run/validation_report.txt" in names
    assert "run/effective_settings.json" in names
    assert not any(name.endswith(".xlsx") for name in names)
    assert not any(name.endswith(".csv") for name in names)


def test_editing_a_config_file_changes_the_next_run_manifest_hash(
    staged_package: Path,
    tmp_path: Path,
) -> None:
    """A mapping/configuration change applies without a rebuild, and is recorded.

    The edit is made in a *copy* of the package, using a harmless fixture note
    added to a mapping-owned configuration file: the canonical mapping workbooks
    are never touched.

    The dashboard command is used because it is the one that consumes these
    assets. A tiny synthetic comparison file is enough — the run stops at input
    validation, and the configuration hashes are recorded before validation
    runs, which is exactly the property under test.
    """
    from codebase.portable_release.provenance import sha256_file
    from codebase.portable_release.validation import DASHBOARD_COMPARISON_COLUMNS

    copy_root = tmp_path / "edited"
    shutil.copytree(staged_package, copy_root)
    components = copy_root / "config" / "mappings" / "all_demand_aggregated_components.json"

    comparison = tmp_path / "comparison.csv"
    comparison.write_text(
        ",".join(DASHBOARD_COMPARISON_COLUMNS)
        + "\nesto_leap_ninth,ESTO,02_BD,historical,2022,01,1.01,row1,1.0\n",
        encoding="utf-8",
    )
    rows = tmp_path / "rows.csv"
    rows.write_text("common_row_id\nrow1\n", encoding="utf-8")

    def recorded_hash(label: str) -> str:
        result = _run_package(
            copy_root,
            [
                "dashboard",
                "--economy",
                "20_USA",
                "--comparison-data-path",
                str(comparison),
                "--common-rows-path",
                str(rows),
                "--run-label",
                label,
            ],
            cwd=tmp_path,
        )
        # The synthetic file covers a different economy, so the run stops at
        # validation. The manifest is still written, with the config hashes.
        assert result.returncode == 1, result.stdout
        manifest = json.loads(
            (
                copy_root
                / "output"
                / "20_USA"
                / "dashboard"
                / "run_records"
                / label
                / "run_manifest.json"
            ).read_text(encoding="utf-8")
        )
        records = {item["role"]: item for item in manifest["configuration"]}
        assert set(records) >= {
            "config:dashboard_template",
            "config:dashboard_series_config",
            "config:dashboard_code_colors",
            "config:all_demand_aggregated_components",
        }
        return records["config:all_demand_aggregated_components"]["sha256"]

    before = recorded_hash("before_edit")
    assert before == sha256_file(components)

    payload = json.loads(components.read_text(encoding="utf-8"))
    payload["_fixture_note"] = "harmless test edit; not a mapping change"
    components.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    after = recorded_hash("after_edit")
    assert after == sha256_file(components)
    assert after != before, "the run manifest did not follow the edited config file"


# ---------------------------------------------------------------------------
# Error behaviour
# ---------------------------------------------------------------------------


@golden_inputs
def test_invalid_input_is_explained_and_produces_no_workbook(
    staged_package: Path,
    tmp_path: Path,
) -> None:
    copy_root = tmp_path / "invalid"
    shutil.copytree(staged_package, copy_root)
    result = _run_package(
        copy_root,
        [
            "balance-review",
            "--economy",
            "20_USA",
            "--scenario",
            "Target",
            "--year",
            "2022",
            "--balance-export-workbook",
            str(GOLDEN_BALANCE_EXPORT),
            "--diagnostics-directory",
            str(tmp_path / "no-such-folder"),
            "--run-label",
            "invalid",
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "diagnostics folder does not exist" in result.stdout

    record_dir = copy_root / "output" / "20_USA" / "balance_review" / "run_records" / "invalid"
    assert (record_dir / "validation_report.txt").is_file()
    manifest = json.loads((record_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["validation"]["ok"] is False
    assert not list((copy_root / "output" / "20_USA" / "balance_review").glob("*.xlsx"))


def test_incomplete_package_refuses_to_run(staged_package: Path, tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    shutil.copytree(staged_package, broken)
    shutil.rmtree(broken / "config")
    result = _run_package(broken, ["info"], cwd=tmp_path)
    assert result.returncode == 2
    assert "not usable as extracted" in result.stdout


def test_build_fails_when_the_manifest_is_invalid(tmp_path: Path) -> None:
    tampered = tmp_path / "manifest.toml"
    tampered.write_text(
        MANIFEST_PATH.read_text(encoding="utf-8").replace(
            '"codebase/portable_release/commands.py"',
            '"codebase/../../../etc/passwd"',
        ),
        encoding="utf-8",
    )
    with pytest.raises((ReleaseBuildError, Exception)) as excinfo:
        build(tampered, build_root=tmp_path / "build", freeze=False)
    assert "escapes the repository root" in str(excinfo.value)
