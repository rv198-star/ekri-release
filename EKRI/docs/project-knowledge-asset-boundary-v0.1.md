# EKRI Project Knowledge Asset Boundary v0.1

Status: implementation contract

Issue: `#878`

## Decision

EKRI distinguishes two classes below `.EKRI/`:

1. repository-root-bound local runtime state;
2. portable, content-addressed project knowledge assets.

The earlier blanket `.EKRI/` ignore conflated Git durability with formal-corpus
admission. The permanent observation rule remains unchanged:

```python
PROTECTED_PATH_PREFIXES = (
    "EKRI/",
    ".EKRI/",
)
```

Tracked `.EKRI/project/**` paths are therefore still removed before any formal
target blob read. Git tracking does not make them target evidence and does not
let generated knowledge certify itself.

## Layout

```text
.EKRI/
├── project/                         # tracked portable project knowledge
│   └── <asset-id>/
│       ├── PROJECT_KNOWLEDGE_MANIFEST.json
│       ├── architecture-memory.json
│       ├── evidence-index.json
│       ├── reconstruction-report.json
│       └── capability-catalog.json
├── manifests/                       # ignored local runtime
├── knowledge/                       # ignored local runtime
├── intelligence/                    # ignored local runtime
├── evolution/                       # ignored local runtime
├── audit/                           # ignored local runtime
├── runtime/project-assets/          # ignored hydrated copies and receipts
├── cache/                           # ignored
└── logs/                            # ignored
```

The repository `.gitignore` ignores `.EKRI/*` and explicitly re-admits only
`.EKRI/project/**`.

## Portable asset contract

A project asset records:

- immutable target commit and tree;
- admitted path-set digest;
- portable artifact paths and SHA-256 digests;
- capability, alias, and ambiguity counts;
- the repository-root token `${REPOSITORY_ROOT}`;
- unchanged formal-corpus exclusions;
- a claim ceiling.

Portable artifacts may contain Git identities, repository-relative source paths,
blob OIDs, blob SHA-256 values, evidence anchors, semantic knowledge states, and
bounded timestamps. They must not contain absolute repository paths, machine
cache/log paths, symlink-derived identities, or evidence from `EKRI/**` or
`.EKRI/**`.

## Verification

`verify_project_asset` does not trust Git tracking or manifest self-description.
It:

1. verifies the asset path is below `.EKRI/project` and crosses no symlink;
2. resolves the target commit and exact target tree;
3. verifies every artifact digest;
4. rejects absolute machine paths;
5. reopens every evidence source from the named Git tree;
6. compares the exact blob OID and SHA-256;
7. rejects evidence paths below `EKRI/**` or `.EKRI/**`;
8. verifies Architecture Memory and capability-catalog evidence-reference
   closure;
9. verifies capability profile counts and reconstruction count consistency.

A committed asset that fails any check is unusable.

## Hydration

A verified asset may be rebound to the current repository root below:

```text
.EKRI/runtime/project-assets/<asset-id>/
```

Hydration replaces `${REPOSITORY_ROOT}` only after verification and writes a
`HYDRATION_RECEIPT.json` containing the tracked manifest digest, target identity,
current root, and output digests. Hydration does not make an old baseline current
for a changed tree.

## Existing Capability Intelligence

Before Generate prefers a verified tracked project asset when one is available.
This allows a clean or dirty development worktree to query durable baseline
knowledge without copying another worktree's absolute-path observation manifest.
If an explicit project asset id fails verification, the request fails closed.
When no project asset is selected or available, the original fully verified local
Phase 1 runtime path remains supported.

The result identifies the authority mode as either:

- `verified-tracked-project-asset`;
- `verified-local-runtime`.

Neither mode proves exhaustive capability absence or implementation fitness.

## Initial project asset

The first tracked asset is:

```text
.EKRI/project/wff-v1.6.2-baseline/
```

It was regenerated in a clean committed scanner worktree from the immutable WFF
v1.6.2 commit/tree and contains:

- 20 architecture nodes;
- 17 responsibility entries;
- 8 implementation intents;
- 6 assurance entries;
- 7 constraints;
- 4 unknowns;
- 25 evidence blobs and 134 evidence anchors;
- 16 capabilities;
- 124 normalized exact aliases;
- 0 ambiguous aliases.

This is a portable baseline, not a claim that v1.6.2 is the current repository
architecture. Current changes still require registration, incremental
reconstruction, Architecture Evolution, and Change Impact.

## Evolution and self-scan boundary

Architecture Evolution must not use `EKRI/**` or `.EKRI/**` as registered
expected paths. The portable asset verifier proves the tracked asset's target,
blob, digest, and evidence closure. EKRI source/project-asset semantics remain
protected scanner state and cannot be promoted to observed architecture fact by
EKRI itself. Registration for this change therefore verifies only non-protected
repository control surfaces such as `.gitignore`, repository context, and the
work index; the registered intent remains explicitly not independently proven.

## Package boundary

EKRI remains outside WFF Skills, install profiles, install packs, and release
bundles. Both `EKRI/**` and `.EKRI/**` remain package-leak failures.
