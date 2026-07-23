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

## Review findings — 2026-07-23

Scope of this pass: read `codebase/refining_workflow.py` end to end (555
lines), plus every caller/reference found via `grep -rn refining_workflow`
across the repo, `codebase/configuration/workflow_config.py`,
`codebase/functions/analysis_input_write_dispatcher.py`,
`codebase/functions/supply_export_builder.py`,
`codebase/functions/supply_results_saver.py`,
`codebase/baseline_seed_comparison_workflow.py`,
`codebase/functions/supply_leap_io.py`, `docs/system_overview_for_rewrite.md`,
`docs/check_registry.md`, `docs/baseline_seed_rule_inventory.md`, and
`tests/test_refining_capacity_policy.py`. No code was changed. All four
questions below have concrete answers; none required guessing.

### Q1 — Standalone tool, or should the orchestrator be the only normal caller?

**It is a standalone tool today, and there is no wiring anywhere that calls
it from the reconciliation orchestrator.**

- `run_with_config()` (`codebase/refining_workflow.py:434`) is invoked only
  from this module's own `if __name__ == "__main__":` guard
  (`codebase/refining_workflow.py:552-554`). A repo-wide grep for
  `run_with_config\(\)` and for `import refining_workflow` /
  `from codebase import refining_workflow` /
  `from codebase.refining_workflow` turns up no caller in
  `codebase/supply_reconciliation_workflow.py`,
  `codebase/functions/supply_results_saver.py`, or any other production
  module — only this file's own module body and `tests/test_refining_capacity_policy.py`
  (which imports the module directly to unit-test one private helper, not to
  run the workflow).
- `codebase/baseline_seed_comparison_workflow.py:604-619` and
  `codebase/functions/supply_leap_io.py:1784-1790` both contain a function
  that maps `Transformation\Oil Refin...` branch paths to the *label*
  `"refining_workflow"` for diagnostic attribution/producer-coverage
  reporting. This is read-only string bookkeeping — it recognizes refining
  branches if/when they appear in a combined export, it does not call the
  module or its `run_with_config()`.
- `codebase/functions/supply_results_saver.py:4053-4066` builds
  `baseline_seed_sources` (the dict of per-workflow export paths fed into
  `write_per_economy_combined_workbooks(..., source_workbooks_by_workflow=...)`
  at line 4079) from `supply_workflow`, `transformation_workflow`,
  `transfers_workflow`, `electricity_heat_interim_workflow`,
  `other_loss_own_use_proxy_workflow`, `aggregated_demand_workflow`, and
  `demand_zeroing_workflow` — **there is no `"refining_workflow"` key**.
  Refining output is only picked up if it happens to land inside a
  `transformation_workflow` export and gets re-labelled by the branch-path
  heuristic above; there is no dedicated per-economy refining export feed
  into the orchestrator's baseline-seed source list.
- The module's own output path constant, `REMAP_OUTPUT_PATH`
  (`codebase/refining_workflow.py:414-417`), writes under
  `STANDALONE_LEAP_EXPORTS_ROOT` (`codebase/utilities/output_paths.py:18`,
  literally `LEAP_EXPORTS_ROOT / "standalone"`), which is the same
  "standalone" tree used by other non-orchestrated manual tools — reinforcing
  that this workflow's output is not treated as an orchestrator-managed
  intermediate artifact.
- `docs/system_overview_for_rewrite.md:754-756` states the intended
  modelling boundary explicitly: *"Refining initialisation is part of the
  transformation/supply setup, but later refining model adjustments should
  be reviewed separately rather than hidden inside the supply reconciliation
  loop."* That is a deliberate design choice, not an oversight.
- Sibling workflows that previously had the same "hand-edited module
  constants" shape have since been migrated to accept economy/scenario
  arguments driven by the orchestrator (e.g. `codebase/supply_workflow.py:50-96`
  takes `economies: Iterable[str] | None` and resolves defaults from
  `workflow_cfg.SUPPLY_WORKFLOW_DEFAULT_ECONOMIES`). `refining_workflow.py`
  never received that migration — a grep for `^ECONOMY\s*=` /`^REGION\s*=`
  across `codebase/transfers_workflow.py`, `codebase/transformation_workflow.py`,
  `codebase/other_loss_own_use_proxy_workflow.py`, and
  `codebase/electricity_heat_interim_workflow.py` finds none of those
  constants; only `refining_workflow.py:59,68` still has them.

**Conclusion:** as written, this is a standalone manual tool the orchestrator
does not call and does not expect to call. `docs/work_queue.md:1296-1313`
("[15] Modelling-configuration scoped reviews") and
`docs/system_overview_for_rewrite.md:754-756` both treat that separation as
intentional. The proposed bounded implementation (a `REFINING_NOTEBOOK_*`
block, §"Proposed bounded implementation") should keep it a standalone
notebook entry point — it should not be rewired to be orchestrator-only
without a separate decision to reverse the documented design boundary.

