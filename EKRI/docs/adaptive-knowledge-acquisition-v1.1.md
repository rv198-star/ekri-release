# EKRI v1.1 Adaptive Knowledge Acquisition

Status: Issue #1073 implementation/release contract.

## Product intent

EKRI v1.1 improves how engineering knowledge is acquired and refreshed. It does not redesign the stable v1.0 Engineering Knowledge Model.

```text
Mission + exact target + current Project Knowledge + budget
→ Mission Context
→ Agent-authored Competency Questions
→ Knowledge Sufficiency
→ ephemeral Mission Exploration Plan
→ bounded WAE acquisition loop
→ exact Evidence Receipts
→ Candidate Knowledge Delta
→ existing family authority boundary
```

The acquisition layer is a control plane, not a semantic store.

## Stable and dynamic boundary

Stable: source identity, family semantics, identity/evidence/authority rules, knowledge state, Project Knowledge versioning, Exploration Constitution, generic operator semantics, WAE budget/stop rules.

Dynamic: competency questions, gap priority, operator selection, scope, collector choice, depth, iteration count and bounded candidate deltas. Plans may vary across Agents; durable EKRI knowledge remains governed by stable rules.

## Exploration Constitution

1. Reuse verified Project Knowledge before source expansion.
2. Bind missions and evidence to exact Git commit/tree context.
3. A search/graph/collector miss cannot prove absence.
4. Structural topology cannot create semantic ownership or architecture authority.
5. Unknown and conflicting posture remains explicit.
6. Plans, operators, collectors and WAE traces are acquisition controls only.
7. Deepening is budgeted with explicit stop/return conditions.
8. Durable changes route through an existing or explicitly versioned family authority contract.

## Mission Context and Sufficiency

Mission Context binds the mission, exact target, selected Project Knowledge v1/v2, `exact-target / stale-target / no-project-knowledge` freshness, family availability, a Git path-metadata-only environment hint, constitution, generic operator registry and caller budget. The environment hint reads no business blobs and makes no technology/framework classification.

The host Agent authors Competency Questions with decision relevance, blocking posture, family requirements, accepted availability, freshness requirement and uncertainty policy. EKRI mechanically classifies each as `sufficient-existing` or `requires-exploration`.

## Mission Exploration Plan

The typed plan is deliberately not a workflow DSL. It contains gap priority/rationale, bounded slices, one generic operator per slice, scope refs, evidence kinds, expected information gain, budgets, success/failure posture, and stop/return conditions.

Rules: sufficient questions cannot be rescanned; every blocking gap is covered; non-blocking gaps are covered or explicitly deferred; only registered generic operators are allowed; planned budgets cannot exceed Mission budget; `mission-sufficient`, `budget-exhausted`, and `source-context-changed` remain mandatory stops.

## Generic operators

`query-existing-knowledge`, `identify-boundary`, `discover-entrypoints`, `discover-capability-candidates`, `inspect-contracts`, `inspect-state-and-data`, `trace-flow`, `map-ownership`, `expand-structural-neighborhood`, `assess-freshness`, `locate-unknowns-and-conflicts`.

Collectors may be technology-specific and disposable; they cannot redefine operator semantics or become authority. v1.1 ships only an exact Git target-blob receipt collector as the general evidence primitive.

## Bounded WAE loop

Each iteration records selected slice, evidence receipts, challenge findings, reconciliation, question-state updates, cumulative budget, material gain and next action (`continue / replan / converge / return / blocked`). Convergence requires all blocking questions to be satisfied/resolved, except explicit review-bound policies. Validators independently recompute state transitions and budget usage rather than trusting fingerprints alone.

WAE controls knowledge acquisition depth only. It does not own WFF lifecycle/PX routing or semantic family truth.

## Candidate Delta and family routing

A converged mission may emit a non-authoritative Candidate Knowledge Delta. The generic routing gate never writes truth; it can only route to an existing family authority review, reject promotion for a derived-only family such as Flow, require an explicit new family contract, or record that no family update is needed.

## Conformance and economy

Three bounded shapes—service/contract/state, interaction/client, and data-pipeline—use the same constitution/operator registry while selecting different operator sequences. No `EKRI/profiles/` technology-methodology directory is allowed.

The economy audit compares the same WFF v1.9.2 questions from-zero vs reuse-aware Project Knowledge. It reports reused questions, remaining gaps and planned tool/source/byte ceilings only. The known blocked Architecture gap remains visible; no actual token/time/money savings claim is made.

## Non-goals

No technology Profile matrix, Human Projection, PX route decision (#1064), convergence discovery (#1065), always-on scanner, generic Agent scheduler/plugin platform, new semantic writer/store/family, direct Candidate Delta promotion, autonomous refactoring/deletion/UAT/production approval.

## Claim ceiling

EKRI v1.1 can prove bounded, source-bound, reuse-aware adaptive knowledge acquisition and safe routing of non-authoritative candidates to existing family authority boundaries. It cannot prove exhaustive project understanding, complete dependency/absence knowledge, actual runtime savings, autonomous semantic acceptance, PX correctness, refactoring correctness, UAT, production readiness or owner sign-off.
