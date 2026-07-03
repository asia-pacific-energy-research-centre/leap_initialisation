"""Known, temporary spelling gaps between the live LEAP model and the mappings.

Each entry means: treat ``leap_label`` (the spelling that appears in the live
LEAP model / its raw full-model export) as an alias of ``mapping_label`` (the
spelling used in ``outlook_mappings_master.xlsx`` — ``leap_combined_ninth`` /
``leap_combined_esto`` — and the rest of this codebase) when an exact-string
join against those sheets or the full-model-export template would otherwise
fail.

This is deliberately *not* a general fuzzy-matching layer. It exists only for
known, reviewed spelling gaps that will eventually be corrected in the LEAP
model itself. Remove an entry once the LEAP model is corrected upstream and the
alias stops firing (watch the ``[INFO] rescued ... via KNOWN_LEAP_LABEL_EXCEPTIONS``
rescue log — once it goes quiet the entry is dead and should be deleted).

Do not expand this dict beyond the reviewed entries without checking first: the
Finn-approved boundary is that this covers documented LEAP-model spelling gaps,
not arbitrary label normalisation.
"""

from __future__ import annotations


# Maps ``leap_label`` (live LEAP model spelling) -> ``mapping_label``
# (outlook_mappings_master / codebase spelling).
KNOWN_LEAP_LABEL_EXCEPTIONS: dict[str, str] = {
    # Top-level Industry fuel. ``leap_combined_ninth``/``leap_combined_esto``
    # spell it "Black liquor"; the live LEAP model, its raw export, and
    # ESTO_PRODUCT_LIST ("15.04 Black liqour") use the typo "Black liqour".
    "Black liqour": "Black liquor",
}


def alias_leap_label(value: str) -> str:
    """Return the mapping-side spelling for a LEAP-side label, if aliased.

    Safe to apply eagerly to a LEAP fuel/sector label before a plain
    string-key join against the mapping sheets: the alias only rewrites keys
    that would not otherwise match (a correctly spelled label is not a key in
    ``KNOWN_LEAP_LABEL_EXCEPTIONS``).
    """
    return KNOWN_LEAP_LABEL_EXCEPTIONS.get(value, value)
