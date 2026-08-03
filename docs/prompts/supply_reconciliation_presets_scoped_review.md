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
- `_PRESET_PATCH_BASELINE_SEEDS`: selective regeneration of modules in existing
  seeds. Transformation modules regenerate their source workbooks through the
  owning producer before their configured branch prefixes are patched.
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

## Findings — 2026-07-23 scoped review (read-only)

Traced all three preset dicts in `codebase/supply_reconciliation_workflow.py`
(`_PRESET_BASELINE_SEED` 878-933, `_PRESET_PATCH_BASELINE_SEEDS` 983-1004,
`_PRESET_RESULTS_UPDATE` 1006-1055) and every module each field reaches. No
code was changed; this is evidence only.

### 1. Effective-setting inventory (selected rows; file:line per claim)

| Setting | `_PRESET_BASELINE_SEED` | `_PRESET_RESULTS_UPDATE` | `_PRESET_PATCH_BASELINE_SEEDS` | Downstream consumer |
|---|---|---|---|---|
| `RUN_MODE` | not set (defaults `"full"`, workflow.py:1066) | not set (`"full"`) | `"patch_baseline_seeds"` (workflow.py:988) | workflow.py:1283 branches the whole run |
| `CAPACITY_UNMET_PASS_MODE` | `"baseline_seed"` (workflow.py:883) | `"results_update"` (workflow.py:1012) | **not set** | `_resolve_capacity_unmet_pass_mode` (supply_reconciliation_history.py:410); also drives `_automatic_run_output_label` (workflow.py:699) and the results_update readiness gate (workflow.py:1214) |
| `RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT` | `True` (workflow.py:884) | `False` (workflow.py:1013) | not set | gated by `reset_is_effective()` (analysis_input_write_dispatcher.py:87), consumed at supply_leap_io.py:2479 and supply_results_saver.py:3081,3456,3935 |
| `RUN_ELECTRICITY_HEAT_INTERIM` | `True` (workflow.py:887) | `False` (workflow.py:1015) | not set (config default `False`, supply_reconciliation_config.py:254) | supply_results_saver.py:3712/3813 |
| `USE_AGGREGATED_DEMAND_AS_DUMMY` | `True` (workflow.py:892) | `True` (workflow.py:1033) | not set (config default `True`, supply_reconciliation_config.py:1058) | `load_results_demand_table` (supply_reconciliation_tables.py:734-828) |
| `AGGREGATED_DEMAND_USE_SECTOR_BRANCHES` | `False` (workflow.py:916) | `False` (workflow.py:1039) | not set | forwarded into both `build_aggregated_demand_as_dummy` and the LEAP-import workbook writer, must stay consistent (supply_reconciliation_tables.py:806/821, supply_results_saver.py:3766) |
| `ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT` | `True` (workflow.py:920) | `True` (workflow.py:1042) | not set | supply_results_saver.py:3950/4051, gated jointly with `USE_AGGREGATED_DEMAND_AS_DUMMY` |
| `OTHER_LOSS_OWN_USE_PROXY_STAGE` | `"first"` (workflow.py:927) | `"second"` (workflow.py:1049) | **not set** (config default `"auto"`, supply_reconciliation_config.py:264) | `_resolve_other_loss_own_use_proxy_activity_source_mode` (supply_leap_io.py:1071-1097); `"auto"` falls through to `CAPACITY_UNMET_PASS_MODE` |
| `PATCH_MODULE` / `PATCH_ECONOMIES` / `PATCH_RUN_WORKFLOW` | n/a | n/a | `["losses_own_use"]` / `None` / `True` (workflow.py:996-1003) | `patch_baseline_seeds.run_patch` (patch_baseline_seeds.py:1041), routed per-module through `MODULE_REGISTRY` (patch_baseline_seeds.py:181-257) |
| Capacity-unmet caps | n/a (not preset-controlled) | n/a | n/a | `CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS` / `..._PRODUCTION_UPPER_LIMITS` (supply_reconciliation_config.py:717-829): sentinel *code* (`_ModuleCapRule`, lines 61-118) mixed with a hardcoded, economy-keyed literal dict — only `"20_USA"` has entries today, everything else falls back to whatever the unkeyed default resolves to. This is exactly the "structural code vs. economy numeric data" split Design Goal 2 asks to separate, and it is not separated yet. |
| Preflight toggles | `RUN_PREFLIGHT_COMPRESSED_PROJECTION=True` (workflow.py:881) | `RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE=True` (workflow.py:1009) | n/a (patch mode returns before either preflight runs, workflow.py:1283-1290) | both preflight toggles' *other* member keeps whatever the workflow-level default is (`RUN_PREFLIGHT_COMPRESSED_PROJECTION=True` at workflow.py:1079, `RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE=False` at workflow.py:1089) rather than the inactive preset explicitly disabling it — intentional per the comment at workflow.py:870-876, not a defect |
| Cache / skip-existing / deferred-error / output label | none of the three presets set `TRANSFORMATION_SUPPLY_CACHE_ENABLED`, `SKIP_ECONOMIES_WITH_EXISTING_EXPORTS` (baseline/results_update explicitly re-set it to their own `False`, workflow.py:932/1054), `THROW_ERROR_AFTER_RUN`, or `RUN_OUTPUT_LABEL` | | | these remain true run-scope controls, confirming the brief's assumption that they are separate from pass-mode selection |

