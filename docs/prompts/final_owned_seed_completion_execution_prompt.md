# Final owned-seed completion execution prompt

Type: staged implementation and equivalence verification. No full supply-reconciliation run unless the user explicitly asks.

## Status — deferred (2026-07-17)

Do not start this implementation as the next cleanup task. The design is a
valid longer-term direction, but it is not a fast, output-preserving refactor:
it introduces a new ownership abstraction at the final seed emit boundary,
where all producers converge. The current boundary already owns the structural
rules that must be central (`prepare_seed_rows_for_write`, canonical-share
completion, ID enrichment, and validation), while the remaining fill/reset
mechanisms have materially different semantics.

In particular, own-use and demand zero-fill already share the generic mechanics
in `export_zero_fill.py`. Transformation zero-fill intentionally remains local:
it combines process ownership, scenario windows, canonical-share anchors, and
capacity/efficiency safeguards. Moving these mechanisms merely because they
look repetitive would hide policy differences and risks changing missing-row
behaviour.

The initial planner stages would produce inventory and diagnostics, not faster
seed results or immediate code removal. Every migrated domain would still need
post-boundary equivalence evidence. Therefore, prioritise the per-economy
export-template/reset-scope work and other concrete correctness items first.

### Conditions to resume

Pick this up only when all of the following are true:

- there is a concrete need beyond general code tidiness (for example, two or
  more additional low-risk zero/default domains would otherwise duplicate the
  same template-aware completion mechanics);
- Stage 0 identifies at least one candidate whose owner, template-key scope,
  scenarios/years, zero semantics, and backing invariant are unambiguous;
- the candidate has an existing stable post-boundary output that can be used as
  an equivalence baseline, with the current economy's resolved template;
- the migration can be tested without a full reconciliation run and without
  inventing share, capacity, efficiency, or scenario-year policy; and
- per-economy template routing and reset-scope work is sufficiently settled
  that a template-aware comparison cannot be confounded by a pinned USA
  template or an economy-inappropriate reset scope.

Messy-looking producer code alone is not a sufficient reason to resume. If a
candidate fails any condition, leave its producer-local mechanism in place and
record the reason in the ownership inventory rather than adding a broad
fallback.

## Short version

Move toward a single final, template-aware completion step for baseline seeds:

```text
all producer rows
-> merge and resolve duplicates
-> compare against the current economy's template
-> add rows only for branch/measure domains owned by this run
-> canonical share completion and capacity/efficiency rules
-> validation and write
```

This is not an early blanket reset. Do not overwrite rows before all producers
have contributed, and do not infer an ownership rule from a missing row.

## Why

The current code has several workflow-local zero/default mechanisms. They are
needed to prevent stale LEAP values, but a generic early reset is unsafe: a
later producer can be skipped or fail, and different measures require different
completion rules.

- Ordinary owned reset rows can be `0`.
- Output, Process, and Feedstock shares require canonical siblings and a valid
  100-percent profile, not a blanket zero.
- Process Efficiency defaults to 100 only where the existing capacity rule
  allows it; nonzero Exogenous Capacity requires a usable supplied expression
  (`SEED-013` / `SEED-C030`).

`prepare_seed_rows_for_write` is already the F2 emit boundary. It resolves
duplicates, completes canonical shares, enriches IDs, validates, writes
diagnostics, and blocks invalid seeds. Extend that boundary incrementally rather
than creating another writer or moving resets to workflow startup.

## Existing evidence to preserve

- `docs/check_registry.md` F1 distinguishes gap-fill from reset and records the
  current backing checks.
- `docs/check_registry.md` F2 defines the emit boundary and its three callers.
- `docs/baseline_seed_rule_inventory.md` defines SEED-C001--C030; do not change
  share, ID, capacity, or efficiency semantics during this refactor.
- `codebase/functions/baseline_seed_validation.py::prepare_seed_rows_for_write`
  and `complete_canonical_share_groups` are the existing final-stage machinery.
- `codebase/functions/export_zero_fill.py` centralizes only the generic
  own-use/demand filtering mechanics. Transformation zero-fill deliberately
  remains local because its ownership, share-anchor, and capacity behaviour is
  more specific.
- Templates are structural references, not data-value sources. Resolve the
  template per economy; never silently fall back to a different economy's
  template for an economy-specific write.

## Objective

Create a small, testable final-completion planner that receives merged rows,
the current economy's template, and explicit ownership declarations. It should
report which template keys are owned-and-missing and produce only the
well-defined completion rows for that declaration. Migrate no domain until its
ownership and completion policy are proven by tests and an equivalence check.

## Stages

### Stage 0: ownership inventory and design checkpoint