### Q2 — Approved per-economy export/template source

**There is no per-economy refining export source configured or discovered
anywhere in the repo; `20_USA` / `"../data/refining model export.xlsx"` /
`"United States"` are the only values that exist, and they are hardcoded
together rather than derived.**

- `codebase/refining_workflow.py:58-68` hardcodes
  `leap_export_filename = "../data/refining model export.xlsx"`,
  `ECONOMY = "20_USA"`, and `REGION = "United States"` as three independent
  module constants with no cross-check between them.
- `data/README.md:279-280` documents the file as a single workbook:
  *"`refining model export.xlsx` — Refining import workbook used by
  `codebase/refining_workflow.py`."* There is no per-economy naming
  convention documented (contrast with, e.g., supply/transformation export
  templates that are generated per economy by `supply_data_pipeline.py`).
  `data/*` is gitignored (`.gitignore:217`), so the actual file content
  could not be inspected in this review; only the docstring at
  `codebase/refining_workflow.py:282-288` is authoritative: *"Refining
  starts from a hand-maintained export workbook"* — i.e. refining's source
  is not derived from ESTO/9th-outlook data like its sibling workflows, it
  is a manually curated spreadsheet, so there is currently no automated way
  to produce an equivalent file for a different economy.
- The repo does already have a canonical economy→region resolver,
  `get_region_for_economy()` (`codebase/functions/supply_export_builder.py:136-146`,
  built on `APEC_ECONOMY_REGION_MAP` / `EXPORT_ECONOMY_REGION_OVERRIDES`),
  used by `codebase/functions/patch_baseline_seeds.py:700,1151` and
  `codebase/functions/supply_leap_io.py:1850,2176,2209,2335,2388`.
  `refining_workflow.py` does not call it anywhere — `REGION = "United
  States"` is a separate hardcoded literal that happens to agree with
  `ECONOMY = "20_USA"` today but is not derived from it, so nothing would
  catch the two constants drifting apart, and nothing resolves a region for
  any other economy automatically.

