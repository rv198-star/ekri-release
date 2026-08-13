# Engineering Knowledge Reconstruction and Intelligence v0.1 (Restarted Line)

Status: internal design authority for restarted WFF v1.7

Parent issue: `#826`

Baseline target: commit `764dc832eb7488b32ff0e24591a2018bfa719d39`,
tree `e7bd7082e1674cce1f2d2e2f11f5978555f973b1`

## Purpose

EKRI gives an AI engineering agent an evidence-linked understanding of an
existing software system before it generates new work. It is not Code RAG, a
file summary, an LLM wiki, or an automatic architecture-truth generator.

EKRI must answer whether a capability exists, which subsystem owns it, which
constraints explain it, what evidence supports it, and whether a proposed
change should reuse, extend, replace, or avoid duplicating it.

## Product boundary

EKRI is a top-level subproject incubated in the WFF repository. It is not a WFF
Skill, P1-P4/PX phase, install profile, install-pack surface, or release-bundle
dependency. Its contracts avoid unnecessary WFF lifecycle coupling so later
extraction remains possible.

Repository layout:

```text
WFF/
├── EKRI/             # source, schemas, tests, evaluation, and internal design
├── .EKRI/project/    # tracked portable project knowledge
├── .EKRI/<runtime>/  # ignored manifests, knowledge, intelligence, audit, cache, and logs
├── skills/           # WFF release Skills; unrelated to EKRI
└── ...
```

## Observation independence

The active scanner must never contribute evidence about itself. The permanent
invariant is therefore **formal-corpus disjointness**:

- scanner and target commit/tree identities are recorded independently;
- Git replacement objects cannot alter either identity;
- `EKRI/**`, `.EKRI/**`, and the explicit oracle prefix are excluded before
  target blob reads;
- the accepted path corpus is recorded and digested;
- later phases may read only blobs named by that accepted corpus;
- generated knowledge and evaluation outputs cannot certify themselves;
- tracked `.EKRI/project/**` assets remain excluded from the corpus and must be
  reverified against target Git blobs before consumption.

Physical scanner/target checkout separation is not required while EKRI is a
same-repository incubated subproject. A same-repository target is admissible
only after protected scanner surfaces are excluded and the active scanner is
cleanly identified. This replaces the earlier root-disjoint draft model.

## Layered model

```text
Knowledge Reconstruction
├── Architecture
├── Design
├── Implementation
├── Validation
├── Evolution
└── Constraint

Intelligence
├── Existing Capability
├── Change Impact
├── Before Generate
└── Reuse Recommendation
```

Reconstruction recovers engineering memory. Intelligence consumes that memory
to support a decision and must not silently create missing knowledge.

## Knowledge state

Every assertion distinguishes:

- `observed-fact`: directly supported by source evidence;
- `inferred-knowledge`: reasoned from evidence with confidence;
- `unknown`: unresolved or contradictory;
- `registered-change`: an expected change not yet verified as repository truth.

Inference is allowed, but never presented as confirmed author intent.

Every non-unknown assertion carries evidence references into the admitted Git
tree. Generated summaries are projections over those assertions, not new
source truth.

## Progressive disclosure

A later agent receives the smallest useful packet:

1. capability orientation;
2. responsibility and design detail;
3. implementation, validation, constraint, and evolution evidence for the
   affected neighborhood;
4. source references and uncertainty on demand.

Phase 1 uses Git-friendly JSON and Markdown projections. A graph database is
deferred until a demonstrated query need justifies it.

## Roadmap

### Phase 0 — Trust foundation

Establish scanner and source identity, permanent protected-path exclusion,
final-corpus validation, secure output identity, and provenance manifest. No
engineering knowledge is rebuilt.

Authority: `phase0-observation-independence-v0.2.md`.

### Phase 1 — WFF baseline knowledge reconstruction

Consume one valid Phase 0 manifest and recover a bounded WFF architecture
memory snapshot from the fixed v1.6.2 Git tree.

Required outputs:

- capability-oriented System Architecture Tree;
- Module Responsibility Map with owned and explicitly non-owned concerns;
- Implementation Intent Summary separating fact, inference, confidence, and
  unknowns;
- Validation / Assurance Ownership Map;
- Constraint Knowledge;
- evidence index and reconstruction report.

Phase 1 must read target content only through admitted manifest paths and exact
Git tree identities. It may use a reviewed WFF reconstruction specification to
direct evidence acquisition, but a specification entry becomes knowledge only
when its evidence rule is satisfied. Missing or contradictory evidence yields
`unknown`, never a fabricated fact.

### Phase 2 — Existing capability intelligence

Consume one verified Phase 1 snapshot and produce a deterministic,
evidence-linked capability catalog plus Before Generate checks.

Required answers:

- whether the capability is confirmed, inferred, unknown, or ambiguous;
- where it is represented and who owns it;
- which non-responsibilities and constraints limit reuse;
- whether the trigger is observed failure, declared requirement, or
  hypothetical risk;
- whether the capability affects the WFF mainline directly, conditionally, as
  support, or outside runtime mainline;
- whether evidence supports reuse, extension, replacement, new capability, or
  insufficient evidence.

A catalog miss does not prove absence. Replacement and separate new capability
postures require caller-declared `decision_status=accepted`, an explicit
decision reference, and a non-reuse reason; the acceptance assertion remains
unverified metadata rather than repository truth. Mainline-impact classifications
remain evidence-linked inference. Phase 2 does not rescan target code to create
knowledge or update Architecture Memory.

Authority: `phase2-existing-capability-intelligence-v0.1.md`.

### Phase 3 — Evolution and impact intelligence

Add incremental reconstruction, capability evolution, deferred verification,
snapshot refresh, and change-impact reasoning.

## Architecture-memory boundaries

- The architecture tree is capability-oriented, not a directory tree.
- Responsibility ownership must include non-ownership and conflict evidence.
- Implementation intent must label inference and confidence.
- Validation artifacts prove behavior or cap claims; they do not own business
  or architecture truth.
- Architecture Evolution describes verified past change; Change Impact predicts
  possible future effects and remains separate.
- Registered change is an intent signal, not repository truth.

## Global boundaries

- Workflow controls order and evidence capture, not engineering truth.
- Agentic reasoning may infer meaning only with evidence and uncertainty.
- Templates/specifications direct attention but cannot decide truth.
- Evidence caps claims; it does not become architecture or business ownership.
- Generated knowledge is never self-certifying evidence.
- No EKRI phase changes P1-P4/PX behavior without separate authority.
- Historical v1.7.0 RC artifacts from the abandoned line are not evidence for
  the restarted v1.7 sequence.
