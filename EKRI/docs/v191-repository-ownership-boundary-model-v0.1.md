# V1.9.1 Repository Ownership Boundary Model v0.1

## Purpose

Define the EKRI relationship layer used by Issue #969 after Repository Asset Identity has frozen the asset denominator.

P2 answers:

> Which repository assets are structurally coupled, which accepted responsibility/capability evidence already applies, and what boundary work is required before physical separation?

It does not assign semantic ownership from imports, path proximity, profile membership, graph topology, or absence of consumers.

## Immutable Input

P2 consumes the P1 Repository Asset Knowledge Map without rewriting its asset IDs, Git identities, observed roles, ownership evidence, capability evidence, or retirement ceiling.

## Edge Classes

### Authority edges

Authority edges may only project evidence already present in the P1 map:

- asset -> accepted responsibility family / owner evidence;
- asset -> verified capability evidence.

Structural evidence must never create an authority edge.

### Structural edges

Structural edges describe repository coupling only:

- exact Python AST import;
- exact repository-path textual reference;
- structured install-profile exclusion reference;
- structured install-profile declaration reference;
- formal profile membership;
- maintainer bundle membership;
- analysis-only profile declaration.

A profile exclusion is negative metadata, not a consumer. Generic textual references are path-update evidence, not automatically runtime dependencies. Only exact import edges are treated as code-consumer evidence.

Code Graph, when used, remains an optional structural evidence provider and cannot establish ownership or deletion authority.

## Structural Owner Neighborhood

For unresolved or multi-owner assets, P2 may report nearby assets that already have single-owner evidence. The output is explicitly named `structural_owner_neighborhood` and remains inferred dependency knowledge.

It must never be copied into `owner_evidence_labels` or treated as an accepted owner.

## Boundary Flags

P2 may mechanically expose multiple simultaneous flags:

- owner-unresolved
- multi-owner
- mixed-lifecycle
- active-historical-coupling
- active-proof-coupling
- active-assurance-coupling
- compatibility-boundary
- analysis-internal-boundary
- outside-active-closure
- active-inbound-import-consumers
- active-inbound-path-references
- profile-exclusion-metadata-reference
- profile-declaration-metadata-reference
- proof-or-history-inbound-references

Flags are observations, not retirement states.

## Decoupling Requirements

P2 may derive bounded preconditions such as:

- resolve-owner-boundary-before-physical-move;
- migrate-formal-import-consumers-before-separation;
- migrate-maintainer-import-consumers-before-separation;
- migrate-analysis-import-consumers-before-separation;
- update-formal-path-references-before-separation;
- update-maintainer-path-references-before-separation;
- update-analysis-path-references-before-separation;
- update-profile-exclusion-metadata-after-move;
- update-profile-declaration-metadata-after-move;
- preserve-or-update-proof-history-references-before-separation;
- preserve-or-relocate-proof-reference;
- preserve-historical-reproduction-context;
- replace-or-freeze-compatibility-contract;
- dependency-absence-not-proven.

No requirement authorizes deletion or physical movement by itself.

## No Active Self-Scan

`EKRI/**` and `.EKRI/**` remain control-plane surfaces and are excluded from target asset facts. EKRI self-changes are verified through scanner commit/surface provenance and clean bootstrap, not target Architecture Evolution registrations.

## P2 Non-goals

- no deletion;
- no retirement/deprecation state;
- no physical relocation;
- no ownership inference from import topology;
- no graph-only dependency completeness claim;
- no rewriting of P1 identity or authority evidence.

## Audit Requirements

1. Ownership Boundary Audit
2. Dependency Impact Audit
3. EKRI Authority Contamination Audit
