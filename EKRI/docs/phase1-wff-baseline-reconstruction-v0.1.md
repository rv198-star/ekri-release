# EKRI Phase 1 — WFF Baseline Knowledge Reconstruction v0.1

Status: implementation contract

Issue: `#859`

Parent: `#826`

Depends on: `#858`

Target commit: `764dc832eb7488b32ff0e24591a2018bfa719d39`

Target tree: `e7bd7082e1674cce1f2d2e2f11f5978555f973b1`

## Objective

Phase 1 creates the first evidence-linked Engineering Knowledge snapshot for the
fixed WFF v1.6.2 Git tree. It reconstructs architecture memory rather than a
repository directory summary, generic code index, call graph, or LLM wiki.

The output must answer:

- which major WFF capabilities and routes exist;
- which layer owns each responsibility and what it must not own;
- which implementation intentions are directly observed or reasonably inferred;
- which tests, runtime evidence, gates, and review surfaces own assurance;
- which constraints limit downstream claims;
- which important questions remain unknown.

Phase 1 does not yet answer whether a proposed capability should be reused or
changed. That belongs to Phase 2 intelligence.

## Trust chain

```text
Phase 0 observation manifest
  -> independently revalidate historical scanner commit/tree
  -> independently revalidate target commit/tree and admitted corpus
  -> load reviewed reconstruction specification
  -> read only admitted Git blobs by exact blob object id
  -> verify required source anchors and line locations
  -> admit observed facts / bounded inferences / unknowns
  -> render machine memory and human projection
  -> persist atomically below .EKRI/knowledge/<tree>/
```

The current Phase 1 scanner must also match a clean committed `EKRI/**` surface
before reconstruction begins.

## Persisted Phase 0 revalidation

Phase 1 does not trust a JSON file merely because it is stored under
`.EKRI/manifests/`.

Before target reads it revalidates:

- exact manifest structure and valid verdict;
- historical scanner repository root, implementation root, commit, tree,
  object format, EKRI surface digest, and path count;
- target repository root, commit, tree, and object format;
- disabled Git replacement objects;
- protected scanner/runtime/oracle exclusions;
- candidate, excluded, and accepted path counts;
- complete accepted path list and digest;
- fixed output identity and boundary checks.

This historical verification is intentionally separate from current scanner
verification. A later clean EKRI implementation may consume a valid earlier
Phase 0 manifest without pretending that the earlier scanner and current
scanner are the same binary.

## Admitted Git reader

`AdmittedGitReader` is the only Phase 1 target-content access path.

For each requested source it:

1. validates the path grammar;
2. requires the path to exist in the Phase 0 admitted corpus;
3. resolves the exact blob object id from the recorded tree;
4. reads the blob with Git replacement objects disabled;
5. records mode, object type, blob id, SHA-256, and size;
6. decodes text as UTF-8 or fails closed.

Dirty or untracked worktree content is never read. A committed target file
changed in the ambient worktree still resolves to the recorded Git blob.

## Reconstruction specification

The first profile is directed by:

```text
EKRI/specs/wff-v162-baseline-reconstruction.json
```

The specification is a reviewed scanner instruction surface. It is not target
source truth and cannot prove an assertion by itself.

It declares:

- admitted target source paths to inspect;
- required source anchors;
- proposed capability-oriented architecture nodes;
- responsibility, intent, assurance, constraint, and unknown assertions;
- knowledge state, confidence, rationale, and evidence references;
- the profile claim ceiling.

Every evidence reference must resolve to an anchor found in an admitted target
blob. Missing paths or anchors reject reconstruction. This design preserves
Agentic review of architecture meaning while keeping evidence acquisition and
claim checks deterministic.

## Knowledge states

### `observed-fact`

Requirements:

- at least one resolved evidence reference;
- confidence must be `verified`;
- the statement must remain within what the cited source says.

### `inferred-knowledge`

Requirements:

- at least one resolved evidence reference;
- confidence must be `high`, `medium`, or `low`;
- rationale must explain why the evidence supports the inference;
- output must not present inferred author intent as confirmed fact.

### `unknown`

Requirements:

