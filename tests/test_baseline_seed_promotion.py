"""Promotion of run-scoped baseline seeds into the primary directory.

A labelled run writes everything under `baseline_seed/runs/<LABEL>/`, but the
patcher and the equivalence harness glob the primary `baseline_seed/` directory
only. These tests lock the promotion step that closes that gap, plus the two
hazards it has to respect: never destroy an existing seed, and never let a seed
with blocking findings pass as clean output.
"""

#%%

import re
from pathlib import Path

import pytest

from codebase.functions.patch_baseline_seeds import (
    SEED_FILENAME_PATTERN,
    _economy_from_seed_filename,
)
from codebase.functions.supply_leap_io import promote_baseline_seed_to_primary_dir


def _make_run_seed(tmp_path, name="leap_import_baseline_seed_01_AUS_20260721.xlsx"):
    """Create a seed inside a run-scoped directory and return (seed, primary_dir)."""
    primary = tmp_path / "baseline_seed"
    run_dir = primary / "runs" / "SEED_01_AUS_TGT_REF_CA"
    run_dir.mkdir(parents=True)
    seed = run_dir / name
    seed.write_bytes(b"seed-content")
    return seed, primary


def test_promotes_run_scoped_seed_to_primary_dir(tmp_path):
    seed, primary = _make_run_seed(tmp_path)

    promoted = promote_baseline_seed_to_primary_dir(seed, unverified=False)

    assert promoted == primary / seed.name
    assert promoted.read_bytes() == b"seed-content"
    # The run-scoped copy stays as the record of the run.
    assert seed.exists()


def test_unlabelled_run_is_a_no_op(tmp_path):
    """A seed already in the primary directory must not self-copy."""
    primary = tmp_path / "baseline_seed"
    primary.mkdir(parents=True)
    seed = primary / "leap_import_baseline_seed_01_AUS_20260721.xlsx"
    seed.write_bytes(b"seed-content")

    assert promote_baseline_seed_to_primary_dir(seed, unverified=False) is None
    assert seed.exists()


def test_blocking_findings_tag_the_promoted_copy(tmp_path):
    seed, primary = _make_run_seed(tmp_path)

    promoted = promote_baseline_seed_to_primary_dir(seed, unverified=True)

    assert promoted.name == "leap_import_baseline_seed_01_AUS_UNVERIFIED_20260721.xlsx"
    # The untagged name must NOT exist, or the seed could be mistaken for clean.
    assert not (primary / seed.name).exists()


def test_unverified_marker_composes_with_prelim(tmp_path):
    """A provisional seed that also has blocking findings keeps both markers."""
    seed, _ = _make_run_seed(
        tmp_path, name="leap_import_baseline_seed_02_BD_PRELIM_20260721.xlsx"
    )

    promoted = promote_baseline_seed_to_primary_dir(seed, unverified=True)

    assert promoted.name == "leap_import_baseline_seed_02_BD_PRELIM_UNVERIFIED_20260721.xlsx"


@pytest.mark.parametrize(
    "name, economy",
    [
        ("leap_import_baseline_seed_01_AUS_20260721.xlsx", "01_AUS"),
        ("leap_import_baseline_seed_02_BD_PRELIM_20260721.xlsx", "02_BD"),
        ("leap_import_baseline_seed_01_AUS_UNVERIFIED_20260721.xlsx", "01_AUS"),
        ("leap_import_baseline_seed_02_BD_PRELIM_UNVERIFIED_20260721.xlsx", "02_BD"),
    ],
)
def test_marked_seeds_stay_discoverable_to_the_patcher(name, economy):
    """Markers must not make a seed invisible -- the regex anchors on the stamp,
    so an unmatched marker would silently drop the file from the patcher's view."""
    assert SEED_FILENAME_PATTERN.match(name), name
    assert _economy_from_seed_filename(Path(name)) == economy


def test_existing_primary_seed_is_archived_not_destroyed(tmp_path):
    seed, primary = _make_run_seed(tmp_path)
    existing = primary / seed.name
    primary.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"previous-good-seed")

    promoted = promote_baseline_seed_to_primary_dir(seed, unverified=False)

    assert promoted.read_bytes() == b"seed-content"
    archived = list((primary / "archive").glob("*.xlsx"))
    assert len(archived) == 1, archived
    # The previous seed survives intact -- promotion must never destroy work.
    assert archived[0].read_bytes() == b"previous-good-seed"
    assert re.search(r"_superseded_\d{8}_\d{6}\.xlsx$", archived[0].name), archived[0].name


#%%
