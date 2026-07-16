# Export Zero-Fill Consolidation Execution Prompt

Type: implementation (refactor with equivalence verification). No production runs.

## Short version

Extract the four independently developed "zero unfilled rows from
`data/full model export.xlsx`" mechanisms used by the supply-reconciliation
sub-workflows into one shared helper module
(`codebase/functions/export_zero_fill.py`), migrate the workflows onto it in
stages, and prove byte-equivalent (or explained-diff) output workbooks at each
stage. Do not change what gets zeroed, which measures are covered, or the
expression style each workflow emits — this is a consolidation, not a
behaviour change.

## Context (as of 2026-07-15 — update before use)

An audit found that each sub-workflow run by
`codebase/supply_reconciliation_workflow.py` grew its own zeroing logic
independently:

1. `add_zero_rows_for_unset_values` in
   `codebase/functions/other_loss_own_use_proxy_utils.py` — gap-fill for
   `Activity Level` and `Final Energy Intensity` under
   `Demand\Other loss and own use`, scoped by a key table read via
   `load_export_key_table` (hardcodes `header=2`). Emits per-year
   `Data(y0,0.0,...,yN,0.0)` series expressions, with a single-year form for
   Current Accounts.
2. `build_aux_fuel_zero_rows` in
   `codebase/functions/transformation_record_builder.py` — gap-fill for
   `Auxiliary Fuel Use`, `Feedstock Fuel Share`, and `Output Share` from a
   branch catalog, two-tier prefix scoping, plus a 100.0 fallback so LEAP does
   not reject an all-zero feedstock process. Also used by
   `codebase/functions/patch_baseline_seeds.py` and the electricity/heat
   interim workflow.