- confidence must be `not-applicable`;
- rationale must explain the evidence boundary;
- source references may explain why the question remains unresolved;
- unknowns must not be silently filled from scanner assumptions.

## Required outputs

The fixed output root is:

```text
.EKRI/knowledge/<target-tree>/
```

Files:

### `evidence-index.json`

Records:

- target commit/tree;
- every target blob actually read;
- blob mode, object id, SHA-256, and size;
- source anchor text, exact line numbers, and excerpts;
- the complete read-path list.

### `architecture-memory.json`

Records:

- source and current scanner provenance;
- observed corpus/configuration inventory;
- capability-oriented System Architecture Tree;
- Module Responsibility Map;
- Implementation Intent Summary;
- Validation / Assurance Ownership Map;
- Constraint Knowledge;
- known unknowns;
- claim ceiling.

### `ARCHITECTURE_MEMORY.md`

A human-readable projection of the machine memory. It does not become a second
source authority.

### `reconstruction-report.json`

Acts as the output completion marker and records:

- passed reconstruction checks;
- evidence and knowledge counts;
- exact target blob read paths;
- output file digests;
- claim ceiling.

The report is written last. If an earlier output write fails, the absence of a
valid report prevents the partial directory from being treated as a completed
snapshot.

## Capability-oriented architecture rule

Architecture nodes describe capabilities, routes, phases, support layers,
assurance surfaces, or distribution responsibilities.

They must not merely mirror:

- top-level directories;
- all source files;
- every Python module;
- a function call graph.

The WFF baseline tree is rooted at the lifecycle system and includes bounded
subtrees for admission/routing, P1-P4, PhaseX, shared support, assurance,
Human Review projection, packaging, and role-agent adaptation.

## Observed inventory

Phase 1 also extracts bounded machine facts from admitted configuration:

- skill catalog counts, categories, phase entries, and release postures;
- install capability packages, profiles, and resource-module count;
- generated-output and Human Review sidecar policy;
- admitted corpus top-level and phase-script counts.

These facts support orientation but do not replace the semantic architecture
memory.

## Output safety

The observation manifest is loaded with no-follow directory and file opens.
Knowledge output directories are created/opened through no-follow directory
file descriptors. Each file is written to an exclusive temporary file,
`fsync`ed, and atomically replaced. Existing destination symlinks are replaced,
not followed. A symlink in `.EKRI`, `knowledge`, or the tree directory rejects
the run.

Callers cannot select another knowledge root.

## Fail-closed conditions

Reconstruction rejects when:

- current scanner provenance is dirty or unverifiable;
- the Phase 0 manifest cannot be independently revalidated;
- the target is not the fixed WFF v1.6.2 commit/tree;
- a requested path is not in the admitted corpus;
- a target object is not a blob or is not UTF-8 text;
- a required evidence anchor is missing;
- an evidence reference is unresolved;
- an observed fact or inference lacks evidence;
- knowledge state and confidence disagree;
- the architecture tree has no single root, a missing parent, or a cycle;
- the observation input or output path crosses a symlink;
- atomic persistence fails.

## First baseline evidence scope

The reviewed profile intentionally reads a small authoritative set rather than
all 3,045 admitted paths. It covers 25 source blobs:

- root governance and product orientation;
- public route and review contracts;
- workflow/agentic/evidence responsibility matrix;
- skill catalog and install-profile configuration;
- generated-output policy;
- the external router and P1/P2/P3/P4/PX entry contracts;
- project-context, traceability, reader-translation, and interaction-map support contracts;
- bounded P1-P4 runner, PhaseX authored-case validator, and install-pack builder implementation surfaces.

A path outside this evidence scope is not claimed to be understood merely
because it was admitted by Phase 0.

## Claim ceiling

A successful Phase 1 run proves that the named WFF v1.6.2 Git tree supports the
recorded bounded architecture memory through the cited evidence.

It does not prove:

- exhaustive architecture completeness;
- author intent beyond labeled inference;
- runtime or production readiness;
- real UAT or owner sign-off;
- universal standalone skill installability;
- capability reuse fitness;
- architecture evolution;
- future change impact.