### 2. Delivery/observability mechanism already exists and is stronger than the brief assumed

`_broadcast_preset_overrides()` (workflow.py:378-394) pushes every preset key
(union of all three `_PRESET_*` dicts, workflow.py:369-375) into every loaded
`codebase.*` module's own `__dict__` via `_broadcast_config_overrides`
(supply_preflight.py:1815-1835) — this includes `supply_reconciliation_config`
itself, since it is already imported and holds the same attribute names.
`_effective_setting()` (workflow.py:449-471) then reports what consumers
actually hold, not what the wrapper's own global says, and
`_preset_delivery_warnings()` (workflow.py:474-500) prints `[WARN] Preset not
in effect: ...` for any consumer that disagrees. This is called from
`_run_with_config_locked` (workflow.py:1382-1424) and is teed to
`RESULTS_RUNTIME_DIR/supply_reconciliation_workflow.log` (workflow.py:1121-1123,
1269), so a full-workflow run already gets a persisted "what actually ran"
line. **Design Goal 1 (printable/persisted effective config) is roughly
two-thirds built for full runs already** — it prints preset-controlled toggles,
derived values (e.g. `INCLUDE_LEAP_IMPORT`), and reset-effectiveness
(`reset_is_effective`, analysis_input_write_dispatcher.py:87-109 — fails closed
on ambiguous consumer state, a real "prevent invalid combinations" mechanism
already in production). What's still missing for Design Goal 1: no preset
*name* is printed (only its resolved keys), no template/data fingerprint, and
no commit hash — the doc's "printable and persisted... including preset name...
template/data fingerprints, and commit hash" is not met.

### 3. Confirmed gap: `_PRESET_PATCH_BASELINE_SEEDS` does not pin the pass mode it depends on — ✅ Fixed 2026-07-23 (`5d20099`)

`CAPACITY_UNMET_PASS_MODE: "baseline_seed"` and
`OTHER_LOSS_OWN_USE_PROXY_STAGE: "first"` added to
`_PRESET_PATCH_BASELINE_SEEDS` (`supply_reconciliation_workflow.py`),
matching `_PRESET_BASELINE_SEED`'s own values, per this finding's first
recommended option. 2 new tests in `tests/test_reconciliation_state_forwarding.py`
(one pinning the values, one characterizing the bug directly via
`_resolve_other_loss_own_use_proxy_activity_source_mode`); one existing test
in `tests/test_reconciliation_phase4_characterization.py` updated — it had
pinned the old gap ("results_update") as an intentional contract in its own
comment, which was itself part of what this finding corrected.

**Original finding, for context:**

`CAPACITY_UNMET_PASS_MODE` and `OTHER_LOSS_OWN_USE_PROXY_STAGE` are preset keys
in the other two dicts but are absent from `_PRESET_PATCH_BASELINE_SEEDS`
(workflow.py:983-1004). Unlike `RUN_MODE`, which the wrapper explicitly resets
to `"full"` before unpacking any preset (workflow.py:1066), there is no
equivalent reset for `CAPACITY_UNMET_PASS_MODE` — its only "default" is the
`from codebase.supply_reconciliation_config import *` at load time
(workflow.py:65), which sets it to `"results_update"`
(supply_reconciliation_config.py:162).

