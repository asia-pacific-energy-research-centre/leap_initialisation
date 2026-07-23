#%%
"""Load a canonical Outlook mapping sheet for backward-compatible callers.

Retired 2026-07-23 (Phase 3 D3.1,
``docs/prompts/phase_3_canonical_mapping_migration_execution.md``): the
former consolidation API (``load_source_records``, ``build_unified_name_lookup``,
``resolve_name``, and the ``_is_genuine_override`` helper it depended on) read
a ``matches_original_product_flow_name`` column that no longer exists in the
canonical workbook, so every row silently read as "not an override" and every
authored ``leap_display_name`` override was discarded in favour of a
mechanically derived name. Repairing the check against the current schema
would mean inventing an override rule no mapping author wrote down, so the
API is retired rather than repaired. ``load_active_mapping_sheet`` is
unaffected - it never depended on that column - and is kept as the sole
surviving export, matching its only live caller
(``aggregated_demand_workflow.py``).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from codebase.mappings.canonical_loaders import (
    CANONICAL_WORKBOOK_PATH,
    load_canonical_sheet,
)


def load_active_mapping_sheet(
    sheet_name: str,
    workbook_path: Path = CANONICAL_WORKBOOK_PATH,
) -> pd.DataFrame:
    """Load an active canonical sheet for backward-compatible callers."""
    required_by_sheet = {
        "leap_combined_esto": (
            "leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"
        ),
        "leap_combined_ninth": (
            "leap_sector_name_full_path", "raw_leap_fuel_name", "ninth_sector", "ninth_fuel"
        ),
        "ninth_pairs_to_esto_pairs": ("ninth_sector", "ninth_fuel", "esto_flow", "esto_product"),
        "leap_display_names": ("code_type", "code", "leap_display_name"),
    }
    required = required_by_sheet.get(sheet_name)
    if required is None:
        raise ValueError(
            f"Unsupported canonical mapping sheet {sheet_name!r}; "
            f"expected one of {sorted(required_by_sheet)}."
        )
    return load_canonical_sheet(sheet_name, required, workbook=workbook_path, dtype=object)
