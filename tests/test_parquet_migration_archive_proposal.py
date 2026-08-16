"""Focused safety tests for the Parquet archive proposal generator."""

from pathlib import Path

from scripts import parquet_migration_archive_proposal_exploration as proposal


def test_sampled_deflate_ratio_detects_compressible_content(tmp_path: Path) -> None:
    candidate = tmp_path / "compressible.pkl"
    candidate.write_bytes(b"repeated-cache-value" * 100_000)

    ratio, sampled_bytes = proposal._sampled_deflate_ratio(candidate)

    assert sampled_bytes == candidate.stat().st_size
    assert 0.0 < ratio < 0.1


def test_pickle_proposal_describes_regenerable_family_not_false_exact_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_root = tmp_path / "outputs" / "runtime" / "balance_demand_cache"
    cache_root.mkdir(parents=True)
    candidate = cache_root / "old-key.pkl"
    candidate.write_bytes(b"old cache")
    monkeypatch.setattr(proposal, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(proposal, "SHARED_PICKLE_ROOTS", (cache_root,))

    rows = proposal.collect_shared_pickle_candidates()

    assert len(rows) == 1
    replacement = str(rows[0]["replacement_logical_artifact"])
    assert replacement.endswith(
        "balance_demand_cache/*.parquet_cache (runtime-keyed and regenerated on demand)"
    )
    assert "old-key.parquet_cache" not in replacement
    assert "no live code reads pickle" in str(rows[0]["selection_evidence"])
