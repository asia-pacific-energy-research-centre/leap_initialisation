# Supply reconciliation presets - scoped review and implementation brief

## Purpose

`codebase/supply_reconciliation_workflow.py` is the long-running orchestrator.
Its presets select a modelling pass, not merely notebook defaults. The current
baseline-seed, results-update, and patch-baseline-seeds dictionaries combine
demand source, own-use activity stage, import/reset handling, power interim
behaviour, preflight, and patch semantics.

This brief is linked from `docs/work_queue.md` [15]. It is a design and
characterisation task; do not move preset values into the generic Phase 2
configuration pattern.

## Current preset model

- `_PRESET_BASELINE_SEED`: ESTO/ninth initialisation, supply/transformation
  import/export reset, interim power enabled, aggregated demand and zeroing
  enabled, and first-stage own-use proxy activity.
- `_PRESET_RESULTS_UPDATE`: results-linked pass, no import/export reset,
  interim power disabled, aggregate demand/zeroing retained while demand models
  are absent, and second-stage own-use activity.
- `_PRESET_PATCH_BASELINE_SEEDS`: selective regeneration of verified modules in
  existing seeds. Transformation auto-regeneration is deliberately gated until
  it can reproduce a full run exactly.
- `ECONOMIES`, `SCENARIOS`, output label, preflight toggles, cache toggle, and
  deferred-error policy are run controls around the preset, but some interact
  with it and need explicit ownership.

## Required inventory

Before code changes, make a table with one row per effective setting and these
columns: setting, default owner, each preset value, downstream consumer,
behaviour changed, safe to override per run, and validation/evidence required.
At minimum include:

- pass mode, import/export reset, power interim;
- aggregated demand, branch mode, zeroing, exclusions;
- own-use stage and source/LEAP-import controls;
- patch module/economy/regen controls;
- projection and results-update preflights;
- cache, skip-existing-exports, deferred error, output label, and scope;
- capacity-unmet policies and caps (structural code versus economy numeric data).

## Design goals

1. Make a run's effective configuration printable and persisted beside its
   outputs, including preset name, explicit overrides, economy list, scenario
   list, template/data fingerprints, and commit hash.
2. Keep structural sentinel logic in Python. Store only genuinely
   economy-specific numeric values externally, with validation.
3. Prevent invalid combinations early (for example, a results-update preset
   without its required LEAP balance input, or aggregate demand plus conflicting
   detailed-demand behaviour).
4. Preserve notebook-first operation: a modeller can select a named pass and
   edit a short, obvious run-scope block without mutating model definitions.
5. Keep the active fleet run's temporary `RUN_OUTPUT_LABEL` lifecycle separate;
   do not refactor this file while a production run is using it.

## Safe implementation sequence

1. Read-only inventory and effective-config snapshot function, with no changed
   preset values.
2. Focused validation of impossible combinations and tests against each current
   preset's expected resolved config.
3. Separate run scope/label controls from preset dictionaries while maintaining
   exact resolved outputs.
4. Only after equivalence evidence, move structural configuration into a small
   config module as part of the planned monolith split.

## Verification and release gate

- Unit tests resolve every named preset and assert the documented key values.
- Snapshot tests prove explicit run overrides win only where allowed.
- One baseline and one results-update representative run retain their expected
  workbook/seed keys, pass-mode diagnostics, and validation outcome.
- A production run records its effective config before processing begins; if
  data/template fingerprints change mid-run, flag the result invalid rather
  than certifying it.

Do not implement preset changes until the inventory is reviewed and a separate
execution prompt names the specific behaviour to change.
