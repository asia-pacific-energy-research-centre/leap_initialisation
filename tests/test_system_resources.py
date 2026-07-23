"""Tests for the system-resource diagnostics used by the parallel economy runner."""
from __future__ import annotations

import os

from codebase.utilities import system_resources as sysres


def test_get_system_resource_snapshot_reports_plausible_values() -> None:
    snapshot = sysres.get_system_resource_snapshot()
    assert snapshot.logical_cpu_count > 0
    assert snapshot.total_ram_bytes > 0
    assert 0 <= snapshot.available_ram_bytes <= snapshot.total_ram_bytes


def test_snapshot_to_dict_includes_gb_conversions() -> None:
    snapshot = sysres.get_system_resource_snapshot()
    payload = snapshot.to_dict()
    assert payload["total_ram_gb"] == round(snapshot.total_ram_bytes / (1024 ** 3), 2)
    assert payload["available_ram_gb"] == round(snapshot.available_ram_bytes / (1024 ** 3), 2)
    assert payload["logical_cpu_count"] == snapshot.logical_cpu_count


def test_process_rss_bytes_returns_positive_value_for_current_process() -> None:
    rss = sysres.process_rss_bytes(os.getpid())
    assert rss is not None
    assert rss > 0


def test_process_rss_bytes_returns_none_for_a_dead_pid() -> None:
    # A PID that is astronomically unlikely to exist on any real system.
    assert sysres.process_rss_bytes(2**31 - 1) is None
