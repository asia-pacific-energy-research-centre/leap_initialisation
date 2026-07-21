# Phase 3 - canonical mapping migration: execution plan

Type: implementation + verification brief. Status: active, re-scoped 2026-07-21.

## Short version

`AGENTS.md` says Phase 3 is "connect the seven workflow scripts to
`outlook_mappings_master.xlsx`, blocked on leap_mappings M2". **Both halves of
that sentence are now out of date.** M2 is done, and the initialisation-side
migration of runtime mapping reads is done. What is left is *not* a workbook
repoint; it is **schema-contract hardening, ownership, dead-path cleanup, and
the output-equivalence evidence that was explicitly deferred at migration
time.** Do not open this phase by grepping for legacy workbook paths and
swapping them - that work already happened and re-doing it mechanically will
regress deliberate compatibility layers.

Read `docs/canonical_mapping_migration_notes.md` in full before touching code.

## Current-state evidence

### The stated blocker (M2) is cleared

Verified in `C:\Users\Work\github\leap_mappings` (read-only) on 2026-07-21:

| Claim in `AGENTS.md` | Measured reality |
|---|---|
| Stage 1-3 scripts read `config/leap_mappings.xlsx` | All three read `config/outlook_mappings_master.xlsx`: `mapping_tools/build_energy_balance_relationships.py:2045`, `build_common_esto_structure.py:1764`, `apply_common_esto_structure.py:1766` |
| `_find_repo_root` keys off `config/leap_mappings.xlsx` | All three key off `AGENTS.md` + `config/outlook_mappings_master.xlsx` (`:279/:128/:134`) |
| Rollup rules not applied at Stage 1 | `build_energy_balance_relationships.py:1630` loads the three rollup sheets; downstream rollup work has since landed (`4042d5e`, `89887fa`, `6f03197`) |

So the dependency arrow "Phase 3 waits on M2" should be deleted from
`AGENTS.md`, not re-asserted.

### The initialisation-side migration already landed

`docs/canonical_mapping_migration_notes.md` records changes C1-C7. Verified
still true at HEAD:

- `codebase/mappings/canonical_loaders.py` is the single validated entry point.
  It already does the "validate expected sheets and columns before processing
  begins" that `AGENTS.md` lists as the Phase 3 deliverable: it raises
  `CanonicalMappingError` naming workbook, sheet and missing columns rather
  than falling back (`_resolve_workbook`, `load_canonical_sheet`).
- `tests/test_canonical_only_mapping_sources.py` guards against reintroducing
  legacy master-config mapping reads.
- Display-name resolution is canonical in supply, transformation, transfers
  (`supply_config_builder.load_code_to_name_mapping`,
  `transformation_analysis_utils.load_code_to_name_mapping`), own-use proxy
  (C3) and refining (C4).
- **C5 is no longer blocked and is no longer legacy.**
  `electricity_heat_interim_workflow.py` now reads canonical
  `load_canonical_sheet("ninth fuel to esto product", ...)`
  (`_load_esto_product_to_ninth_fuel`) and canonical
  `build_code_to_display_name(include_excluded=True)`
  (`_load_power_interim_display_name_map`). The migration notes still describe
  C5 as BLOCKED; **that section is stale and must be corrected as part of this
  phase** (see Documentation, below).

### What is actually still open

**O1 - the canonical schema moved under us and nothing pins it.**
`leap_display_names` was 475 rows with columns including `auto_name` and
`matches_original_product_flow_name` when the migration was written. Measured
2026-07-21: **605 rows**, columns
`code_type, code, leap_display_name, Note, USED_IN_LEAP_INITIALISATION,
IS_LEAP_ROLLUP_NAME`. Both previously-named columns are **gone**. No test in
this repo asserts the expected column set of any canonical sheet, so the next
column rename in a repo we do not own fails deep in processing - exactly the
failure mode Phase 3 was supposed to remove.

Current measured sheet inventory of `outlook_mappings_master.xlsx`:

