# Other Loss/Own-Use Proxy Hardening Prompt

## Short Version

You are working in:
`C:\Users\Work\github\leap_initialisation`

Harden the first-run own-use/loss proxy workflow in:

- `codebase/other_loss_own_use_proxy_workflow.py`
- `codebase/functions/other_loss_own_use_proxy_utils.py`

Implement three changes:

1. Enable `oil_refineries` proxy in `PROXY_CONFIG`.
2. Add robust first-run fallback chains (ESTO/9th alternative-source activity) for selected vulnerable proxy processes beyond liquefaction/regasification.
3. Add a strict data-quality guardrail: raise (configurable) error when `proxy_activity == 0` while `target_energy > 0` for a proxy row.

Then run targeted validation for `01_AUS` and produce a concise report with before/after outcomes.

---

## Background and Current State

The workflow writes difficult-to-allocate ESTO own-use/loss rows to:

- `Demand\Other loss and own use\{process}\{fuel}`

Current enabled proxies include:

- coal_mines
- electricity_chp_and_heat_plants
- liquefaction_regasification_plants
- oil_and_gas_extraction
- pump_storage_plants
- nuclear_industry
- gasification_plants_for_biogases
- transmission_and_distribution_losses

Current known issues/gaps:

- `oil_refineries` is currently `enabled=False` in `PROXY_CONFIG`.
- `ESTO_NINTH_ACTIVITY_FALLBACKS` currently includes only `liquefaction_regasification_plants`.
- In some cases, target energy can be non-zero while activity proxy is zero; current intensity formula then forces intensity to 0:

  - `intensity = 0.0 if proxy_activity == 0 else target_energy / proxy_activity`

- This can silently mask data-quality problems.

---

## Objective

Make first-run (`activity_source_mode = "esto_ninth"`) proxy generation more robust and auditable by:

- including oil refineries where policy intends proxy-led handling,
- using fallback activity sources for additional fragile sectors,
- and failing fast (or at least explicitly warning, based on config) for impossible combinations (`target_energy > 0` with zero activity).

---

## Scope

### In scope

1. **Enable oil refineries proxy**
   - In `PROXY_CONFIG`, set:
     - `process_key="oil_refineries"`
     - `enabled=True`
   - Keep existing activity and target source definitions unless a concrete bug is found.

2. **Add first-run fallback chains beyond liquefaction/regasification**
   - Extend `ESTO_NINTH_ACTIVITY_FALLBACKS` with explicit per-process fallback tiers for high-risk zero-activity processes.
   - At minimum, evaluate and implement for:
     - `pump_storage_plants`
     - `electricity_chp_and_heat_plants` (only if truly needed and semantically safe)
     - `oil_refineries` (if enabling reveals zero-activity cases)
   - Fallback definitions must include both ESTO and 9th clauses and use explicit `value_mode`.
   - Keep fallback tiers conservative and auditable (clear `fallback_key` and `activity_label`).

3. **Add zero-activity vs positive-target guardrail**
   - Add a validation stage after `target["proxy_activity"]` and `target["intensity"]` are computed in `build_proxy_detail_table` flow.
   - Detect rows where:
     - `proxy_activity == 0` AND `target_energy > 0`
   - Add configurable behavior with default **strict**:
     - `STRICT_PROXY_ACTIVITY_TARGET_CONSISTENCY = True`
     - If strict: raise `ValueError` summarizing process/fuel/year count and sample rows.
     - If not strict: write rows to a diagnostics CSV and print a warning.

4. **Diagnostics and reporting outputs**
   - Write a dedicated CSV under existing supporting files folder, e.g.:
     - `proxy_activity_target_consistency_issues.csv`
   - Include columns at least:
     - `economy`, `process_key`, `process_label`, `fuel_branch_label`, `year`, `proxy_activity`, `target_energy`, `source_dataset`, `activity_source_mode`, `issue_type`

