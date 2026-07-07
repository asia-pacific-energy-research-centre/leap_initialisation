# Balance-demand conservation check

## What this check answers (one question, both modes)

*"Do the demand totals this repository produces match the ESTO + 9th Outlook
totals we are trying to build them to match?"*

It compares two **independently-derived** sides:

- **Reference / target** — raw pre-mapping ESTO base-year and 9th Outlook
  projection demand (`build_raw_demand_conservation_reference`). This is the
  thing we are trying to match.
- **Actual / produced** — the demand *this repository builds and hands to LEAP*:
  the aggregated-demand dummy (`build_aggregated_demand_as_dummy`) plus any
  detailed sector rows the workflow itself generates.

A mismatch here is *our* bug — a dropped row, a bad mapping, a double count —
and it should be ~zero. That is what "conservation" means.

### This check does NOT involve the LEAP balance readback

Reading demand back from the LEAP balance export answers a *different* question
("did LEAP produce the balance we expected?"), whose answer is **not** expected
to be zero — rebalancing is the whole point of reconciliation. That question is
covered by the convergence metrics and the dashboard, and it must never be
folded into this check. Accordingly, the actual side is **never** sourced from
`load_balance_demand_inputs` / the LEAP-derived `sector_demand_table`.

### Both modes are identical

`baseline_seed` and `results_update` build the conservation inputs the same way.
The produced-demand side comes from `build_aggregated_demand_as_dummy`, which is
computed from ESTO/9th source data and the canonical mappings and is independent
of LEAP. Any remaining mode difference is a *scope* difference expressed through
the shared `conservation_exclusions` set (see below), not a difference in which
dataset the actual side comes from.

## Comparison surface

The comparison unit is:

`economy + scenario + sector_context + esto_product + year`

`reference_total` sums the raw ESTO/9th rows in that unit; `resolved_total` sums
the produced-demand rows in the same unit. The headline diagnostic
(`build_balance_demand_conservation_diagnostics`) reports `resolved − reference`
with the configured `tolerance_pj` and a `status` / `is_mismatch` verdict. **This
totals diagnostic is the pass/fail signal.**

- Subtotal rows are removed by the source workflows, not inferred here, so the
  check stays independent of the mapping/subtotal rules it verifies.
- ESTO product codes that structurally have child codes are also excluded from
  the base-year reference when the source incorrectly marks them
  `is_subtotal=False`. The lineage records these as
  `mis_flagged_parent_subtotal`; this prevents parent-plus-child double counting
  without changing produced demand. The inferred parents can be cross-checked
  against `leap_mappings/results/tree_structure/esto_tree.csv` and
  `common_esto_validation_totals.csv`.
- The same deliberate sector exclusions are applied to **both** sides before
  comparison (see next section).
- An *empty* comparison is treated as a **failure** (`status = failed_empty`),
  never a silent pass.

### Shared exclusions ("already modelled" sectors)

Sectors already represented as active detailed demand branches are excluded from
the aggregated-demand placeholder via
`resolve_effective_aggregated_demand_exclusions`
(→ `resolve_active_branch_excluded_sectors`, keyed off
`DETAILED_DEMAND_BRANCHES_ACTIVE` / `AGGREGATED_DEMAND_EXCLUDED_SECTORS`). The
resulting `conservation_exclusions` list is passed identically to
`build_raw_demand_conservation_reference` (reference side) and
`build_aggregated_demand_as_dummy` (produced side), so both sides drop the same
sectors and excluded sectors never surface as spurious mismatches.
`tests/test_balance_demand_conservation.py::test_reference_and_produced_demand_apply_identical_exclusions`
proves the two sides drop the same sector and still reconcile.

## Drill-down outputs (inspectable, not pass/fail)

Two support CSVs are written beside the totals diagnostic:

- `..._balance_demand_conservation_breakdown.csv` — explains each total
  difference. `source_to_expected_mapping` shows energy lost or gained while
  mapping raw demand to produced demand (the conservation gap);
  `expected_mapping_to_actual_resolved` decomposes the produced total across
  `esto_product`. Summing the `difference` column for one economy/scenario/year
  reproduces the totals-diagnostic difference for that group.
- `..._balance_demand_conservation_lineage.csv` — the underlying rows in labelled
  stages: `original_source`, `expected_mapped`, `actual_resolved`, plus
  `source_scope` records for included/excluded ESTO or 9th rows. The
  `actual_resolved` stage is labelled as **produced demand**
  (`source_system = PRODUCED_DEMAND`), not a LEAP readback.

The workflow does not retain a row-by-row link from every raw source row through
allocation to its produced row, so the lineage says
`mapped_but_source_link_not_retained` rather than inventing that link. Where one
source fans out to many products with no retained allocation share, the edge is
listed one-sided rather than fabricated (honest "Option A" fan-out handling,
matching `leap_mappings`).

## Compressed synthetic year

The compressed results-update preflight fabricates a signed-sum synthetic
`BASE_YEAR + 1`. When `FINAL_YEAR == BASE_YEAR + 1`, that year is flagged in the
outputs with `year_type = compressed_projection` (real years are
`year_type = actual`) so a synthetic total is never read as a real annual
balance.

## Shared conventions with `leap_mappings`

`leap_mappings` already built the same *"compare two independently-derived totals
and explain the gap without fabricating allocation"* pattern one layer upstream
(`reconcile_anchor_validation.py`). This check harmonizes toward its conventions
so a reviewer moving between the two repos reads one consistent method. See
[`leap_mappings/docs/mappings_system.md`](../../leap_mappings/docs/mappings_system.md).

| Concern | Convention here |
| --- | --- |
| Two independent sides | Reference (raw ESTO/9th) vs produced demand — read from different sources, so the check is not a tautology. |
| Status vocabulary | `match` / `value_mismatch` / `missing_resolved` / `unexpected_resolved`, plus a `reason`; an empty comparison is `failed_empty` (never a silent pass). |
| Deterministic IDs + schema version | Content-derived `_deterministic_row_ids`; every output carries `schema_version = BREAKDOWN_SCHEMA_VERSION` so schema changes are visible and IDs stay stable across runs. |
| No-allocation fan-out | Unretained fan-out edges are listed one-sided, not split by a fabricated share. |
| Value-quality glossary | `exact` (`exact_direct` / `exact_aggregated`, no split needed) · `allocated` (explicit proportional share) · `estimated` (equal-split fallback) · `excluded` (deliberately out of scope) · `untraceable` (present but source link not retained). |

The two codebases are **not** merged into shared code — they map different
vocabularies (source→ESTO in mappings; source→produced-demand in
initialisation). The goal is matching conventions and output semantics, not
shared implementation.

For any LEAP-side terminology or behaviour that is not obvious from the
workflow code itself, use the local manual clone at
`C:\Users\Work\github\LEAP_manual` as the tie-breaker reference. The most
useful sections are `08 - Transformation`, `10 - Resources`, `18 - Expressions`,
and `21.1 - API`.

## Implementation

- `codebase/functions/balance_demand_conservation.py` — builder functions. They
  accept prepared tables rather than re-reading mapping inputs, so the diagnostic
  does not depend on the rules it is checking.
- `codebase/functions/supply_results_saver.py` — wires the produced-demand actual
  side, the shared exclusions, and the compressed-year flag, then writes the
  three CSVs.
- `tests/test_balance_demand_conservation.py` — proves the actual side is built
  from produced demand (not a LEAP balance input), that conservation holds on a
  controlled fixture, that an injected leak is caught and localized by the
  breakdown, and the exclusion/year-type/empty/schema conventions above.
