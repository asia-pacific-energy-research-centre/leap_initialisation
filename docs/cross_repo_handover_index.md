# Cross-repository handover index — `leap_initialisation` side

**Snapshot date:** 2026-07-28

**Last verified:** 2026-07-28 — path constants and resolvers read from current
code in all three repositories; git state read directly from each.

**Owner of this document:** `leap_initialisation`

**Parent document:** `leap_mappings/docs/cross_repository_handover_index.md` is
the programme-level index. It owns repository ownership, the
`leap_mappings` → `leap_dashboard` contract, the published Common ESTO schemas,
the pipeline refresh order, and mapping failure ownership. **Read it first.**

This document is its `leap_initialisation` half. It exists because the parent
declares two dependency directions as thin or undeclared:

- its § 2.2 records the `leap_initialisation` → `leap_mappings` balance-export
  dependency as *"Not yet a wired contract… an undeclared dependency"*; and
- it has no section for `leap_mappings` → `leap_initialisation`, which is the
  **largest live code-level coupling in the programme** and the one that blocked
  a production run on 2026-07-28.

Everything below was verified against code, not inferred from documentation.

## 1. What this repository owns

| Owns | Does not own |
|---|---|
| LEAP area initialisation: baseline seeds, the supply/transformation/transfers reconciliation, demand aggregation, loss/own-use proxies, refining, interim electricity/heat. | Mapping semantics. `AGENTS.md` routes mapping-only maintenance to `leap_mappings`. |
| LEAP import/export integrity: per-economy export templates, BranchID/VariableID/ScenarioID/RegionID resolution, the zeroing workbooks, the seed patcher. | Dashboard presentation, chart routing, page layout. |
| The **raw LEAP Energy Balance exports** — the only copy of what LEAP actually produced. | The Common ESTO comparison dataset and its contract. |
| The results-update loop: balance diagnostics, allocation preview, adjustment strategies. | The canonical mapping workbook, rollup rules, comparison scopes. |

## 2. Files crossing the boundary

### 2.1 Produced by `leap_mappings`, consumed by `leap_initialisation` — **not covered by the parent index**

This is a **runtime, code-level** dependency, not a reference one.

| Consumed file | Consumer | Nature |
|---|---|---|
| `leap_mappings/config/outlook_mappings_master.xlsx` | `codebase/mappings/canonical_loaders.py` (`load_canonical_sheet`, `filter_leap_rollup_names`, `resolve_rollup_components`) | **Hard runtime dependency.** The loader raises with "Expected leap_mappings/config/outlook_mappings_master.xlsx" if absent. Every reconciliation run reads it. |
| the same workbook | `codebase/utilities/leap_results_dashboard_balance.py`, `codebase/mapping_tools/build_energy_balance_relationships.py`, `codebase/mapping_tools/update_mapping_cardinality.py` | Additional readers of the same canonical workbook. |
| `leap_mappings/config/mapping_issue_exception_sets.xlsx` (`subtotal_mismatch_allowed` sheet) | the canonical ninth mapping validation | **Gate.** An unapproved subtotal-to-non-subtotal mismatch **stops the run**. |
| `leap_mappings/codebase/mapping_tools/convert_leap_results_to_esto.py` | referenced by `codebase/utilities/leap_balance_export_resolver.py` | Conversion reference for LEAP balance → ESTO axis. |

Three properties of this coupling matter at handover:

1. **It is a blocking gate, not a soft input.** On 2026-07-28 the `12_NZ` Target
   results-update run failed after 122 seconds on exactly two unapproved
   mismatch rows. Neither repository could resolve it alone: the code is correct
   to refuse, and the decision belongs to the mapping owner. See INITQ-014 in
   [`handover_work_queue_20260728.md`](handover_work_queue_20260728.md).
2. **The workbook is a live Excel file on one machine.** `leap_mappings` carried
   an open-workbook lock (`config/~$outlook_mappings_master.xlsx`) at this
   snapshot. The parent index records that an open workbook forces `_rebuilt`
   fallback writes on the mapping side; on this side it can also make a read
   fail outright.
