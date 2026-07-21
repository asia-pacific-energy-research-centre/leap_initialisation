# Other loss and own-use proxy - scoped review and implementation brief

## Purpose

`codebase/other_loss_own_use_proxy_workflow.py` creates values for
`Demand\\Other loss and own use` where losses/own-use cannot be represented by
a specific transformation module. It is a modelling proxy: activity source,
fuel intensity, validation strictness, and fallback handling all affect the
seed values.

This brief is linked from `docs/work_queue.md` [15]. It should be reviewed
before any large refactor or rewrite.

## Important current facts

- `PROXY_ACTIVITY_SOURCE_MODE = "esto_ninth"` and
  `PROXY_INTENSITY_MODE = "target_matching_initialisation"` are model choices.
- The reconciliation presets select the first (ESTO/ninth) or second
  (LEAP-balance) activity stage; this is a pass-mode decision, not a wrapper
  default.
- `PROXY_CONFIG` maps individual processes to activity and target data. Treat
  it as the model specification until a reviewed replacement exists.
- The workflow now resolves export keys from the requested economy's template.
  USA fallback remains only for aggregate/no-template cases. This prevents
  cross-economy BranchID borrowing.
- The known `Non specified own uses` issue is a template migration gap: do not
  create missing LEAP IDs in Python or copy them from another economy.

## Discovery deliverables

Create a compact inventory (in this prompt or a companion findings note) with:

1. Every enabled `PROXY_CONFIG` process, its activity numerator/denominator,
   ESTO/ninth source filters, LEAP balance rows, and intended branch target.
2. Every fallback path: no activity, zero throughput, no target fuel, missing
   template branch, missing region, and no LEAP balance export.
3. Output contract: workbooks, diagnostics, strictness switches, and which
   conditions are warnings versus seed-blocking errors.
4. A sample of real-template economies plus one aggregate/preflight case,
   reporting template provenance, region, BranchID coverage, and unresolved
   paths.

## Design decisions required

- Whether the 2,900-line module should be decomposed incrementally or rewritten
  behind an exact workbook-output contract.
- Who owns the proxy process list and fuel mappings: this repository or
  `leap_mappings`. Do not duplicate canonical mappings without an agreed reason.
- Whether target-matching intensity is retained for every process and pass.
- Whether strict consistency issues fail a production run, remain diagnostics,
  or differ by pass type.
- The migration path for template-only branches such as non-specified own use:
  update the real LEAP area/template, then rerun; code must report rather than
  fabricate IDs.

## Safe implementation phases

1. Add characterization tests around existing output workbooks before moving
   logic. Include first-stage and second-stage activity modes.
2. Extract pure, data-frame-level helpers one at a time (activity selection,
   intensity calculation, template-ID attachment, diagnostics). Preserve input
   and output schemas.
3. Keep orchestration and all `PROXY_CONFIG` values unchanged until their
   inventory is reviewed.
4. Consider a clean rewrite only after fixtures cover each enabled process and
   a before/after real-economy comparison is exact within stated tolerance.

## Acceptance

For each migrated portion, compare keyed rows and expressions to the existing
workflow for a baseline seed and a results-update seed. Verify no output row
uses another economy's template IDs, and separately report genuine missing
template branches. Do not combine this work with a full fleet run.
