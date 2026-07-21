# Remaining work queue

Single source of truth for *what is left, in what order, and what blocks what*
across the supply-reconciliation / baseline-seed work. Cross-references the
detail rather than duplicating it.

> Living document — last reconciled with the tree **2026-07-21** ([1]
> transformation ungate settled: gate stays, see below). Re-check
> `git status --short` before trusting the "blocked" markers.

## How to use this

1. **One issue at a time. One issue → one commit.** Each item below is sized to
   land on its own.
2. **Before starting, the files you will touch must be clean** (`git status --short`).
   Editing a file another agent holds is how work gets silently lost.
3. **Verification runs against a dirty tree are unreadable.** See the blocker
   below — this is not a style preference, it cost a retracted conclusion.

## Parallel workpaths

Two agents may work concurrently only when their file ownership is explicit.
This queue is the shared coordination point; each agent must update the status
of its own work before handing files across.

### Workpath A — per-economy export-template routing

**Current owner:** unowned — ✅ **complete and handed back 2026-07-17.**
All four files are released; Workpath B may take them.

Delivered:

- `6af7833` — aggregate-aware resolution promoted to shared public API
  (`resolve_leap_export_template_or_fallback`); `supply_leap_io` alias unchanged.
- `ee4e5d1` — the three standalone modules route `id_lookup_path` per economy.
  Nine entry points no longer default to `20_USA`'s area. `EXPORT_ID_LOOKUP_PATH`
  survives in each module as the **aggregate/no-template fallback only**.

Released files: `transformation_workflow.py`, `transfers_workflow.py`,
`electricity_heat_interim_workflow.py`, `leap_export_template_resolver.py`
(coordinate before changing the shared helper again).

**Do not reintroduce a pinned `id_lookup_path` default or pass the constant "to
be explicit"** — that is the `073c489` bypass, which made a routing fix a
production no-op for a day while its tests stayed green because they pinned the
template too. `tests/test_standalone_export_id_lookup_routing.py` now fails if a
pinned default reappears.

### Workpath B — catalog and LEAP export readiness

**Current owner:** catalog/readiness agent. **Status:** catalog and transfer preflight
Phase 1 complete; readiness framework is next.

Completed:

- incremental all-template fuel-branch catalog;
- exact-label fuel registry;
- canonical `leap_fuel_branch_catalog.csv` name with legacy compatibility copy;
- transfer export catalog preflight and legacy-root rejection.

Next work may use `fuel_catalog_preflight.py`, `supply_leap_io.py`, readiness
tests, and documentation, but must not modify Workpath A files. The remaining
full-model dependency is tracked below as a cross-cutting follow-up and should
be split by file ownership before implementation.

### Handoff rules

- Before editing, check `git status --short` and this section.
- Do not edit a file listed under another active workpath.
- One coherent change per commit; state the files and tests in the commit.
- When a shared helper must change, pause and coordinate rather than creating a
  second resolver or key implementation.
- Verification runs must use a clean tree or an isolated worktree.

### Shared-helper handoff ✅ DONE 2026-07-17 — `supply_leap_io.py` released to Workpath B

The aggregate-aware wrapper is now public API:
`leap_export_template_resolver.resolve_leap_export_template_or_fallback(economy, *, fallback=...)`.
`supply_leap_io._leap_export_template_for_economy` is a thin alias over it and is
unchanged for every existing caller.

**Workpath B is unblocked: `supply_leap_io.py` is released.** Workpath A will not
touch it again for the standalone routing.

Two design points worth keeping:

- **The fallback is injected, not imported.** `leap_export_template_resolver` is a
  leaf utility with no `codebase` imports; importing the config that owns the
  legacy single export would create a cycle. Each caller passes its own legacy
  constant, so the three standalone modules can share one wrapper while keeping
  their own `EXPORT_ID_LOOKUP_PATH` fallback. Keep that module import-free.
- Verified behaviour-identical to the pre-promotion wrapper across `12_NZ`,
  `01_AUS`, `20_USA`, `05_PRC` (provisional), `00_APEC` (aggregate) and an
  unknown economy. 98 tests pass, including Workpath B's
  `test_fuel_catalog_preflight`.

## The blocker structure

The transformation prerequisite has landed. **The export-template track's
external event has now happened** (2026-07-17: `01_AUS` became a real template),
so [7] is live rather than paced. The remaining checks/refactors below are ready
for a single agent to take one at a time.

```text
[0] transformation output/efficiency corrections (completed 2026-07-16)
      ├── [1] transformation ungate
      ├── [2] last conservation site
      ├── [3] remaining header routes
      ├── [4] Process Efficiency backing invariant
      └── [9] reset-scope chain (completed 23aac52, verified 2026-07-17)

[7] finish the per-economy export-template rollout   <- DEADLINE ARRIVED 2026-07-17
      01_AUS is now a real template; the system is half-routed for it
      ├── [8]  supply_branch_classification threading (completed 2026-07-16)
      ├── [9]  reset-scope chain (completed 23aac52, verified 2026-07-17)
      └── [10] GLOBAL_REGION decision (resolved 39f82df; region now per economy)
              └── attach_export_ids ID-borrowing removed (12e1482)
```

---

## [0] Transformation output/efficiency corrections — completed 2026-07-16

Landed in `8c32504` with 26 targeted transformation/efficiency tests passing.
The working tree was subsequently consolidated and is clean. The earlier
12_NZ + 20_USA equivalence check was confounded only while this work was
uncommitted; it no longer blocks the following items.