3. **`leap_mappings` filters on a column this repository names.** Its
   `codebase/utilities/outlook_mappings_filters.filter_used_in_leap_initialisation`
   and the `used_for_ninth_to_leap_initialisation` /
   `ninth_to_leap_initialisation` columns exist specifically to scope mappings to
   this repository's use. Renaming that column is a breaking change here.

### 2.2 Produced by `leap_initialisation`, consumed by `leap_mappings`

| Produced file / tree | Consumer | Status |
|---|---|---|
| `data/leap balances exports/<economy>/` | `leap_mappings/codebase/utilities/leap_balance_export_resolver.py`, which resolves `REPO_ROOT.parent / "leap_initialisation" / "data" / "leap balances exports"` and errors with "Expected raw exports under the sibling leap_initialisation" if missing | **Wired, sibling-relative.** The parent index's § 2.2 describes this as undeclared; it is in fact resolved in code, but by *relative path*, which is why it does not survive a non-sibling checkout layout. |
| the same tree | `leap_mappings/codebase/mapping_tools/source_coverage_audit.py` (`INITIALISATION_ROOT = REPO_ROOT.parent / "leap_initialisation"`) | Wired, sibling-relative. |
| `data/leap_export_templates/` | `leap_mappings/codebase/mapping_tools/build_esto_extended_test.py` pins `LEAP_INITIALISATION_ROOT = Path(r"C:\Users\Work\github\leap_initialisation")` | **Hard-coded absolute path.** Breaks on any other machine. Flagged as a handover risk in § 5. |
| `data/full model export.xlsx` | `leap_mappings/codebase/archive/outlook_mapping_maintenance_workflow.py` | **Dangling.** The file was retired from this repository and no longer exists. The reference is in an archived module, so it is not live — but it will mislead. |

**Balance-export naming contract.** `codebase/utilities/leap_balance_export_resolver.py`
parses filenames with:

```text
full model output all years <date_id> <SCENARIO>[ <suffix>].xlsx
```

`date_id` is 5–8 digits; `SCENARIO` is one of `REF`/`TGT` (aliases `ref`,
`reference`, `tgt`, `target`). Files that do not match are not discovered.
Workbooks must be exported at **LEAP detail Level 2 or better** — Level 1 is
blocked before extraction, and detail is proven by the presence of indented
child rows.

Economies with balance exports present at this snapshot: `00_APEC`, `01_AUS`,
`02_BD`, `12_NZ`, `20_USA` (in both `data/leap balances exports/` and
`data/leap balances exports - testing/`).

### 2.3 Produced by `leap_initialisation`, consumed by `leap_dashboard`

| Path | Consumer | Nature |
|---|---|---|
| the repository root itself | `leap_dashboard/codebase/common_esto_dashboard_workflow.py` builds a path via `… / "leap_initialisation"` | Sibling-relative reference only. The dashboard's substantive inputs come from `leap_mappings`; this repository is not on its critical path. |

## 3. Schemas this repository owns

The parent index documents the Common ESTO published schemas. These are the
`leap_initialisation`-side artifacts a consumer may need.

### Baseline seed workbook — `leap_import_baseline_seed_<economy>_<date>.xlsx`

The LEAP import artifact. Keyed on `BranchID` / `VariableID` / `ScenarioID` /
`RegionID`, with `Region` carrying the economy's LEAP area name. Invariants a
reviewer should check:

- **zero rows with `BranchID = -1`** — a `-1` means an unresolved branch;
- `Region` uniform and equal to that economy's area (not `United States`, unless
  the artifact really is the `00_APEC` aggregate sentinel, where
  `GLOBAL_REGION` deliberately falls back to USA);
- no `PRELIM` marker in the filename — `PRELIM` means the seed was built against
  a provisional `_COMP_GEN` template rather than a real per-economy export.

