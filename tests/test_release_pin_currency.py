"""Tests for the two things that make a pin trustworthy.

A pin exists so a release is reproducible and so nobody's work-in-progress can
reach a colleague. Two gaps undermined that in practice:

* a pin could silently fall behind a fix and nobody noticed for days;
* an untracked data table could be swapped between builds with nothing to say so.

Both are checked at validation time now, and both checks are written to stay
quiet unless there is something to act on - a warning that fires on every build
is one nobody reads.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest

from codebase.portable_release.manifest import (
    DataAssetSpec,
    ManifestValidationReport,
    ReleaseManifest,
    RepositorySpec,
    _check_pins_are_current,
    _staged_paths_of,
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small real repository: git behaviour is the thing under test."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "shipped.py").write_text("first\n", encoding="utf-8")
    (root / "not_shipped.py").write_text("first\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "first")
    return root


def _manifest(commit: str, *, paths: list[str]) -> ReleaseManifest:
    return ReleaseManifest(
        schema_version=1,
        name="test",
        version="0.1.0",
        description="",
        runtime_python=">=3.11",
        runtime_packages=[],
        repositories={
            "demo": RepositorySpec(key="demo", commit=commit, stage_dir="demo", paths=list(paths))
        },
        config_assets=[],
        commands=[],
    )


def _validate(manifest: ReleaseManifest, root: Path) -> list[str]:
    report = ManifestValidationReport(manifest_name="test", manifest_version="0.1.0")
    _check_pins_are_current(manifest, {"demo": root}, report)
    return report.warnings


# ---------------------------------------------------------------------------
# Pin currency
# ---------------------------------------------------------------------------


def test_a_pin_at_head_is_silent(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    assert _validate(_manifest(head, paths=["shipped.py"]), repo) == []


def test_a_pin_behind_a_commit_that_changes_what_ships_is_reported(repo: Path) -> None:
    """The bunkers case: a fix landed and the release never picked it up."""
    pinned = _git(repo, "rev-parse", "HEAD")
    (repo / "shipped.py").write_text("fixed\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "Fix the thing that ships")

    warnings = _validate(_manifest(pinned, paths=["shipped.py"]), repo)

    assert len(warnings) == 1
    assert "Fix the thing that ships" in warnings[0]
    assert pinned[:12] in warnings[0]


def test_a_pin_behind_only_unrelated_commits_stays_silent(repo: Path) -> None:
    """Other people commit to these repositories constantly.

    Warning on commits that cannot reach the package would fire on nearly every
    build, and a warning that is usually noise is exactly what let the real one
    go unnoticed.
    """
    pinned = _git(repo, "rev-parse", "HEAD")
    (repo / "not_shipped.py").write_text("changed\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "Something the release never sees")

    assert _validate(_manifest(pinned, paths=["shipped.py"]), repo) == []


def test_a_pin_on_another_branch_is_left_alone(repo: Path) -> None:
    """A pin off the mainline is a decision, not staleness."""
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "shipped.py").write_text("side\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "side work")
    side = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    (repo / "shipped.py").write_text("main\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "main work")

    # `side` is not an ancestor of HEAD, so it is not "behind" anything.
    assert _validate(_manifest(side, paths=["shipped.py"]), repo) == []


def test_a_config_asset_counts_as_something_that_ships(repo: Path) -> None:
    """The bunkers fix changed a template, not only code."""
    from codebase.portable_release.manifest import ConfigAssetSpec

    pinned = _git(repo, "rev-parse", "HEAD")
    (repo / "template.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "Change the template")

    manifest = _manifest(pinned, paths=[])
    manifest.config_assets.append(
        ConfigAssetSpec(repository="demo", path="template.json", dest="t.json", role="t")
    )

    warnings = _validate(manifest, repo)
    assert len(warnings) == 1 and "Change the template" in warnings[0]


def test_staged_paths_include_assets_not_just_code() -> None:
    from codebase.portable_release.manifest import ConfigAssetSpec

    manifest = dataclasses.replace(
        _manifest("0" * 40, paths=["a.py"]),
        config_assets=[ConfigAssetSpec(repository="demo", path="c.json", dest="c", role="c")],
        data_assets=[DataAssetSpec(repository="demo", path="d.csv", dest="d", role="d")],
    )
    assert _staged_paths_of(manifest, "demo") == {"a.py", "c.json", "d.csv"}


def test_a_repository_with_no_staged_paths_is_not_reported(repo: Path) -> None:
    pinned = _git(repo, "rev-parse", "HEAD")
    (repo / "shipped.py").write_text("changed\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "change")
    assert _validate(_manifest(pinned, paths=[]), repo) == []


# ---------------------------------------------------------------------------
# Content pins for untracked tables
# ---------------------------------------------------------------------------


def test_a_declared_digest_is_what_makes_an_untracked_table_reproducible() -> None:
    """Without one, the manifest cannot say which table a release used."""
    spec = DataAssetSpec(
        repository="demo", path="d.csv", dest="d", role="d", sha256="abc123"
    )
    assert spec.allow_untracked is True
    assert spec.sha256 == "abc123"


def test_the_real_manifest_pins_every_untracked_table() -> None:
    """Regression guard for the gap this closed.

    Every data asset in this release is gitignored by design, so without a
    content pin none of them are reproducible from the manifest alone.
    """
    from codebase.portable_release.build_release import DEFAULT_MANIFEST_PATH
    from codebase.portable_release.manifest import load_release_manifest

    manifest = load_release_manifest(DEFAULT_MANIFEST_PATH)
    unpinned = [
        asset.role
        for asset in manifest.data_assets
        if asset.allow_untracked and not asset.sha256
    ]
    assert unpinned == [], f"data assets with no content pin: {unpinned}"


def test_declared_digests_are_full_length_lowercase_sha256() -> None:
    """A truncated or upper-case digest would never match and never be noticed."""
    from codebase.portable_release.build_release import DEFAULT_MANIFEST_PATH
    from codebase.portable_release.manifest import load_release_manifest

    manifest = load_release_manifest(DEFAULT_MANIFEST_PATH)
    for asset in manifest.data_assets:
        if asset.sha256:
            assert len(asset.sha256) == 64, f"{asset.role}: {asset.sha256}"
            assert asset.sha256 == asset.sha256.lower()


# ---------------------------------------------------------------------------
# Version and changelog
# ---------------------------------------------------------------------------


def test_the_declared_version_has_a_changelog_entry() -> None:
    """A bump advertises a change; the entry is what says what it was."""
    from codebase.portable_release.build_release import DEFAULT_MANIFEST_PATH
    from codebase.portable_release.manifest import CHANGELOG_PATH, load_release_manifest

    manifest = load_release_manifest(DEFAULT_MANIFEST_PATH)
    changelog = Path(__file__).resolve().parents[1] / CHANGELOG_PATH
    assert changelog.is_file()
    assert f"## {manifest.version}" in changelog.read_text(encoding="utf-8")


def test_a_version_with_no_entry_is_reported(tmp_path: Path) -> None:
    from codebase.portable_release.manifest import (
        CHANGELOG_PATH,
        _check_version_is_described,
    )

    root = tmp_path / "repo"
    (root / Path(CHANGELOG_PATH).parent).mkdir(parents=True)
    (root / CHANGELOG_PATH).write_text("# Log\n\n## 0.1.0\n\nFirst.\n", encoding="utf-8")

    report = ManifestValidationReport(manifest_name="t", manifest_version="0.2.0")
    _check_version_is_described(
        dataclasses.replace(_manifest("0" * 40, paths=[]), version="0.2.0"),
        {"leap_initialisation": root},
        report,
    )
    assert len(report.warnings) == 1 and "0.2.0" in report.warnings[0]


def test_a_described_version_is_silent(tmp_path: Path) -> None:
    from codebase.portable_release.manifest import (
        CHANGELOG_PATH,
        _check_version_is_described,
    )

    root = tmp_path / "repo"
    (root / Path(CHANGELOG_PATH).parent).mkdir(parents=True)
    (root / CHANGELOG_PATH).write_text("# Log\n\n## 0.2.0\n\nThings.\n", encoding="utf-8")

    report = ManifestValidationReport(manifest_name="t", manifest_version="0.2.0")
    _check_version_is_described(
        dataclasses.replace(_manifest("0" * 40, paths=[]), version="0.2.0"),
        {"leap_initialisation": root},
        report,
    )
    assert report.warnings == []


@pytest.mark.parametrize(
    "current,part,expected",
    [
        ((0, 1, 0), "minor", "0.2.0"),
        ((0, 2, 0), "patch", "0.2.1"),
        ((0, 2, 3), "major", "1.0.0"),
        ((0, 2, 3), "1.4.2", "1.4.2"),
    ],
)
def test_version_arithmetic(current, part, expected) -> None:
    from scripts.bump_release_version import next_version

    assert next_version(current, part) == expected


def test_a_nonsense_bump_is_refused() -> None:
    from scripts.bump_release_version import next_version

    with pytest.raises(SystemExit):
        next_version((0, 1, 0), "sideways")


def test_the_changelog_ships_in_the_package() -> None:
    """Useless in the repository if a colleague never receives it."""
    from codebase.portable_release import build_release

    assert build_release.CHANGELOG_SOURCE_PATH == "docs/CHANGELOG.md"
    assert build_release.CHANGELOG_PACKAGE_NAME == "CHANGELOG.md"


def test_the_build_stamp_distinguishes_two_builds_of_one_version() -> None:
    """The gap this closes: several 0.1.0 builds, no way to tell them apart."""
    from codebase.portable_release.portable_main import _build_stamp

    assert _build_stamp({"built_utc": "2026-08-05T02:50:20+00:00"}) == "  (built 2026-08-05)"
    assert _build_stamp({}) == ""
    assert _build_stamp({"built_utc": "nonsense"}) == ""
