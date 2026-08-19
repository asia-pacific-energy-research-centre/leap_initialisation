# WEBQ-002 — Diagnose synthetic 09.08 own-use rollups before seeding

## Objective

Independently determine whether synthetic `09.08.* (including own use)`
parent rows can enter the baseline-seed/carry-forward path when a direct 9th
projection comparator is missing. Produce reproducible evidence and a narrow
go/no-go recommendation; do not implement a broad fallback today.

## Context that must remain separate

The dashboard’s inclusive Coke-oven/Blast-furnace presentation has already
been validated as a comparison/display boundary. It does not prove that an
inclusive rollup is a valid direct LEAP seed source. Seed logic must establish
child-level evidence first and must not confuse `10.01.*` own-use/loss
ownership with missing `09.08` split evidence.

Relevant files named by the queue:

- `codebase/functions/baseline_seed_balance_diagnostics.py`
- `codebase/functions/ninth_projection_mapping.py`
- `codebase/functions/transformation_analysis_utils.py`
- `docs/initialisation_flow_estimation_methods.md`

## Evidence procedure

1. Inspect the actual source→diagnostic→seed/carry-forward call chain. Record
   exact predicates and the row identifiers that can classify a rollup as
   eligible.
2. Build a small reproducible table from the original issue context containing
   at least one row for each of `09.08.01` through `09.08.05`, where available:
   source label/code, synthetic-rollup flag, resolved 9th comparator,
   child comparator(s), `10.01.*` relationship, fallback decision, and proposed
   LEAP destination. Include an explicit before/after *candidate-row set*, not
   only prose.
3. Test the child-comparator resolver before any fallback. Distinguish:
   - a valid child-level comparator;
   - a known synthetic parent with no child comparator;
   - missing/ambiguous split evidence; and
   - a `10.01.*` own-use/loss relationship that must not be substituted for a
     `09.08` split.
4. Reproduce the present behavior in a focused test or a durable diagnostic
   fixture. Do not use the existing untracked `.tmp_webq002_*.py` files,
   `build_apec_2026_preliminary.py`, or its test without coordinating with
   their owner.

## Recommendation rule

Recommend a rollup-source blocker if the evidence confirms the queue’s risk:
synthetic `(including own use)` process rows must resolve children first and
may be direct seed sources only with a child-level comparator or a reviewed,
explicit exception. Unresolved cases remain visible as
`no_direct_projection_comparator` / `seed_or_carry_forward_process`; they do
not become silent seed assumptions.

If evidence contradicts that design, explain precisely which row identity and
LEAP destination make direct seeding safe. Do not infer a parent→child split
from names alone.

## Deliverable and stop condition

Create one concise diagnostic note or test-backed evidence table covering:

- current behavior and minimal reproducer;
- before/after candidate row set;
- child-resolution coverage and ambiguous cases;
- recommendation, impacted code locations, and a focused regression-test
  outline.

Implement only if the behavior is unambiguous, the owner agrees on the narrow
rule, and the change can land with a regression test in a separate commit.
Otherwise stop at the evidence note and mark `REVIEW_REQUIRED`; that is a
successful outcome for today.