**What it is (corrected — it is an intentional fix, not a suspicious change).**
The `multi_output` default flipped `False` → `True`. With `False`,
`summarize_transformation_flows` kept only the **single largest-value output fuel
per flow**; genuine co-products (coke oven gas, coal tar, benzole) were silently
dropped from the process record and back-filled with `Output Share = 0` — "rows
that look like legitimate zeros but are not". Only `oil_refineries` set
`multi_output: True` explicitly; nine other sectors fell through to the default.
Motivating bug: 01_AUS coke ovens `Coal tar` Output Share was 0 despite nonzero
source data. Full detail and the verification plan:
`docs/prompts/transformation_multi_output_default_verification_prompt.md`.

**Blast radius** (why it confounds any transformation diff): a recovered
co-product raises the output total, so capacity, historical production,
efficiency, output shares and aux-fuel ratios all move by **one exact ratio** —
USA coke ovens ×1.16676 (efficiency 60.97 → 71.14), NZ blast furnaces ×1.04001.
Every `20260715` seed predates it.

**MODELLER-CONFIRMED CORRECT (2026-07-16).** The modelling question is settled —
the change is right, and the observed diffs are the *expected correction*, not
something to chase. Confirmed:

- **Coke ovens** — coke oven gas is genuinely an output.
- **NZ blast furnaces** — `Other recovered gases` is a genuine co-product (+4%).
- **The other newly-multi-output sectors** (`coal_patent_fuel_plants`,
  `coal_bkb_pb_plants`, `coal_liquefaction`, `gas_blending`, `coal_mines`,
  `charcoal_processing`, `nonspecified_transformation`) — expected behaviour.

Consequence: where fresh and a `20260715` seed disagree on these sectors, **the
seed is out of date — fresh is right.** Do not read those diffs as regressions.

**Still deferred** — the mechanical sweep in
`docs/prompts/transformation_multi_output_default_verification_prompt.md`, which
its author deliberately deferred to the next full baseline-seed run: share sums
≈ 100% across all economies, efficiency/aux ratios staying plausible (not >1 or
negative), fewer zero-filled `Output Share` rows, and deliverable 1 — confirming
01_AUS coke ovens `Coal tar` Output Share is now nonzero and matches the raw ESTO
value. Domain judgement is done; the numbers still need a pass.

