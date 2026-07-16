# Remaining work queue

Single source of truth for *what is left, in what order, and what blocks what*
across the supply-reconciliation / baseline-seed work. Cross-references the
detail rather than duplicating it.

> Living document — last reconciled with the tree **2026-07-16**. Re-check
> `git status --short` before trusting the "blocked" markers.

## How to use this

1. **One issue at a time. One issue → one commit.** Each item below is sized to
   land on its own.
2. **Before starting, the files you will touch must be clean** (`git status --short`).
   Editing a file another agent holds is how work gets silently lost.
3. **Verification runs against a dirty tree are unreadable.** See the blocker
   below — this is not a style preference, it cost a retracted conclusion.

## The blocker structure

Two independent tracks. The transformation track funnels through one blocker;
the export-template track is blocked by nothing and paced by an external event.

```
[0] land/park the in-flight transformation work
      ├── unblocks [1] transformation ungate
      ├── unblocks [2] last conservation site
      └── unblocks [3] remaining header routes (partly)

[7] finish the per-economy export-template rollout   <- not blocked
      deadline: the first real (non-COMP_GEN) economy export
      ├── [8]  supply_branch_classification threading
      ├── [9]  reset-scope chain
      └── [10] GLOBAL_REGION decision
```

---

## [0] BLOCKER — land or park the in-flight transformation work

**Status:** blocking. **Owner: unidentified — not either agent.** Verified
2026-07-16: none of the eight commits from the export-template or
zero-fill/registry workstreams (`10cb432`, `073c489`, `cdb813d`, `6bda122`,
`af0662c`, `1fd4a19`, `60b6600`, `5c6b34a`) touch any `transformation_*` file.
Both agents' work is committed. **Neither can land or park this** — whoever
authored the multi-output / process-efficiency change must. Do not ask an agent
to commit it: nobody has read it, and committing unreviewed work across a
four-workstream dirty tree is how the regression below got in unnoticed.

Dirty: `transformation_analysis_utils.py`, `transformation_record_builder.py`,
`transformation_sector_analysis.py`, plus untracked
`tests/test_process_efficiency_zero_fill.py` and
`docs/prompts/transformation_multi_output_default_verification_prompt.md`.

**Why it blocks everything:** on 2026-07-16 a 12_NZ + 20_USA transformation
equivalence check returned large diffs that were **entirely** explained by this
uncommitted code, not by the thing under test. Until it lands, no transformation
verification means anything.

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

