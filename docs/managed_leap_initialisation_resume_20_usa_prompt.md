# Managed LEAP initialisation — resume directly with 20_USA

This is a companion prompt to `docs/managed_leap_initialisation_run_prompt.md`.
Read and follow the base prompt in full, including its ADDENDUM, then read the
durable journal at:

`outputs/leap_exports/supply_reconciliation/supporting_files/runtime/managed_runs/managed_run_notes.md`

Do not re-litigate decisions already recorded there. Preserve every uncommitted
working-tree change; they are deliberate. Do not commit, stage, reset, restore,
or discard anything.

## Immediate objective

Resume Phase 2 by launching a fresh full production run for `20_USA` immediately.
Do **not** try `_PRESET_PATCH_BASELINE_SEEDS`: there is no accepted 20_USA final
baseline seed in the live output directory for that preset to patch. Use the full
`_PRESET_BASELINE_SEED` workflow and the existing managed 20_USA runner.

If 20_USA succeeds, verify the primary outputs exactly as required by the base
prompt, journal the result, and proceed to Phase 3 for all canonical economies.

## Current verified regression gate

The complete suite passed for the current source/test state after the latest
contextual-disaggregation and validation-policy changes:

```text
297 passed, 6 skipped, 10 warnings, 13 subtests passed
exit code 0
duration 17:53
```

Log:

`outputs/leap_exports/supply_reconciliation/supporting_files/runtime/managed_runs/pytest_full_suite_20260703_contextual_disaggregation.log`

Treat this as the current valid regression gate and start with 20_USA without
rerunning pytest, provided all of the following are true after reconstruction:

1. `git status --short` shows no source or test changes beyond the state described
   below.
2. No managed workflow or pytest process is active.
3. The gate log ends with the passing summary above.
4. No file was modified after that gate in a way that affects source or tests.

If any condition is false or ambiguous, do not launch. Reconstruct the state and
rerun the full suite with:

```powershell
& 'C:\Users\Work\miniconda3\python.exe' -m pytest -q --ignore=tmp
```

Do not delete or modify `tmp/pytest`.

## Launch instructions

Reuse:

`outputs/leap_exports/supply_reconciliation/supporting_files/runtime/managed_runs/managed_runner_20_usa.py`

Launch it with `C:\Users\Work\miniconda3\python.exe`, redirect stdout/stderr to
new timestamped managed logs, record the exact Python PID and full command line,
and manage it using the base prompt's 10-minute polling rule.

The runner must verify and use:

- `RUN_MODE == "full"`;
- active preset `_PRESET_BASELINE_SEED`;
- `ECONOMIES == ["20_USA"]` after the authorized override;
- scenarios `Target`, `Reference`, and `Current Accounts`;
- workbook analysis-input write mode;
- patch-only/preflight-only mode false;
- `SCRAPE_LEAP_RESULTS = False`;
- `RUN_PREFLIGHT_COMPRESSED_PROJECTION = False` after override;
- `KEEP_PC_AWAKE_WHILE_RUNNING = True`.

Keep the user-authorized exact-duplicate mapping environment switch already in
the runner. Do not restore the retired blanket subtotal waiver.

## Current source decisions and fixes

All changes below are intentional and uncommitted:

- Authored subtotal flags and reviewed subtotal exception sets govern mapping
  validation; computed disagreements are diagnostics, not blockers.
- Fully identical mapping duplicates may be dropped losslessly under the existing
  runner environment switch; differing duplicates still block.
- Transfer-adjacent producer ownership and zero-skeleton scenario borrowing are
  implemented as recorded in the base ADDENDUM and journal.
- Zero skeletons for processes absent from the full-model catalog are dropped
  before strict display-name resolution.
- Duplicate-row deterministic signatures support heterogeneous column-label types.
- Aggregate 9th fuels in aggregated demand are now disaggregated within the
  narrowest supported sector/module context using corresponding ESTO base-year
  flow/product shares. Source aggregate totals are conserved; mapping workbook
  row order is no longer an allocation method.
- Detailed 9th demand rows resolve to their deepest mapped sector ancestor.
- Where an exact 9th sector/fuel crosswalk pair is absent, reviewed sector-to-flow
  and fuel-to-product axes are combined, then matching ESTO values determine the
  contextual shares.
- Generated `Demand\All demand aggregated\...` placeholder branches absent from
  the canonical LEAP model are warning-only. Retain them with `BranchID=-1` and
  valid remaining IDs so the absence is visible; SEED-003/004/011 must not block
  solely for this reviewed case.
- The patch utility's aggregated-demand strip scope was corrected from the entire
  `Demand\` tree to `Demand\All demand aggregated\` only. This is tested, but the
  patch preset is not the current run path.

Focused verification before the complete gate passed:

```text
114 passed
```

The latest real USA diagnostic check preserved the complete 2023 aggregated
demand total (`69,235.899170 PJ`) while distributing thermal coal, jet fuel, and
other petroleum products contextually.

## Working-tree state expected at handoff

Expected modified files include:

- `codebase/aggregated_demand_workflow.py`
- `codebase/functions/baseline_seed_validation.py`
- `codebase/functions/patch_baseline_seeds.py`
- `codebase/functions/supply_leap_io.py`
- `codebase/functions/supply_preflight.py` (pre-existing/unrelated; preserve)
- `codebase/functions/transformation_analysis_utils.py`
- `codebase/functions/transformation_record_builder.py`
- `codebase/functions/transformation_sector_analysis.py`
- `codebase/utilities/energy_balance_template_extractor.py`
- `docs/special_rules_and_design_decisions.md`
- `tests/test_aggregated_demand_workflow.py`
- `tests/test_baseline_seed_comparison_workflow.py`
- `tests/test_zero_skeleton_scenario_borrowing.py` (untracked)
- `docs/managed_leap_initialisation_run_prompt.md` (untracked)

This companion prompt is also expected to be untracked. Treat additional or
missing source/test changes as a state mismatch requiring investigation before
launch.

## Failure boundary

Continue to apply only small, unambiguous mechanical fixes under the base prompt.
Stop and report mapping, balance, data, model-structure, allocation-policy, or
other domain failures. Do not weaken validation beyond the explicit decisions
recorded above.

At every transition, append a complete durable journal entry. Every user-visible
progress message and final report must begin exactly with:

`Dear Finn,`

