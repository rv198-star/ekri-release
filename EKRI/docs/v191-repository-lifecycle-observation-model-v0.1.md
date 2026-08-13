# V1.9.1 Repository Lifecycle Observation Model v0.1

## Purpose

Issue #972 adds a bounded observation layer over the repository boundaries reconstructed in V1.9.1 P0-P4.

The model answers:

> What evidence is currently observable for a known repository asset or compatibility surface?

It does not answer:

> Should this asset be deprecated, retired, removed, or deleted?

Those are V1.9.2 governance decisions.

## Observation Denominator

The first V1.9.1 snapshot tracks two related but distinct denominators:

1. **23 priority implementation assets** identified in P0/P2. Their P1 stable asset IDs survive later physical moves.
2. **13 strong compatibility surfaces**: seven pre-existing compatibility paths plus six old paths left as P3 compatibility shims after their implementation bodies moved to `scripts/maintenance/**`.

A compatibility surface is not assigned the P1 implementation asset ID. It receives a separate path-seeded `surface_id` because the moved implementation and its old compatibility shim now have different responsibilities.

## Stable Identity Across P3 Moves

For the six P3 moved assets:

- `asset_id` remains the P1 stable ID seeded from the original baseline path;
- `baseline_path` remains the P1 path;
- `current_path` becomes the P3 canonical `scripts/maintenance/**` path;
- the old path is observed independently as a compatibility surface.

This prevents a physical move from becoming a false deletion/new-asset event.

## Observation Signals

Each tracked asset or compatibility surface may record:

- current Git-tree presence;
- current line count for text/Python files;
- formal profile file membership;
- maintainer bundle membership;
- exact internal Python import consumers;
- exact repository-path textual references;
- source-role counts for tests, formal distribution, maintainer distribution, proof/history, and other repository sources.

The absence of an observed signal is recorded as an observation ceiling, not as proof of absence.

## Observation Classification

The snapshot may derive only evidence-oriented observation classes:

- `active-distribution-observed`
- `non-test-import-observed`
- `test-import-observed`
- `reference-only-observed`
- `present-no-positive-use-observed`
- `absent-current-tree`

These are observation summaries, not lifecycle governance states.

## Snapshot Comparison

Two snapshots may be compared by stable `asset_id` or `surface_id`.

Comparison output may report:

- signal added;
- signal removed;
- current path changed;
- LOC changed;
- still observed;
- no longer observed for a particular evidence signal.

Comparison must not emit `deprecated`, `retirement-candidate`, `removal-eligible`, `safe-delete`, or equivalent decisions.

## Authority Boundary

EKRI reconstructs and compares observation evidence only.

- Structural/import/reference evidence cannot create semantic ownership.
- Observation absence cannot create retirement authority.
- A long observation history cannot autonomously authorize deletion.
- Lifecycle governance remains a WFF Agentic/governance/human decision in V1.9.2.

## No Active Self-Scan

Formal target facts still use the EKRI Phase 0 observation boundary. `EKRI/**` and `.EKRI/**` are excluded from target facts.

EKRI self-changes are validated by scanner commit/surface provenance and clean bootstrap, not by self-Evolution registration.

## P5 Non-goals

- no source deletion;
- no physical move;
- no deprecation marker;
- no retirement candidate;
- no removal eligibility;
- no safe-delete claim;
- no change to P1/P2/P3/P4/PX runtime behavior.
