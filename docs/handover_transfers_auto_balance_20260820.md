# Handover — transfers: AUTO BALANCE, ESTO label repair, carry-forward

Written 2026-08-20 for a fresh agent picking this up. Branch
`claude/baseline-seed-transfer-fallback-5b0e5e`, worktree
`.claude/worktrees/baseline-seed-transfer-fallback-5b0e5e`. The completed work
is committed as `dd20a4c` (ESTO preparation and one-sided transfers) and
`5c304fd` (scenario-aware fallback).

## What this session was, in one paragraph

Started as a read-only design review of work-queue item `[50]` (scenario-aware
transfer projection fallback). The review found the queue's premise was half
wrong, and then uncovered three separate defects underneath it. The code-side
defects are fixed and verified. The remaining operational prerequisite is a
LEAP-area change the maintainer is doing by hand.

## Decisions the maintainer made (do not relitigate)

1. **Carry-forward is the transfer projection policy.** Where the 9th supplies a
   projection, use it (including genuine zeros). Where it does not, carry the
   ESTO base year forward flat. Rationale: zero asserts transfers cease, which no
   source claims; this repo is not the place to estimate transfer trajectories; a
   flat carry-forward is an honest, replaceable placeholder. This overrode the
   review's `HUMAN_SEMANTIC_DECISION_REQUIRED` on different grounds — do not
   re-open the "what did the 9th mean" question, it is moot.
2. **One-sided transfers get a synthetic counterpart on a real LEAP fuel named
   `AUTO BALANCE`, code `99`.** All caps, deliberately.
3. **ESTO label repairs are hard-coded per code, never by blanket rule.** New
   drift must raise an error, not be silently normalised.
4. **Proxy-based transfer projections** (own-use/loss pattern: upstream on FF
   production, refinery/blending on refinery+petrochemical activity, unallocated
   a mix) are a **nice-to-have, not scheduled**.

## State of play

### DONE and verified

**A. ESTO label repair (Step 0 in the vintage pipeline).**
`codebase/mapping_tools/prepare_new_esto_data.py` — `normalise_esto_labels()`,
`CANONICAL_FLOW_LABELS`, `CANONICAL_PRODUCT_LABELS`, `UnreviewedEstoLabelError`.
Five repairs, each an explicit entry: `08.99` (`Transformation`→`Transfers
nonspecified`), `10.02` (`Transmision`), `06.04`/`07.15` (double spaces),
`15.04` (`Black liqour`). Unreviewed drift for a *known* code raises; an unknown
*code* is reported only. Validated against `ESTO_PRODUCT_LIST`/`ESTO_SECTORS` in
`codebase/configuration/all_products_and_flows.py`.
Docs: `docs/esto_vintage_onboarding.md`. Rebuilt
`data/00APEC_2026_low_with_subtotals_PRELIMINARY.csv` (gitignored — won't show in
a diff).

*Why it mattered:* six economies including `01_AUS` and `20_USA` keep their whole
base-year transfer mass under `08.99`. Adopting the 2026 vintage unrepaired would
have silently emptied their transfers module.

**B. One-sided transfer balancing.**
`codebase/transfers_workflow.py` — `ONE_SIDED_TRANSFER_BALANCE_POLICY`,
`balance_one_sided_transfer_flow()`, `_auto_balance_value()`,
`_report_one_sided_transfer_balance()`. Hooked into **both** branches of
`build_transfer_rows` (the per-flow loop *and* the `transfer_flows_combined`
branch — missing the second one is why an earlier attempt fixed PRC but not PNG).
Counterpart is `99 AUTO BALANCE`, sized to `max(1.0, peak_measured / (ceiling/100))`
so the efficiency ceiling holds by construction.

Verified end to end: `05_PRC` 0 rows → 2 rows; `13_PNG` massless → 1.00 PJ;
`21_VN` gets 3.03 PJ for its inflow-only 1998-2016 years; the other seven seed
economies byte-identical.

Tests: `tests/test_transfer_one_sided_balance.py` (11),
`tests/test_prepare_new_esto_data.py` (9). Full local set: **32 passing**.

### DONE and verified

**C. Scenario-aware carry-forward — work-queue `[50]`.** Implemented in
`5c304fd`, with the three parts originally specified in
`docs/decision_transfer_projection_fallback_20260820.md` §5-§7:

1. The run scenario is threaded through `_collect_transformation_and_transfer_rows`
   (`codebase/supply_reconciliation/tables.py:182-206`). `build_transfer_process_records`
   needs a `scenario` parameter (or swap that call site to `build_transfer_rows`);
   `collect_transformation_rows` needs `projection_scenario`; **both balance tables
   need a `scenario` column** — that is the structural part, not just an unpassed arg.
2. `(economy, scenario)` is classified into `projection_supplied` /
   `projection_unavailable` / `structural_zero` / `no_ninth_rows`, **upstream of
   the `fillna(0.0)` at `codebase/functions/ninth_projection_mapping.py:1957`** —
   after that line, "supplied zero" and "no projection" are indistinguishable.
   Emit as a seed-run diagnostic.
3. Carry-forward applies only to `projection_unavailable`. It affects `02_BD`,
   `11_MEX`, `12_NZ`, `21_VN`, plus `05_PRC` and `13_PNG` now that B is fixed.

The three focused regression cases pass as part of the 56-test verification set.

### Template rows added 2026-08-20

**D. AUTO BALANCE template rows.** The supplied AUS example was applied to all
11 active economy templates (72 rows per template; 6 branch paths × 8 variables
× 3 scenarios, under
`Transformation\{Transfers unallocated | Refinery and blending transfers |
Upstream liquids transfers}\{Output Fuels | Processes\...\Feedstock Fuels}\AUTO BALANCE`).