**Evidence already gathered here (feeds that prompt's validation steps 2-4):**
the 2026-07-16 NZ+USA run corroborates the intended signature — efficiency and
aux ratios shifted exactly as the added output implies (their step 3), and share
sums still reach 100% (NZ: 96.152607 + 3.847393). Their step 4 assumes "USA
blast furnaces unaffected" — true here (only coke ovens moved) — but **NZ blast
furnaces gained `Other recovered gases` (+4%)**, i.e. a newly-multi-output sector
in another economy, which is exactly the gap that prompt says it did not cover.

---

## [1] Transformation ungate

**Blocked by [0].** See `docs/prompts/patch_baseline_seeds_module_verification_prompt.md`
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

**Blocked by [0]** (lives in `transformation_analysis_utils.py`).

`transformation_analysis_utils.py:1820` still chooses its own strictness via the
last surviving `PROJECTION_STRICT_CONSERVATION` (`:137`), so it **blocks** while
every other producer warns. Migrate it to
`conservation_policy.build_with_conservation_policy` and delete the flag. See
`docs/check_registry.md` § F5. It errs on the stricter side meanwhile, so this is
not urgent.

## [3] Finish the header-detector routing

Partly blocked: `supply_leap_io` / `supply_results_saver` sit in the
export-template work area.

`leap_excel_io.find_leap_header_row` / `read_leap_sheet` exist and two callers are
routed. Remaining callers, their quirks, and their scan depths are tabulated in
`docs/check_registry.md` § F1 ("Header-parsing drift"):
`patch_baseline_seeds._find_header_row` (needs `drop_blank_columns=True`),
`supply_leap_io._read_leap_data` + `_read_workbook_sheet_with_header_detection`,
`supply_results_saver._find_header_row`, `leap_excel_io.read_export_sheet`
(different `BranchID` criterion — decide whether to unify), and
`load_export_key_table` (drop its hardcoded `header=2` — the format-drift risk).

## [4] Process Efficiency backing invariant

**Coupled to [0]** (same workstream/files).

`baseline_seed_validation.py` contains **zero** references to "Efficiency".
Nothing catches "nonzero Exogenous Capacity, no Process Efficiency", so per the
registry's rule B the efficiency gap-fill is **not safe to gate**: the fill is
currently the only safety net. If it is made optional
(`FILL_MISSING_DEFAULTS`), pair it with a capacitied-process-must-have-efficiency
invariant mirroring the share capacity-guard. Worth adding regardless. See
`docs/check_registry.md` hotspot 2.

## [5] Zero-fill mechanism consolidation (stages 2–3)

Not blocked. See `docs/prompts/export_zero_fill_consolidation_execution_prompt.md`
(premise corrected 2026-07-16; stage 1 is the header detector, partly done).
Stage 2 = own-use + demand-zeroing gap-fill onto a shared helper; stage 3 =
transformation (most entangled — skip if it contorts). Also proposed there:
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

**Why this is currently safe, and exactly when it stops being safe:** 19 of 21
templates are `_COMP_GEN` — generated from the USA area and carrying its
BranchIDs **verbatim** (0 of 714 differ; only the `Region` column is relabelled).
So every un-routed path and every routed path agree today, because they all
resolve to USA's IDs either way.

> **Deadline.** The first time a real (non-`COMP_GEN`) export lands for any
> economy, the routed paths use that economy's area while the un-routed paths
> still use USA's — and they silently disagree about which area they are in.
> A half-routed system is worse than either end state. `12_NZ` is already real;
> it is only safe because its remaining gaps happen to be inert (see [8]).

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

## [8] `supply_branch_classification` threading

**Not blocked.** Depends on [7]'s direction.

The three lookups are cached per source workbook (`10cb432`), and the loaders
take a `source_path` — but **nothing passes it**. `supply_export_builder:256,264`
still call `_resolve_supply_branch_label_from_export` /
`_supply_branch_exists_in_export_source` bare, so Resources `Primary`/`Secondary`
classification and branch-existence use USA's export for every economy.

**Inert today, by luck not design:** `12_NZ` and `20_USA` classify all **70**
Resources fuels identically — 0 differences, none missing either side. So the
gap cannot bite until an economy's Resources tree diverges. Re-run the
comparison when any real export lands; do not assume it still holds.

Note `_SUPPLY_ROOT_LOOKUP_MISS_WARNED` / `_SUPPLY_BRANCH_PATH_MISS_WARNED` remain
unkeyed (warn-once dedupe only, not data). `supply_export_builder` imports the
latter and mutates it as a set, so reshaping it touches two modules.
Consequence is minor: one economy's missing-fuel warning suppresses another's.

## [9] Reset-scope chain

**Blocked by [0]** (`supply_preflight.py` is dirty).

`supply_preflight._load_reset_scope_from_full_model_export` derives the
transformation reset/zeroing scope from the single export, behind another
unkeyed module cache (`_RESET_SCOPE_FROM_EXPORT_CACHE`), via zero-argument
helpers `_configured_reset_module_names` / `_configured_reset_fuel_labels`
called from **five** modules (`supply_reconciliation_workflow`, `supply_leap_io`,
`supply_results_saver`, `supply_reconciliation_tables`, `supply_preflight`).

This is the sharpest edge of [7]'s deadline: reset scope built from USA's 714
branches applied to an economy with 646 resets branches that economy lacks.

## [10] `GLOBAL_REGION` — open decision, not a task

`workflow_config:70` hardcodes `GLOBAL_REGION = "United States"`, then
`transformation_record_builder.resolve_export_region_from_process_economies`
maps `01_AUS` → `Australia` over the top of it, and `attach_export_ids` tolerates
region-only mismatches (`tests/test_transformation_export_region_guard.py:37`).

That accommodation exists *because* one template served every economy. Each
template now carries its own `Region` column, so the global plus its post-hoc
patching is redundant — but removing it is a behaviour change with its own blast
radius. Every template uses `RegionID=1`, so region **IDs** need no work.
Decide deliberately; do not fold it into a threading commit.

## [11] `fuel_catalog_preflight` — open question, not a task

`DEFAULT_FULL_MODEL_EXPORT_PATH` pins the single export. **Whether the fuel
catalog is even economy-specific is unresolved** — fuel *names* may legitimately
be shared across areas, in which case pinning is correct and should be documented
as deliberate rather than "fixed". Answer the question before touching it.

---

## Known pre-existing failures — not regressions, do not chase

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
- **Areas legitimately lack branches.** With a correct per-economy template,
  `12_NZ` surfaces 33 `Non specified transformation\...\Auxiliary Fuels\*` rows
  (Biogasoline, Electricity, …) as *only-in-seed* / `BranchID=-1`. That is a real
  area gap, not a patch defect — `12_NZ` has 646 branch paths to `20_USA`'s 714.
  Only-in-seed normally reads as a hard failure; classify by area first.
  **Confirmed harmless 2026-07-16:** all 33 are zero-valued, so they are genuine
  no-ops (per `data/README.md`, a *nonzero* `-1` row would be actionable — an
  intended value silently skipped). Signed off: leave them. If a *nonzero* `-1`
  ever appears for NZ, that is new and real — which is why the writer's
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

## Related documents

- [check_registry.md](check_registry.md) — every pre-export check, five families, rules A/B/C, hotspots.
- [baseline_seed_rule_inventory.md](baseline_seed_rule_inventory.md) — SEED-C rule detail.
- [prompts/patch_baseline_seeds_module_verification_prompt.md](prompts/patch_baseline_seeds_module_verification_prompt.md) — patch verification recipe + transformation reassessment.
- [prompts/export_zero_fill_consolidation_execution_prompt.md](prompts/export_zero_fill_consolidation_execution_prompt.md) — F1 consolidation.