**Conclusion:** do not preserve the USA file path as a hidden generic
default. There is no approved per-economy export source today — the correct
fix is (a) make economy/export-path/region three independently-checkable
inputs to a parameterised runner rather than three parallel constants, and
(b) derive `REGION` from `ECONOMY` via the existing
`get_region_for_economy()` helper instead of a separate literal, while
leaving the *export file itself* as an explicit, required caller-supplied
value (per the brief's own §2: "An explicit caller value wins; do not
invent IDs or borrow another economy's IDs") until/unless a real per-economy
hand-maintained export convention is established.

### Q3 — Is `SOURCE_SCENARIO_FOR_MISSING[Target] = Reference` a general modelling rule or a legacy export-completion fallback?

**It is refining-specific export-completion plumbing that happens to point
in the same direction as a real modelling convention used elsewhere, but it
is not the same mechanism and is not shared by any sibling workflow.**

- `_ensure_export_contains_scenarios()` (`codebase/refining_workflow.py:122-186`)
  and its `SOURCE_SCENARIO_FOR_MISSING` dict (`codebase/refining_workflow.py:63-65`)
  exist specifically to patch gaps in the hand-maintained refining export
  workbook: if the `Target` scenario has no rows, it copies `Reference`
  rows and relabels them (`codebase/refining_workflow.py:154-171`). If no
  source scenario is configured or found, it silently falls back to
  whichever scenario happens to be first in the sheet
  (`codebase/refining_workflow.py:157-161`) — a permissive, order-dependent
  fallback, not an explicit modelling decision.
- A grep for `SOURCE_SCENARIO_FOR_MISSING`, `_ensure_export_contains_scenarios`,
  and `scenario.*fallback` across `codebase/transfers_workflow.py`,
  `codebase/transformation_workflow.py`,
  `codebase/other_loss_own_use_proxy_workflow.py`, and
  `codebase/electricity_heat_interim_workflow.py` returns no hits — none of
  the sibling workflows that read ESTO/9th-outlook-derived exports need this
  mechanism, because those exports are generated with full scenario
  coverage. It exists in `refining_workflow.py` only because its input is a
  hand-edited workbook that may not have a `Target` sheet filled in yet.
- There is a genuinely separate, real modelling convention elsewhere with
  the same direction (Target borrows from Reference when missing): the
  transformation share-group "Reference→Target fallback profile" described
  in `docs/check_registry.md:374-381` (`complete_canonical_share_groups`,
  running only across `prepare_seed_rows_for_write`). That is a documented,
  tested (`baseline_seed_validation.complete_canonical_share_groups` and
  canonical-group tests per `docs/baseline_seed_rule_inventory.md:75`)
  modelling rule for output shares. Refining's
  `SOURCE_SCENARIO_FOR_MISSING` is a different code path operating on raw
  export rows before any canonical-share logic runs, with no equivalent
  test coverage (see Q4) and an unconditional first-available-scenario
  fallback that the transformation mechanism does not have.
- The dict also does not cover `Current Accounts`, which is deliberately
  excluded from scenario completion (`CURRENT_ACCOUNT_LABELS`,
  `codebase/refining_workflow.py:71,114,142-143`) — so today only one
  direction (Target←Reference) is configured at all; there is no fallback
  for a missing `Reference` scenario itself.

**Conclusion:** treat `SOURCE_SCENARIO_FOR_MISSING` as legacy
export-completion plumbing for the hand-maintained workbook, not as a
codified modelling rule. If the intent is genuinely "Target defaults to
Reference whenever absent," that should be stated as an explicit, tested
modelling rule (mirroring the transformation share-group convention) rather
than left as an implicit dict with a silent first-row fallback.

### Q4 — Which settings may a modeller edit vs. which must be fixed in code and tested?

**Already-centralised (confirms the split done in Phase 2 elsewhere is the
right model to extend here):**
- `WRITE_MODE` (`codebase/refining_workflow.py:53`) is not a local literal —
  it is resolved via `get_analysis_input_write_mode()`
  (`codebase/functions/analysis_input_write_dispatcher.py:68-80`), which
  reads `workflow_cfg.ANALYSIS_INPUT_WRITE_MODE` and validates it. This is
  the pattern to keep, not change.
- `REFINING_USE_HISTORICAL_PRODUCTION_CAPACITY_HEURISTIC` already lives in
  `codebase/configuration/workflow_config.py:93-95` with a comment marking
  it a *"Retained modelling decision,"* and is the only refining setting
  with a dedicated regression test
  (`tests/test_refining_capacity_policy.py:9-56`, one case: heuristic
  enabled; the disabled early-return branch at
  `codebase/refining_workflow.py:289-291` has no test).

**Still module-local and, per the brief's own §"Leave these local," should
stay local (modelling/operational choices, not run selection):**
`REMAP_FUELS`, `MAPPING_CSV_PATH`, subtotal removal
(`SUBTOTAL_FUEL_NAMES`/`_drop_subtotal_fuel_branch_rows`), capacity-logic
constants (`CAPACITY_UNITS`, `CAPACITY_SCALE`,
`REFINING_PROCESS_PATH_PREFIX`), `SKIP_VARIABLES`
(`codebase/refining_workflow.py:423-431`), `default_branch_type`
(`BRANCH_DEMAND_CATEGORY`/`BRANCH_DEMAND_TECHNOLOGY`,
`codebase/refining_workflow.py:512`), `HANDLE_CURRENT_ACCOUNTS_TOO`, and
`FILL_ALL_SCENARIOS` / `CREATE_BRANCHES_FOR_ALL_SCENARIOS` policy branches.
None of these change per run; they encode how refining branches are built,
which is exactly what this brief says must not be silently generalised.

**Currently module-local but are run-selection, not modelling policy, and
are the actual candidates for the proposed `REFINING_NOTEBOOK_*` block:**
`leap_export_filename`, `ECONOMY`, `REGION`, `SCENARIOS`, `SCENARIO`,
`BASE_YEAR` (`codebase/refining_workflow.py:58-68`) — these vary by who is
running the notebook and for which economy, and (per Q2) `REGION` should be
derived rather than hand-entered.

**Untested today (relevant to "must be fixed in code and covered by
regression tests"):** per
`docs/system_overview_for_rewrite.md:758-763`, *"No dedicated direct test
file currently covers `refining_workflow.py` end to end."* Confirmed by
direct inspection: `tests/test_refining_capacity_policy.py` is the only
test importing the module, and it exercises exactly one private helper
(`_apply_transformation_capacity_logic_to_refining_export`), one branch
(heuristic enabled). `run_with_config()`, `_ensure_export_contains_scenarios()`,
`_drop_subtotal_fuel_branch_rows()`, `_discover_fill_scenarios()`, and every
branch-creation/fill/API-vs-workbook dispatch path in
`codebase/refining_workflow.py:434-542` have zero test coverage. Any
parameterisation of the run-selection constants should add the
import/default/argument-forwarding test and scenario-resolution test the
brief already calls for in its own §"Verification," since none of that
exists yet to protect against regressions.

### Net answer for implementation planning

The brief's proposed bounded implementation (§"Proposed bounded
implementation") is consistent with all four findings above: keep this a
standalone notebook tool (Q1), turn the three parallel USA-shaped constants
into explicit, resolvable, non-redundant inputs rather than a hidden default
— deriving `REGION` from `ECONOMY` via `get_region_for_economy()` (Q2),
document `SOURCE_SCENARIO_FOR_MISSING` as either a stated, tested modelling
rule or keep it clearly scoped as legacy export-completion plumbing rather
than implying it is general policy (Q3), and add the missing
import/default/scenario-resolution tests before parameterising anything
(Q4). No code was changed in this review pass.

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
