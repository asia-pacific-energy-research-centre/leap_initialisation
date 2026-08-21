from pathlib import Path

from codebase.utilities import apec_aggregate_sources as sources


def test_resolve_apec_ninth_aggregate_accepts_portable_bundle_location(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    source = data_dir / "merged_file_energy_ALL_20251106.csv"
    bundled_aggregate = data_dir / "9th merged_file_energy_00_APEC_20251106.csv"
    source.touch()
    bundled_aggregate.touch()
    monkeypatch.setattr(sources, "APEC_AGGREGATES_DIR", data_dir / "APEC_aggregates")

    assert sources.resolve_apec_ninth_aggregate(source) == bundled_aggregate