Reference figures from the verified `01_AUS` run (`b45ccc6`, 2026-07-21): 3,432
rows, 504 rows on AUS-discriminating paths following AUS IDs, 0 following USA
IDs, 0 on neither.

### Zeroing workbook — `supply_transformation_zeroing_<economy>.xlsx`

The **only** reset artifact. Import order into a populated LEAP area is fixed:

1. `supply_transformation_zeroing_<economy>.xlsx`
2. the generated main supply/transformation workbook

**Reversing that order overwrites the generated values with zeroes.**

### Per-economy export templates — `data/leap_export_templates/`

21 templates at this snapshot: **11 real** (AUS, BD, MAS, MEX, NZ, PHL, PNG,
PRC, THA, USA, VN) and **10 `_COMP_GEN`**, the latter generated from the USA area
and carrying its BranchIDs verbatim with only `Region` relabelled. Resolved by
`codebase/utilities/leap_export_template_resolver.py`.

Note that this ratio **inverted on 2026-07-28** — eight real templates landed
that day. Documentation that says "18 of 21 are `_COMP_GEN`" is stale; see
INITQ-012.

### Run diagnostics — `outputs/leap_exports/supply_reconciliation/**/supporting_files/checks/`

Every diagnostic family is catalogued in [`check_registry.md`](check_registry.md)
against its F1–F5 taxonomy, which is enforced by `tests/test_check_registry.py`.
Treat that file, not this one, as the schema directory for run diagnostics.
`leap_dashboard` reads from `supporting_files/checks/` directly in at least one
place, so those paths are a soft contract.

## 4. Refresh order — this repository's steps

The parent index § 4 owns the end-to-end order. This is what steps 2 and "LEAP"
actually involve here, which the parent compresses to one line.

1. **Canonical mappings must be current first.** This repository reads
   `outlook_mappings_master.xlsx` at runtime, so a mapping edit lands here on the
   next run with no rebuild step. Close the workbook in Excel before running.
2. **Generate** — `codebase/supply_reconciliation_workflow.py` with
   `ACTIVE_PRESET = _PRESET_BASELINE_SEED`. Use
   `C:/Users/Work/miniconda3/python.exe`; the repository `.venv` is WSL-created
   and unusable from Windows shells. Set a unique `RUN_OUTPUT_LABEL` for any run
   you intend to keep, and restore `"auto"` afterwards.
3. **Import into LEAP** — zeroing workbook first, then the main workbook.
   Manual; the LEAP COM API is decommissioned and Excel import/export is the
   supported path.
4. **Recalculate in LEAP.** Manual.
5. **Export the Energy Balance** at Level 2 or better into
   `data/leap balances exports/<economy>/`, using the filename contract in § 2.2.
6. **Diagnose** — `codebase/baseline_seed_balance_diagnostics_workflow.py`,
   then the results-update preview.
7. **Downstream** — `leap_mappings` Stages 1–3, then `leap_dashboard`, per the
   parent index § 4.

Steps 3–5 require a human in LEAP. No part of this loop is unattended today.

**Concurrency.** Per-economy parallelism goes through
`codebase/supply_reconciliation/parallel_runner.py`, which launches one OS process
per economy with its own `LEAP_WORKER_SNAPSHOT_JSON` snapshot and
`run_output_label`. Do **not** launch a second bare invocation of
`supply_reconciliation_workflow.py` from the same working tree — `ECONOMIES` is
a module literal that a late preflight import can re-read from disk mid-run.
(`AGENTS.md` and `docs/current_execution_roadmap.md` both still say the runner
does not exist; they are wrong — see `D-02` in
[`documentation_audit_20260728.md`](documentation_audit_20260728.md).)

## 5. Failure ownership — initialisation side

The parent index § 5 covers mapping and dashboard failures. These are this
repository's.

