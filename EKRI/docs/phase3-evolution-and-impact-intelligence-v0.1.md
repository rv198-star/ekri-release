# EKRI Phase 3 — Evolution and Impact Intelligence v0.1

Status: implementation contract

Parent: `#826`

Dependencies: accepted Phase 0, Phase 1, and Phase 2 authority

## Objective

Phase 3 adds bounded incremental reconstruction, registered-change verification,
Architecture Evolution, Change Impact, and snapshot refresh over the fixed WFF
v1.6.2 Architecture Memory.

Phase 3 does not rewrite the Phase 1 snapshot. It persists an evidence-linked
overlay that distinguishes immutable baseline knowledge, observed repository
change, registered intent, and future-impact inference.

## Input authority

Every supported run revalidates:

- the fixed Phase 0 observation manifest;
- the complete Phase 1 Architecture Memory, evidence index, reconstruction
  report, output digests, source anchors, and admitted read-path closure;
- the Phase 2 capability catalog projection and capability IDs;
- the active clean EKRI scanner commit/tree.

The supported public entry point is:

```python
run_phase3_evolution_analysis(...)
```

Low-level scan, event, Evolution Map, Impact Map, and persistence builders are
internal. A caller-created dictionary or forged dataclass is not accepted as
verified authority.

## Incremental reconstruction modes

### Baseline

`baseline` confirms the verified Phase 1 source tree and creates an empty delta.
It does not create new architecture truth.

### Local change

`local-change` requires explicit seed paths. The scanner computes a bounded
frontier from:

- changed paths;
- Phase 1 evidence-path co-membership;
- Phase 2 capability locations;
- capability and ownership neighborhoods.

Only regular Git blobs inside that frontier are read. Hidden dependency risk is
always reported as `managed-not-eliminated`; local scanning never claims a
complete dependency graph.

### Drift

`drift` covers the complete admitted path delta between the verified baseline
and target Git trees. It is required for release snapshot refresh.

All modes:

- resolve immutable commit/tree identities with replacement objects disabled;
- evaluate the target through the Phase 0 observation boundary before target
  blob reads;
- permanently exclude `EKRI/**`, `.EKRI/**`, and oracle paths;
- record added, deleted, modified, type-changed, renamed, and copied paths;
- retain exact before/after blob identities and bounded read receipts;
- keep unmapped changed paths and residual uncertainty visible.

## Change Registration

A registration is an intent signal, not repository truth:

```text
registered -> planned -> observed -> verified -> archived
```

Caller-managed state is limited to:

```text
registered -> planned
```

`observed` and `verified` are scanner-owned states. Direct dataclass
construction cannot bypass this rule because every registration is rebuilt and
compared with the canonical builder contract before a run.

Each registration records:

- change ID;
- existing baseline capability ID;
- change kind;
- intent summary;
- expected admitted paths;
- optional decision reference;
- registration time.

The current profile verifies changes to capabilities represented in the fixed
Phase 1/2 baseline. A genuinely new capability remains outside verified
Architecture Evolution until a future reconstruction profile admits it.

## Deferred verification

Verification is triggered only when:

- Existing Capability Intelligence consumes the affected capability;
- a design decision depends on it;
- explicit verification is requested;
- release verification runs.

A registration becomes repository-surface `verified` only when every expected
path is present in the internally verified admitted Git delta. Partial matches
remain `observed / pending`; no match remains `registered` or `planned`.
Unimplemented registration paths selected for local verification are recorded as
`deferred_unobserved_registration_paths`; they do not block the scan or become
mandatory changed seeds.

Path verification proves that the registered surface changed. It does not prove
that the caller's semantic description, business acceptance, or runtime
behavior is correct. Each event therefore separates the two states structurally:

```text
verification_scope: repository-surface
observed_fact.knowledge_state: observed-fact
registered_intent.knowledge_state: registered-change
registered_intent.semantic_claim_state: not-independently-proven
```

## Architecture Evolution Map

Architecture Evolution contains only internally verified events. It answers:

