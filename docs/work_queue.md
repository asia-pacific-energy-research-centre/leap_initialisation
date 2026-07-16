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

Almost everything outstanding funnels through one thing:

```
[0] land/park the in-flight transformation work
      ├── unblocks [1] transformation ungate
      ├── unblocks [2] last conservation site
      └── unblocks [3] remaining header routes (partly)
```

---

## [0] BLOCKER — land or park the in-flight transformation work

**Status:** blocking. **Owner:** the multi-output / process-efficiency workstream.

Dirty: `transformation_analysis_utils.py`, `transformation_record_builder.py`,
`transformation_sector_analysis.py`, plus untracked
`tests/test_process_efficiency_zero_fill.py` and
`docs/prompts/transformation_multi_output_default_verification_prompt.md`.

**Why it blocks everything:** on 2026-07-16 a 12_NZ + 20_USA transformation
equivalence check returned large diffs that were **entirely** explained by this
uncommitted code, not by the thing under test. Until it lands, no transformation
verification means anything.

Its blast radius is worth reviewing on its own merits before it lands: it
reclassifies fuels (Coke oven gas moves feedstock → output), which cascades into
capacity, historical production, efficiency, output shares and aux-fuel ratios
simultaneously — USA coke ovens **+17%** efficiency (60.97 → 71.14), NZ blast
furnaces **+4%**. Every `20260715` seed predates it.

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

---

## Known pre-existing failures — not regressions, do not chase

- `tests/test_supply_assets.py::test_prepare_supply_assets_maps_names_aggregates_and_builds_lookup`
  — **stale test**. It monkeypatches `apply_matt_subtotal_mapping`, which now
  only exists under `archive/` and `scrapbook/`. Verified failing at HEAD
  independently of any current work. Either update or delete the test.
- `tests/test_module_attribute_contracts.py::test_no_bare_name_misattribution[codebase.functions.supply_leap_io]`
  — was failing on in-flight `leap_export_template_resolver` usage
  (`reference_df`, `id_lookup_resolved`, `branch_to_id`, … referenced but not
  imported). Should clear once that work settles; re-check rather than assume.

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
  `12_NZ` surfaces ~33 `Auxiliary Fuels` rows as *only-in-seed*. That is a real
  area gap, not a patch defect. Only-in-seed normally reads as a hard failure —
  classify by area first.
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
