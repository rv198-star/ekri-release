# EKRI v1.0 Supported Product Contract

Date: 2026-08-13  
Status: release-candidate contract; publication requires explicit release authorization

## 1. Product Identity

EKRI v1.0 is the first deliberately supported **Engineering Knowledge System architecture** release.

Its product model is:

```text
rich but shallow Engineering Knowledge Model
+ named Query / View contracts
+ progressive disclosure
+ evidence / authority / context qualification
```

Internally, semantic normalization uses:

```text
Object
Occurrence
Assertion
```

Those three categories are implementation semantics, not the normal vocabulary that engineers or Agents must traverse.

## 2. General Engineering Knowledge Model

Supported general concepts include:

```text
Architecture / System Element
Capability
Artifact / Repository Asset
Constraint
Authority
Evidence
Context / Snapshot
Flow / Handoff
Evolution / Impact
Unknown / Conflict posture
```

The taxonomy is intentionally shallow. Domain/profile concepts may specialize these without becoming new meta-kernel roots.

## 3. Epistemic and Normative Posture

Supported epistemic posture:

```text
observed-fact
inferred-knowledge
unknown
conflicting
```

`unknown` and `conflicting` are distinct. Conflict requires bounded evidence for incompatible claims and must not be silently collapsed into one owner/answer.

Normative/authority posture remains separate from epistemic certainty. Observed evidence does not itself create product, architecture, ownership, retirement, deletion or production-approval authority.

## 4. Supported General Query/View Surface

### Architecture View

Schema:

`ekri.architecture-view.v1`

The View preserves source Context, semantic IDs, responsibilities/non-responsibilities, constraints, assurance ownership, implementation intent, unknown/conflicting posture, evidence refs and claim ceiling.

Architecture View is a derived product View. It is not a peer Architecture semantic writer.

### Capability Authority

Schema:

`ekri.capability-semantic-authority.v1`

Capability is the first v1.0 semantic slice fully cut over to ontology-authoritative storage/semantics. The legacy v0.9 Capability Catalog is compatibility output only.

### Capability named queries

Supported normal-consumer queries:

```text
find_capability(...)
get_realizations(...)
explain_authority(...)
get_evidence(...)
```

Progressive disclosure:

```text
L0 orientation / existence
L1 realization
L2 authority / constraints
L3 evidence
```

A query miss never proves capability absence.

### Bounded Flow/Handoff query

Supported bounded query:

```text
trace_flow(...)
```

FlowDefinition is knowledge; bounded handoffs are Occurrences; route/carriage/authority/reliance/order are qualified relations/assertions. There is no peer Flow truth store.

## 5. Existing Supported General Intelligence

The following existing EKRI surfaces remain supported with their established authority boundaries:

- Observation Independence / exact Git trust boundary;
- Repository Asset Identity;
- Repository Ownership Boundary;
- Repository Lifecycle Observation;
- Evolution and predictive Impact Intelligence;
- Portable Project Knowledge.

v1.0 does not require every existing semantic slice to migrate to the new authority substrate in the same release. It requires **one semantic authority per knowledge slice/context**, preserved firewalls, real retirement after cutover, and no new peer truth store.

## 6. WFF Profile Compatibility

WFF remains EKRI's first host/stress corpus but is not EKRI's semantic boundary.

The following are explicitly profile/compatibility surfaces rather than general EKRI requirements:

```text
Before Generate / run_existing_capability_check
WFF P1/P2/P3/P4/PX vocabulary
WFF Core boundary/contract/extraction/migration analysis
fixed WFF baseline reconstruction convenience profile
.EKRI/intelligence/** legacy Capability compatibility output
```

WFF profile behavior must not force WFF concepts into the general meta-kernel.

## 7. Internal / Migration / Conformance Surfaces

The following are intentionally not stable normal-consumer APIs:

- raw Object/Occurrence/Assertion traversal;
- P1 shadow semantic compiler;
- Architecture round-trip parity tooling;
- Repository firewall stress projection;
- non-WFF conformance harness;
- retained audit/bootstrap helpers.

They may change within the 1.x line provided supported product contracts and evidence/authority guarantees remain compatible.

## 8. Identity / Context / Evidence Contract