- which registered capability surface changed;
- which change category was registered;
- which immutable baseline and target trees were compared;
- which admitted change records matched;
- which Git-delta evidence references support the event;
- which registrations remain pending.

It is not a Git-log summary, does not use commit messages as architecture truth,
and does not claim complete semantic history.

## Change Impact Map

Change Impact is separate from Evolution:

- Evolution describes verified past repository-surface change.
- Impact predicts possible future effects.

Every non-unknown impact remains:

```text
knowledge_state: inferred-knowledge
confidence: medium
truth_boundary: prediction-not-architecture-fact
```

A non-unknown impact must reference baseline Phase 1 evidence. Unknown or
unsupported capability and evidence references fail closed.

## Snapshot refresh

The refresh artifact binds:

- the immutable Phase 1 baseline snapshot;
- the target observation manifest;
- the incremental scan;
- verified evolution event IDs;
- pending registrations;
- unmapped changed paths.

It uses the overlay model:

```text
verified-evolution-over-phase1-baseline
```

Release verification is a project-governance action, not a P1-P4 runtime step.
It requires:

- `scan_mode=drift`;
- `verification_trigger=release-verification` and `release_verification=true`
  selected together;
- a release reference that resolves to the scanned target commit.

## Runtime outputs

```text
.EKRI/evolution/<target-tree>/
├── incremental-reconstruction.json
├── change-register.json
├── architecture-evolution-map.json
├── change-impact-map.json
├── architecture-snapshot-refresh.json
├── PHASE3_EVOLUTION.md
└── phase3-audit.json
```

Writes use no-follow directory handles and atomic replacement. Symlinked output
parents fail closed.

## Reproducible independent-audit bootstrap

A clean worktree intentionally contains no ignored `.EKRI/` runtime state, but
may contain verified tracked `.EKRI/project/**` baseline knowledge. Before
Generate can consume that portable asset directly. Phase 3 Evolution still
requires a current repository-root-bound Phase 0 manifest, so its clean-worktree
bootstrap regenerates local runtime authority rather than copying an old
observation manifest with an absolute repository-root identity.

The independent-audit bootstrap therefore regenerates Phase 0 and Phase 1 from
the immutable baseline, then compares stable semantic fingerprints with the
committed expectation fixture:

```text
EKRI/audit-fixtures/wff-v162-phase3-baseline.json
```

Run:

```bash
python3 EKRI/scripts/bootstrap_phase3_audit.py \
  --repository-root /path/to/clean/worktree
```

The fixture fixes:

- baseline commit/tree;
- admitted path count and path-set digest;
- Phase 1 record counts;
- root-, timestamp-, and scanner-independent Phase 1 semantic fingerprints;
- Phase 2 capability/alias/ambiguity profile.

The bootstrap report is written to:

```text
.EKRI/audit/phase3-bootstrap.json
```

The fixture is scanner-side audit expectation, not target evidence, and cannot
certify Phase 3 behavior by itself.

## Command

```bash
python3 EKRI/scripts/run_phase3_evolution.py \
  --repository-root /path/to/repository \
  --target-ref HEAD \
  --scan-mode drift \
  --registrations /path/to/registrations.json \
  --impacts /path/to/impacts.json \
  --verification-trigger explicit-request
```

Use `--no-write` for analysis without Phase 3 output persistence.

## Schemas

- `change-registration.schema.json`
- `incremental-reconstruction.schema.json`
- `architecture-evolution-map.schema.json`
- `change-impact-map.schema.json`
- `architecture-evolution-snapshot.schema.json`
- `phase3-evolution-audit.schema.json`
- `phase3-audit-fixture.schema.json`

## Claim ceiling

Phase 3 proves bounded immutable Git deltas, admitted frontier blob receipts,
repository-surface verification of registered expected paths, and explicitly
inferred future impact. It does not prove exhaustive architecture history,
complete dependency impact, semantic implementation correctness, accepted
architecture decisions, release readiness, production behavior, or business
truth.
