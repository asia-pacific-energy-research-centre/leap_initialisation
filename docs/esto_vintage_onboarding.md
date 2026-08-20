# Onboarding a new ESTO vintage

How a freshly-received ESTO extract becomes a usable source table. Run this
whenever `data/new 2026 esto data/` (or the equivalent folder for a later
issue) gains an economy file, or an existing one is reissued.

Implementation:
[`codebase/mapping_tools/prepare_new_esto_data.py`](../codebase/mapping_tools/prepare_new_esto_data.py)
(per-extract preparation) and
[`codebase/mapping_tools/build_apec_2026_preliminary.py`](../codebase/mapping_tools/build_apec_2026_preliminary.py)
(APEC-wide aggregate assembly). Tests:
`tests/test_prepare_new_esto_data.py`, `tests/test_build_apec_2026_preliminary.py`.

## Why this exists

A raw ESTO extract is not shaped like the aggregate tables the pipeline reads
(`data/00APEC_2024_low_with_subtotals.csv` and its successors). Three things
are reliably wrong, and all three fail *quietly* — the pipeline runs, produces
a plausible-looking seed, and silently omits whatever it could not recognise.
That is the reason each step exists, and the reason each one reports what it
did rather than just doing it.

## The three steps

`prepare_new_esto_data()` runs them in order. It is idempotent — rows a source
already carries correctly are left untouched — so re-running on an
already-prepared table is safe.

### Step 0 — canonical flow and product labels

The same ESTO code arrives under a different name between issues. Much of this
repository matches flows and products **by exact label string**, not by code —
for example `TRANSFER_FLOW_CODES` in
[`transfers_workflow.py`](../codebase/transfers_workflow.py). A drifted label
therefore drops every row under it, with no error.

**Every repair is an explicit entry** in `CANONICAL_FLOW_LABELS` /
`CANONICAL_PRODUCT_LABELS`, keyed by ESTO code — including whitespace-only ones.
There is deliberately **no** general "collapse the spacing" rule: a silent
normalisation is exactly the kind of unreviewed edit to source data these tables
exist to prevent. What gets changed is enumerated and reviewable, and the run
prints each `before → after`.

Corrections carried today, all found in the 2026 extract:

| Axis | Code | Extract label | Canonical label |
|---|---|---|---|
| flow | `08.99` | `Transformation nonspecified` | `Transfers nonspecified` |
| flow | `10.02` | `Transmision and distribution losses` | `Transmission and distribution losses` |
| product | `06.04` | `Additives/  oxygenates` | `Additives/ oxygenates` |
| product | `07.15` | `Paraffin  waxes` | `Paraffin waxes` |
| product | `15.04` | `Black liqour` | `Black liquor` |

### What happens to an unreviewed label

A label that differs from the maintained vocabulary with **no entry** raises
`UnreviewedEstoLabelError`, naming the code, the vintage's spelling and the
expected one. That is the intended signal when a new vintage changes something:
confirm the code's meaning is unchanged, then add an entry. Nothing is guessed.

The vocabulary is `ESTO_PRODUCT_LIST` / `ESTO_SECTORS` in
[`all_products_and_flows.py`](../codebase/configuration/all_products_and_flows.py).
It agrees exactly with the 2024/2025 production tables on every code except two,
where it carries the LEAP-side spellings (`15.04 Black liqour`,
`07.15 Paraffin  waxes`) documented in
[`known_leap_label_exceptions.py`](../codebase/configuration/known_leap_label_exceptions.py).
The canonical tables override the vocabulary for those two codes, targeting the
spelling this repository's data tables and mapping sheets actually use — which
is also what stops the check firing on them.

A code **absent from the vocabulary entirely** is reported but does not raise.
ESTO adds codes between issues, and the 2024/2025 tables already carry ten the
list has not caught up with (`09.13*`, `10.01.19`, `16.01.01`, `16.01.99`,
`16.10`–`16.12`). Treating those as errors would fail every run today.

The `08.99` case shows why this is not cosmetic. `08.99` is a **transfers**
subflow; the 2026 extract named it a *transformation* one. Six economies —
including `01_AUS` and `20_USA`, the only two with 9th transfer projections —
carry their entire base-year transfer mass under that code. Left unrepaired,
switching to the 2026 vintage would have silently emptied the transfers module
for `01AUS` (418.61 PJ), `20USA` (13,676.49), `11MEX` (343.81), `12NZ` (35.30),
`04CHL` (132.08) and `08JPN` (73.34).

**To add a correction:** confirm the code's *meaning* is unchanged and the
extract's label is simply wrong, then add the entry. A genuinely new flow
deserves a new code, not a rename entry. Whitespace-only differences never
need an entry.

### Step 1 — `is_subtotal` labelling

Raw extracts usually carry no subtotal flag at all. Every row (original and
newly added) is labelled by matching `(flow code, product code)` against
reference vintages that already have a reliable flag, with a product-hierarchy
fallback. The summary reports how many rows resolved by each route; anything
that defaulted to `False` with no signal from any source is listed for review.

### Step 2 — structurally-required rows

Recent vintages split out rows a raw extract sometimes omits. These are
computed from the extract's own data, never invented:

- `16.01.99 Commercial and public services unallocated` = `16.01` minus
  `16.01.01 Datacentres` (or the full parent where no Datacentres row exists).
- `09.06.02.01 Liquefaction` / `09.06.02.02 Regasification`, split from the
  combined `09.06.02` flow. Direction comes from signed ESTO NG/LNG data where
  present, then the 9th table's own signed values, then a qualitative
  per-economy trade-direction fallback.

## Running it

For the APEC-wide 2026 preliminary aggregate — combines every available
economy extract with the remaining economies backfilled from the 2025 vintage,
and rebuilds from scratch every time:

```bash
python -m codebase.mapping_tools.build_apec_2026_preliminary
```

Read the printed summary rather than assuming success. It reports the label
renames applied (with before → after for each), rows added per structural
step, how `is_subtotal` resolved, and two warnings worth stopping for:
unreviewed label divergences, and `(flow, product)` pairs with no subtotal
signal from any source.

The output is written to
`data/00APEC_2026_low_with_subtotals_PRELIMINARY.csv`, shaped exactly like the
2024/2025 tables so it drops in wherever those are selectable. It stays tagged
`_PRELIMINARY` while the issue is incomplete and some economies are still
carried-forward figures rather than real releases.

For a single extract outside the aggregate, use
`prepare_new_esto_data_from_paths()`.

## Related

- [`initialisation_flow_estimation_methods.md`](initialisation_flow_estimation_methods.md)
  — what the prepared table is then used for.
- [`decision_transfer_projection_fallback_20260820.md`](decision_transfer_projection_fallback_20260820.md)
  — where the `08.99` finding came from, and the one-sided transfer handling
  that shares this source data.
