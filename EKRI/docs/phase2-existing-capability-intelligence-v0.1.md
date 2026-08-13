# EKRI Phase 2 — Existing Capability Intelligence v0.1

Status: implementation contract

Issue: `#860`

Parent design: `engineering-knowledge-reconstruction-intelligence-v0.1.md`

## Objective

Phase 2 consumes verified Architecture Memory before new engineering work is
generated. It answers whether a requested capability is already represented,
where it is owned, which boundaries constrain reuse, what triggered the change,
how the capability relates to the WFF mainline, and which bounded posture is
supported.

Phase 2 is an intelligence layer over reconstructed knowledge. It is not a
second scanner and does not create missing architecture truth.

## Fixed input authority

The first profile consumes the Phase 1 snapshot for:

```text
commit: 764dc832eb7488b32ff0e24591a2018bfa719d39
tree:   e7bd7082e1674cce1f2d2e2f11f5978555f973b1
```

Before every formal query, Phase 2 revalidates:

- Architecture Memory, Evidence Index, reconstruction report, and human
  projection file presence through no-follow reads;
- source commit/tree and snapshot identity agreement;
- Phase 1 output digests;
- report counts against persisted content;
- target blob read-path agreement;
- Architecture Memory evidence-reference closure.

If any check fails, no capability lookup runs.

## Capability catalog

The catalog is a reviewed consumption index over Phase 1 records. Every entry
must reference existing:

- architecture node IDs;
- responsibility IDs;
- constraint IDs;
- implementation-intent IDs;
- assurance-ownership IDs;
- admitted evidence references.

The catalog may add deterministic aliases and mainline-impact interpretation,
but those interpretations must remain evidence-linked. It cannot add a new
capability that Architecture Memory does not represent.

The first WFF catalog covers:

- lifecycle routing and accepted handoffs;
- P1-P4 greenfield lifecycle;
- requirements intake;
- product requirements;
- architecture design;
- implementation delivery;
- validation closure;
- brownfield assessment;
- project context;
- traceability;
- reader translation;
- interaction maps;
- evidence and claim control;
- Human Review;
- install-profile packaging;
- role-agent adaptation.

## Exact alias policy

Lookup uses Unicode-normalized, case-folded, punctuation-insensitive **exact
aliases**. It does not use embeddings, fuzzy semantic search, or code RAG.

Outcomes:

- one match: continue with that capability;
- more than one match: `ambiguous`, block the decision;
- no match: `not-found`, retain capability existence as `unknown`.

A lookup miss never proves capability absence because Architecture Memory is a
bounded snapshot.

## Before Generate request

Every request declares:

- capability query;
- trigger basis;
- requested change mode;
- trigger reference when the trigger is observed or declared;
- explicit decision status plus decision reference and non-reuse reason when a
  caller asserts that an architecture decision was accepted;
- optional context note.

Trigger basis is one of:

- `observed-failure`;
- `declared-requirement`;
- `hypothetical-risk`.

Change mode is one of:

- `use-as-is`;
- `additive-extension`;
- `behavior-replacement`;
- `new-capability`.

## Six required answers

Every report answers:

1. Does the capability already exist?
2. Where does it exist and who owns it?
3. Which non-responsibilities and constraints may limit reuse?
4. Is the trigger an observed failure, declared requirement, or hypothetical
   risk?
5. Does the change touch the WFF mainline directly, conditionally, as support,
   or outside runtime mainline?
6. Is the supported posture `reuse`, `extend`, `replace`, `create-new`, or
   `insufficient-evidence`?

## Recommendation policy

### Reuse

`use-as-is` over a uniquely resolved capability produces `reuse` unless the
capability state is unknown.

### Extend

`additive-extension` produces `extend`. Requesting a new capability when a
related capability already exists also defaults to `extend` unless an explicit
reviewed separation decision is supplied.

### Replace

Replacement requires all three:

- `decision_status=accepted`;
- an explicit decision reference;
- a concrete non-reuse reason.

The accepted status is caller-supplied metadata and is preserved as
`caller-asserted-accepted-not-independently-verified`; EKRI does not promote it
into verified repository truth. Observed failure or declared requirement
identifies pressure but does not by itself authorize replacement. Hypothetical
risk alone never authorizes replacement.

### Create new

A new capability may be recommended only with `decision_status=accepted`, an
explicit decision reference, and a non-reuse reason. Acceptance remains a
caller assertion. When lookup did not find a capability, the report must still
state that absence was not proven.

### Insufficient evidence

The result is blocked when:

- the query is ambiguous;
- the query is not found without a reviewed new-capability decision;
- the matched capability has unknown existence/ownership state;
- replacement lacks a decision and non-reuse reason.

## Mainline impact

Mainline impact is explicit:

Every mainline-impact classification is labeled `inferred-knowledge` with an
explicit confidence and evidence references. Classifications are:

- `direct-mainline`: owns or controls P1-P4 admission, execution, evidence, or
  closure;
- `conditional-mainline`: side route that may re-enter the mainline;
- `supporting-mainline`: supports multiple phases without owning their truth;
- `outside-runtime-mainline`: distribution, adaptation, or review projection
  that does not change P1-P4/PX runtime state;
- `unknown`: no unique capability resolved.

## Authority and runtime outputs

Phase 2 accepts either:

- a fully revalidated local Phase 1 runtime snapshot; or
- a verified tracked `.EKRI/project/**` asset whose target tree, artifact
  digests, evidence blobs, protected-path exclusions, and evidence-reference
  closure have been rechecked.

A committed asset is not trusted merely because Git contains it. The result
records `verified-local-runtime` or `verified-tracked-project-asset` as the
active authority mode.

Generated query output remains local and ignored:

```text
.EKRI/intelligence/<tree>/
├── capability-catalog.json
├── checks/
│   ├── <request-id>.json
│   └── <request-id>.md
└── audits/
    └── <request-id>.json
```

Writes use no-follow directory handles and atomic replacement. Existing output
symlinks are replaced rather than followed; symlinked parent directories are
rejected.

## Supported API boundary

The supported Python surface is intentionally narrow:

- `build_request(...)` validates caller input;
- `run_existing_capability_check(...)` verifies tracked project knowledge or
  revalidates local Phase 1 authority, evaluates the request, and optionally
  persists outputs in one controlled call.

Low-level catalog construction and report evaluation remain internal and are
not exported from the `ekri` package. A plain or caller-mutated catalog cannot
be presented to the evaluator as verified authority.

## Command

```bash
python3 EKRI/scripts/check_existing_capability.py \
  --repository-root /path/to/repository \
  --capability "traceability" \
  --trigger-basis declared-requirement \
  --trigger-reference REQ-123 \
  --change-mode additive-extension
```

Use `--project-asset-id <asset-id>` to require one explicit tracked project
asset. Use `--no-write` for a read-only check.

Exit codes:

- `0`: actionable bounded recommendation;
- `2`: invalid input or unverifiable authority;
- `4`: structurally valid report blocked by insufficient evidence.

## Claim ceiling

Phase 2 proves only that a bounded recommendation was produced from one
verified Architecture Memory snapshot and caller-supplied trigger metadata. It
does not prove exhaustive capability coverage, implementation fitness,
accepted architecture approval, production readiness, architecture evolution,
or complete future change impact.
