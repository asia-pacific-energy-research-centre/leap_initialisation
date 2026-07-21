# Phase 2 configuration standardisation — execution plan

## Purpose and status

This prompt is the detailed implementation companion to
[`docs/work_queue.md` [14]](../work_queue.md). Phase 2 standardises **notebook
defaults** in the initialisation workflow wrappers. It is not a migration of
modelling rules, mappings, or producer behaviour.

Completed foundation: `70613de` changed `supply_workflow.py` from a hidden
USA-only notebook default to `workflow_config.SUPPLY_NOTEBOOK_ECONOMIES`, with
an import/argument-forwarding test.

## Target convention

- `codebase/configuration/workflow_config.py` owns shared notebook defaults.
- A workflow retains short editable `NOTEBOOK_*` constants, derived from that
  config at import time.
- Callable functions retain explicit arguments. An explicit caller argument
  always wins over a notebook default.
- Copy lists at import time; do not alias mutable config/core lists.
- Do not move modelling rules, mapping lists, paths, ID fallbacks, or producer
  function defaults merely because they are module-level constants.

## Global guardrails

1. One script (or tightly coupled config/test pair) per commit.
2. Add focused import/default/argument-forwarding tests that use no production
   ESTO/9th data and do not call LEAP.
3. Preserve output scenarios and runtime fallbacks exactly unless the user
   explicitly approves a behavioural change.
4. Do not introduce JSON config unless genuine economy-specific numeric
   overrides require it.
5. Do not edit the reconciliation preset system as part of this prompt.

## Commit 1 — transformation workflow

**Files:** `workflow_config.py`, `transformation_workflow.py`, new focused
`test_transformation_workflow_config.py`.

Add a labelled transformation notebook-default section to `workflow_config.py`:

- `TRANSFORMATION_NOTEBOOK_ECONOMIES = None` to preserve the current fallback
  to `core.ECONOMIES_TO_ANALYZE`.
- `TRANSFORMATION_NOTEBOOK_SCENARIOS = list(GLOBAL_SCENARIOS)`.
- `TRANSFORMATION_NOTEBOOK_INCLUDE_LEAP_IMPORT = None` to preserve the current
  API/write-mode decision when not explicitly configured.
- `TRANSFORMATION_NOTEBOOK_CURRENT_ACCOUNTS = True`.
- `TRANSFORMATION_NOTEBOOK_AGGREGATE_ECONOMY_LABEL = GLOBAL_AGGREGATE_ECONOMY_LABEL`.

Update only the wrapper's notebook constants to derive from these values. Keep
the current fallback resolution and scenario-derived import list. Test that
`run_with_notebook_config()` forwards economies, scenarios, import decision,
import scenario, Current Accounts handling, and aggregate label without
preparing source data.

**Keep local:** `EXPORT_ID_LOOKUP_PATH`; analysis flags and registry;
`LEAP_API_AVAILABLE`/write-mode runtime decision; producer arguments, paths,
and all transformation calculations.

## Commit 2 — electricity/heat interim workflow

**Files:** `workflow_config.py`, `electricity_heat_interim_workflow.py`, new
focused `test_electricity_heat_interim_workflow_config.py`.

Add a labelled interim notebook-default section:

- economies: a copied central global-economy list;
- scenarios: preserve the current `Target` + `Current Accounts` default;
- include LEAP import: `None` means retain the existing runtime API/write-mode
  decision.

**Policy decision:** do **not** change the interim default to all global
scenarios without explicit approval. Adding `Reference` is an output change,
not configuration cleanup.

Remove the dynamic notebook-economy helper only if it becomes unused. It must
not trigger `prepare_transformation_assets()` or otherwise load core source
tables at import time. Test central defaults and argument forwarding with the
producer function monkeypatched.

**Keep local:** `INTERIM_MODULES`, sector/fuel allow/deny lists, branch-label
rules, template fallback/reference paths, mapping caches, validation logic,
file/sheet identity, and all function arguments.

## Transfers review — no commit currently justified

`transfers_workflow.py` already derives its notebook economies, scenarios,
import decision, Current Accounts handling, and aggregate label from central
configuration. Leave `TRANSFER_PROCESS_CONFIG`, flow/subflow lists,
`DROP_SUBTOTALS_FIRST`, unallocated policy, and split-sector settings alone:
they change constructed processes and outputs.

Two local booleans (`INCLUDE_OUTPUT_SERIES`, `USE_OUTPUT_TARGETS`) can be
centralised later only if a wider standard requires every notebook toggle to be
central. That is cosmetic and does not merit a standalone commit.

## Explicitly deferred scopes

- `aggregated_demand_workflow.py`: its selective data loading and demand
  settings require a separate task.
- `other_loss_own_use_proxy_workflow.py`: proxy/fallback settings are modelling
  behaviour, not simple defaults.
- `refining_workflow.py`: legacy mutable settings and hard-coded paths need a
  separately tested adapter.
- `supply_reconciliation_workflow.py`: its presets, pass modes, and run-label
  lifecycle are a distinct design.

## Completion and archival

After the approved commits pass their focused tests, update `work_queue.md`
[14] with the commit hashes and any deferred decisions. Once all scope in this
prompt is completed or superseded, move this file and its findings/status note
to `docs/archive/` according to the repository prompt-doc workflow.