**Do not bulk-copy that file into the other economy templates with only the
Region name changed.** `BranchID` is per-area: `Demand\All demand
aggregated\Buildings\Anthracite` is 3098 in AUS, 3462 in NZ, 3073 in USA. Copying
AUS's `BranchID` 1188/1206 into other templates injects AUS IDs into other areas —
the exact bug class `codebase/utilities/leap_export_template_resolver.py` and
`attach_export_ids` (`codebase/functions/leap_excel_io.py:232-265`) exist to
prevent; the latter deliberately keeps `BranchID=-1` rather than borrowing.
(Also note the AUS file gives one BranchID `1188` to three distinct branch paths,
which cannot be right for three separate branches — treat its IDs as placeholders.)

Rows retain `BranchID=-1`; their `VariableID`, `ScenarioID`, and `RegionID` are
copied from each target template's matching existing fuel row. This avoids
borrowing AUS branch IDs. The template directory is gitignored, so these are
local source-data updates rather than repository-tracked files.

The remaining LEAP-area task is to ensure the `AUTO BALANCE` fuel/branches exist
in each real area. Re-exporting each area later remains the route to replacing
the deliberately unresolved BranchIDs with LEAP-owned IDs.

### Next implementation work

1. **Code→name mapping.** `map_code_label` falls back to the raw label, so the
   workbook currently emits the branch as `99 AUTO BALANCE`. If the LEAP fuel is
   named `AUTO BALANCE`, add a `leap_display_names` entry
   (`esto_product`, code `99 AUTO BALANCE`, name `AUTO BALANCE`,
   `USED_IN_LEAP_INITIALISATION=1`) in
   `leap_mappings/config/outlook_mappings_master.xlsx`. Not done — cross-repo data
   edit, and this repo forbids a second local crosswalk.
2. **Fuel catalog preflight** (`codebase/utilities/fuel_catalog_preflight.py`)
   refreshes by probing LEAP, so it should pick the fuel up once it exists —
   confirm rather than assume.
3. **Balance ingestion / checks** — exclude `AUTO BALANCE` from real-energy
   comparisons. Enumerate the sites against a real fuel rather than guessing.

## Findings a fresh agent will otherwise rediscover the hard way

- **The seed workbook path is already scenario-aware.** `results_saver.py:1977` →
  `save_transfer_exports_with_supply_overrides` → `build_transfer_rows(scenario=)`.
  Verified: `01_AUS` 2060 is 79.01 Reference vs 73.56 Target. Scenario is lost only
  on the *reconciliation input* path. The work-queue text predates this correction.
- **Passing the scenario does not remove the zeros.** The 9th stores exact `0.0`
  for the affected economies; `12_NZ` Reference already came from the
  scenario-aware path and is zero across all 38 projection years.
- **Only 2 of 11 seed economies have any 9th transfer projection** (`01_AUS`,
  `20_USA`; APEC-wide it is those two plus `03_CDA`, `09_ROK`).
- **`20_USA` Reference and `03_CDA` are exact flat carry-forwards of 2022** in the
  9th. That is evidence the 9th team encodes carry-forward when they have no view —
  which is what made the maintainer's decision reasonable.
- **One-sidedness is present at every aggregation level** — leaf, subflow-sum, and
  the `08 Transfers` parent alike. Rolling up does not resolve it.
- **`05_PRC` has never been two-sided** in the 2024 vintage (0 of 23 years).
  **`13_PNG` normally is** (17 of 23) — 2022 is its anomaly. `04_CHL` is one-sided
  in 2024 only; `07_INA` *becomes* one-sided from 2025.
- **Three spellings are in play** for `15.04` and `07.15`: the data tables, the
  mappings sheets, and `ESTO_PRODUCT_LIST`/the live LEAP model (see
  `codebase/configuration/known_leap_label_exceptions.py`). The canonical tables
  target the data-table/mapping spelling. This was a judgement call inside a
  pre-existing inconsistency, not a typo fix.
- **Run traps:** `prepare_transformation_assets()` takes ~8 minutes; budget for it.
  Run from the main repo root, not the worktree — the worktree has no
  `data/leap_export_templates`, so `transfers_workflow` fails at import.

## Files touched

Committed in `dd20a4c`: `codebase/mapping_tools/prepare_new_esto_data.py`,
`codebase/transfers_workflow.py`, `codebase/mapping_tools/build_apec_2026_preliminary.py`,
`docs/README.md`, `docs/initialisation_flow_estimation_methods.md`,
`docs/work_queue.md`, `tests/test_prepare_new_esto_data.py`.

Committed in `dd20a4c`: `docs/decision_transfer_projection_fallback_20260820.md`,
`docs/esto_vintage_onboarding.md`, `tests/test_transfer_one_sided_balance.py`,
this file.

Committed in `5c304fd`: `codebase/supply_reconciliation/{tables.py,leap_io.py,results_saver.py}`,
`codebase/transfers_workflow.py`, and the transfer projection regression tests.

Regenerated (gitignored): `data/00APEC_2026_low_with_subtotals_PRELIMINARY.csv`.

Pre-existing untracked from other sessions, **not part of this work**:
`.tmp_webq002_*.py`, `docs/webq_002_synthetic_own_use_rollup_findings.md`,
`docs/coal_transformation_own_use_grossup_findings.md`. `build_apec_2026_preliminary.py`
and `test_build_apec_2026_preliminary.py` arrived untracked from another session and
were *modified* here.