- semantic identity is distinct from path/location and exact content digest;
- exact content hashes prove materialization integrity, not semantic continuity;
- source Context is explicit and reviewable;
- evidence/provenance chains terminate at admitted trust roots;
- generated knowledge cannot self-certify;
- stable semantic IDs are not reminted solely because storage/schema changes;
- derived views/indexes expose provenance/staleness/rebuild posture and are not peer truth stores.

## 9. Authority Firewalls

The following remain release-blocking invariants:

1. structural evidence cannot establish semantic ownership;
2. observation absence cannot establish retirement/removal/deletion authority;
3. predictive Impact cannot become accepted Architecture fact;
4. unknown/conflicting/multi-owner/mixed-role posture remains visible;
5. Portable Project Knowledge cannot self-certify;
6. moved assets preserve stable semantic identity where identity policy says continuity holds;
7. compatibility-surface identity remains distinct from moved implementation identity;
8. EKRI control-plane paths remain excluded from formal target observation;
9. normal consumers do not require raw meta-kernel traversal;
10. no semantic slice may have peer authoritative writers or bidirectional semantic synchronization.

## 10. Capability Cutover / Compatibility

The v1.0 Capability chain is:

```text
verified Architecture authority
  -> proven Architecture View
  -> Capability Semantic Authority
  -> derived Query Index / L0-L3 answers
  -> derived v0.9 Catalog / Before Generate compatibility output
```

The old private Capability Catalog semantic writer/evaluator is retired. Core Boundary and Evolution consume the Capability Authority rather than rebuilding the old Catalog internally.

## 11. Schema / API Compatibility Policy

For supported 1.x surfaces:

- schema identity changes that are backward compatible may add optional/defaultable fields;
- incompatible semantic changes require an explicit migration decision and normally a major-version boundary;
- named query meaning, authority posture and claim ceilings are compatibility obligations;
- profile-specific WFF compatibility may change independently if general contracts remain unaffected;
- physical storage changes are not semantic-ID changes by themselves.

Pre-release P3 implementation labels that exposed v0.9 migration detail were generalized before v1.0 RC:

```text
semantic-authority-derived-realization
resolve-through-verified-evidence-index
```

## 12. Single-Authority Migration / Rollback

Allowed migration modes:

```text
shadow-non-authoritative
compatibility-view-from-current-authority
ontology-authoritative-with-derived-legacy-view
```

Forbidden:

```text
peer dual-write
bidirectional semantic synchronization
silent fallback between authoritative writers
```

Rollback before cutover: discard shadow/derived state and retain the sole existing authority.

Rollback after cutover: freeze the failed/new Context, explicitly restore **one** accepted authority source, rebuild derived views/compatibility outputs, and retain the failed Context as historical evidence. Temporary peer authority is not a rollback mechanism.

## 13. Non-WFF Conformance

P8 validates the same general Architecture/Capability/Flow surfaces against the unrelated Mercury CI software-delivery fixture using exact Git-backed evidence.

The fixture proves:

- non-WFF Architecture View use;
- non-WFF ontology-authoritative Capability use;
- L0-L3 Capability queries;
- bounded `trace_flow`;
- explicit conflicting deployment-owner evidence;
- explicit production-approval unknown;
- false-absence protection;
- no WFF P1/P2/P3/P4/PX meta-kernel dependency.

One non-WFF fixture is sufficient for the bounded v1.0 product-generalization claim; it is not universal domain completeness.

## 14. Supported vs Experimental Machine Record

Canonical machine-readable classification:

`EKRI/specs/v100-product-surface-classification.json`

The classification is part of the v1.0 Release Gate.

## 15. Claim Ceiling

EKRI v1.0 may claim a supported general Engineering Knowledge Model and named Query/View architecture with evidence-bounded trust, one semantic authority per slice, one completed Capability authority cutover/legacy-writer retirement chain, WFF plus non-WFF conformance, and preserved repository/lifecycle authority firewalls.

It does **not** claim:

- universal engineering ontology completeness;
- exhaustive dependency/absence proof;
- autonomous ownership, retirement, deletion or production-governance authority;
- production readiness of a host application;
- complete future Flow/Decision/Claim/Code Graph/distributed-trace/domain-profile coverage;
- that every internal migration/conformance module is a stable public API.
