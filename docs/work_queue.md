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

## The blocker structure

The transformation prerequisite has landed. The export-template track is paced
by an external event; the remaining checks/refactors below are ready for a
single agent to take one at a time.

```
[0] transformation output/efficiency corrections (completed 2026-07-16)
      ├── [1] transformation ungate
      ├── [2] last conservation site
      ├── [3] remaining header routes
      ├── [4] Process Efficiency backing invariant
      └── [9] reset-scope chain

[7] finish the per-economy export-template rollout   <- not blocked
      deadline: the first real (non-COMP_GEN) economy export
      ├── [8]  supply_branch_classification threading (completed 2026-07-16)
      ├── [9]  reset-scope chain
      └── [10] GLOBAL_REGION decision
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

## [9] Reset-scope chain

**Ready.** `supply_preflight.py` is clean and its aggregate-source preflight
support landed in `560353d`.

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