| Sheet | Rows | Consumed by initialisation |
|---|---|---|
| `leap_combined_esto` | 2251 | yes (26 cols, incl. `Unnamed:` filler) |
| `leap_combined_ninth` | 2467 | yes (7 cols) |
| `ninth_pairs_to_esto_pairs` | 2474 | yes (7 cols) |
| `leap_display_names` | 605 | yes (6 cols) |
| `ninth fuel to esto product` | - | yes (electricity/heat interim) |
| `leap_rollup_rules` / `esto_rollup_rules` / `ninth_rollup_rules` | - | **yes** - `supply_demand_mapping.py:587-589` |
| `rollup_label_overrides` | - | no (leap_mappings-side) |
| `Guide`, `deleted rows - might regret`, `NINTH unique sectors and fuels`, `ESTO unique flows and products`, `leap transport non road mapping` | - | no |

**O2 - a real latent defect in `unified_name_lookup.py`.**
`_is_genuine_override(row)` reads `matches_original_product_flow_name`, a
column that no longer exists. `row.get(...)` returns `""`, so the function
returns `False` for every row, so `load_source_records()` and
`build_unified_name_lookup()` **discard every authored `leap_display_name`
override and return mechanically derived names only**. Blast radius today is
small - the only in-repo caller is `aggregated_demand_workflow.py:41`, which
imports `load_active_mapping_sheet` (a different function, unaffected) - plus
`codebase/scrapbook/aggregated_demand_bridge_jetfuel_test.py`. This is a
decision, not an automatic fix: the consolidation API may simply be dead.

**O3 - `IS_LEAP_ROLLUP_NAME` is a new canonical column nothing here reads.**
leap_mappings added it alongside its standalone-rollup work (`4042d5e`,
`0581941`). Initialisation resolves display names from the same sheet without
distinguishing rollup labels from real LEAP branch labels. Whether a rollup
label may ever be selected as a LEAP branch display name is a **mapping-owner
question**, not a coding preference.

**O4 - compatibility redirect layer and legacy files still present.**
`codebase/utilities/master_config.py` keeps `CANONICAL_WORKBOOK_SHEETS`,
`CANONICAL_COMPATIBILITY_SHEETS` and `_read_canonical_compatibility_table`,
which reconstruct retired codebook shapes from canonical sheets - including a
guarded reference to the now-absent `auto_name`. `config/master_config.xlsx`
and `config/leap_mappings.xlsx` **still exist on disk**, so a new caller can
silently re-enter the legacy path. `read_config_table` has ~19 live call sites,
most of which read *operational* tables (subtotal maps, sheet maps, reassignment
CSVs), not mapping semantics; they must not be lumped together.

**O5 - the equivalence evidence was deferred and never collected.**
The migration notes state plainly: "Not run: a live end-to-end
supply-reconciliation preflight for a real economy. **C2 in particular changes
which 9th->ESTO pairs are used - a real preflight + conservation check is still
required before LEAP import.**" That is still true. Phase 3 cannot be declared
complete on unit tests alone.

## Dependencies and blockers

- **Not blocked on leap_mappings M2** (done). Blocked only on *decisions* (O2,
  O3, O4) and on *evidence* (O5).
- O5's evidence is cheapest to harvest from the fleet run already in flight
  (`SEED_21ECON_POST_TEMPLATE_REFRESH_20260721_151747`) rather than by
  launching a new run. Harvesting is read-only and safe now; interpreting it
  requires the run to finish.
- O3 requires an answer from the mapping owner before any code change.
- Anything that changes display-name resolution changes **LEAP branch labels**,
  which changes seed rows. Treat every O2/O3 code change as output-affecting.