**Evidence already gathered here (feeds that prompt's steps 2-4):** the NZ+USA run
shows the intended signature — efficiency and aux ratios shift by exactly the
ratio the added output implies (step 3), and share sums still reach 100% (NZ:
96.152607 + 3.847393 = 100.0). Its step 4 assumption "USA blast furnaces
unaffected" holds here (only coke ovens moved).

---

## [1] Transformation ungate — ⛔ SETTLED 2026-07-21: gate STAYS (harness returned DEFECT)

**The definitive test has now run and the gate's premise holds. Do not delete the
gate.** The earlier hypothesis that it rested on a raw-vs-seed measurement
artifact is **disproven for `12_NZ`.**

**Evidence (post-boundary vs post-boundary, the trap avoided).**
`codebase/scrapbook/transformation_ungate_equivalence_harness.py 12_NZ` ran the
REAL patcher (`_run_patch_locked`, bypassing only the `NotImplementedError`
gate) against a fresh full-run seed and diffed the result:

- seed: `leap_import_baseline_seed_12_NZ_20260717.xlsx` (stamp `20260717`, past
  the `20260716` transformation-rules change — not stale);
- both sides cross `prepare_seed_rows_for_write`, so canonical share completion /
  cross-scenario borrowing applies equally — the raw-vs-seed artifact is excluded
  by construction;
- verdict **DEFECT**: **1209 rows dropped**, **21 rows invented**, 0 benign +
  **72 non-benign value changes**.

**Nature of the defect — a mix of all three failure classes, structural not
numeric:**

- *Changed values (single-output selection differs).* Gas to liquids Output
  Share flips `Gas and diesel oil` 100→0 and `Kerosene` 0→100; Gas works plants
  Feedstock Share flips `Coal tar` 100→0 and `Lignite` 0→100; Hydrogen
  transformation `Ammonia` Import Target 0 → ~0.11/0.023.
- *Dropped rows (patch omits split-target rows).* e.g. BKB and PB plants
  `Output Fuels\{BKB and PB, Peat products}` Export Target / Import Target across
  all three scenarios — rows the workbook producer emits and the simplified path
  does not.
- *Invented rows.* Hydrogen transformation `Processes\Smr wo ccs`
  Exogenous Capacity / Historical Production / Process Efficiency — emitted by
  the patch, absent from the full run.

**Root cause = the exact gap this item always named.** The patcher's
transformation path uses the simplified `_collect_auto_regen`, **not** the
workbook producer `save_transformation_exports_with_split_targets`. The two are
not equivalent, so deleting the gate would corrupt every patched transformation
seed.

**Smallest follow-up to actually ungate (unchanged, now mandatory not optional):**
rewire the patcher's transformation path to be workbook-based via
`save_transformation_exports_with_split_targets` (the `transfers` model), remove
`auto_sector_keys` from the transformation `MODULE_REGISTRY` entries **only after**
that path is in place, then re-run this harness and require PASS. Keep the gate
until it does. Full recipe in the harness header and
`docs/prompts/transformation_final_handoff_and_verification_prompt.md` (§ If the
result is DEFECT).

Run artifact: `outputs/transformation_ungate_12_NZ_rerun.log` (RESULT block).

## [2] Last conservation site ✅ Completed 2026-07-17

`prepare_transformation_assets` (`transformation_analysis_utils.py`) now routes
through `conservation_policy.build_with_conservation_policy`, and the last
`PROJECTION_STRICT_CONSERVATION` definition is deleted. **No producer chooses its
own conservation severity any more, and no duplicate flag exists to drift.** See
`docs/check_registry.md` § F5.

**Behaviour change — it used to block, it now warns.** A run that previously
halted on a transformation projection conservation failure will complete and
print `[WARN] transformation projection: strict conservation check failed;
proceeding with the non-strict allocation: …`. **A green run is no longer
evidence that conservation held — read the log**, especially on the first full
run after this. `CONSERVATION_FAILURES_ARE_ERRORS=True` restores blocking
everywhere at once.

Guarded by `tests/test_conservation_policy.py` (14 passing): every producer
imports the shared helper, neither module redefines the flag, and the site pins
no severity of its own.

## [3] Finish the header-detector routing ✅ Completed 2026-07-16

All F1 callers listed in the registry now use `leap_excel_io` detection. `patch_baseline_seeds` retains
its blank-spacer-column removal. `read_export_sheet` and, through it,
`load_export_key_table` deliberately retain the export-specific `BranchID`
header criterion; it is the ID-bearing export-format contract, not a standard
LEAP import-sheet header.

## [4] Process Efficiency backing invariant ✅ Completed 2026-07-16

`SEED-013` now blocks a final seed when a transformation process has nonzero
Exogenous Capacity but no usable Process Efficiency expression for the same
scenario and region. It deliberately validates presence and parseability only;
efficiency-value plausibility remains a separate modelling rule.

## [5] Zero-fill mechanism consolidation (stages 2–3) ✅ Completed 2026-07-16

Not blocked. See `docs/prompts/export_zero_fill_consolidation_execution_prompt.md`
  (premise corrected 2026-07-16; stage 1 is the header detector, complete).
  `export_zero_fill.zero_fill_unset_rows` now handles stage 2 (own-use and
  demand-zeroing) while preserving their separate scope and expression styles.
  Stage 3 was assessed and deliberately not migrated: transformation zero-fill
  combines measure-specific process ownership, scenario windows, 100% share
  anchors, tiered sector scope, and capacity/efficiency safeguards. Forcing it
  through the stage-2 helper would obscure those policies and risk drift. Also proposed there:
per-measure `FILL_MISSING_DEFAULTS`, since the two **reset** mechanisms are gated
but the **gap-fills** are not.

## [6] `leap_core` share-normalization divergence — dormant

Not blocked; low priority **while the LEAP API stays decommissioned**.
`_normalize_share_columns_wide` equal-splits all-zero share groups instead of
borrowing a donor scenario's profile, adds no missing canonical siblings, and has
no capacity guard. It cannot execute today (`LEAP_API_BLOCKED`), so it is
dormant. **If the API is ever re-enabled, converge this first** — see
`docs/check_registry.md` hotspot 3, which records the concrete test.

## [7] Finish the per-economy export-template rollout

> **Status 2026-07-21 — the ID-routing class is COMPLETE; 01_AUS verified safe.**
> A full re-inventory (grep the path string `full model export.xlsx`, per the
> method warning below) plus an empirical resolver check settles the dangerous
> direction. No production path stamps USA IDs onto a real economy's rows:
>
> - **Every ID-lookup / ID-borrowing site now routes per economy.**
>   `attach_export_ids` requires Region **and** Scenario to match (`12e1482`,
>   test `test_transformation_export_region_guard.py` now asserts the *safe*
>   behaviour — the 4-day-old memory listing this as "open/approved" was stale);
>   the three standalone modules' `EXPORT_ID_LOOKUP_PATH` default to `None` =
>   resolve-per-economy (`ee4e5d1`); `aggregated_demand` defaults `ID_LOOKUP_AUTO`
>   (`6714db0`); `supply_branch_classification` routes (`3756ccb`); reset scope
>   routes (`23aac52`); combined-workbook writer routes (`e799029`).
> - **Empirical resolver check** (recipe below), run 2026-07-21: `01_AUS` resolves
>   to its own **real** template `leap_export_template 01_AUS.xlsx`
>   (`is_provisional=False`), **303 of 2748** shared paths carry a *different*
>   BranchID from USA; `12_NZ` 304/2749; `20_USA` 0/3102; every `_COMP_GEN`
>   economy (`05_PRC`, `06_HKC`, `07_INA`, …) 0 discriminating paths (USA IDs
>   verbatim, as designed). So the resolver hands `01_AUS` its own area, and every
>   ID caller goes through the resolver.
> - **Remaining `full model export.xlsx` references are all deliberate**, each now
>   classified: resolver/`x or FALLBACK` fallbacks (`patch_baseline_seeds:87`,
>   `RESULTS_VERIFICATION_EXPORT_PATH`, `SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH`,
>   the standalone `EXPORT_ID_LOOKUP_PATH` constants); shared-union / shared-column
>   references by design ([11]: `fuel_catalog_preflight`,
>   `POWER_INTERIM_REFERENCE_WORKBOOK_PATH`,
>   `workflow_common.diagnose_missing_canonical_branches` (informational, never
>   raises), `ANALYSIS_INPUT_CANONICAL_TEMPLATE_PATHS` (canonical column layout,
>   shared by every area; also on the decommissioned API path)); and cross-economy
>   verification artifacts (`supply_results_saver` single-file combine at `:3796`
>   and the results-verification diagnostic at `:1772` — both now carry a comment
>   explaining the deliberate pin).
>
> **✅ END-TO-END EVIDENCE LANDED 2026-07-21 — [7] is complete for the real
> templates.** The `01_AUS` seed run (the honest remaining evidence) was run to
> completion at `b45ccc6` and its seed audited against AUS's own template:
>
> | Measurement | Result |
> | --- | --- |
> | Seed | `runs/SEED_01_AUS_TGT_REF_CA/leap_import_baseline_seed_01_AUS_20260721.xlsx` (3,432 rows, no `PRELIM` — real template) |
> | Discriminating paths (AUS vs USA template BranchID differs) | 303 |
> | Seed rows on those paths following **AUS** IDs | **504** |
> | Seed rows following **USA** IDs | **0** |
> | Seed rows on neither | **0** |
> | `Region` values in seed | `Australia` (uniform) |
> | `BranchID=-1` rows in seed | **0** |
>
> Contrast the pre-fix failure recorded in [12]: `12_NZ`'s old seed carried 507
> rows across 131 paths on **USA** BranchIDs. `01_AUS` now carries none.
>
> Run also doubles as [13] Task 7 evidence: it completed with
> `data/full model export.xlsx` **archived**, with zero file-not-found /
> `IDs will be -1` / `missing/empty` regressions in the log.
>
> **Known, pre-existing and NOT a regression:** the deferred preflight error
> (`48 row(s) have BranchID=-1 with non-zero values`). Every one is
> `Demand\Other loss and own use\Non specified own uses\*` — the migration-lag
> class already recorded in the traps section. They never reach the seed (which
> has 0 `-1` rows). Note the APEC-aggregate preflight artifact reports these with
> `Region='United States'`: that is the deliberate `GLOBAL_REGION` fallback for
> the `00_APEC` sentinel ([10]), **not** the region-routing bug — the AUS run
> proper reports them as `Region='Australia'`.
>
> Remaining under [7]: nothing for the real templates. The 18 `_COMP_GEN`
> economies still resolve to USA-derived IDs by construction and can only be
> fixed by a real per-area export ([12]) — now surfaced by the `PRELIM` seed
> naming policy.

**Not blocked.** Paced by an external event, not by other work — see the deadline.

Landed: the resolver, the combined-workbook writer, and the seed patcher resolve
per economy. **Nothing else does.** Roughly 15 module-level constants still pin
`data/full model export.xlsx` (i.e. `20_USA`'s area):

`transformation_workflow:47`, `transfers_workflow:92`,
`electricity_heat_interim_workflow:79,161`, `aggregated_demand_workflow:226`,
`other_loss_own_use_proxy_workflow:168`, `baseline_seed_comparison_workflow:615`,
`fuel_catalog_preflight:29`, `workflow_config:185,313`,
`supply_reconciliation_config:310,312`, `supply_branch_classification:20`,
`patch_baseline_seeds:86` (deliberate fallback).

Mostly mitigated today because the per-workflow producers ship the ID columns
**empty on purpose** for the combine step to fill — which is why fixing the
writer fixed the IDs. They are still live for standalone runs.

**Why this *was* safe:** 18 of 21 templates are `_COMP_GEN` — generated from the
USA area and carrying its BranchIDs **verbatim** (713 paths, 713 of 713
identical to USA; only the `Region` column is relabelled). For those, every
un-routed path and every routed path still agree, because they resolve to USA's
IDs either way.

> **Deadline — ARRIVED (measured 2026-07-17).** `01_AUS` is now a **real**
> template (`leap_export_template 01_AUS.xlsx`, no `_COMP_GEN` suffix), and was
> migrated to match `12_NZ`'s structure the same day: 645 branch paths, **133 of
> 632** paths shared with USA carry a *different* BranchID. Per the recipe below,
> "any other economy differing means a real export landed" — it has. Real
> templates are now `01_AUS`, `12_NZ`, `20_USA`.
> The system is now half-routed *in the dangerous direction* for `01_AUS`: the
> routed paths use Australia's area while the ~15 un-routed constants below
> still use USA's. `12_NZ` was tolerable only because its gaps are inert (see
> [8]); **that argument does not transfer to `01_AUS`** — nobody has shown its
> gaps are inert. Finish the rollout before trusting any `01_AUS` output.
>
> `01_AUS` and `12_NZ` now share 644 paths and differ on **143** BranchIDs —
> structurally identical, own numbering. Two real templates that agree on shape
> and disagree on IDs is precisely the configuration a pinned template silently
> corrupts.

### Liveness audit 2026-07-17 — what is actually live vs dormant

Not all ~15 constants are equal. Audited by call site (not by definition):

> **Method warning, learned the hard way.** The first pass of this audit grepped
> the *constant name* (`EXPORT_ID_LOOKUP_PATH`) and so missed
> `aggregated_demand_workflow`, which pins the same path under a different name
> (`FULL_MODEL_EXPORT_PATH`) — and that one was live, writing USA IDs into
> non-USA seeds via `patch_baseline_seeds`. **Grep the path string
> (`full model export.xlsx`), not the constant**, then classify each hit by what
> it reads the export *for*: IDs and metadata must be per economy; branch
> existence may legitimately be shared-union ([11]); aggregate/legacy fallbacks
> are deliberate. A name-based sweep gives false confidence in exactly the
> direction this work keeps failing.

| Constant | Verdict |
| --- | --- |
| `supply_leap_io` combined-workbook template | **WAS LIVE — fixed `e799029`.** `save_combined_supply_transformation_export` pinned USA while taking `economy_label`; `combined_st_12_NZ` had 126/126 discriminating paths on USA IDs, `combined_st_01_AUS` 125/125. Seeds unaffected. Verified end-to-end by a 12_NZ run: the same 126 paths flipped 0→126 following NZ. |
| `aggregated_demand_workflow:262` `FULL_MODEL_EXPORT_PATH` | **WAS LIVE — fixed `6714db0`. This audit originally missed it**: the sweep grepped `EXPORT_ID_LOOKUP_PATH`, and this module names its constant differently. `patch_baseline_seeds` calls `save_aggregated_demand_as_leap_workbook(economy=…)` with no `id_lookup_path`, so `run_patch("aggregated_demand", ["12_NZ"])` wrote NZ rows with USA BranchIDs into a seed. Now defaults to `ID_LOOKUP_AUTO`. Note `None` here means "attach no IDs" — a third, distinct value; do not conflate it with auto. |
| `supply_reconciliation_config:312` `AGGREGATED_DEMAND_ID_LOOKUP_PATH` | **DEAD — zero references** anywhere including tests. Orphaned when `cdb813d` fixed the bypass. Delete it. |
| `transformation_workflow`, `transfers_workflow`, `electricity_heat_interim_workflow` `EXPORT_ID_LOOKUP_PATH` | **WAS LIVE for standalone runs — routed `ee4e5d1`.** Nine entry points defaulted `id_lookup_path` to `20_USA`'s area; a standalone run for any other economy stamped USA BranchIDs onto its rows. Now `None` = resolve the workbook's economy; the constant remains the aggregate/no-template fallback only. The baseline-seed path was never affected (it passes no `id_lookup_path`, so the combine fills IDs). |
| `electricity_heat_interim_workflow:161` `POWER_INTERIM_REFERENCE_WORKBOOK_PATH` | **Not an ID lookup — different class, deliberately left.** It backs `validate_power_interim_fuel_coverage`, a fuel-branch *existence* check. Per [11] fuel branches are shared-union by design, so pinning is defensible here — and Workpath B's catalog work may supersede it. **Workpath B call, not routing.** Do not "fix" it by analogy with the ID lookups. |
| `supply_reconciliation_config:310` `RESULTS_VERIFICATION_EXPORT_PATH` | Mostly a deliberate fallback: `_leap_export_template_for_economy` returns it for aggregate sentinels and unresolvable economies, and `supply_preflight` uses it only via `template_path or ...` where no caller relies on the default. |
| `workflow_config:313` `SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH` | Routed in `3756ccb` ([8]); used only as `source_path if source_path is not None else ...`. |
| `patch_baseline_seeds:87` | Deliberate fallback; per-economy writing/validation already call `_template_for_economy`. |
| `fuel_catalog_preflight:29` | Shared-union catalog by design; template changes trigger incremental rebuilds. Do not make it economy-specific. See [11]. |
| `baseline_seed_comparison_workflow:615` | Standalone comparison default; pass the resolved template when template-backed validation is enabled. |

**Both next steps are done** (`ee4e5d1` standalone routing, `28dabe7` dead
constant). Every ID-lookup path identified by this audit now resolves per
economy. What remains under [7] is the wider *full-model dependency* sweep below
(metadata, branch existence, validation references) — a different class from ID
lookups, and one where a shared or aggregate source is sometimes correct. Do not
route those by analogy; classify each first.

### Patcher verification 2026-07-17 — routing confirmed; two findings

Ran `run_patch("aggregated_demand", ["12_NZ"])` to verify `6714db0` on its only
live path (a normal seed run cannot: it passes `id_lookup_path` explicitly, so
the fixed default is a no-op there).

**1. The fix is verified.** The workbook the patcher built carries the NZ area:

| `aggregated_demand_12_NZ` rows on paths where NZ and USA IDs differ | follows NZ | follows USA |
| --- | --- | --- |
| pre-fix (`20260715` seed, 24 rows) | 0 | 24 |
| post-fix (patcher-built workbook, 24 rows) | **24** | **0** |

Region is `New Zealand` on all 420 rows, confirming `39f82df` on the same path.

**2. The `20260715` seeds cannot be patched — they must be regenerated.**
`run_patch` raised: the seed itself fails validation against the NZ template
(SEED-003=33, SEED-008=78, SEED-011=33) because it was built with USA IDs. The
guard is correct; the seed is the problem. This corroborates [12]: do not try to
patch the old seeds forward, and do not read this refusal as a patcher defect.

**3. The patcher does NOT honour `BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS`,
but the main writer does.** `supply_leap_io` reads the flag and passes
`blocking_findings_are_warnings=` into `prepare_seed_rows_for_write`
(`:1013-1027`); `patch_baseline_seeds` calls the same function without it, taking
the default `False`. So the same findings are warnings in a full run and blocking
in a patch. That divergence may well be intentional — a surgical patch arguably
*should* be stricter than a full rebuild — but it is undocumented and was found
by accident. **Decide and write it down**; it is directly relevant to the open
INIT-005 review (see Known pre-existing failures).

### Remaining full-model dependency — separate follow-up

The fuel catalog no longer treats `data/full model export.xlsx` as the complete
fuel-branch source, but several other real-economy paths still use it for IDs,
metadata, branch existence, reset scope, or validation. Add and execute this as
a separate set of file-scoped tasks after the standalone routing handoff:

1. Inventory each remaining caller and classify it as per-economy, shared-union,
   aggregate fallback, or legacy-only.
2. Route real-economy ID/metadata/branch-existence checks through the resolved
   economy template **after excluding Workpath A's three standalone modules**;
   their `EXPORT_ID_LOOKUP_PATH` routing is already tracked above.
3. Review remaining zero-fill/catalog scope sources. Reset-scope routing is
   already complete in [9] (`23aac52`) and must not be reimplemented here.
4. Retain `data/full model export.xlsx` only where an explicit aggregate or
   legacy fallback is intended, and document each retained use.
5. Verify NZ first, then test the shared resolver contract for other economies;
   a full end-to-end run for every economy is not required solely to prove
   region routing.

The NZ run exposed the current priority case: `Demand\\Other loss and own use\\Non
specified own uses\\Electricity` exists in the NZ template but not in the USA
`full model export.xlsx`, so the later verification step still reports it as
unmatched. This is both a real full-model-source dependency and part of the
documented area-migration lag; do not design a permanent economy-specific
exception for it.

**First priority completed 2026-07-17:** `other_loss_own_use_proxy_workflow`
now resolves its export-key workbook from the requested economy's template.
The USA full-model export remains an explicit fallback for aggregate or
unresolved-template cases and an explicit override for tests/custom callers.
The remaining full-model uses still need separate classification, especially
multi-economy verification artifacts that cannot use one economy's IDs for all
rows.

**Verification recipe that worked** (reuse it): compare `_build_id_lookups`
across every template — 20 economies must come back *identical* to the legacy
export, `12_NZ` must differ (646 vs 714 branch paths, 134 of 634 shared paths
with a different BranchID). Any other economy differing means a real export
landed and the deadline above has arrived.

**Watch for the bypass.** `073c489` routed the writer and was a **no-op in
production** for a day, because both real callers passed
`id_lookup_path=AGGREGATED_DEMAND_ID_LOOKUP_PATH` explicitly and took the
override branch. Fixed in `cdb813d`. When routing anything here, check the
*callers*, not just the function — and note the tests passed throughout, because
they pin the template explicitly too, exercising the very branch that masked it.

## [13] Retire / archive `data/full model export.xlsx` — scoped 2026-07-21

**Not blocked; follow-on to [7].** ID-routing no longer depends on this file, but
it is still read at runtime as the **shared-union fuel-catalog source** (currently
the *sole* source under `LEAP_API_BLOCKED`), the **cross-economy single-file /
verification reference**, and several **fallbacks**. Archiving is a
*repoint-and-verify* task (repoint these uses at the canonical `20_USA` template),
not a delete. Full inventory, sequenced one-commit tasks, and the acceptance gate:
[full_model_export_retirement_scope.md](full_model_export_retirement_scope.md).
**Task 0 gates the rest:** confirm `full model export.xlsx` ≡
`leap_export_template 20_USA.xlsx` before repointing anything.

## [8] `supply_branch_classification` threading — completed 2026-07-16

Landed in `3756ccb`. `supply_export_builder` now passes the current economy's
resolved template through both Resources branch-label/existence lookups, and
the lookup caches are keyed by source workbook. The implementation is covered
by the resolver and supply-production regression tests.

The warning-deduplication sets remain global rather than source-keyed. This is
only a logging limitation (one economy's missing-branch warning can suppress
another's) and is not a data-routing concern; leave it until warning reporting
is revisited deliberately.

## [9] Reset-scope chain ✅ Completed in `23aac52` — verified 2026-07-17

**This item was already done when it was written down.** It described an unkeyed
cache and zero-argument helpers; `23aac52` had already routed both. Re-verified
against the tree 2026-07-17 before starting work — nothing to implement:

- `_RESET_SCOPE_FROM_EXPORT_CACHE` **is** keyed, by resolved source path
  (`supply_preflight.py:580`), so entries cannot cross templates.
- `_load_reset_scope_from_full_model_export`, `_configured_reset_module_names`,
  `_configured_reset_fuel_labels` and
  `_configured_reset_output_fuel_labels_by_module` all take `template_path`.
- **No call site anywhere relies on the `None` default** (which would fall back
  to `RESULTS_VERIFICATION_EXPORT_PATH`, i.e. USA). Verified by grep.
- `reset_supply_and_transformation_import_export_to_zero`
  (`supply_reconciliation_tables.py:1741`) **self-partitions**: >1 economy in the
  reconciliation table → it recurses per economy with
  `template_path=resolve_leap_export_template(economy)` (`:1807`); exactly 1 →
  same resolver (`:1815`). Its `supply_results_saver:3159` caller therefore
  correctly passes no template.
- `supply_leap_io:485` resolves per economy inside an economy-keyed loop.

Focused suite passes: **72** (`test_reset_scope_template_routing`, template
resolver, check registry) — the same count the NZ readiness doc recorded.

**One residual edge, not worth chasing:** if a reconciliation table has no
`economy` column at all, `unique_economies` is empty, neither partition branch
fires, and `template_path` stays `None` → the USA fallback. Not reachable from
the current callers, which always carry `economy`.

## [10] `GLOBAL_REGION` — ✅ decided and implemented 2026-07-17 (`39f82df`, `12e1482`)

**Decided:** region resolves per economy; the global survives only as a fallback
for codes with no APEC region entry (so the `00_APEC` sentinel, and the preflight,
are unchanged). `39f82df` routed the aggregated-demand, own-use-proxy and
demand-zeroing writers via `get_region_for_economy`; `12e1482` removed
`attach_export_ids`' ID-borrowing fallbacks.

**It was not the cosmetic cleanup this section assumed.** The mismatch *deleted
data*: the seed writer keeps only rows whose branch resolves, so a "United States"
label made a non-USA lookup fail and the rows were dropped before reaching the
seed — `12_NZ` was silently losing 9 rows including 465.5 PJ of own-use
electricity.

**Correction to the analysis below** (kept for the record, but it is wrong):
`resolve_export_region_from_process_economies` is **not** redundant post-hoc
patching. All four callers of `save_transformation_export` pass the global
`core.EXPORT_REGION = "United States"`, so that resolver is the *only* thing
giving transformation exports a correct per-economy region. Removing it would
reintroduce the bug. Its multi-region raise is independently valuable.

**Follow-up, own commit, not urgent:** transformation infers its economy from
`process_records` while every other writer is *told* the economy — so its `region`
parameter is a lie (passed, then discarded). Preferred end state: pass `economy`
explicitly like the other writers, derive region from it, and keep the resolver
as a cross-check that the records agree with the declared economy. Consistency
plus the guard.

### Original analysis (superseded, retained for context)

`workflow_config:70` hardcodes `GLOBAL_REGION = "United States"`, then
`transformation_record_builder.resolve_export_region_from_process_economies`
maps `01_AUS` → `Australia` over the top of it, and `attach_export_ids` tolerates
region-only mismatches (`tests/test_transformation_export_region_guard.py:37`).

That accommodation exists *because* one template served every economy. Each
template now carries its own `Region` column, so the global plus its post-hoc
patching is redundant — but removing it is a behaviour change with its own blast
radius. Every template uses `RegionID=1`, so region **IDs** need no work.
Decide deliberately; do not fold it into a threading commit.

## [11] `fuel_catalog_preflight` — shared-union design decision

The fuel catalog is intentionally a **shared union of valid fuels**, not an
economy-specific branch catalog. The LEAP model is being built so every economy
area contains fuels that may be used by any economy for the relevant sector.
Therefore the catalog should validate generated fuel scopes against the union,
even when an individual economy's template does not yet contain every member of
that union.

`12_NZ` is currently the most up-to-date real economy template and is the primary
real-template validation case. A clean NZ run is sufficient evidence for the
current routing work; USA/AUS and other economies do not need separate end-to-end
runs merely to prove region handling, provided the resolver correctly selects the
economy template and preserves template differences.

Open implementation check: confirm that the catalog-building path actually
constructs the intended union rather than treating `data/full model export.xlsx`
(the USA export) as the complete source. Do not make the catalog economy-specific.

### Catalog filename transition

The canonical output is now `leap_fuel_branch_catalog.csv`. For compatibility,
the old `transformation_supply_fuel_branch_catalog.csv` is written as a second
copy and remains readable as a fallback. Remove the legacy copy only after:

1. repository code and archived workflows read the canonical filename;
2. downstream notebooks, scheduled jobs, and external review scripts have been
   checked for the old filename; and
3. at least one complete workflow run has produced and consumed the canonical
   file successfully.

At that point, stop writing the compatibility copy, update the output manifests,
and delete the old file from generated output directories. Do not remove it
merely because the new file exists; the old name may still be used by external
review tooling.

## [12] Baseline-seed trustworthiness — audited 2026-07-17, regeneration is NOT the answer

Audit of `SEED_21ECON_0E555F_TGT_REF_CA` against each economy's *resolved*
template (script pattern: compare seed BranchID to template BranchID, restricted
to paths where template and USA **disagree** — otherwise the comparison is not
discriminating).

| Fact | Measurement |
| --- | --- |
| Seeds in the "21ECON" run | **20** — there is no `01_AUS` seed. The label is wrong. |
| `12_NZ` | **507 rows across 131 paths carry USA BranchIDs.** Proven contaminated. Regenerated correctly 2026-07-17 (`SEED_12_NZ_TGT_REF_CA`, 0 of 3,378 rows disagree). |
| `20_USA` | Trivially correct (it *is* the pinned area). |
| The other 18 | Template is `_COMP_GEN`, i.e. USA's BranchIDs verbatim → **0 discriminating paths**. The seed agrees with its template *for the wrong reason*. |

**A full 21-economy regeneration would be close to a no-op and must not be
treated as the next milestone.** For the 18 `_COMP_GEN` economies the resolver
hands back a USA-derived template, so a regenerated seed lands on the *same* IDs
it already has. Regeneration cannot fix them; only a **real per-area export**
can. That makes [7]'s deadline — not regeneration — the gating milestone.

What regeneration *does* buy today: `01_AUS` (real template, absent from the
baseline) and the `Region` label fix ([10]).

**Do not use this baseline as a correctness reference.** It is the exact failure
mode recorded in the traps section: both sides of the diff agree because both
carry the same distortion.

---

## Known pre-existing failures — not regressions, do not chase

- `tests/test_baseline_seed_writer_validation.py` — **3 failures**, and they are
  **an intentional open deviation, not stale tests and not a regressed guard**
  (diagnosed 2026-07-17; an earlier revision of this entry guessed "stale or
  regressed" and was wrong on both):
  `test_final_writer_writes_diagnostics_before_conflict_blocks`,
  `test_writer_accumulates_economy_failures_and_writes_no_final_workbook`,
  `test_default_reference_validation_window_requires_2023_through_2060`.

  **Sole cause:** `workflow_config.py:91`
  `BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS = True`, set at the
  user's instruction on 2026-07-10. The comment at `workflow_config.py:79-91`
  names these three tests. Monkeypatching the flag to `False` turns all 16 green.
  Mechanism: `prepare_seed_rows_for_write` (`baseline_seed_validation.py:1835`)
  clears the `blocking` column, and the raise at `supply_leap_io.py:1977-1984` is
  gated on `blocking` being non-empty. (SEED-012 tests still pass because their
  findings are appended at `supply_leap_io.py:1960-1961`, after that path.)
  Test 3 is the same cause, not a config move: `BASE_YEAR=2022`/`FINAL_YEAR=2060`
  are intact and the sibling window test passes; SEED-009 simply no longer blocks.

  **Do not touch the tests** — they assert the confirmed INIT-005 behaviour and
  go green the moment the guard is restored. The recorded sequence is: complete
  the findings-clearing run, then revert the flag to `False`. See INIT-005
  History in `docs/special_rules_and_design_decisions.md:265-292`. The flag has
  only ever been *committed* as `True`; the 2026-07-10 `False` period was
  working-tree only.

  **The real open question is a judgement call, pending since 2026-07-10:**
  whether the current blocking findings are genuinely insignificant enough to
  leave the flag `True`. Read the latest `*_consolidated_rule_findings.csv` to
  settle it.

  **Gap worth closing meanwhile:** nothing pins this deviation as intentional —
  three unexplained reds are the same shape as "a guard stopped blocking and
  nobody noticed", which is why it was misdiagnosed above. If the flag stays
  `True` for any length of time, mark them `xfail(reason=...)` naming the flag,
  so the suite is green *and* the deviation stays visible.

- `tests/test_supply_assets.py::test_prepare_supply_assets_maps_names_aggregates_and_builds_lookup`
  — **stale test**. It monkeypatches `apply_matt_subtotal_mapping`, which now
  only exists under `archive/` and `scrapbook/`. Verified failing at HEAD
  independently of any current work. Either update or delete the test.
- ~~`tests/test_module_attribute_contracts.py::test_no_bare_name_misattribution[codebase.functions.supply_leap_io]`~~
  — **cleared.** Was failing mid-flight while the export-template work was
  uncommitted; passes at `6bda122` (39/39). Left here only to stop it being
  re-reported. This is what a verification run against a dirty tree looks like
  from the outside.

## Traps that already cost time — recorded so they are not rediscovered

- **Never diff raw export output against a finished seed.** The seed writer
  (`prepare_seed_rows_for_write` → `complete_canonical_share_groups`) does
  canonical share completion and cross-scenario borrowing. Comparing pre-boundary
  output to a post-boundary seed **manufactures false differences** — this is
  what the transformation gate's premise appears to rest on. Always compare
  post-boundary.
- **Always resolve the template per economy** (`_template_for_economy`), never a
  pinned `FULL_MODEL_EXPORT_PATH`. Each economy is a separate LEAP area. This
  fails in the *dangerous* direction: seeds built pre-resolver share the same
  distortion, so both sides of the diff agree and the check reports **EQUIVALENT
  for the wrong reason**.
- **Areas differ only because a migration is unfinished — they do NOT
  "legitimately lack branches".** Corrected 2026-07-17; the earlier wording here
  taught the wrong reason. Every area is intended to be structurally identical
  apart from its own IDs (and possibly Resources fuel distribution) — see
  *Areas are structurally identical by intent* in `data/README.md`. With a
  correct per-economy template, `12_NZ` surfaces 33
  `Non specified transformation\...\Auxiliary Fuels\*` rows (Biogasoline,
  Electricity, …) as *only-in-seed* / `BranchID=-1`, and 123 own-use
  `Oil refineries` rows likewise — 156 in total. `12_NZ` has 646 branch paths to
  `20_USA`'s 714 **because `12_NZ` is the first area migrated, not because New
  Zealand is different.** (It is true that NZ's only refinery closed in 2022;
  that coincidence makes the wrong reading tempting. The branch is being deleted
  from every area regardless.)
  **Confirmed harmless 2026-07-16, reason corrected 2026-07-17:** all 156 are
  zero-valued, so they are genuine no-ops (per `data/README.md`, a *nonzero* `-1`
  row would be actionable — an intended value silently skipped). Signed off:
  leave them; they resolve when the other areas migrate. Do **not** add fallback
  logic or per-area special cases to make them go away. If a *nonzero* `-1` ever
  appears for NZ, that is new and real — which is why the writer's
  `[WARN] … unresolved BranchID=-1` should stay.
- **Multi-output WIP signature.** If capacity, historical production, efficiency,
  output shares and aux-fuel ratios all move by **one exact ratio**, that is the
  output *set* changing (a fuel counted as output rather than feedstock), not a
  patch-path defect. Observed: USA coke ovens ×1.16676, NZ blast furnaces ×1.04001.

## Landed 2026-07-16 — do not redo

- **LEAP API decommissioned structurally.** The real leak was that all five
  API-import guards in `supply_leap_io` read
  `get_analysis_input_write_mode() == "api" and not leap_api.is_available()`,
  which is False in workbook mode — so workbook runs attempted every API import
  anyway and swallowed the guard's `RuntimeError` as a WARN. Guards decoupled,
  toggles default False, locked by `tests/test_leap_api_decommissioned.py`.
- **Projection conservation severity unified** behind
  `functions/conservation_policy.py` (warn by default;
  `CONSERVATION_FAILURES_ARE_ERRORS=True` to raise). 4 of 5 sites migrated; one
  duplicate flag deleted. See [2] for the remainder.
- **Check registry + contract test** — `docs/check_registry.md` plus
  `tests/test_check_registry.py`, which caught the registry going stale within
  minutes of being written.
- **Shared LEAP header detector** — `find_leap_header_row` / `read_leap_sheet` in
  `leap_excel_io`; two callers routed. See [3].
- **`leap_core` breakpoints** — 26 raw `breakpoint()` calls now route through the
  repo's guarded `esto_data_utils.try_debug_breakpoint()`.
- **Transformation output/efficiency corrections** — multi-output is now the
  default for flow sectors, sub-percent feedstock shares are not double-scaled,
  and missing Process Efficiency has a capacity guard. See [0].
- **Own-use proxy and APEC preflight corrections** — non-specific own use is
  proxied from total transformation throughput, balance activity signs are
  aligned with ESTO/9th, and synthetic APEC preflight sources are generated
  only for the APEC path.

## Related documents

- [check_registry.md](check_registry.md) — every pre-export check, five families, rules A/B/C, hotspots.
- [baseline_seed_rule_inventory.md](baseline_seed_rule_inventory.md) — SEED-C rule detail.
- [prompts/patch_baseline_seeds_module_verification_prompt.md](prompts/patch_baseline_seeds_module_verification_prompt.md) — patch verification recipe + transformation reassessment.
- [prompts/export_zero_fill_consolidation_execution_prompt.md](prompts/export_zero_fill_consolidation_execution_prompt.md) — F1 consolidation.
- [prompts/transformation_multi_output_default_verification_prompt.md](prompts/transformation_multi_output_default_verification_prompt.md) — deferred full-run verification of the confirmed multi-output fix.
- [prompts/baseline_seed_aus_things_to_check.md](prompts/baseline_seed_aus_things_to_check.md) — focused checks for the next Australia seed refresh.
