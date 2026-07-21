# Advance the repo — 2026-07-22 execution prompt

Type: implementation prompt with single-economy verification.
Status: active. **Single-economy runs only today. Do not launch a 21-economy
fleet run** — it takes 8–12 hours and forbids committing to `codebase/` while it
runs, which would block all of the work below.

## Orientation — read in this order

1. [`session_handoff_20260722.md`](session_handoff_20260722.md) — current state,
   the uncommitted line, the two pre-existing test failures.
2. `docs/work_queue.md` **[18]** — the main task, already designed.
3. `AGENTS.md` → "Launching a run" — three traps that have each cost a run.
   Read this **before** typing a run command, not after.

## Task 1 — prove the repo is clean (do this first, it runs in the background)

`SEED_01_AUS_PRESETFLIP_FIXED_20260721` is a known-good `01_AUS` baseline seed
produced at `c5401a5`. HEAD now carries two further commits, `9c65e45` and
`2f90cc5`, which are **reporting-only and have never been measured in a run**.

Re-run `01_AUS` at HEAD. It must reproduce that leg **exactly**. This
simultaneously establishes today's baseline for Task 2 and proves those two
commits inert.

Config (working-tree edits, **do not commit them**):

```python
ECONOMIES = ["01_AUS"]
RUN_OUTPUT_LABEL = "SEED_01_AUS_CLEANCHECK_20260722"
```

Launch, pinning the interpreter — a bare `python` can resolve to the Windows
Store shim with different pandas/numpy:

```bash
"C:/Users/Work/miniconda3/python.exe" codebase/supply_reconciliation_workflow.py
```

Then verify **which** process is running (`Get-CimInstance Win32_Process -Filter
"Name LIKE 'python%'"`, read the `CommandLine`) and that its log is growing,
before reporting it as launched. Expect ~29 min preflight + ~31 min main run.
Poll at most every 10 minutes.

**Compare all three artifacts** against the FIXED leg, post-boundary on both
sides — this is the method [17] used and it is the standard here:

| Artifact | Expectation |
| --- | --- |
| `leap_import_baseline_seed_01_AUS_*.xlsx` (sheet `LEAP`, header row 3) | 3,432 rows, 0 key changes, 0 expression changes |
| `supply_recon_run_baseline_seed_01_AUS_*.xlsx` | 2,520 rows, 0 changes |
| yearly balance tables | 6 tables identical, REF 2022 = 2,374,831.8 |

Tolerance 1e-6 relative, 1e-9 absolute floor; key sets must match exactly.

**Any difference is a stop-and-report**, not a rounding note. `9c65e45` and
`2f90cc5` touch only printed output; if a value moved, something is wrong and
understanding it takes priority over everything below.

## Task 2 — [18], the supply/transformation zeroing workbook

The substance of today. Full design is in `work_queue.md` [18]; read it rather
than reconstructing it here. Summary of the defect:

The trade reset is the wipe half of a wipe-then-fill pair whose fill was the
LEAP API import. That API is decommissioned. In workbook mode the wipe was
applied to the **in-memory reconciliation table** at
`supply_results_saver.py:3251`, before every downstream consumer, with nothing
to refill it — so the workbook shipped with the values deleted. Measured on
`01_AUS`: 1,111,593 PJ of exports gone, REF 2022 balance moved +271,919 PJ.
`c5401a5` gates the reset off in workbook mode, which stops the harm without
solving the problem.

**The user re-imports into a populated LEAP area**, so the staleness the reset
guards against is a live risk. This must be built, not deleted.

The demand side already solves this correctly and is the pattern to copy:
`build_other_demand_zeroing_workbooks` (`supply_leap_io.py:2256`) emits a
*separate* `demand_zeroing_{economy}.xlsx`, imported before the main workbook,
so zeroing happens inside LEAP through its own artifact and the main workbook
keeps real values. The supply/transformation side has no analogue.

Build it, per [18]'s five steps. Two constraints from [18] that are **not
optional**:

- **Never bundle the mechanism with the behaviour change.** Land the builder
  inert first, then flip it in an isolated commit that can be reverted alone.
  [17]'s flip passed a clean forwarding report, 60 green tests and an
  AST-derived blast radius — and still deleted a million PJ. Static checks do
  not catch this class of defect in this codebase; only running it does.
- **Verify with a single-economy A/B** against Task 1's baseline, comparing the
  same three artifacts. Expect exports **preserved** in the main workbook and a
  new zeroing workbook present. Classify every difference.

Two `supply_reconciliation_tables.py` defects are in scope and currently pinned
by tests written to fail when fixed (so fixing inverts the test rather than
deleting it): `sector_set` never narrowing the reconciliation mask, and the
strict template resolver raising on aggregate sentinels like `00_APEC` — masked
by the gate, and it returns the moment the gate does.

## Task 3 — filler while runs execute

Runs occupy an hour at a time. **T2's remaining characterization tests**
(register `initialisation_refactor_continuation.md`) are test-only, safe
alongside a run, and unblock T3. Use the waiting time for those rather than
idling or, worse, editing `codebase/` mid-run — a mid-run commit gives the
process a mixed set of module versions and has killed a run before.

## Speed tip for iteration

`RUN_PREFLIGHT_COMPRESSED_PROJECTION = False` skips the ~29 min preflight while
developing. **Re-enable it and do one full run before declaring [18] done** —
the projection preflight runs `00_APEC`, an aggregate sentinel, and that is
exactly the path the strict template resolver breaks on.

## Ground rules

- Single economy only today. No fleet run.
- Do not commit `ECONOMIES` or `RUN_OUTPUT_LABEL` edits; stage around them.
- Do not commit to `codebase/` while a run is in flight.
- The two failing tests (`test_read_area_from_real_usa_template`,
  `test_prepare_supply_assets_maps_names_aggregates_and_builds_lookup`) are
  pre-existing at `2713a51` and are **not** yours to fix unless [18] touches
  them — but note the first is in the export template resolver, the same
  machinery as the sentinel defect.
- Report what actually happened, including runs that failed or were not started.