## Decisions needed before implementation

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D3.1 | `unified_name_lookup` consolidation API (O2) | (a) delete `load_source_records`/`build_unified_name_lookup`, keep `load_active_mapping_sheet`; (b) repair `_is_genuine_override` against the current schema | **(a)** - the override semantics the function encodes no longer exist in the sheet; repairing it invents a rule nobody authored |
| D3.2 | Must display-name resolution exclude `IS_LEAP_ROLLUP_NAME` rows? (O3) | exclude / include / include-with-warning | Ask the mapping owner. Do not guess - a rollup label written as a LEAP branch name is a silent data defect |
| D3.3 | Retire `config/master_config.xlsx` and `config/leap_mappings.xlsx` from the repo? | delete / move to `config/legacy/` / keep | **move to `config/legacy/`** and let the compat layer resolve by name; deletion is a separate, later step once no path resolves to them |
| D3.4 | Does initialisation own its rollup-rule reading, or should it call a shared leap_mappings helper? | duplicate reader here / import from leap_mappings / agreed frozen column contract | **frozen column contract + contract test here.** Cross-repo Python imports are not currently a pattern in this repo |
| D3.5 | Tolerance for O5 equivalence | exact keys + totals within X PJ | Propose: branch-row key sets exactly equal; per economy/scenario/fuel totals within 1e-6 relative |

## Staged sequence of small commits

Each commit is independently revertible and adds its own focused test.

1. **`codex: pin canonical mapping sheet schemas`** *(safe during fleet run)*
   Add `tests/test_canonical_schema_contract.py`: for each of the seven
   consumed sheets, assert the exact set of columns initialisation depends on
   is present, and assert the sheets initialisation does *not* consume are not
   silently required. Add `CANONICAL_SHEET_CONTRACT` to
   `codebase/mappings/canonical_loaders.py` as the single declared dependency
   surface. No behaviour change.

2. **`codex: contract-test the rollup rule sheets`** *(safe during fleet run)*
   `supply_demand_mapping.py:587-589` reads three sheets owned by another repo
   with no column assertion. Add the columns (`rollup_context`, input pair,
   rolled pair, `include`, `Note`) to the contract from commit 1 and a focused
   test that an unexpected schema fails fast with a named error rather than
   producing empty rule sets. Record D3.4's answer in the module docstring.

3. **`codex: retire the unified name lookup consolidation API`** *(safe)*
   Implements D3.1. If (a): delete the two functions plus their dead
   `_is_genuine_override` helper, keep `load_active_mapping_sheet` and its
   callers untouched, and update the scrapbook caller or mark it archived. If
   (b): repair against current columns and add a test proving an authored
   override survives. Either way add a regression test.

4. **`codex: resolve rollup labels in display-name lookup`** *(needs D3.2)*
   Only if the mapping owner says rollup labels must be excluded. Route the
   exclusion through `canonical_loaders` so all five display-name call sites
   inherit it, alongside the existing `USED_IN_LEAP_INITIALISATION` filter.
   **Output-affecting** - see equivalence gate below.

5. **`codex: move legacy mapping workbooks out of the runtime config dir`**
   *(needs D3.3, safe during fleet run only if nothing resolves to them - prove
   it first)* Move to `config/legacy/`, keep the compat redirect resolving by
   filename, add a test asserting no runtime code path opens either file.

6. **`codex: record canonical migration equivalence evidence`** *(must wait for
   the fleet run)* Documentation-only commit carrying the O5 measurements.

## Safety boundaries - what must not change

- **Mapping semantics.** Do not add, remove, or re-target a mapping row. Every
  mapping content change belongs in `leap_mappings`, authored in the workbook.
- **The canonical petroleum split**: `07_x_other_petroleum_products` ->
  `07.17 Other products`, `07_petroleum_products_unallocated` ->
  `07.99 PetProd nonspecified`. Pinned by
  `tests/test_canonical_only_mapping_sources.py`; it must stay green.
- **Semantic roles must not be collapsed.** `canonical_loaders` deliberately
  keeps pair/context mappings distinct from fuel-only dictionaries. Do not
  build a global fuel dictionary "for convenience".
- **Ambiguity must not be resolved by first-row selection.** C3's
  `LAST_FUEL_MAPPING_AMBIGUITY` reporting is the intended behaviour.
- **One-to-many 9th->ESTO keys stay reported, not resolved** (224 measured).
- **`outlook_mappings_master.xlsx` is read-only from this repo.** Enforced in
  spirit by `supply_demand_mapping.py:574`'s comment about never using a reader
  that may save the workbook; keep that.
- Do not touch `codebase/supply_reconciliation_workflow.py` while the fleet run
  holds it (the working tree carries a temporary `RUN_OUTPUT_LABEL`).

