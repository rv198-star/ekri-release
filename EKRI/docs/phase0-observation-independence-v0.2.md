# EKRI Phase 0 — Git-tree Observation Independence v0.2 (Amended)

Status: implementation contract

Issue: `#858`

Parent: `#826`

## Objective

The active knowledge-reconstruction system, its schemas, tests, evaluation
oracle, and generated state must never enter the formal observation corpus.

The invariant is about **observation-corpus independence**, not physical
checkout separation. EKRI may be incubated in the same Git repository as WFF
because the formal target is a verified commit/tree and protected paths are
removed before any target blob can be read.

This amendment supersedes the earlier root-disjoint wording in the original
issue description. A same-repository scan is valid only when scanner identity
is independently proven and every active scanner/runtime/oracle path is absent
from the admitted corpus.

## Permanent protected-path invariant

The implementation fixes these values and exposes no override:

```python
ACTIVE_SCANNER_PATH_PREFIXES = ("EKRI/",)
RUNTIME_STATE_PATH_PREFIXES = (".EKRI/",)
ORACLE_PATH_PREFIXES = ("EKRI/evaluation-oracle/",)
PROTECTED_PATH_PREFIXES = ("EKRI/", ".EKRI/")
```

The oracle prefix is recorded separately even though it is already contained
by `EKRI/`, so manifests make the oracle exclusion explicit.

## Mandatory order

```text
resolve and verify active scanner identity
→ resolve target commit/tree with Git replacement objects disabled
→ enumerate target tree metadata only
→ classify and remove EKRI/**, .EKRI/**, and oracle paths
→ validate the complete final path corpus
→ permit later phases to read only admitted target blobs
→ semantically re-evaluate the manifest before persistence
→ persist atomically through the fixed .EKRI/ layout
```

Phase 0 performs no target blob reads. Scanner Git metadata may be read to prove
which implementation is running; that evidence is separate from target corpus
content.

## Scanner identity

Every formal observation records and verifies:

- scanner Git repository root;
- scanner implementation root;
- scanner commit and tree;
- Git object format;
- digest and path count of the committed `EKRI/**` surface;
- scanner version and exclusion-policy identity;
- whether the runtime EKRI surface matches the recorded scanner commit.

Formal evaluation fails closed when the scanner is not in a Git repository,
its implementation is not the top-level `EKRI/` subtree, the committed EKRI
surface is missing, or tracked/untracked active scanner content differs from
the recorded scanner commit.

## Target identity

Every formal observation records:

- target Git repository top-level root;
- requested ref;
- resolved commit;
- resolved tree;
- Git object format;
- accepted path-set digest.

All Git commands run with replacement objects disabled. `refs/replace/*` or
legacy replacement behavior must not change the recorded commit/tree pair.
Worktree-only and dirty target content is outside the formal target.

## Self-scan verdict

A manifest records one of these valid states:

- `same-repository-protected-surfaces-excluded`;
- `external-repository-target`.

The first does not mean EKRI inspected itself. It means the target tree shared a
repository with the scanner, but all `EKRI/**`, `.EKRI/**`, and oracle paths
were removed before target content became readable.

## Output identity and persistence

Repository-root-bound runtime output is local and ignored:

```text
.EKRI/
├── manifests/<tree>-observation.json
├── knowledge/<tree>/
├── intelligence/<tree>/
├── evolution/<tree>/
├── audit/
├── runtime/
├── cache/<tree>/
└── logs/
```

Portable, content-addressed Engineering Knowledge may be promoted separately to
tracked `.EKRI/project/**` after runtime reconstruction. Tracking does not admit
that knowledge to the target corpus: the entire `.EKRI/` prefix remains
permanently excluded before blob reads. Project assets must be verified against
the named target tree and exact evidence blobs before use.

Callers cannot supply alternate runtime output roots. Before writing, EKRI reconstructs
the manifest from the recorded target commit and requires exact semantic
identity with the candidate manifest. This rejects mutation of source,
scanner, exclusion, corpus, digest, count, verdict, or output fields.

Persistence uses directory file descriptors, no-follow directory opens,
exclusive temporary-file creation, file and directory `fsync`, and atomic
replacement. `.EKRI`, `.EKRI/manifests`, or the destination cannot redirect the
write through a symlink.

A write-capable CLI prints a valid verdict only after persistence succeeds. If
persistence fails, stdout contains a rejected manifest with the exact failure
reason and the process exits non-zero.

## Fail-closed checks

Phase 0 rejects when:

- scanner provenance is missing, dirty, misplaced, or unverifiable;
- target repository root or ref cannot be resolved;
- target commit/tree identity is missing or malformed;
- Git object format is unsupported;
- a tree path is empty, unsafe, non-canonical, duplicated after normalization,
  or not valid UTF-8;
- the fixed protected-prefix invariant has changed;
- any protected path remains in the final corpus;
- a candidate manifest differs from a fresh formal evaluation;
- output directories are symlinks or non-directories;
- atomic persistence through the fixed `.EKRI/` layout fails.

No caller parameter can weaken scanner identity, protected prefixes, oracle
exclusion, target identity, or output location.

## Manifest claim

`ekri.observation-manifest.v2` proves only:

> A named Git tree produced a formally admitted path corpus after active
> scanner, runtime-state, and oracle exclusions, before any target blob content
> was read, under the independently recorded scanner identity.

It does not prove reconstruction completeness, architecture truth, reuse
fitness, change impact, release readiness, or production suitability.