| Symptom | Owner | First check |
|---|---|---|
| Run stops on a subtotal-to-non-subtotal mismatch | **joint** — mapping owner decides | `outputs/.../checks/subtotal_flag_blocking_mismatches_leap_combined_ninth.csv`. Either an authored mapping defect (fix in `leap_mappings`) or an intentional mismatch (approve in `mapping_issue_exception_sets.xlsx`). Never auto-approve. |
| Canonical workbook read fails or returns stale sheets | `leap_mappings` | Excel lock `config/~$outlook_mappings_master.xlsx`; then whether the sibling checkout is present at `../leap_mappings`. |
| Seed rows carry another economy's BranchIDs | `leap_initialisation` | The template resolver. Confirm the economy resolves to its own template and not to a `_COMP_GEN` or USA fallback. |
| Seed contains `BranchID = -1` rows with non-zero values | `leap_initialisation` | Unresolved branches. The recorded migration-lag class is `Demand\Other loss and own use\Non specified own uses\*`; anything else is new. |
| Balance export not discovered | `leap_initialisation` | The filename contract in § 2.2, then the Level 2 detail check. |
| LEAP values are ~1/100 or ~1000× expected | `leap_initialisation` | Two known causes: a LEAP leaf Activity Level interpreted as a percentage/share (fix the live LEAP setting to blank), and the "Units: Thousand Petajoule" export header. |
| Imported values are zeroes | operator | Workbook import order — the zeroing workbook must go **first**. |
| A results-update run proposes a change nobody agreed to | `leap_initialisation` | `docs/results_update_dry_run_preview.md`. Updates are governed by a balance-variable contract; `02 Imports` is the default balancing variable. Differences in protected flows are an issue to raise, not a value to change. |
| `leap_mappings` cannot find balance exports | `leap_initialisation` | The sibling path in § 2.2 and whether the economy/scenario was exported at all. |

## 6. Handover risks recorded from this side

These complement the parent index § 6; they are not repeats of it.

1. **The canonical-workbook dependency is a blocking gate with a cross-repository
   owner.** A mapping decision nobody has made stops an initialisation
   production run. There is no queue, no SLA, and no named decision-maker for
   that handoff today. INITQ-014.
2. **`leap_mappings/codebase/mapping_tools/build_esto_extended_test.py` hard-codes
   `C:\Users\Work\github\leap_initialisation`.** A clean-checkout rehearsal on
   any other machine or path will fail there. Should become a sibling-relative
   resolution like every other cross-repository path.
3. **Every cross-repository path is sibling-relative.** All three repositories
   must be checked out as siblings under one parent directory. Nothing states
   this as a prerequisite; the Week 3 runbook (INITQ-010) must.
4. **The raw LEAP balance exports exist in one place and are not reproducible
   without LEAP.** They are the output of manual steps 3–5 above. If
   `data/leap balances exports/` is lost, it cannot be regenerated from code —
   only by redoing the LEAP work. Confirm it is included in whatever backup or
   transfer the handover uses.
5. **Only 5 of 21 economies have balance exports**, so the results-update loop is
   exercised for a minority of the fleet. Any claim about update behaviour
   generalising across economies is untested.
6. **142 commits of initialisation work exist only on this machine** (201 across
   all three repositories). INITQ-003.

## 7. Verification for the Week 4 rehearsal

INITQ-013 validates this document alongside the parent index § 7. In order:

1. Clone all three repositories **as siblings** under one parent directory.
2. Restore `data/` and `config/` from documentation alone — including the raw
   balance exports.
3. Confirm `codebase/mappings/canonical_loaders.py` resolves
   `../leap_mappings/config/outlook_mappings_master.xlsx` with no absolute path
   and no manual edit.
4. Run a two-year `01_AUS` baseline seed and confirm the artifact invariants in
   § 3 (zero `BranchID = -1`, uniform `Region`, no `PRELIM`).
5. Run the balance diagnostics against an existing export and confirm the
   filename contract and Level 2 check both pass.
6. Record every step that needed knowledge absent from this document, the parent
   index, or the runbook. Each one is a defect to fix before handover.