5. **Tests / validation**
   - Add or update tests in `tests/test_other_loss_own_use_proxy_workflow.py`.
   - Include tests for:
     - oil_refineries enabled and present in detail output when source data supports it,
     - fallback activation for at least one newly-covered process,
     - strict guardrail raises on synthetic `proxy_activity=0 && target_energy>0`,
     - non-strict mode logs issues without raising.

### Out of scope

- Large-scale redesign of proxy methodology.
- Changing LEAP balance mode semantics beyond what is required for guardrail compatibility.
- Dashboard code changes.

---

## Implementation Requirements

### A. Config switches (add near existing editable constants)

Add configurable flags in `codebase/other_loss_own_use_proxy_workflow.py`:

- `ENABLE_OIL_REFINERIES_PROXY = True` (or equivalent direct config edit in `PROXY_CONFIG`)
- `STRICT_PROXY_ACTIVITY_TARGET_CONSISTENCY = True`
- `WRITE_PROXY_ACTIVITY_TARGET_CONSISTENCY_ISSUES = True`

If you prefer fewer knobs, keep at least:

- `STRICT_PROXY_ACTIVITY_TARGET_CONSISTENCY` (default `True`)

### B. Guardrail behavior detail

When issues exist:

- strict mode:
  - raise with an error message including:
    - total issue count,
    - unique process count,
    - first N sample tuples `(process_key, fuel_branch_label, year)`.
- non-strict mode:
  - continue execution,
  - write CSV issues file,
  - print warning with path and count.

### C. Preserve existing fallback reports

Do not break existing:

- `proxy_activity_source_fallbacks.csv`
- `proxy_activity_source_warnings.csv`

If newly added fallback chains activate, they should naturally appear in fallback reports.

### D. Naming and style

- Keep notebook-safe workflow style unchanged (`#%%` compatible).
- Keep paths resolved via existing repo-root helpers.
- Keep comments concise and operational.

---

## Validation Plan

Run at least:

1. Focused tests:

- `tests/test_other_loss_own_use_proxy_workflow.py`

1. Targeted 01_AUS run for own-use/loss proxy workflow.

1. Confirm outputs under:

- `outputs/leap_exports/standalone/supporting_files/other_loss_own_use_proxy/01_AUS/`

Check specifically:

- `oil_refineries` rows now present (if source supports activity/target rows).
- New fallback processes produce fallback records when configured activity is zero.
- Guardrail behavior:

  - strict mode: run fails on inconsistent rows,
  - non-strict mode: run completes and writes `proxy_activity_target_consistency_issues.csv`.

---

## Acceptance Criteria

All must pass:

1. `oil_refineries` is enabled in active `PROXY_CONFIG`.
2. `ESTO_NINTH_ACTIVITY_FALLBACKS` includes additional process fallback chains (not only liquefaction/regasification).
3. Guardrail exists and is configurable, default strict.
4. In strict mode, `proxy_activity == 0 && target_energy > 0` raises a clear error.
5. In non-strict mode, same condition is logged to diagnostics CSV and workflow continues.
6. Existing fallback/warning outputs remain intact and meaningful.
7. Tests for fallback + guardrail pass.
8. Provide a short implementation summary listing:
   - files changed,
   - config switches added,
   - fallback chains added,
   - test results,
   - 01_AUS before/after deltas.

---

## Suggested Process Prioritization for Fallback Expansion

Apply fallback tiers in this order:

1. `pump_storage_plants` (known risk: target/activity mismatches in transition years)
2. `oil_refineries` (after enabling)
3. `electricity_chp_and_heat_plants` (only if real zero-activity gaps are observed)

Use conservative alternatives tied to physically meaningful parent or trade/production indicators and avoid broad fallbacks that could hide real data problems.

---

## Notes

- Prefer explicit failure over silent zeroing when data is inconsistent.
- Keep diagnostics human-readable and easy to trace by economy/process/fuel/year.
- Do not downgrade existing correctness checks.
