# Refining workflow - scoped review and implementation brief

## Purpose

`codebase/refining_workflow.py` is a compact legacy-style workflow that reads a
refining export, optionally remaps fuels, applies refining capacity logic, and
writes either a workbook or LEAP API updates. It is a good first modelling
configuration task because its scope is small, but its current module constants
combine run selection with operational behaviour.

This brief is linked from `docs/work_queue.md` [15]. It is not part of Phase 2
configuration standardisation.

## Current evidence

- The notebook defaults include a USA export path, `ECONOMY`, `REGION`, three
  scenarios, and the target fallback scenario.
- The same module also controls branch creation, fuel remapping, scenario
  materialisation, capacity transformation, API/workbook dispatch, unit writes,
  and skipped LEAP variables.
- `run_with_config()` is the only notebook entry point. It resolves scenarios
  from the export file before branch creation/filling.

Consequently, moving every uppercase constant to central configuration would
silently turn process behaviour into a shared default. Do not do that.

## Decisions required before implementation

1. Is this workflow still a standalone refining import tool, or should the
   reconciliation orchestrator be its only normal caller?
2. What is the approved per-economy export/template source? Do not preserve a
   USA file path as a hidden generic default if real economy exports are now the
   intended input.
3. Is `SOURCE_SCENARIO_FOR_MISSING[Target] = Reference` an intended modelling
   rule for all areas, or only a legacy export-completion fallback?
4. Which settings may a modeller edit in a notebook run, versus which must be
   fixed in code and covered by regression tests?

Record answers in a short findings section in this file before changing code.

## Proposed bounded implementation

Only after the decisions above:

1. Introduce a small, explicit `REFINING_NOTEBOOK_*` block near the bottom of
   the module (or a typed function call from that block). It may contain the
   requested economy, input export, optional output directory, and explicit
   write mode.
2. Resolve the economy's region and template/export source at runtime. An
   explicit caller value wins; do not invent IDs or borrow another economy's
   IDs.
3. Pass the selected values into a parameterised runner. Preserve default
   behaviour for existing callers until an equivalence test proves the new
   route identical.
4. Leave these local and documented as modelling/operational choices:
   `REMAP_FUELS`, fuel mapping source, subtotal removal, capacity logic,
   `SKIP_VARIABLES`, branch types, fill/create policy, and Current Accounts
   handling.

Do not change refining calculations, branch paths, output expressions, or
LEAP API behaviour in this task.

## Verification

- Add an import/default/argument-forwarding test using a tiny temporary export
  workbook or monkeypatched writer functions; it must not connect to LEAP.
- Add one small scenario-resolution test covering missing Target rows and the
  configured fallback.
- For a known export, compare the old and new workbook-mode outputs by LEAP key
  `(Branch Path, Variable, Scenario, Region)` and `Expression` before enabling
  the new entry point by default.
- Run the focused tests plus the relevant existing refining tests.

## Completion

Commit only the refining config/runner/tests in one coherent commit. Update
this brief and work queue with the decision and test evidence. Archive this
prompt only once the implementation is complete.
