"""Helpers for writing Excel workbooks safely."""

from __future__ import annotations

import re

MAX_EXCEL_SHEET_NAME_LENGTH = 31
INVALID_SHEET_NAME_CHARS = re.compile(r"[:\\/?*\[\]]")


def safe_excel_sheet_name(sheet_name: object, used_names: set[str] | None = None) -> str:
    """Return an Excel-safe sheet name that respects the 31-character limit."""
    text = "" if sheet_name is None else str(sheet_name).strip()
    text = INVALID_SHEET_NAME_CHARS.sub("_", text)
    if not text:
        text = "Sheet"
    text = text[:MAX_EXCEL_SHEET_NAME_LENGTH]

    if used_names is None:
        return text

    candidate = text
    suffix_index = 1
    while candidate in used_names:
        suffix = f"_{suffix_index}"
        base = text[: MAX_EXCEL_SHEET_NAME_LENGTH - len(suffix)]
        candidate = f"{base}{suffix}"
        suffix_index += 1

    used_names.add(candidate)
    return candidate
