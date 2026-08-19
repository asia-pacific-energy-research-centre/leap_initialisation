# Today’s three-hour colleague handover plan — 2026-08-20

## Intended outcome at T+3:00

Hand colleagues a safe, evidence-backed release decision rather than a large
set of unrelated code changes:

1. MAPQ-052 has either a committed and measured first-pass memory reduction,
   or an honest stop report that identifies the phase which prevents a safe
   mapping refresh.
2. WEBQ-002 and initialisation queue item [50] each have a short reproducible
   diagnosis and a recommended next implementation decision.
3. If, and only if, the mapping validation gate is green, one clean-checkout
   dashboard/review-app rehearsal has a recorded result. Otherwise the
   downstream release is explicitly held with its exact dependency named.

This is a handover pack. Each numbered task file is independent enough to
give to a colleague or agent. Do not combine the code work into one commit.

## Priority and dependency graph

```text
MAPQ-052 measured first pass ── green, equivalent ──> fresh mapping output
                                                      │
                                                      └─> DASHQ-007 / DASHQ-017
                                                           + review-app release gate

WEBQ-002 rollup diagnosis ──────────────────────────> later baseline-seed fix
Item [50] transfer decision ─────────────────────────> later baseline-seed fix
```

The two baseline-seed items are research-only today. They must not launch a
baseline-seed run while MAPQ-052 deep validation is running: the mapping queue
records a 17.9 GB Stage 3 incident and explicitly requires its bounded run to
run alone.

## Suggested allocation

| Role | Time box | Handoff file | Deliverable |
|---|---:|---|---|
| Mapping owner | Full three hours | `01_mapq_052_stage3_memory_first_pass.md` | One focused commit plus RSS/equivalence evidence, or a stop report |
| Seed investigator A | 75–90 min | `02_webq_002_synthetic_own_use_rollup_diagnosis.md` | Reproducer and go/no-go design recommendation |
| Seed investigator B | 75–90 min | `03_transfer_projection_fallback_decision.md` | Scenario coverage table and explicit policy recommendation |
| Dashboard/review release owner | Prep in first 60 min; execute after the mapping gate | `04_dashboard_and_review_release_gate.md` | Rehearsal result or blocked release record |

## Clock and coordinator decisions

- **T+00–15 min:** each owner records `git status --short`, claims only the
  files in their task, and posts the intended output location. Preserve the
  known existing changes: initialisation has an edited work queue and new
  mapping helper/test files; dashboard has a user-owned `code_colors.json`
  edit; the review runtime is substantially dirty and has an untracked
  integration checklist.
- **T+75 min:** mapping owner reports phase markers, current peak RSS, focused
  test result, and whether an equivalent bounded run is still credible. The
  seed investigators return their first evidence tables.
- **T+135 min:** coordinator chooses the downstream route. Only a completed,
  equivalent MAPQ-052 bounded validation permits mapping-output regeneration
  and dashboard/review rehearsal. A failed, incomplete, or memory-killed run
  is a release hold, not a reason to bypass checks.
- **T+180 min:** collect four concise evidence notes: commit/hash (if any),
  tests run, output/run identifier, and the next owner/action. Move no active
  prompt to `docs/archive/` today; these tasks are not complete merely because
  their plans exist.

## Explicitly not today

- Do not start the broader streaming Stage 3 redesign described after MAPQ-052
  until its narrow first pass has passed equivalence.
- Do not implement a transfer fallback before the projection semantics are
  chosen from evidence.
- Do not alter dashboard-owned mapping logic, enable DASHQ-047 during the
  mixed LEAP-export cutover, or hand-edit `leap_review_web_app/runtime/`.
- Do not run cleanup/archive work or make the P3 semantic decisions. They are
  separate approval gates, not readiness work.

## Source queue notes reviewed

- `leap_mappings/docs/work_queue.md`: MAPQ-052 is P1, reviewed on 2026-08-19;
  its 17.9 GB Stage 3 incident is the critical technical risk.
- `leap_initialisation/docs/work_queue.md`: new items [51]/WEBQ-002 and [50]
  are explicitly awaiting independent diagnosis/design review.
- `leap_dashboard/docs/work_queue.md`: DASHQ-007 needs a fresh coherent
  mapping baseline; DASHQ-017 is the P0 clean-checkout handover rehearsal.
- `leap_review_web_app/docs/work_queue.md` and its untracked
  `docs/post_mapping_integration_checklist.md`: the prepared runtime must be
  regenerated from committed sources after mapping completion, never repaired
  by hand.
