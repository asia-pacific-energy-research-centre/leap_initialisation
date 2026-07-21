# Handoff — 2026-07-22 morning

Type: state-of-the-world brief for an agent picking this repo up cold.
Written by the session that landed [17]'s mechanism fix and its follow-ups.

**Read this first, then
[`initialisation_refactor_continuation.md`](initialisation_refactor_continuation.md)
for the thread register, which is the real backlog.**

## Why this file exists

The previous work was done by **two agents in separate sessions** who could not
see each other's conversations with the user and relayed messages by hand
through them. Everything technical was written into the repo as it happened, so
the code and the register are trustworthy. What is *not* in the repo is the
coordination, the wrong turns, and the current physical state of the machine.
That is what follows.

## Current state — check these before doing anything

| | State |
| --- | --- |
| Branch / HEAD | `master`, `bf9b366` |
| Working tree | **one deliberate uncommitted line** (below) |
| Runs in flight | none; economy locks cleared 2026-07-22 08:0x |
| Test suite | 2 failed, 818 passed, 11 skipped, 3 xfailed (~19 min) |

The two failures — `test_read_area_from_real_usa_template` and
`test_prepare_supply_assets_maps_names_aggregates_and_builds_lookup` — are
**pre-existing and confirmed failing at `2713a51`**, before any of this work.
They are not regressions. Neither is diagnosed. The first sits in the export
template resolver, which is the same machinery whose aggregate-sentinel path
broke a run on 2026-07-21; if economies fail in a fleet run, look there first.

### The uncommitted line is deliberate

```python
RUN_OUTPUT_LABEL = "SEED_21ECON_POSTFIX_20260722"   # in supply_reconciliation_workflow.py
```

Set for a fleet run that **has not happened yet**. Restore `"auto"` if you are
not doing that run. Do not commit it either way. See trap 3 in `AGENTS.md` for
why `"auto"` is not a safe default for a run you intend to keep.

`outputs/.../runs/SEED_21ECON_POSTFIX_20260722/` holds 5 orphan preflight files
from a 90-second aborted launch. Safe to delete; contains no seeds.

## What was finished

[17] — two preset overrides never reached the modules that read them — is
**closed on measured evidence**. `work_queue.md` [17] has the full write-up and
T1 in the register has the commit table. The one-line outcome:

> delivery mechanism fixed, logging honest, behaviour unchanged today,
> flag live if the API returns.

**The single most important lesson, and the reason to distrust static checks
here:** delivering the flags was the obvious fix, it passed *everything* — a
clean forwarding report, 60 green tests, an AST-derived blast radius — and it
deleted 1,111,593 PJ of `01_AUS` exports and moved the REF 2022 energy balance
by +271,919 PJ. Only running it revealed that. The reset is the wipe half of a
wipe-then-fill pair whose fill was the decommissioned LEAP API import; in
workbook mode nothing refills. `c5401a5` gates it off, which stops the harm but
does not solve the problem — that is **[18]**.

## What is outstanding

Ordered per the register's own "Suggested order", which is the authority:

1. **T2** remaining characterization tests — unblocks T3 safely.
2. **[18]** supply/transformation zeroing workbook. Fully designed in
   `work_queue.md` [18]; **not started**. The user confirmed they re-import into
   a *populated* LEAP area, so the staleness the reset guards against is a live
   risk. Copy the demand-side pattern (`build_other_demand_zeroing_workbooks`),
   which already does this correctly with a separate artifact.
3. **T6 G1**, then **T6 G2**. G2 is *sharpened, not unblocked* — the
   demand-zeroing builder is armed and correct, and emits nothing today only
   because every non-aggregated `Demand` branch sits under
   `Demand\Other loss and own use`, excluded on purpose. Measured on `01_AUS`:
   8,315 rows → 2,298 → 1,236 → **0**. The first real sector handover adds
   branches outside that prefix and they **will** be zeroed.
4. **T4**, **T3**, **T5**, **T8**, **T7 proper**, **T9**, **T10** — see register.
5. **T11** fleet run — unblocked, never run. See the conflict below.

## Two decisions the user needs to make, not you

**Fleet run vs. [18].** They conflict. A fleet run takes 8–12 hours and forbids
committing anything to `codebase/` while it runs (a mid-run commit killed a run
on 2026-07-21 — Python imports lazily, so the process ends up with mixed module
versions). [18] is mostly `codebase/` work. Pick one; do not start both.

**Do not launch T11 expecting the reset to act.** It is gated off in workbook
mode by design. The log will say `reset is SKIPPED` and
`RUN_RESET_...=True (in effect: False)`, and both are correct. A fleet run
launched in the belief that seeds now differ would be launched on a false
premise.

## Errors made in the previous session, recorded because they were instructive

Every one was caught by checking against real data, and several were *asserted
before* being checked. Treat this as a prior on your own confident conclusions
in this codebase:

- **`zero_fill_unset_rows` declared broken when it was correct.** Reported as "a
  live defect nobody owns", having seen an empty result against 2,298 valid
  input rows without checking the exclusion the *caller* passes in. Retracted.
- **A fix queued for a symptom whose cause was guessed wrong.**
  `SKIP_ECONOMIES_WITH_EXISTING_EXPORTS` reporting `['False','None']` was
  assumed to be a late-import delivery gap; it was the duplicate wrapper module.
  It dissolved when that was fixed and never needed its own change.
- **A healthy run declared dead.** `Get-Process python` does not match
  `python3.13.exe`. Nearly caused a second run to be started on top of a live one.
- **A run killed and not relaunched.** Correctly stopped for running under the
  wrong interpreter, then simply not restarted — the machine sat idle overnight
  and the user woke to no seeds. If you stop something, restart it in the same
  turn or say plainly that you have not.
- **One agent "corrected" another's account of a user conversation it could not
  see** (`919a8a4`, reversed in `fdfba0f`). Two agents on one repo cannot see
  each other's user exchanges; neither should correct the other's account of one.

## If you are one of two agents again

The previous pair converged independently on the same findings, which was
genuinely valuable — two implementations agreeing that exactly 40 `Exports` rows
changed was much stronger evidence than either alone. What it cost: a mid-task
commit that briefly made an A/B unattributable, and duplicated investigation.

If it happens again, agree a **file ownership split** up front and say so in
commit messages. Last time: one agent held
`supply_reconciliation_workflow.py` + its tests, the other held
`work_queue.md` + `supply_results_saver.py` + `supply_reconciliation_tables.py`.
That worked.

## Open items owned by the other agent, pinned by failing-when-fixed tests

Two defects in `supply_reconciliation_tables.py` are deliberately **not** fixed,
with tests that fail when they are — so the fix inverts the test rather than
deleting it:

- `sector_set` computed but never applied to the reconciliation mask, so the
  reset's blast radius cannot be narrowed by module even with
  `RESET_SCOPE_SECTOR_TITLES` set.
- The strict template resolver raising on aggregate sentinels like `00_APEC`.
  **Masked by the gate, not resolved** — it returns the moment the gate does,
  which makes it in-scope for [18].