3. `build_demand_zeroing_rows` / `save_demand_zeroing_workbook` in
   `codebase/aggregated_demand_workflow.py` — blanket reset of ALL non-share
   `Demand\` branches (constant `Expression="0"`), excluding the
   aggregated-demand prefix and (via
   `ZERO_OTHER_DEMAND_EXCLUDE_OWN_USE_PROXY_BRANCHES`) the own-use prefix.
   Ships as a separate `demand_zeroing_{econ}.xlsx` workbook via
   `build_other_demand_zeroing_workbooks` in
   `codebase/functions/supply_leap_io.py`.
4. `reset_supply_and_transformation_import_export_to_zero` in
   `codebase/functions/supply_reconciliation_tables.py` — supply/transformation
   import-export reset.

**Header parsing — CORRECTED 2026-07-16, and partly done.** This section used to
say the export header was parsed "three different ways". That was wrong on two
counts, so do not plan from it:

1. It is **~8 implementations**, not three, with **three different detection
   criteria** (`Branch Path`+`Variable`; `BranchID` in
   `leap_excel_io.read_export_sheet`; and `header=2` hardcoded in
   `load_export_key_table`) and scan depths of 6 rows, 8 rows and unlimited.
2. They do **not all read the full model export**. Only `build_demand_zeroing_rows`
   and `load_export_key_table` do; `_read_leap_data` reads per-economy *producer*
   workbooks. So the shared concern is *"read a LEAP-style sheet by detecting its
   header"*, **not** *"load the export universe"* — a `load_export_universe`
   loader is the wrong abstraction for it.

Done: `find_leap_header_row` / `read_leap_sheet` now live in
`codebase/functions/leap_excel_io.py` (which already owns LEAP sheet I/O), with
`analysis_input_write_dispatcher` and `build_demand_zeroing_rows` routed through
them; guarded by `tests/test_leap_sheet_header_detection.py`. Remaining callers
and their quirks are tabulated in `docs/check_registry.md` (family F1, "Header-parsing
drift"). This drift was the main maintenance risk; the rest of this prompt is
about the zero-fill **mechanisms**, which are still unconsolidated.

Related fix already applied (2026-07-15, may be uncommitted — check
`git log`/`git status`): own-use zero rows are now merged into the proxy
workbook's `LEAP` sheet in
`other_loss_own_use_proxy_workflow.py::assemble_proxy_workbook` before
`save_export_files`, not only the `LEAP_WITH_IDS` sheet, because
`write_per_economy_combined_workbooks` reads the `LEAP` sheet. Preserve this
behaviour through the refactor.

## Objective

One shared module, e.g. `codebase/functions/export_zero_fill.py`, providing:

- `load_export_universe(path, sheet)` — a single loader for
  (Branch Path, Variable, Scenario, Region [, IDs]) rows from the full model
  export, replacing the three parsing implementations. Must locate the header
  row by scanning (do not hardcode `header=2`; make the own-use path tolerant
  of format drift too).
- `zero_fill_unset_rows(written_df, universe, *, include_prefixes,
  exclude_prefixes, variables, scenarios, zero_style, ...)` — one gap-fill /
  blanket-zero function parameterized by scope and by zero style. Zero style
  must be an explicit parameter because the differences are intentional:
  constant `"0"` (demand zeroing) vs `Data()` year series with a Current
  Accounts single-year form (own-use), vs measure-specific fallbacks
  (transformation feedstock 100.0).

Each workflow keeps only its scope/style configuration and calls the shared
helper.

## Staging (do in this order; each stage is separately committable)

1. ~~Shared loader only: introduce `load_export_universe`~~ **Superseded — see
   the corrected header-parsing note above.** The shared header detector
   (`leap_excel_io.find_leap_header_row` / `read_leap_sheet`) exists and two
   callers are routed. To finish this stage, route the remaining readers listed
   in `docs/check_registry.md` (F1) — `patch_baseline_seeds._find_header_row`
   (needs `drop_blank_columns=True`), `supply_leap_io._read_leap_data` and
   `_read_workbook_sheet_with_header_detection`, `supply_results_saver._find_header_row`,
   `leap_excel_io.read_export_sheet` (different `BranchID` criterion — decide
   whether to unify), and `load_export_key_table` (drop its hardcoded
   `header=2`). No output-shape changes: `drop_blank_columns` and
   `drop_empty_rows` default to preserving each caller's current behaviour.
2. Own-use + demand-zeroing gap-fill onto `zero_fill_unset_rows`. These two
   already coordinate via `ZERO_OTHER_DEMAND_EXCLUDE_OWN_USE_PROXY_BRANCHES`
   and share the Demand tree; keep that exclusion semantics identical.
3. Transformation (`build_aux_fuel_zero_rows`) last — it has the most
   entangled semantics (two-tier prefixes, feedstock 100.0 fallback, callers
   in patch_baseline_seeds and electricity/heat interim). Skip this stage if
   the parameterization becomes contorted; a shared helper that only covers
   stages 1–2 is still a win.
4. `reset_supply_and_transformation_import_export_to_zero` is likely out of
   scope (it is a reset of specific existing rows, not export-universe
   enumeration). Confirm and document rather than force it in.

## Constraints

- Run `git status --short` first; preserve unrelated working-tree changes
  (there may be uncommitted own-use/electricity changes — do not revert them).
- No behaviour changes: same rows zeroed, same measures, same expression
  strings, same sheet placement (`LEAP` + `LEAP_WITH_IDS` for own-use).
- 12 core `codebase/*.py` files carry a UTF-8 BOM — read as `utf-8-sig` when
  scripting over sources; keep files ASCII otherwise.
- Do not change mapping/data/methodology decisions (which branches are
  excluded, share-variable lists, etc.). If an inconsistency between the four
  mechanisms looks like a bug, report it; do not silently "fix" it in the
  shared helper.
- Module attribution: new functions live in `export_zero_fill.py`; update
  `tests/test_module_attribute_contracts.py` if it guards these modules.

## Validation

- Existing suites must pass:
  `tests/test_other_loss_own_use_proxy_workflow.py` (note: as of 2026-07-15
  two tests fail on the uncommitted `INCLUDE_ELECTRICITY_IN_TD_LOSSES` change,
  unrelated to this work — verify against HEAD behaviour), plus the
  aggregated-demand and transformation test files.
- Per stage, equivalence check on real data: generate the affected workbook(s)
  for at least `20_USA` before and after the change (own-use proxy workbook,
  `demand_zeroing_*.xlsx`, and for stage 3 a transformation export) and diff
  row sets on (Branch Path, Variable, Scenario, Expression). Zero diffs
  expected; any diff must be root-caused and explained before committing.
- Add unit tests for `load_export_universe` (header-scan behaviour) and for
  each `zero_style`.

## Stop conditions

- Stop and report (no code change) if the four mechanisms turn out to disagree
  on something user-visible (e.g. scenario coverage or share-variable
  exclusions) — that is a methodology decision for the user.
- Stop stage 3 and deliver stages 1–2 if `build_aux_fuel_zero_rows` cannot be
  expressed through the shared helper without widening its behaviour.
- Ask before any full supply-reconciliation run; equivalence checks should use
  workbook-generation entry points only, not LEAP imports.

## Deliverables

- `codebase/functions/export_zero_fill.py` + unit tests.
- Migrated call sites per completed stage, each stage a separate commit.
- A short findings note if any cross-mechanism inconsistencies were found.
- Archive this prompt to `docs/archive/` when complete (per AGENTS.md).

## Update before use

Function names, flags, and file paths above were verified on 2026-07-15.
Re-verify with `rg` before editing: `add_zero_rows_for_unset_values`,
`build_aux_fuel_zero_rows`, `build_demand_zeroing_rows`, `_read_leap_data`,
`load_export_key_table`, `ZERO_OTHER_DEMAND_EXCLUDE_OWN_USE_PROXY_BRANCHES`.
