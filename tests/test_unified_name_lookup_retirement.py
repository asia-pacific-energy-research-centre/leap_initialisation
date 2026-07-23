"""Phase 3 D3.1: the unified-name-lookup consolidation API is retired.

``load_source_records``/``build_unified_name_lookup`` read a
``matches_original_product_flow_name`` column that no longer exists in the
canonical workbook, so every authored ``leap_display_name`` override was
silently discarded. See
``docs/prompts/phase_3_canonical_mapping_migration_execution.md`` D3.1.
``load_active_mapping_sheet`` is unaffected and is the only function kept.
"""
from __future__ import annotations

import inspect

from codebase.functions import unified_name_lookup


def test_retired_names_are_gone() -> None:
    for name in (
        "load_source_records",
        "build_unified_name_lookup",
        "_is_genuine_override",
        "resolve_name",
        "invalidate_cache",
        "_get_lookup",
        "_derive_name",
        "_LOOKUP_CACHE",
    ):
        assert not hasattr(unified_name_lookup, name), f"{name} should have been retired"


def test_load_active_mapping_sheet_still_serves_its_only_live_caller() -> None:
    """aggregated_demand_workflow.py:41 imports this function - it must survive."""
    assert callable(unified_name_lookup.load_active_mapping_sheet)
    signature = inspect.signature(unified_name_lookup.load_active_mapping_sheet)
    assert list(signature.parameters) == ["sheet_name", "workbook_path"]


def test_load_active_mapping_sheet_still_resolves_a_real_canonical_sheet() -> None:
    frame = unified_name_lookup.load_active_mapping_sheet("leap_display_names")
    assert not frame.empty
    assert {"code_type", "code", "leap_display_name"}.issubset(frame.columns)


def test_load_active_mapping_sheet_still_rejects_an_unsupported_sheet_name() -> None:
    try:
        unified_name_lookup.load_active_mapping_sheet("not_a_real_sheet")
    except ValueError as exc:
        assert "not_a_real_sheet" in str(exc)
    else:
        raise AssertionError("expected a ValueError for an unsupported sheet name")
