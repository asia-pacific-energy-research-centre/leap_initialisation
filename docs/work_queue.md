# Remaining work queue

Single source of truth for *what is left, in what order, and what blocks what*
across the supply-reconciliation / baseline-seed work. Cross-references the
detail rather than duplicating it.

> Living document — last reconciled with the tree **2026-07-17**. Re-check
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

**Current owner:** routing agent. **Status:** active and paused at the shared-helper handoff.

Primary files:

- `codebase/transformation_workflow.py`
- `codebase/transfers_workflow.py`
- `codebase/electricity_heat_interim_workflow.py`
- shared template-resolution helpers, if required

Objective: route standalone `EXPORT_ID_LOOKUP_PATH` entry points through the
economy-specific template resolver. Do not edit these files from Workpath B
until the routing work is handed back and verified.

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

### Shared-helper handoff — required before Workpath A continues

Workpath A needs aggregate-aware template resolution for `00_APEC` and for
economies without a dedicated template. The current wrapper is
`_leap_export_template_for_economy` in `codebase/functions/supply_leap_io.py`,
which is held by Workpath B, while the resolver primitives live in
`codebase/utilities/leap_export_template_resolver.py`.

The agreed solution is to promote the aggregate-aware wrapper into public API in
`leap_export_template_resolver.py`, leaving a thin compatibility alias in
`supply_leap_io.py`. This is a coordinated two-workpath change. Do not import a
private function across the workpaths or duplicate the wrapper in the three
standalone workflow modules.

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

## [1] Transformation ungate

**Ready.** See `docs/prompts/patch_baseline_seeds_module_verification_prompt.md`
(§ transformation auto-regen sectors) for the full reassessment and the definitive test.

The gate (`run_patch` raises `NotImplementedError` for any module with
`auto_sector_keys`) may rest on a measurement artifact — its evidence appears to
have compared **raw** helper output against a finished seed, skipping the seed
writer. That is **not yet evidenced**: the AUS/USA runs that suggested it were
themselves confounded (pinned template + multi-output WIP) and were retracted.

To settle it, run with **both** controls in place:
- `_template_for_economy(econ)` per economy (never a pinned `FULL_MODEL_EXPORT_PATH`), and
- clean HEAD transformation code (e.g. a temporary `git worktree` at HEAD with
  seed/data paths pointed back at the main repo).

Note ungating is **not just deleting the gate**: the patcher's transformation path
uses `_collect_auto_regen` (the simplified path), **not**
`save_transformation_exports_with_split_targets`. Ungating means rewiring
transformation to be workbook-based via that helper (the `transfers` model), then
dropping the gate.

## [2] Last conservation site

**Ready** (lives in `transformation_analysis_utils.py`).

`transformation_analysis_utils.py:1820` still chooses its own strictness via the
last surviving `PROJECTION_STRICT_CONSERVATION` (`:137`), so it **blocks** while
every other producer warns. Migrate it to
`conservation_policy.build_with_conservation_policy` and delete the flag. See
`docs/check_registry.md` § F5. It errs on the stricter side meanwhile, so this is
not urgent.

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

| Constant | Verdict |
| --- | --- |
| `supply_leap_io` combined-workbook template | **WAS LIVE — fixed `e799029`.** `save_combined_supply_transformation_export` pinned USA while taking `economy_label`; `combined_st_12_NZ` had 126/126 discriminating paths on USA IDs, `combined_st_01_AUS` 125/125. Seeds unaffected. |
| `supply_reconciliation_config:312` `AGGREGATED_DEMAND_ID_LOOKUP_PATH` | **DEAD — zero references** anywhere including tests. Orphaned when `cdb813d` fixed the bypass. Delete it. |
| `transformation_workflow:47`, `transfers_workflow:92`, `electricity_heat_interim_workflow:79`, `:161` `EXPORT_ID_LOOKUP_PATH` | **Standalone-only, still un-routed.** Defaults on `assemble_*_workbook` / `run_*_export_and_import` / `run_*_pipeline`. The baseline-seed path never passes `id_lookup_path`, so `save_transformation_export` skips `attach_export_ids` and the combine fills IDs. These pipelines already take `economies=`, so routing them is the same `None`-means-resolve pattern. **Live the moment anyone runs a standalone pipeline for a real-template economy — which now includes `01_AUS`.** |
| `supply_reconciliation_config:310` `RESULTS_VERIFICATION_EXPORT_PATH` | Mostly a deliberate fallback: `_leap_export_template_for_economy` returns it for aggregate sentinels and unresolvable economies, and `supply_preflight` uses it only via `template_path or ...` where no caller relies on the default. |
| `workflow_config:313` `SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH` | Routed in `3756ccb` ([8]); used only as `source_path if source_path is not None else ...`. |
| `patch_baseline_seeds:87` | Deliberate fallback; per-economy writing/validation already call `_template_for_economy`. |
| `fuel_catalog_preflight:29` | Shared-union catalog by design; template changes trigger incremental rebuilds. Do not make it economy-specific. See [11]. |
| `baseline_seed_comparison_workflow:615` | Standalone comparison default; pass the resolved template when template-backed validation is enabled. |

**Next concrete step:** route the standalone `EXPORT_ID_LOOKUP_PATH` entry points
(transformation / transfers / electricity-heat). They take `economies=` already;
default `id_lookup_path` to `None` and resolve per economy, keeping the constant
only as a fallback. Delete `AGGREGATED_DEMAND_ID_LOOKUP_PATH` as its own commit.

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
