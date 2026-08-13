# V1.9.1 Repository Asset Identity Model v0.1

## Purpose

Define the EKRI repository asset identity model used by Issue #968.

This model answers:

> What is this repository asset, why does it exist, and what evidence supports its identity?

It does not decide deletion or retirement.

## Asset Identity

Each asset has:

- stable asset identity
- repository path(s)
- asset type
- ownership references
- ownership observation status
- observed roles and lifecycle observation status
- dependency references
- evidence references

## Asset Types

Asset type is a mechanical repository-shape classification, not a lifecycle or ownership decision. Initial types:

- code
- test
- package-asset
- proof-asset
- historical-asset
- documentation-asset
- configuration-asset
- other

Compatibility, assurance, and active-runtime meaning must not be inferred from filename or directory shape alone.

## Observed Roles And Lifecycle Observation

One asset may legitimately carry several roles at the same time. P1 therefore records `observed_roles[]` rather than forcing one lifecycle label.

Allowed observed roles include:

- active-formal-distribution
- active-maintainer
- active-analysis-internal
- assurance
- proof-retained
- historical
- compatibility
- external-or-reference

`lifecycle_observation_status` is only one of:

- single-role-observed
- mixed-role-observed
- unknown

`mixed-role-observed` is a first-class result, not a defect. No retirement, deprecated, unused, or safe-to-delete state is introduced in P1.

Ownership evidence is independently classified as `single-owner-evidence`, `multi-owner-evidence`, or `unresolved`. Multiple capability/ownership labels must remain mixed evidence; P1 may not collapse them into one current owner. Final ownership-boundary reconciliation belongs to P2.

## Control-plane boundary

Formal target asset reconstruction continues to obey EKRI No Active Self-Scan. `EKRI/**` and `.EKRI/**` are excluded from the target corpus. EKRI knowledge/control surfaces may be cited only as control-plane references and are never promoted into self-observed target facts.

## Evidence Rules

Asset identity may consume:

- EKRI reconstruction evidence
- profile/package evidence
- runtime references
- test references
- proof references
- documented ownership

Code graph output is structural evidence only and cannot establish semantic ownership.

## P1 Non-goals

- no deletion
- no retirement candidate assignment
- no physical movement
- no ownership inference from absence of references

## Audit Requirements

1. EKRI identity correctness audit
2. Destructive simulation audit using reconstructed asset boundaries
