"""Cross-platform system-resource diagnostics.

Read-only reporting used by the parallel economy runner (and any other
diagnostic caller) to record what machine a run executed on and how much
memory it actually used. A worker-count decision measured on one machine is
not automatically safe on another - recording both the machine's specs and
the measured memory cost lets that decision be sanity-checked (or re-derived)
elsewhere rather than assumed to transfer.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class SystemResourceSnapshot:
    """A point-in-time read of this machine's CPU/RAM capacity."""

    hostname: str
    platform: str
    logical_cpu_count: int
    physical_cpu_count: int | None
    total_ram_bytes: int
    available_ram_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "hostname": self.hostname,
            "platform": self.platform,
            "logical_cpu_count": self.logical_cpu_count,
            "physical_cpu_count": self.physical_cpu_count,
            "total_ram_bytes": self.total_ram_bytes,
            "available_ram_bytes": self.available_ram_bytes,
            "total_ram_gb": round(self.total_ram_bytes / (1024 ** 3), 2),
            "available_ram_gb": round(self.available_ram_bytes / (1024 ** 3), 2),
        }


def get_system_resource_snapshot() -> SystemResourceSnapshot:
    """Return this machine's current CPU count and RAM (total/available)."""
    vm = psutil.virtual_memory()
    return SystemResourceSnapshot(
        hostname=platform.node(),
        platform=platform.platform(),
        logical_cpu_count=psutil.cpu_count(logical=True) or 0,
        physical_cpu_count=psutil.cpu_count(logical=False),
        total_ram_bytes=int(vm.total),
        available_ram_bytes=int(vm.available),
    )


def process_rss_bytes(pid: int) -> int | None:
    """Return a process's current resident memory (Working Set on Windows), or None if gone."""
    try:
        return int(psutil.Process(pid).memory_info().rss)
    except psutil.NoSuchProcess:
        return None