Consequence, traced end to end: when `PATCH_MODULE=["losses_own_use"]` runs,
`patch_baseline_seeds.py`'s `losses_own_use` branch (patch_baseline_seeds.py:859-882)
does a **fresh, local** `from codebase.supply_reconciliation_config import
CAPACITY_UNMET_PASS_MODE, OTHER_LOSS_OWN_USE_PROXY_STAGE` and calls
`_resolve_other_loss_own_use_proxy_activity_source_mode(proxy_stage=OTHER_LOSS_OWN_USE_PROXY_STAGE,
iteration_run_mode=CAPACITY_UNMET_PASS_MODE)` (patch_baseline_seeds.py:879-882).
Since the patch preset never sets either name, `OTHER_LOSS_OWN_USE_PROXY_STAGE`
stays `"auto"` and resolves via whatever `CAPACITY_UNMET_PASS_MODE` currently is
(supply_leap_io.py:1071-1097) — the config-module default `"results_update"`
on a fresh interpreter, or leftover state from whichever preset ran earlier in
the same session. A modeller who starts a new kernel, sets `ACTIVE_PRESET =
_PRESET_PATCH_BASELINE_SEEDS` directly, and patches `"losses_own_use"` into
**baseline-seed** files therefore risks silently getting the `"leap_balance"`
(second-stage/results_update) own-use activity source instead of the
`"esto_ninth"` (first-stage/baseline_seed) source the target files need — with
no guard, and no toggle-summary print to catch it, because patch mode returns
at workflow.py:1290, before the `_run_with_config_locked` toggle-print/
`_preset_delivery_warnings()` block (workflow.py:1382-1424) is ever reached.
The only visibility is `patch_baseline_seeds.py`'s own per-economy print of
`activity_source_mode` (patch_baseline_seeds.py:885-888) — informative if read,
but not validated against the run's intent. This is a concrete instance of
Design Goal 3 ("prevent invalid combinations early... a results-update preset
without its required LEAP balance input") applying in the opposite direction:
a *patch of baseline-seed data* silently picking up results-update semantics.

### 4. Stale/inaccurate comment: "Only works for single-economy runs"

`_PRESET_BASELINE_SEED`'s comment on `USE_AGGREGATED_DEMAND_AS_DUMMY`
(workflow.py:891: "Only works for single-economy runs") does not match the
current code. `load_results_demand_table` (supply_reconciliation_tables.py:734-828)
explicitly handles the multi-economy case at lines 808-825: "Multiple
individual economies: build each separately (no cross-economy aggregation),"
looping `build_aggregated_demand_as_dummy(economy=econ, ...)` per economy and
concatenating. The per-economy export path in `supply_results_saver.py`
(3700-3768) also calls it with `economies=[economy]` inside its own per-economy
loop. Either the comment is stale (multi-economy was fixed after the comment
was written and it was never updated) or it refers to a narrower risk not
documented here; either way it should be corrected or clarified as part of any
future inventory work, since a modeller reading the preset today would
over-restrict multi-economy baseline-seed runs unnecessarily. This is a
documentation-accuracy finding, not a functional defect — no code changed.

### 5. Patch-gate status (transformation auto-regen) — matches memory, re-confirmed

`patch_baseline_seeds.run_patch` (patch_baseline_seeds.py:1041-1089) raises
`NotImplementedError` unconditionally for any module with `auto_sector_keys`
set (`"oil_refineries"`, `"lng"`, `"hydrogen"`, `"gas_processing"`,
`"coal_transformation"`, `"petrochemical"`, `"charcoal"`, `"biofuels"`,
`"nonspecified_transformation"`, `"transformation"` —
patch_baseline_seeds.py:181-257). `"supply"`, `"transfers"`, `"power_interim"`,
`"aggregated_demand"`, and `"losses_own_use"` are workbook-based and unaffected
by the gate. This matches the file's own audit comments (workflow.py:935-982)
and the project's `project_transformation_patch_gate_reassessment` memory
entry: the gate stays until the auto path reproduces a full run row-for-row.
No new evidence changes that verdict.

### Answers to the brief's open questions, in summary

- **Is the effective-config-snapshot design goal already met?** Partially, for
  full runs only (baseline_seed/results_update): yes for resolved-value
  reporting and divergence warnings (finding 2); no for preset name, commit
  hash, and fingerprints. Not met at all for patch runs, which skip the
  toggle-print block entirely (finding 3).
- **Are there impossible/silent-wrong combinations reachable today?** Yes — one
  concrete one found (finding 3: patch preset's pass-mode/own-use-stage
  ambiguity). The two combinations the brief worried about in Design Goal 3
  (results-update without LEAP balance input; aggregate demand vs. conflicting
  detailed-demand) are each already guarded: `_run_results_update_readiness_check`
  (workflow.py:1212-1262) and the `reset_is_effective`/workbook-mode fail-closed
  rule (analysis_input_write_dispatcher.py:87-109) respectively.
- **Should capacity-unmet caps move out of `supply_reconciliation_config.py`?**
  The sentinel *rules* (`_ModuleCapRule` and friends) are exactly the kind of
  structural code Design Goal 2 says to keep in Python. The economy-keyed
  literal dict that currently only covers `"20_USA"` is the "genuinely
  economy-specific numeric value" Design Goal 2 says to externalize with
  validation — it has not been externalized yet. This is unchanged/newly-
  confirmed scope for the eventual config-module split, not itself an
  incorrect behaviour.
- **Is the transformation patch gate still correctly closed?** Yes, reconfirmed
  read-only (finding 5); no action needed here.

No code was changed to produce these findings. The concrete next action this
review recommends (not implemented here, per the brief's own gate): either add
`CAPACITY_UNMET_PASS_MODE: "baseline_seed"` and
`OTHER_LOSS_OWN_USE_PROXY_STAGE: "first"` explicitly to
`_PRESET_PATCH_BASELINE_SEEDS`, or have `patch_baseline_seeds.py`'s
`losses_own_use` branch require an explicit stage argument instead of
resolving `"auto"` from a value the patch preset never sets. Either change
needs its own execution prompt per this brief's closing instruction.