## Tests and real-run equivalence evidence

Focused tests (no production ESTO/9th data, no LEAP):

- schema contract per sheet, including negative cases (missing column, renamed
  column) asserting a `CanonicalMappingError` that names workbook + sheet +
  column;
- rollup-rule contract, including "unexpected schema does not silently yield
  zero active rules";
- display-name filter behaviour for `USED_IN_LEAP_INITIALISATION` (explicit
  False excludes; blank/True keep) and, if D3.2 says so, `IS_LEAP_ROLLUP_NAME`;
- override-survival or removal test for D3.1;
- a "no legacy workbook is opened at runtime" test for D3.3.

Real-run equivalence (the O5 gate):

1. From the in-flight fleet run, capture for 3 economies - one real template
   (`01_AUS` or `12_NZ`), one `_COMP_GEN` (`05_PRC`), one aggregate (`00_APEC`)
   - the seed branch-path key set, per economy/scenario/fuel totals, and the
   consolidated rule findings.
2. Compare against the same measurements from the pre-migration seed vintage
   where one exists. **Do not compare raw export output against a finished
   seed** (recorded trap: `prepare_seed_rows_for_write` does canonical share
   completion; the comparison must be post-boundary on both sides).
3. Run one compressed preflight + conservation check for a real economy after
   the fleet run completes. This is the check the migration notes deferred.

## Acceptance criteria

- Every canonical sheet and column initialisation depends on is declared in one
  place and asserted by a test that fails on a rename.
- A schema break produces a named, upfront error before any processing.
- No runtime path opens `config/master_config.xlsx` or `config/leap_mappings.xlsx`.
- D3.1-D3.4 are answered in writing in this file.
- O5 evidence recorded: key sets equal and totals within the D3.5 tolerance for
  the three sampled economies, plus one clean preflight + conservation check.
- `docs/canonical_mapping_migration_notes.md` no longer describes C5 as blocked.

## Rollback

Commits 1, 2, 5 are behaviour-neutral: `git revert` is sufficient. Commit 3 is
API removal - revert restores the (defective) functions. **Commit 4 is the only
output-affecting one**: if a seed diff appears after it, revert that single
commit and re-measure before investigating anything else. Never bundle commit 4
with another change.

## Documentation to update on completion

- `AGENTS.md` - rewrite the Phase 3 section (M2 blocker removed; scope is
  schema contract + ownership + evidence) and the "Mapping file inconsistency"
  bullets, which are stale.
- `docs/canonical_mapping_migration_notes.md` - mark C5 resolved with the
  current call sites; record O1-O5 outcomes.
- `docs/work_queue.md` - roadmap entry [16].
- `docs/check_registry.md` - if the schema contract becomes a gating check, it
  belongs in the registry or `tests/test_check_registry.py` will fail.
- `leap_mappings/docs/mappings_system.md` - **read-only from here**; if D3.2/D3.4
  produce an obligation on the mapping repo, report it, do not edit it.

## What leap_mappings must keep providing

M2's deliverable is met. The forward obligation is narrower and should be
stated back to the mapping owner:

1. The seven consumed sheets keep their current column names, or a column
   change is announced and this repo's contract test is updated in the same
   change window.
2. `leap_display_names` keeps `code_type`, `code`, `leap_display_name`,
   `USED_IN_LEAP_INITIALISATION`; the meaning of `IS_LEAP_ROLLUP_NAME` is
   documented (D3.2).
3. Rollup sheets keep `rollup_context`, input pair, rolled pair, `include`.
4. The workbook stays authored in leap_mappings only - no initialisation
   workflow writes to it.

## Safe now vs must wait

| Safe while the fleet run continues | Must wait for it to finish |
|---|---|
| Commits 1, 2, 3, 5 (no output effect, none touch `supply_reconciliation_workflow.py`) | Commit 4 (display-name change alters LEAP branch labels) |
| Reading fleet-run artifacts, building comparison scripts | Preflight + conservation check (O5) |
| All decision-gathering (D3.1-D3.5) | Any decision that implies re-running economies |
