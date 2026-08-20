"""New ESTO vintage data preparation.

When a fresh ESTO source extract arrives (e.g. a new economy/year vintage
such as ``12NZ_2026.csv``), three things are typically wrong before it can be
used in the baseline seed process:

0. Flow/product labels drift — the same ESTO code arrives under a different
   name (a typo, stray whitespace, or an outright wrong word). Much of the
   codebase matches these labels by exact string, so a drifted label drops
   the rows silently instead of erroring. See ``CANONICAL_FLOW_LABELS``.
1. ``is_subtotal`` — the extract usually has no subtotal flag at all.
2. A handful of structurally-required rows that recent ESTO vintages split
   out but a raw extract sometimes omits:
   - ``16.01.99 Commercial and public services unallocated`` = ``16.01
     Commercial and public services`` minus ``16.01.01 Datacentres`` (or the
     full parent value when no Datacentres row exists for that economy).
   - ``09.06.02.01 Liquefaction`` / ``09.06.02.02 Regasification``, split
     from the combined ``09.06.02 Liquefaction/regasification plants`` flow.

``prepare_new_esto_data`` runs both steps and returns one clean, fully
labelled table. This module is self-contained (no runtime dependency on the
sibling ``leap_mappings`` repo) so it can run wherever the ESTO extract
lands.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

SIMPLE_ESTO_CODE_PATTERN = re.compile(r"\d+(?:\.\d+)*")
REQUIRED_ESTO_COLUMNS = ("economy", "flows", "products")

COMPLETION_CONFIG = {
    "parent_flow": "16.01 Commercial and public services",
    "datacentre_flow": "16.01.01 Datacentres",
    "completion_flow": "16.01.99 Commercial and public services unallocated",
    # Reviewed new ESTO product with no parent-minus-child arithmetic to
    # derive from (16.01 has no Hydrogen child yet for most economies) but
    # already rolled out as an always-zero placeholder across every economy
    # in the current APEC vintage — kept structurally present here too.
    "always_required_products": ["16.12 Hydrogen"],
}

# Reviewed canonical labels, keyed by ESTO code. A fresh extract sometimes
# reuses a code under a different name; downstream code matches many of these
# labels by exact string (e.g. `TRANSFER_FLOW_CODES` in transfers_workflow.py),
# so an unrepaired rename drops the rows silently rather than erroring.
#
# EVERY repair is listed here explicitly, including whitespace-only ones. There
# is deliberately no general "collapse the spacing" rule: a silent normalisation
# is exactly the kind of unreviewed edit to source data this table exists to
# prevent. If a new vintage arrives with a drifted label and no entry here,
# `normalise_esto_labels` raises rather than guessing.
#
# Target spelling is the one this repository's ESTO data tables and mapping
# sheets already use (the 2024/2025 aggregates), which is not always the one in
# `all_products_and_flows.ESTO_PRODUCT_LIST` — that list carries two LEAP-side
# spellings (`15.04 Black liqour`, `07.15 Paraffin  waxes`) documented in
# `configuration/known_leap_label_exceptions.py`. Entries for those two codes
# are therefore expected to differ from the canonical list, and are what stops
# the divergence check firing on them.
#
# Only add an entry after confirming the code's *meaning* is unchanged and the
# extract's label is wrong. A genuine new flow deserves a new code, not a
# rename entry here.
CANONICAL_FLOW_LABELS = {
    # 2026 extract renamed a transfers subflow to a transformation one. The
    # code is unambiguously a transfer; the name is not. Six economies keep
    # their whole base-year transfer mass under this code.
    "08.99": "08.99 Transfers nonspecified",
    # 2026 extract typo: "Transmision".
    "10.02": "10.02 Transmission and distribution losses",
}

CANONICAL_PRODUCT_LABELS = {
    # 2026 extract doubles the space after the slash.
    "06.04": "06.04 Additives/ oxygenates",
    # 2026 extract (and ESTO_PRODUCT_LIST) double the space before "waxes".
    "07.15": "07.15 Paraffin waxes",
    # 2026 extract (and ESTO_PRODUCT_LIST) use the typo "Black liqour". The
    # mapping sheets use "Black liquor"; see known_leap_label_exceptions.py.
    "15.04": "15.04 Black liquor",
}

LNG_SPLIT_CONFIG = {
    "source_flow_prefix": "09.06.02",
    "liquefaction_flow": "09.06.02.01 Liquefaction",
    "regasification_flow": "09.06.02.02 Regasification",
    "ng_product_prefix": "08.01",
    "lng_product_prefix": "08.02",
    # Reviewed products for the split flows. Always ensured (at zero when no
    # activity is found) for any economy that has a 09.06.02 parent row at
    # all, so downstream mapping/rollup tooling always has these rows to
    # reference even for economies with no LNG trade (e.g. New Zealand).
    "always_required_products": [
        "07.03 Naphtha",
        "07.09 LPG",
        "08.01 Natural gas",
        "08.02 LNG",
    ],
}

# Ninth (9th Edition Outlook projection table, e.g.
# ``data/merged_file_energy_ALL_20251106.csv``) carries its own signed NG/LNG
# data for the 09.06.02 sub-sector, independently of how ESTO records it —
# confirmed to hold real, sign-consistent historical values (2015-2024) for
# economies where ESTO's own 08.02 LNG code is silent (e.g. Canada, Indonesia,
# Malaysia). Preferred over the qualitative LNG_TRADE_DIRECTION guess below
# whenever it has signal for that economy-year.
NINTH_LNG_CONFIG = {
    "sub2sector": "09_06_02_liquefaction_regasification_plants",
    "ng_subfuel": "08_01_natural_gas",
    "lng_subfuel": "08_02_lng",
    "scenario": "reference",
}

# DRAFT — qualitative LNG trade direction by economy. Used only as a fallback
# when the 08.02 LNG product code has no signal at all for an economy (some
# economies record LNG trade entirely under 08.01 Natural gas, so the
# sign-based split below cannot tell liquefaction from regasification).
# Never overrides real NG/LNG-coded ESTO data. Economies genuinely trading in
# both directions (USA, Indonesia, Malaysia) are marked "both" rather than
# guessing a single side; "both", None, and unlisted economies all keep the
# 50/50 default. Needs a human pass before relying on it for a real run.
LNG_TRADE_DIRECTION = {
    "01AUS": "exporter",
    "02BD": "exporter",
    "03CDA": "importer",  # Saint John/Canaport terminal since 2009 (~0.2 Mt in 2023)
    "04CHL": "importer",
    "05PRC": "importer",
    "06HKC": "importer",
    "07INA": "both",       # ~4.2 Mt imported, ~15.6 Mt exported in 2023
    "08JPN": "importer",
    "09ROK": "importer",
    "10MAS": "both",       # ~2.6 Mt imported, ~26.8 Mt exported in 2023
    "11MEX": "importer",
    "12NZ": None,        # no LNG facilities; split rows are zero regardless
    "13PNG": "exporter",
    "14PE": "exporter",
    "15PHL": "importer",
    "16RUS": "exporter",
    "17SGP": "importer",
    "18CT": "importer",
    "19THA": "importer",
    "20USA": "both",
    "21VN": "importer",
}


# --------------------------------------------------------------------------
# Shared label helpers
# --------------------------------------------------------------------------
def _normalise_text(value: object) -> str:
    """Strip and collapse whitespace for comparisons."""
    if pd.isna(value):
        return ""
    return " ".join(str(value).split())


def _normalise_economy(value: object) -> str:
    """Match compact ESTO and underscored Ninth-style economy codes."""
    return _normalise_text(value).replace("_", "")


def extract_simple_esto_code(label: object) -> str:
    """Return one dot-notation ESTO code, ignoring the descriptive text.

    Matching on the code rather than the full label makes lookups immune to
    label noise (double spaces, typos, minor rewordings) between vintages.
    """
    text = _normalise_text(label)
    if not text:
        return ""
    code = text.split(" ", 1)[0]
    return code if SIMPLE_ESTO_CODE_PATTERN.fullmatch(code) else ""


def _year_columns(df: pd.DataFrame) -> list[str]:
    return [column for column in df.columns if str(column).isdigit()]


def _require_esto_columns(df: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_ESTO_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"ESTO data is missing required columns: {missing}")


# --------------------------------------------------------------------------
# Step 0 — canonical flow/product labels
# --------------------------------------------------------------------------
def _canonical_vocabulary() -> dict[str, dict[str, str]]:
    """Return ``{column: {code: expected label}}`` for the maintained vocabulary.

    `all_products_and_flows` is the repository's maintained ESTO vocabulary. It
    agrees exactly with the 2024/2025 production tables on every code except the
    two spellings carried by `CANONICAL_PRODUCT_LABELS`, which override it.
    """
    from codebase.configuration.all_products_and_flows import (
        ESTO_PRODUCT_LIST,
        ESTO_SECTORS,
    )

    vocabulary: dict[str, dict[str, str]] = {}
    for column, labels, overrides in (
        ("flows", ESTO_SECTORS, CANONICAL_FLOW_LABELS),
        ("products", ESTO_PRODUCT_LIST, CANONICAL_PRODUCT_LABELS),
    ):
        expected = {}
        for label in labels:
            code = extract_simple_esto_code(label)
            if code:
                expected[code] = str(label).strip()
        expected.update(overrides)
        vocabulary[column] = expected
    return vocabulary


def normalise_esto_labels(
    esto_df: pd.DataFrame,
    reference_dfs: list[pd.DataFrame] | None = None,
    strict: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """Return ``esto_df`` with canonical ``flows``/``products`` labels.

    Every repair is an explicit entry in ``CANONICAL_FLOW_LABELS`` /
    ``CANONICAL_PRODUCT_LABELS``, keyed by ESTO code — including whitespace-only
    ones. There is no general normalisation rule, so nothing is rewritten
    without a reviewed decision behind it.

    A label that differs from the maintained vocabulary and has no entry raises
    ``UnreviewedEstoLabelError`` (set ``strict=False`` to collect instead). That
    is the signal that a new vintage has changed something: confirm the meaning
    is unchanged, then add an entry.

    A code absent from the vocabulary entirely is reported but does not raise —
    ESTO adds codes between issues, and the 2024/2025 tables already carry ten
    the vocabulary has not caught up with.
    """
    _require_esto_columns(esto_df)
    working = esto_df.copy()
    renames: list[dict] = []

    for column, canonical in (
        ("flows", CANONICAL_FLOW_LABELS),
        ("products", CANONICAL_PRODUCT_LABELS),
    ):
        original = working[column].astype(str)
        codes = original.map(extract_simple_esto_code)
        resolved = pd.Series(
            [canonical.get(code, label) for code, label in zip(codes, original)],
            index=working.index,
        )
        changed = resolved.ne(original)
        for before, after in (
            pd.DataFrame({"before": original[changed], "after": resolved[changed]})
            .drop_duplicates()
            .itertuples(index=False)
        ):
            renames.append({"column": column, "before": before, "after": after})
        working[column] = resolved

    divergences, unknown_codes = _check_labels_against_vocabulary(working)
    if divergences and strict:
        raise UnreviewedEstoLabelError(divergences)

    summary = {
        "label_renames": renames,
        "label_renames_applied": int(len(renames)),
        "unreviewed_label_divergences": divergences,
        "codes_absent_from_vocabulary": unknown_codes,
    }
    return working, summary


class UnreviewedEstoLabelError(ValueError):
    """A vintage uses an unreviewed label for a known ESTO code."""

    def __init__(self, divergences: list[dict]) -> None:
        self.divergences = divergences
        detail = "\n".join(
            f"  {item['column']} {item['code']}: vintage has {item['vintage_label']!r}, "
            f"expected {item['expected_label']!r}"
            for item in divergences
        )
        super().__init__(
            f"{len(divergences)} ESTO label(s) differ from the maintained vocabulary "
            f"with no reviewed entry:\n{detail}\n"
            "Confirm the code's meaning is unchanged, then add it to "
            "CANONICAL_FLOW_LABELS / CANONICAL_PRODUCT_LABELS in "
            "prepare_new_esto_data.py. Do not normalise it silently."
        )


def _check_labels_against_vocabulary(
    esto_df: pd.DataFrame,
) -> tuple[list[dict], list[dict]]:
    """Return (divergences, codes absent from the vocabulary)."""
    vocabulary = _canonical_vocabulary()
    divergences: list[dict] = []
    unknown: list[dict] = []
    for column in ("flows", "products"):
        if column not in esto_df.columns:
            continue
        expected_by_code = vocabulary[column]
        for label in sorted({str(value).strip() for value in esto_df[column].unique()}):
            code = extract_simple_esto_code(label)
            if not code:
                continue
            expected = expected_by_code.get(code)
            if expected is None:
                unknown.append({"column": column, "code": code, "vintage_label": label})
            elif label != expected:
                divergences.append({
                    "column": column,
                    "code": code,
                    "vintage_label": label,
                    "expected_label": expected,
                })
    return divergences, unknown


# --------------------------------------------------------------------------
# Step 1 — is_subtotal labelling
# --------------------------------------------------------------------------
def _code_subtotal_lookup(reference_df: pd.DataFrame) -> dict[tuple[str, str], bool]:
    """Build a (flow_code, product_code) -> is_subtotal map from a reference
    ESTO vintage that already carries a reliable ``is_subtotal`` column.

    Keying on codes rather than raw labels means the lookup still resolves
    correctly even when a flow's descriptive text has been renamed, typo'd,
    or re-spaced between vintages (verified 1:1 consistent, zero conflicting
    (flow_code, product_code) groups, across a full APEC economy's data).
    """
    working = reference_df.copy()
    working["_fc"] = working["flows"].map(extract_simple_esto_code)
    working["_pc"] = working["products"].map(extract_simple_esto_code)
    working = working[working["_fc"].ne("") & working["_pc"].ne("")]
    working["_is_subtotal"] = working["is_subtotal"].map(
        lambda value: str(value).strip().lower() in {"1", "true", "t", "yes", "y"}
    )
    grouped = working.groupby(["_fc", "_pc"])["_is_subtotal"].agg(lambda s: s.mode().iloc[0])
    return grouped.to_dict()


def _parent_product_codes_by_flow(df: pd.DataFrame) -> dict[tuple[str, str], bool]:
    """Fallback rule: a product is a subtotal within a flow if some other
    product under that same flow has it as a dot-notation prefix.

    Only used for (flow_code, product_code) pairs absent from every
    reference vintage (e.g. a flow that is genuinely new this vintage).
    """
    working = df.copy()
    working["_fc"] = working["flows"].map(extract_simple_esto_code)
    working["_pc"] = working["products"].map(extract_simple_esto_code)
    result: dict[tuple[str, str], bool] = {}
    for flow_code, group in working.groupby("_fc"):
        codes = set(group["_pc"]) - {""}
        parents = {code for code in codes if any(other != code and other.startswith(code + ".") for other in codes)}
        for code in codes:
            result[(flow_code, code)] = code in parents
    return result


def label_esto_subtotals(
    esto_df: pd.DataFrame,
    reference_dfs: list[pd.DataFrame] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Return a copy of ``esto_df`` with ``is_subtotal`` filled for every row.

    Resolution order per row:
      1. Exact (flow_code, product_code) match against each reference
         vintage in ``reference_dfs``, first non-empty list wins.
      2. Product-hierarchy fallback within the row's own flow (parent
         products among the codes already present in ``esto_df``).
      3. ``False`` as a last resort, with the row flagged in the summary for
         manual review.
    """
    _require_esto_columns(esto_df)
    out = esto_df.copy()
    out["_fc"] = out["flows"].map(extract_simple_esto_code)
    out["_pc"] = out["products"].map(extract_simple_esto_code)

    lookups = [_code_subtotal_lookup(reference) for reference in (reference_dfs or [])]
    fallback = _parent_product_codes_by_flow(out)

    resolved: list[bool] = []
    sources: list[str] = []
    for _, row in out.iterrows():
        key = (row["_fc"], row["_pc"])
        value = None
        source = ""
        for index, lookup in enumerate(lookups):
            if key in lookup:
                value = lookup[key]
                source = f"reference_{index}"
                break
        if value is None and key in fallback:
            value = fallback[key]
            source = "product_hierarchy_fallback"
        if value is None:
            value = False
            source = "default_false"
        resolved.append(bool(value))
        sources.append(source)

    out["is_subtotal"] = resolved
    out["_is_subtotal_source"] = sources
    summary = {
        "total_rows": len(out),
        "matched_by_reference": int(sum(s.startswith("reference_") for s in sources)),
        "matched_by_fallback": int(sum(s == "product_hierarchy_fallback" for s in sources)),
        "defaulted_false": int(sum(s == "default_false" for s in sources)),
        "unresolved_rows": out.loc[[s == "default_false" for s in sources], ["flows", "products"]].drop_duplicates(),
    }
    out = out.drop(columns=["_fc", "_pc", "_is_subtotal_source"])
    return out, summary


# --------------------------------------------------------------------------
# Step 2a — 16.01.99 structural completion
# --------------------------------------------------------------------------
def build_commercial_services_unallocated_rows(
    esto_df: pd.DataFrame,
    eligible_product_codes: set[str] | None = None,
) -> pd.DataFrame:
    """Return missing ``16.01.99`` rows as ``16.01`` minus ``16.01.01``.

    Only rows not already present in ``esto_df`` are returned, one per
    economy/product under the ``16.01`` parent flow. Economies with no
    Datacentres row (the common case) get the full parent value.

    ``eligible_product_codes`` optionally limits completion to the products
    expected by a prior ESTO vintage. This matters because newer raw extracts
    can contain more products under ``16.01`` than the established mapped
    target set; inserting all of them would silently expand the source schema.
    """
    _require_esto_columns(esto_df)
    year_cols = _year_columns(esto_df)
    source_columns = list(esto_df.columns)
    cfg = COMPLETION_CONFIG
    parent_code = extract_simple_esto_code(cfg["parent_flow"])
    datacentre_code = extract_simple_esto_code(cfg["datacentre_flow"])
    completion_code = extract_simple_esto_code(cfg["completion_flow"])

    working = esto_df.copy()
    working["_economy_key"] = working["economy"].map(_normalise_economy)
    working["_flow_code"] = working["flows"].map(extract_simple_esto_code)
    working["_product_code"] = working["products"].map(extract_simple_esto_code)
    for column in year_cols:
        working[column] = pd.to_numeric(working[column], errors="coerce").fillna(0.0)

    parent = working[working["_flow_code"].eq(parent_code)]
    if eligible_product_codes is not None:
        parent = parent[parent["_product_code"].isin(eligible_product_codes)]
    datacentres = working[working["_flow_code"].eq(datacentre_code)]
    existing_completion = working[working["_flow_code"].eq(completion_code)]
    key_columns = ["_economy_key", "_product_code"]

    datacentre_groups = {key: group for key, group in datacentres.groupby(key_columns, dropna=False)}
    existing_keys = set(map(tuple, existing_completion[key_columns].itertuples(index=False, name=None)))

    insert_rows: list[dict[str, object]] = []
    for key, parent_group in parent.groupby(key_columns, dropna=False):
        if key in existing_keys:
            continue
        parent_row = parent_group.iloc[0]
        datacentre_group = datacentre_groups.get(key)
        datacentre_values = (
            datacentre_group[year_cols].sum() if datacentre_group is not None else pd.Series(0.0, index=year_cols)
        )
        remainder = parent_row[year_cols].astype(float) - datacentre_values.astype(float)

        output_row = {column: parent_row.get(column, pd.NA) for column in source_columns}
        output_row["flows"] = cfg["completion_flow"]
        if "is_subtotal" in source_columns:
            output_row["is_subtotal"] = False
        for column in year_cols:
            output_row[column] = float(remainder[column])
        insert_rows.append(output_row)
        existing_keys.add(key)

    # Always-required products (e.g. 16.12 Hydrogen) have no parent row to
    # derive from for economies that don't track them yet — add them at zero
    # so the row structurally exists, matching the current all-zero rollout.
    template_by_economy = working.groupby("_economy_key").first()
    for product_label in cfg.get("always_required_products", []):
        product_code = extract_simple_esto_code(product_label)
        if eligible_product_codes is not None and product_code not in eligible_product_codes:
            continue
        for economy_key, template_row in template_by_economy.iterrows():
            key = (economy_key, product_code)
            if key in existing_keys:
                continue
            output_row = {column: pd.NA for column in source_columns}
            output_row["economy"] = template_row.get("economy", economy_key)
            output_row["flows"] = cfg["completion_flow"]
            output_row["products"] = product_label
            if "is_subtotal" in source_columns:
                output_row["is_subtotal"] = False
            for column in year_cols:
                output_row[column] = 0.0
            insert_rows.append(output_row)
            existing_keys.add(key)

    return pd.DataFrame(insert_rows, columns=source_columns)


# --------------------------------------------------------------------------
# Step 2b — LNG liquefaction / regasification split
# --------------------------------------------------------------------------
def _qualitative_lng_shares(economy: str) -> tuple[float, float] | None:
    """Return (liq_share, regas_share) from the qualitative table, or None
    when no override applies (unlisted economy, "both", or explicitly
    unresolved) — the caller should keep its existing 50/50 default then.
    """
    direction = LNG_TRADE_DIRECTION.get(_normalise_economy(economy))
    if direction == "exporter":
        return 1.0, 0.0
    if direction == "importer":
        return 0.0, 1.0
    return None


def _lng_direction_masks(
    esto_df: pd.DataFrame, economy: str, year_cols: list[str]
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Classify each year for ``economy`` as liquefaction, regasification, or
    ambiguous, from the sign of natural gas (08.01) vs LNG (08.02) under the
    combined 09.06.02 flow.

    Liquefaction: NG input (< 0), LNG output (> 0).
    Regasification: LNG input (< 0), NG output (> 0).
    Ambiguous: any other year with NG or LNG activity present.
    """
    cfg = LNG_SPLIT_CONFIG
    source_mask = esto_df["economy"].map(_normalise_economy).eq(_normalise_economy(economy)) & esto_df[
        "flows"
    ].map(extract_simple_esto_code).eq(extract_simple_esto_code(cfg["source_flow_prefix"]))
    source_rows = esto_df[source_mask]

    def _product_series(prefix: str) -> pd.Series:
        codes = source_rows["products"].map(extract_simple_esto_code)
        is_leaf = ~codes.apply(lambda c: c != prefix and any(other.startswith(c + ".") for other in codes if other != c))
        rows = source_rows[codes.str.startswith(prefix, na=False) & is_leaf]
        if rows.empty:
            return pd.Series(0.0, index=year_cols, dtype=float)
        return rows[year_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum()

    ng = _product_series(cfg["ng_product_prefix"])
    lng = _product_series(cfg["lng_product_prefix"])

    liq_mask = (ng < 0) & (lng > 0)
    regas_mask = (ng > 0) & (lng < 0)
    activity_mask = ng.ne(0) | lng.ne(0)
    ambiguous_mask = activity_mask & ~liq_mask & ~regas_mask
    return liq_mask, regas_mask, ambiguous_mask


def _ninth_lng_shares(
    ninth_df: pd.DataFrame, economy: str, year_cols: list[str]
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (liq_share, regas_share, has_signal) from Ninth's own signed
    NG/LNG data for the 09.06.02 sub-sector, per year.

    Ninth carries independently-recorded NG/LNG signal for this sub-sector —
    confirmed to hold real, sign-consistent historical values for economies
    where ESTO's own LNG product code is silent because the economy records
    LNG trade entirely under Natural gas. ``has_signal`` marks the years
    Ninth actually resolved; callers should only trust shares where True.
    """
    cfg = NINTH_LNG_CONFIG
    ninth_year_cols = [c for c in year_cols if c in ninth_df.columns]
    zero = pd.Series(0.0, index=year_cols, dtype=float)
    no_signal = pd.Series(False, index=year_cols, dtype=bool)
    if not ninth_year_cols:
        return zero.copy(), zero.copy(), no_signal

    eco_mask = ninth_df["economy"].map(_normalise_economy).eq(_normalise_economy(economy))
    sector_mask = ninth_df["sub2sectors"].astype(str).map(_normalise_text).eq(cfg["sub2sector"])
    scenario_mask = (
        ninth_df["scenarios"].astype(str).str.lower().eq(cfg["scenario"])
        if "scenarios" in ninth_df.columns
        else pd.Series(True, index=ninth_df.index)
    )
    base_mask = eco_mask & sector_mask & scenario_mask

    def _subfuel_series(subfuel: str) -> pd.Series:
        rows = ninth_df[base_mask & ninth_df["subfuels"].astype(str).map(_normalise_text).eq(subfuel)]
        result = zero.copy()
        if rows.empty:
            return result
        summed = rows[ninth_year_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum()
        result[ninth_year_cols] = summed
        return result

    ng = _subfuel_series(cfg["ng_subfuel"])
    lng = _subfuel_series(cfg["lng_subfuel"])

    lng_positive = lng.clip(lower=0.0)
    lng_negative = (-lng).clip(lower=0.0)
    total = lng_positive + lng_negative
    has_signal = total.gt(0)

    liq_share = zero.copy()
    regas_share = zero.copy()
    liq_share[has_signal] = (lng_positive / total)[has_signal]
    regas_share[has_signal] = (lng_negative / total)[has_signal]
    return liq_share, regas_share, has_signal


def _lng_ambiguous_shares(
    esto_df: pd.DataFrame,
    economy: str,
    year_cols: list[str],
    ambiguous_mask: pd.Series,
    ninth_df: pd.DataFrame | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Return (liq_share, regas_share) for ambiguous years only.

    Resolution order per ambiguous year:
      1. The LNG product's own sign/magnitude, where 08.02 LNG has signal.
      2. Ninth's independently-recorded NG/LNG signal for 09.06.02, when
         ``ninth_df`` is given and has data for that economy-year (real
         historical data — preferred over the static table below).
      3. The qualitative per-economy direction (``LNG_TRADE_DIRECTION``).
      4. 0.5/0.5, for anything still unresolved.
    """
    cfg = LNG_SPLIT_CONFIG
    default_liq, default_regas = _qualitative_lng_shares(economy) or (0.5, 0.5)

    source_mask = esto_df["economy"].map(_normalise_economy).eq(_normalise_economy(economy)) & esto_df[
        "flows"
    ].map(extract_simple_esto_code).eq(extract_simple_esto_code(cfg["source_flow_prefix"]))
    lng_rows = esto_df[
        source_mask & esto_df["products"].map(extract_simple_esto_code).str.startswith(cfg["lng_product_prefix"], na=False)
    ]

    liq_share = pd.Series(default_liq, index=year_cols, dtype=float)
    regas_share = pd.Series(default_regas, index=year_cols, dtype=float)

    if ninth_df is not None:
        ninth_liq, ninth_regas, ninth_signal = _ninth_lng_shares(ninth_df, economy, year_cols)
        liq_share[ninth_signal] = ninth_liq[ninth_signal]
        regas_share[ninth_signal] = ninth_regas[ninth_signal]

    if lng_rows.empty:
        return liq_share.where(ambiguous_mask, 0.0), regas_share.where(ambiguous_mask, 0.0)

    lng_numeric = lng_rows[year_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum()
    lng_positive = lng_numeric.clip(lower=0.0)
    lng_negative = (-lng_numeric).clip(lower=0.0)
    total = lng_positive + lng_negative
    esto_has_signal = total.gt(0)

    liq_share[esto_has_signal] = (lng_positive / total)[esto_has_signal]
    regas_share[esto_has_signal] = (lng_negative / total)[esto_has_signal]
    return liq_share.where(ambiguous_mask, 0.0), regas_share.where(ambiguous_mask, 0.0)


def build_lng_split_rows(esto_df: pd.DataFrame, ninth_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return missing 09.06.02.01/.02 rows split from 09.06.02, per economy.

    Economies with a 09.06.02 parent flow but no LNG activity (e.g. New
    Zealand) still get zero-valued rows for the always-required products, so
    downstream tooling always finds these rows; economies with no 09.06.02
    flow at all produce no rows.

    Pass ``ninth_df`` (the Ninth/9th-Edition projection table, e.g.
    ``data/merged_file_energy_ALL_20251106.csv``) to resolve ambiguous years
    from its own signed NG/LNG data before falling back to the qualitative
    ``LNG_TRADE_DIRECTION`` table.
    """
    _require_esto_columns(esto_df)
    year_cols = _year_columns(esto_df)
    cfg = LNG_SPLIT_CONFIG
    source_code = extract_simple_esto_code(cfg["source_flow_prefix"])

    source_rows = esto_df[esto_df["flows"].map(extract_simple_esto_code).eq(source_code)]
    if source_rows.empty:
        return pd.DataFrame(columns=esto_df.columns)

    liq_code = extract_simple_esto_code(cfg["liquefaction_flow"])
    regas_code = extract_simple_esto_code(cfg["regasification_flow"])
    existing_split = esto_df["flows"].map(extract_simple_esto_code).isin([liq_code, regas_code])
    # Keyed by (economy, flow_code, product_code) — liquefaction and
    # regasification are tracked independently, since real data can carry
    # one without the other.
    existing_keys = set(
        map(
            tuple,
            esto_df.loc[existing_split, ["economy", "flows", "products"]]
            .assign(
                economy=lambda d: d["economy"].map(_normalise_economy),
                flows=lambda d: d["flows"].map(extract_simple_esto_code),
                products=lambda d: d["products"].map(extract_simple_esto_code),
            )
            .itertuples(index=False, name=None),
        )
    )

    codes = {code for code in esto_df["products"].map(extract_simple_esto_code) if code}
    parent_codes = {code for code in codes if any(other != code and other.startswith(code + ".") for other in codes)}

    # Restrict split rows to the reviewed product set. The parent 09.06.02
    # flow is sign-classified from its NG/LNG columns only; broadcasting that
    # direction onto unrelated products (coal, electricity, biomass, ...)
    # would insert plausible-looking but meaningless rows if the parent flow
    # ever carries stray data outside NG/LNG/Naphtha/LPG.
    reviewed_product_codes = {
        extract_simple_esto_code(label) for label in cfg.get("always_required_products", [])
    }

    economies = sorted(source_rows["economy"].map(_normalise_text).dropna().unique())
    insert_rows: list[dict[str, object]] = []
    for economy in economies:
        eco_source = source_rows[
            source_rows["economy"].map(_normalise_text).eq(economy)
            & source_rows["products"].map(extract_simple_esto_code).isin(reviewed_product_codes)
        ]
        liq_mask, regas_mask, ambiguous_mask = _lng_direction_masks(esto_df, economy, year_cols)
        liq_share, regas_share = _lng_ambiguous_shares(esto_df, economy, year_cols, ambiguous_mask, ninth_df=ninth_df)
        eco_key = _normalise_economy(economy)

        for _, row in eco_source.iterrows():
            numeric = pd.to_numeric(row[year_cols], errors="coerce").fillna(0.0)
            product_code = extract_simple_esto_code(row.get("products", ""))

            for flow_code, flow_label, mask, share in (
                (liq_code, cfg["liquefaction_flow"], liq_mask, liq_share),
                (regas_code, cfg["regasification_flow"], regas_mask, regas_share),
            ):
                key = (eco_key, flow_code, product_code)
                if key in existing_keys:
                    continue
                values = numeric.copy()
                values[~mask] = 0.0
                values[ambiguous_mask] = numeric[ambiguous_mask] * share[ambiguous_mask]
                out_row = {column: row.get(column, pd.NA) for column in esto_df.columns}
                out_row["flows"] = flow_label
                if "is_subtotal" in esto_df.columns:
                    out_row["is_subtotal"] = product_code in parent_codes
                for column in year_cols:
                    out_row[column] = float(values[column])
                insert_rows.append(out_row)
                existing_keys.add(key)

    # Always-required products (07.03/07.09/08.01/08.02): ensure both split
    # flows exist at zero for any economy with a 09.06.02 parent presence,
    # even where that specific product row is absent from the parent flow
    # (e.g. an economy that never records LPG under 09.06.02 at all).
    template_by_economy = source_rows.groupby(source_rows["economy"].map(_normalise_text)).first()
    for product_label in cfg.get("always_required_products", []):
        product_code = extract_simple_esto_code(product_label)
        for economy, template_row in template_by_economy.iterrows():
            eco_key = _normalise_economy(economy)
            for flow_code, flow_label in ((liq_code, cfg["liquefaction_flow"]), (regas_code, cfg["regasification_flow"])):
                key = (eco_key, flow_code, product_code)
                if key in existing_keys:
                    continue
                out_row = {column: pd.NA for column in esto_df.columns}
                out_row["economy"] = template_row.get("economy", economy)
                out_row["flows"] = flow_label
                out_row["products"] = product_label
                if "is_subtotal" in esto_df.columns:
                    out_row["is_subtotal"] = product_code in parent_codes
                for column in year_cols:
                    out_row[column] = 0.0
                insert_rows.append(out_row)
                existing_keys.add(key)

    return pd.DataFrame(insert_rows, columns=list(esto_df.columns))


def _reference_product_codes(
    reference_dfs: list[pd.DataFrame] | None,
    flow_code: str,
) -> set[str] | None:
    """Return products used by ``flow_code`` in the first reference vintage.

    ``None`` means no reference constrains the output and callers may use
    their full parent-product set. An empty set is preserved as empty so a
    reference that deliberately has no rows does not accidentally broaden
    the generated schema.
    """
    for reference_df in reference_dfs or []:
        if "flows" not in reference_df.columns or "products" not in reference_df.columns:
            continue
        flow_codes = reference_df["flows"].map(extract_simple_esto_code)
        matching = reference_df.loc[flow_codes.eq(flow_code), "products"]
        return {
            code for code in matching.map(extract_simple_esto_code) if code
        }
    return None


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def prepare_new_esto_data(
    esto_df: pd.DataFrame,
    reference_dfs: list[pd.DataFrame] | None = None,
    ninth_df: pd.DataFrame | None = None,
    strict_labels: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """Prepare a freshly-received ESTO vintage for the baseline seed process.

    0. Repair drifted flow/product labels so every later step (and every
       downstream label match) sees canonical names.
    1. Append missing ``16.01.99`` completion rows and ``09.06.02`` LNG split
       rows (computed directly from ``esto_df``'s own data).
    2. Label ``is_subtotal`` for every row (original and newly added),
       resolved against ``reference_dfs`` (prior vintages that already carry
       a reliable ``is_subtotal`` column) with a product-hierarchy fallback.

    Pass ``ninth_df`` to resolve ambiguous LNG-split years from Ninth's own
    signed NG/LNG data before falling back to the qualitative
    ``LNG_TRADE_DIRECTION`` table — see ``build_lng_split_rows``.

    Returns the prepared DataFrame plus a summary dict describing what was
    added and how ``is_subtotal`` was resolved (for manual review).
    """
    _require_esto_columns(esto_df)
    # Step 0 first: the builders below match flows/products by label, so they
    # must see canonical names.
    esto_df, label_summary = normalise_esto_labels(esto_df, reference_dfs, strict=strict_labels)
    completion_product_codes = _reference_product_codes(
        reference_dfs,
        flow_code=extract_simple_esto_code(COMPLETION_CONFIG["completion_flow"]),
    )
    completion_rows = build_commercial_services_unallocated_rows(
        esto_df,
        eligible_product_codes=completion_product_codes,
    )
    lng_rows = build_lng_split_rows(esto_df, ninth_df=ninth_df)

    combined = pd.concat([esto_df, completion_rows, lng_rows], ignore_index=True)
    labelled, subtotal_summary = label_esto_subtotals(combined, reference_dfs)

    year_cols = _year_columns(esto_df)
    leading_cols = ["economy", "flows", "products", "is_subtotal"]
    other_cols = [c for c in labelled.columns if c not in leading_cols and c not in year_cols]
    labelled = labelled[leading_cols + other_cols + year_cols]

    summary = {
        "input_rows": len(esto_df),
        "commercial_services_unallocated_rows_added": len(completion_rows),
        "lng_split_rows_added": len(lng_rows),
        "output_rows": len(labelled),
        **label_summary,
        **subtotal_summary,
    }
    return labelled, summary


def prepare_new_esto_data_from_paths(
    esto_csv_path: Path,
    reference_csv_paths: list[Path],
    output_csv_path: Path | None = None,
    ninth_csv_path: Path | None = None,
) -> dict:
    """CSV-in, CSV-out convenience wrapper around ``prepare_new_esto_data``."""
    esto_df = pd.read_csv(esto_csv_path, dtype=object, low_memory=False)
    reference_dfs = [pd.read_csv(path, dtype=object, low_memory=False) for path in reference_csv_paths]
    ninth_df = pd.read_csv(ninth_csv_path, dtype=object, low_memory=False) if ninth_csv_path else None

    prepared, summary = prepare_new_esto_data(esto_df, reference_dfs, ninth_df=ninth_df)
    prepared["is_subtotal"] = prepared["is_subtotal"].map(lambda v: "TRUE" if bool(v) else "FALSE")

    destination = output_csv_path or esto_csv_path
    prepared.to_csv(destination, index=False)
    summary["output_path"] = str(destination)
    return summary