1. Read `docs/check_registry.md`, `docs/baseline_seed_rule_inventory.md`, this
   prompt, and the current `prepare_seed_rows_for_write` callers.
2. Create a concise ownership table in a new active design note or in this
   prompt's status note. For every candidate domain record:
   - owner workflow(s);
   - branch-prefix or template-key scope;
   - variables;
   - scenarios/years;
   - completion policy (`zero`, canonical share completion, capacity-aware
     efficiency default, or leave untouched);
   - current producer-local mechanism;
   - backing invariant; and
   - whether a missing row can safely mean reset.
3. Treat ambiguous or overlapping ownership as a stop condition. Report it;
   do not guess a priority order or create a broad fallback.
4. Commit the inventory/design note separately if it changes documentation.

### Stage 1: pure planner, no producer migration

Add a narrowly named helper near the F2 validator, for example
`plan_owned_template_completion(...)`. It must:

- accept a resolved merged row table, a template table/path, and explicit
  ownership declarations;
- use the logical key `(Branch Path, Variable, Scenario, Region)`;
- report owned template keys missing from the intended rows;
- exclude ignored full-model-export rows using the existing policy;
- never emit a row outside a declaration;
- return planned rows and diagnostics separately; and
- make no workbook writes or LEAP calls.

Start with diagnostics-only mode if the row-generation interface would require
an unproven default. Add focused synthetic-template tests for two economies with
different branch sets, duplicate keys, an unowned missing key, and an owned
missing key.

### Stage 2: migrate one low-risk zero domain

Only after Stage 1 is proven, choose one domain whose owner, scope, and zero
semantics are unambiguous. Candidate: a narrowly scoped ordinary reset whose
current output is already gated. Do not migrate demand zeroing, own-use, or
transformation merely because they are convenient.

For the selected domain:

- express ownership as explicit configuration, not inferred prefixes scattered
  through producer code;
- generate `0` only for owned template keys absent after all producer rows are
  merged;
- preserve existing expression style, metadata, scenarios, and sheet placement;
- compare post-boundary logical row sets and expressions before/after on a
  representative economy without running the full reconciliation workflow; and
- commit this migration independently.

### Stage 3: structural completion domains

Do not reimplement canonical share or efficiency logic in the planner.

- Shares continue through `complete_canonical_share_groups`, including canonical
  sibling completion, donor borrowing, deterministic anchors, and the
  Exogenous Capacity gate.
- Process Efficiency continues through its existing producer guard and
  `SEED-013`; only migrate its default generation when the ownership table proves
  that a final-boundary default cannot hide a producer failure.

Any change here needs a separate prompt/commit and targeted equivalence evidence.

## Constraints

- Run `git status --short` before editing. Stop if relevant files are dirty.
- Do not run `supply_reconciliation_workflow.py` or any full baseline-seed run.
- Do not change mappings, source data, LEAP structure, scenarios, or model
  methodology.
- Do not use a USA template for another economy's final write. Structural branch
  sets can differ even when many current generated templates happen to match.
- Preserve `-1` handling: nonzero unresolved-ID rows remain blocking; zero
  unresolved-ID rows remain review findings.
- Do not make optional gap-fills switchable until the registry records a backing
  invariant for that measure.
- Do not remove producer-local logic until its final-boundary replacement has
  passed equivalence tests.

## Validation

- Add unit tests for the planner's ownership filtering, missing-key diagnostics,
  ignored-row handling, and economy-specific template differences.
- Run the focused baseline-seed validation tests and
  `tests/test_check_registry.py`.
- For every migrated domain, compare post-boundary rows on
  `(Branch Path, Variable, Scenario, Region, Expression)` before and after.
  Classify every difference; expected output is no difference unless a separate
  approved correction is being made.
- Run `git diff --check` before each commit.

## Stop conditions

Stop and report before changing code if:

- ownership overlaps or is not documented well enough to decide who may reset a
  key;
- a missing key might belong to another workflow or an intentionally inherited
  LEAP value;
- the proposed planner would need a new share, capacity, efficiency, or
  scenario-year policy;
- equivalence differs unexpectedly; or
- work requires a full reconciliation run or a LEAP structural/data change.

## Deliverables

1. A committed ownership inventory/design decision.
2. A pure planner with tests and diagnostics-only behaviour.
3. Separately committed, equivalence-verified domain migrations only where safe.
4. Registry and rule-inventory updates for every new or renamed check.
5. Archive this prompt with its status note once all approved stages are complete.

## Update before use

Re-check `prepare_seed_rows_for_write`, `complete_canonical_share_groups`,
`zero_fill_unset_rows`, current F1/F2 registry entries, all caller paths, and
the economy-template resolver with `rg` before editing. The line numbers and
current list of producer-local fills will evolve.
