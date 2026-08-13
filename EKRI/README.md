# EKRI

Engineering Knowledge Reconstruction and Intelligence (EKRI) is a top-level
WFF repository subproject. It is not a WFF Skill, lifecycle phase, install-pack
surface, or release-bundle dependency.

## Product version and release line

EKRI is versioned and released independently from WFF while both products remain
in the same Git repository.

```text
EKRI product version source: EKRI/pyproject.toml
EKRI changelog:              EKRI/CHANGELOG.md
EKRI tag namespace:          ekri/vX.Y.Z
WFF version/tag/release:     separate product lifecycle
```

`EKRI v0.9` is the independently released baseline line. `EKRI v1.0.0` is the
first released supported Engineering Knowledge System architecture line. The
formal `ekri/v1.0.0` tag is frozen at
`026f2ffa5c3c8685418adc4bf281911b4ff2d578`. `EKRI v1.1.0` adds Adaptive
Knowledge Acquisition over that stable semantic system without rewriting the
published v1.0 identity.

Starting with v0.9.0, EKRI Releases publish an independent audited release pack.
The pack preserves the top-level `EKRI/` layout required by Formal Scanner Git
provenance and contains the selected EKRI version's runtime source, scripts,
schemas, specs, required audit/conformance fixtures, and bounded product/release
documentation. It does not contain WFF runtime/install-pack content, EKRI tests,
WFF change-registration history, `.EKRI/**` runtime state, or unlisted ontology
exploration/audit history.

The Formal Scanner remains Git-provenance-bound: after extraction, use the
package as a scanner-control Git repository (or place its `EKRI/` directory at
the top level of another scanner-control Git repository), keep the supplied
package-root `.gitignore`, and commit the `EKRI/` surface before formal
observation. The release pack intentionally does not add a non-Git or
self-certified scanner fallback.

`EKRI v1.0.0` supports a rich but shallow Engineering Knowledge Model with named
Query/View contracts and progressive disclosure, backed internally by the
`Object / Occurrence / Assertion` semantic meta-kernel. Capability is the first
semantic slice cut over to ontology-authoritative storage/semantics; legacy
Capability Catalog/Before Generate output remains derived WFF compatibility.

`EKRI v1.1.0` adds a non-authoritative acquisition control layer. A host Agent
binds a Mission to exact source identity and current Project Knowledge, assesses
knowledge sufficiency, authors a disposable bounded plan, runs WAE-style evidence
acquisition, and emits only non-authoritative Candidate Knowledge Delta records
for existing family-authority review. The design does not add technology-stack
Profile directories, Human Projection, PX route authority, convergence discovery,
a peer semantic store, or an always-on whole-repository scanner. See
`docs/adaptive-knowledge-acquisition-v1.1.md`.

See:

- `CHANGELOG.md`;
- `docs/versioning-changelog-release-governance-v0.1.md`;
- `docs/v090-independent-product-baseline-plan-v0.1.md`;
- `docs/v090-m0-baseline-v0.1.md`;
- `docs/v100-engineering-knowledge-system-transition-plan-v0.1.md`.

## Phase 0 — Observation independence

Phase 0 establishes the trust boundary for later reconstruction:

1. verify the active scanner Git commit/tree and complete `EKRI/**` surface;
2. resolve a formal target commit/tree with Git replacement objects disabled;
3. enumerate target tree metadata without reading target blobs;
4. permanently exclude `EKRI/**`, `.EKRI/**`, and the explicit oracle prefix;
5. validate and digest the complete admitted path corpus;
6. re-evaluate the manifest before persistence;
7. write atomically through the fixed, no-follow `.EKRI/` layout.

A same-repository target is supported, but the active scanner never enters the
formal corpus. Dirty or unverifiable scanner implementations fail closed.

Repository-root-bound runtime state is written under ignored `.EKRI` roots.
Portable project knowledge is a separate tracked class under `.EKRI/project/**`;
tracking does not admit it to the formal observation corpus, because all
`EKRI/**` and `.EKRI/**` paths remain permanently excluded before blob reads.

Local runtime layout:

```text
.EKRI/
├── manifests/<tree>-observation.json
├── knowledge/<tree>/
├── intelligence/<tree>/
├── evolution/<tree>/
├── core-boundary/<tree>/
├── audit/
├── cache/<tree>/
├── runtime/project-assets/<asset-id>/
└── logs/
```

Tracked project knowledge is schema-versioned independently from the EKRI
product version and the target-project version.

Legacy v1 assets keep the original fixed baseline layout:

```text
.EKRI/project/<v1-asset-id>/
├── PROJECT_KNOWLEDGE_MANIFEST.json
├── architecture-memory.json
├── evidence-index.json
├── reconstruction-report.json
└── capability-catalog.json
```

A v1 asset contains repository-relative, content-addressed projections only. It
cannot certify itself: verification reopens every evidence blob from the named
Git tree, checks artifact digests and evidence-reference closure, and rejects
absolute machine paths or protected-corpus evidence. A verified v1 asset may be
hydrated into ignored local runtime state with an explicit root-rebinding
receipt.

Project Knowledge Asset v2 adds a manifest-first partial-family contract:

```text
.EKRI/project/<v2-asset-id>/
├── PROJECT_KNOWLEDGE_MANIFEST.json
├── architecture.json
├── capability.json
├── repository-asset-identity.json
├── repository-ownership-boundary.json
├── repository-lifecycle-observation.json
├── evolution-overlay.json
└── flow-handoff.json
```

v2 separates producer EKRI version/source, knowledge-model contract, target
commit/tree, stable semantic identity namespace, asset-schema version and each
family's source-contract/availability/authority posture. A family may be
`native-bounded`, `bounded-overlay`, `migration-supported-legacy`,
`blocked-source-contract-drift`, or `derived-conformance`; unavailable current
Architecture/Capability truth therefore does not force other verified families
to disappear or be fabricated. Family artifacts are bounded portable
projections/evidence with `semantic_authority=false`; rebuildable Query Index,
firewall View and Flow query models are not promoted as peer truth stores.

The first v2 asset is `.EKRI/project/wff-v1.9.2-ekri-v1.0/`, produced by the
released `ekri/v1.0.0` source for exact WFF v1.9.2. It preserves the stable
repository asset namespace `wff-v1.9`, rather than minting IDs from WFF patch or
EKRI product versions. v2 verification is supported; v2 hydration into the
legacy v1 runtime layout is intentionally not defined for partial assets.

Manage project assets:

```bash
python3 EKRI/scripts/manage_project_assets.py promote \
  --repository-root /path/to/repository \
  --source-tree <tree> \
  --asset-id <asset-id>

python3 EKRI/scripts/manage_project_assets.py verify \
  --repository-root /path/to/repository \
  --asset-id <asset-id>

# verify auto-detects v1/v2; promote/hydrate remain the v1 fixed-baseline contract
python3 EKRI/scripts/manage_project_assets.py hydrate \
  --repository-root /path/to/repository \
  --asset-id <asset-id>
```

Run Phase 0:

```bash
python3 EKRI/scripts/validate_observation_boundary.py \
  --repository-root /path/to/repository \
  --target-ref HEAD
```

Use `--no-write` to evaluate without creating runtime state. In write mode, a
valid manifest is printed only after secure persistence succeeds.

## Phase 1 — Baseline knowledge reconstruction

Phase 1 consumes a valid Phase 0 manifest and reads only admitted blobs from the
recorded Git tree. It produces evidence-linked architecture memory rather than
file summaries. The first target is the fixed WFF v1.6.2 baseline.

Run the fixed baseline reconstruction after Phase 0 has persisted the baseline
observation manifest:

```bash
python3 EKRI/scripts/reconstruct_wff_baseline.py \
  --repository-root /path/to/wff-repository
```

Outputs are written below:

```text
.EKRI/knowledge/<target-tree>/
├── evidence-index.json
├── architecture-memory.json
├── ARCHITECTURE_MEMORY.md
└── reconstruction-report.json
```

The machine memory separates `observed-fact`, `inferred-knowledge`, and
`unknown`. Every non-unknown assertion links to evidence anchors in exact Git
blobs. The Markdown file is only a human-readable projection.

## Phase 2 — Existing Capability Intelligence

Phase 2 consumes either a fully revalidated local Phase 1 snapshot or a verified
tracked project asset. It then uses an evidence-linked exact-alias capability
catalog to answer the six Before Generate questions: existence,
location/ownership, reuse limits, trigger basis, mainline impact, and bounded
reuse posture. A tracked asset is accepted only after target-tree blob and
content-digest verification; it is not trusted merely because it is committed.

Example:

```bash
python3 EKRI/scripts/check_existing_capability.py \
  --repository-root /path/to/wff-repository \
  --capability "traceability" \
  --trigger-basis declared-requirement \
  --trigger-reference REQ-123 \
  --change-mode additive-extension
```

Formal results are written below:

```text
.EKRI/intelligence/<target-tree>/
├── capability-catalog.json
├── checks/<request-id>.json
├── checks/<request-id>.md
└── audits/<request-id>.json
```

A miss does not prove absence, ambiguity blocks the decision, and hypothetical
risk alone cannot justify replacement. Phase 2 does not rescan target code or
modify Architecture Memory.

## Phase 3 — Evolution and impact intelligence

Phase 3 compares the verified v1.6.2 baseline with an immutable target Git tree.
It supports baseline, bounded local-change, and complete admitted-drift scans;
keeps hidden dependency risk explicit; verifies registered expected paths; and
persists Architecture Evolution separately from inferred Change Impact.

A clean independent worktree must first reconstruct its ignored Phase 0/1
authority:

```bash
python3 EKRI/scripts/bootstrap_phase3_audit.py \
  --repository-root /path/to/clean/worktree
```

The bootstrap regenerates authority for the worktree and compares stable
semantic fingerprints with the committed audit fixture. It does not copy an
old absolute-path observation manifest.

Run Phase 3:

```bash
python3 EKRI/scripts/run_phase3_evolution.py \
  --repository-root /path/to/repository \
  --target-ref HEAD \
  --scan-mode drift \
  --registrations /path/to/registrations.json \
  --impacts /path/to/impacts.json \
  --verification-trigger explicit-request
```

Formal outputs are written below `.EKRI/evolution/<target-tree>/`. Registration
is only intent; callers may manage `registered -> planned`, while observed and
verified states are scanner-owned. Evolution contains verified repository-
surface events. Impact remains inferred knowledge and never becomes architecture
truth.

## WFF v1.8 P0 — Core boundary reconstruction

The v1.7 tag changes no WFF P1-P4/PX runtime surface. P0 therefore does not
rewrite the accepted v1.6.2 Architecture Memory as fictional architecture
evolution. It instead:

1. reconstructs and fully verifies the v1.6.2 Architecture Memory authority;
2. observes the frozen v1.7 tag with EKRI/.EKRI excluded;
3. proves that the reviewed WFF runtime invariant and complete Architecture
   Memory projection remain equivalent;
4. resolves v1.7-only evidence that explicitly classifies tests, Harness,
   gates, distribution, history support, and EKRI;
5. classifies all 20 architecture nodes, 17 responsibilities, 16 capabilities,
   and required non-mainline surfaces;
6. produces candidate Core contracts, dependency direction/cycle analysis,
   extraction frontiers, risks, unknowns, and disputed boundaries.

Run P0 from a clean committed scanner checkout:

```bash
python3 EKRI/scripts/reconstruct_wff_core_boundary.py \
  --repository-root /path/to/wff-repository
```

Formal outputs are written below:

```text
.EKRI/core-boundary/<v1.7-tree>/
├── baseline-equivalence.json
├── core-candidate-map.json
├── core-noncore-responsibility-matrix.json
├── dependency-direction-cycle-report.json
├── candidate-extraction-frontier.json
├── unknowns-disputed-boundaries.json
├── CORE_BOUNDARY_REVIEW.md
└── core-boundary-audit.json
```

P0 identifies semantic contracts; it does not authorize a `core/` directory,
file movement, package extraction, deletion, or runtime compatibility claim.
Those decisions begin only after the P1 Minimal Core Contract is independently
reviewed.

## v1.8 P1 — Minimal Core Contract

P1 regenerates and verifies P0 authority, then defines `wff-core-contract`
`1.0.0`: nine contracts, thirteen public semantic types, nine public
operations, declarative extension registration, inward-only dependency rules,
compatibility postures for all sixteen current capabilities, migration
decisions, and bounded conformance checks.

Run P1 from a clean committed scanner checkout:

```bash
python3 EKRI/scripts/define_wff_core_contract.py \
  --repository-root /path/to/wff-repository
```

Formal outputs are written below:

```text
.EKRI/core-contract/<v1.7-tree>/
├── wff-core-contract.json
├── core-public-api.json
├── core-internal-api.json
├── extension-interface.json
├── capability-compatibility-matrix.json
├── migration-decisions.json
├── contract-conformance-report.json
├── CORE_CONTRACT_REVIEW.md
└── core-contract-audit.json
```

The extension interface is declarative metadata only. It is not an executable
plugin loader, marketplace, installation protocol, or generic plugin framework.
P1 does not choose a physical Core directory or authorize runtime migration.

## v1.8 P2 — Physical Core Extraction

P2 resolves the physical implementation home as the top-level `wff-core/`
subproject. The distribution is `wff-core`; the Python import package is
`wff_core`. It implements the accepted public types and structural operations,
packages the P1 contract and sixteen current capability descriptors, and has no
third-party runtime dependencies.

Run the committed-target extraction audit:

```bash
python3 EKRI/scripts/audit_wff_core_extraction.py \
  --repository-root /path/to/wff-repository \
  --target-ref HEAD
```

Formal outputs are written below:

```text
.EKRI/core-extraction/<target-tree>/
├── core-extraction-audit.json
├── core-dependency-report.json
├── core-compatibility-report.json
├── core-extraction-measurements.json
├── CORE_EXTRACTION_REVIEW.md
└── core-extraction-output-audit.json
```

P2 keeps current runners and public install packs unchanged. The temporary
repository compatibility adapter demonstrates descriptor consumption but does
not migrate distribution. Static dependency closure is proven only for
committed Core imports/references; exhaustive dynamic closure remains a P4
obligation.

## v1.8 P3 — Core Consumer, Assurance, and Distribution Migration

P3 leaves the accepted `wff_core` source unchanged and migrates current
capability entrypoints, assurance surfaces, support/adaptation entrypoints,
install profiles, and maintainer release bundles to consume its public contract.
Every buildable install profile vendors Core under `scripts/wff_core` and must
resolve it as `packaged-core`; source checkouts retain a bounded fallback until
P4.

Run the committed-target migration audit:

```bash
python3 EKRI/scripts/audit_wff_core_migration.py \
  --repository-root /path/to/wff-repository \
  --target-ref HEAD
```

Formal outputs are written below:

```text
.EKRI/core-migration/<target-tree>/
├── core-migration-audit.json
├── capability-consumer-map.json
├── assurance-consumer-migration.json
├── distribution-migration-report.json
├── compatibility-retirement-status.json
├── CORE_MIGRATION_REVIEW.md
└── core-migration-output-audit.json
```

P3 verifies exact registered change coverage and dependency direction. It does
not authorize compatibility-fallback retirement or replace the mandatory P4
three-scenario P1-P4 plus four-scenario PhaseX validation matrix.

## EKRI v1.0 — Engineering Knowledge System architecture transition

EKRI v0.9 is the released independent-product baseline. The v1.0 program is a
controlled semantic-authority convergence, not a flag-day rewrite and not a
requirement for WFF runtime delivery.

The frozen product direction is:

```text
rich but shallow Engineering Knowledge Model
+ named Query / View contracts
+ progressive disclosure L0-L3
+ internal Object / Occurrence / Assertion semantic normal form
+ one semantic authority per knowledge slice/context
```

Issue #1036 freezes the implementation boundary. P1/#1037 is authorized only to
build a read-only `shadow-non-authoritative` substrate; no v0.9 semantic writer,
schema authority, portable project asset, or WFF runtime surface may be replaced
at that stage. Architecture round-trip parity, Capability query migration,
Asset/Ownership/Lifecycle firewall stress, Flow, first authority cutover,
semantic-writer retirement, non-WFF conformance, and release closure remain
separate later issues.

Primary v1.0 authority records:

- `docs/v100-architecture-authority-freeze-v0.1.md`
- `docs/engineering-knowledge-ontology-synthesis-v0.1.md`
- `docs/v100-engineering-knowledge-system-transition-plan-v0.1.md`
- `docs/v090-m0-baseline-v0.1.md`

P1/#1037 implements the first bounded shadow slice from one fully verified
Phase-1 Architecture Memory snapshot. The compiler preserves current Architecture
semantic IDs, source/evidence posture and claim ceiling, writes only rebuildable
`.EKRI/shadow/<source-tree>/` state, and remains outside the stable public
`ekri.__all__` surface until later parity/cutover work justifies a supported API.

```bash
python3 EKRI/scripts/compile_architecture_shadow.py \
  --repository-root /path/to/repository \
  --source-tree <verified-phase1-tree>
```

Use `--no-write` to evaluate without persisting shadow runtime state. P1 design:
`docs/v100-p1-shadow-semantic-substrate-v0.1.md`.

P2/#1038 proves bounded Architecture round-trip parity through that serialized
shadow. It independently normalizes the verified Phase-1 source and reconstructs
a `derived-non-authoritative` Architecture View from P1 Objects/Assertions, then
compares source Context, identity/structure, responsibility/non-responsibility,
implementation intent, assurance ownership, constraints, unknown posture,
evidence bindings, claim ceiling, and View semantic fingerprint.

```bash
python3 EKRI/scripts/run_architecture_roundtrip.py \
  --repository-root /path/to/repository \
  --source-tree <verified-phase1-tree>
```

The derived `architecture-view.json` and parity report remain rebuildable under
`.EKRI/shadow/<source-tree>/`; they do not replace `.EKRI/knowledge/**`. P2
design: `docs/v100-p2-architecture-roundtrip-v0.1.md`.

P3/#1039 introduces the first product-facing named query family over the shared
semantic path. A rebuildable Capability Query Index stores only capability IDs
and normalized aliases; Architecture, responsibility, constraint, intent,
assurance, ownership and evidence semantics are resolved from the P2 View at
query time rather than copied into a second Capability Catalog.

```python
from ekri import CapabilityQueryService

service = CapabilityQueryService.from_repository(
    "/path/to/repository",
    source_tree="<verified-phase1-tree>",
)
service.find_capability("architecture design")   # L0
service.get_realizations("architecture-design") # L1
service.explain_authority("architecture-design")# L2
service.get_evidence("architecture-design")     # L3
```

CLI entry:

```bash
python3 EKRI/scripts/query_capability.py \
  --repository-root /path/to/repository \
  --query-kind find-capability \
  --query "architecture design"
```

`not-found` remains unknown rather than absence proof. The optional index is
persisted only under `.EKRI/shadow/<source-tree>/capability-query-index.json`
and remains `derived-non-authoritative`. P3 design:
`docs/v100-p3-capability-named-query-v0.1.md`.

P4/#1040 is an internal full-scale authority-firewall stress capability. It
projects validated Repository Asset Identity, Ownership Boundary and Lifecycle
Observation knowledge onto the same Engineering Knowledge Model while keeping
high-cardinality structural edges below semantic authority as raw/rebuildable
observations. It is not a normal consumer API and is intentionally not exported
through `ekri.__all__`.

```bash
python3 EKRI/scripts/run_repository_firewall_stress.py \
  --repository-root /path/to/repository \
  --asset-map /path/to/repository-asset-knowledge-map.json \
  --ownership-map /path/to/repository-ownership-boundary-map.json \
  --lifecycle-snapshot /path/to/repository-lifecycle-observation-snapshot.json \
  --write
```

The stress View preserves stable asset IDs across moves, distinct compatibility
surface identities, unresolved/multi-owner evidence posture and negative
retirement/deletion ceilings. Structural edges remain
`raw-rebuildable-structural-observation` with `semantic_authority=false`. P4
design: `docs/v100-p4-repository-firewall-stress-v0.1.md`.

P5/#1041 adds the first general Flow/Handoff named query without creating a
Flow semantic writer/store. A `FlowDefinition` is an Object, bounded handoffs
are `HandoffOccurrence` records, and routing/carriage/authority/reliance/order
are qualified non-authoritative Assertions. Normal callers use `trace_flow(...)`
and never traverse raw Object/Occurrence/Assertion records.

```python
from ekri import FlowQueryService

service = FlowQueryService.from_fixture_path(
    "EKRI/specs/flow-fixtures/wff-p1-p4-handoff.json",
    repository_root="/path/to/repository",
)
service.trace_flow(disclosure_level="L0")
service.trace_flow(disclosure_level="L2")
service.trace_flow(disclosure_level="L3")
```

CLI entry:

```bash
python3 EKRI/scripts/trace_flow.py \
  --repository-root /path/to/repository \
  --fixture EKRI/specs/flow-fixtures/wff-p1-p4-handoff.json \
  --level L2
```

P5 carries both WFF P1-P4 and non-WFF generic CI fixtures through the same
model/query vocabulary. Fixture occurrences remain explicitly
`fixture-conformance`; every Flow Assertion has `semantic_authority=false`.
There is no `.EKRI/flow*` truth store or persistence API. P5 design:
`docs/v100-p5-flow-handoff-v0.1.md`.

P6/#1042 performs the first bounded semantic-authority cutover on Capability.
The proven-equivalent Architecture View plus committed Capability specification
now establish one `ontology-authoritative` Capability semantic slice. P3 Query
Index/L0-L3 answers remain derived, while the v0.9 Capability Catalog and Before
Generate outputs become compatibility projections from that authority rather
than peer semantic writers.

```text
.EKRI/semantic/<source-tree>/capability-semantic-authority.json
```

is the optional protected persisted authority form. The supported
`run_existing_capability_check(...)` entry point keeps its v0.9 outward schemas,
but reports `authority_source.mode=ontology-authoritative-capability-slice` and
persists the Capability authority before compatibility outputs. P6 design:
`docs/v100-p6-capability-authority-cutover-v0.1.md`.

P7/#1043 performs the required immediate convergence step after that cutover.
The old private Capability Catalog writer/evaluator are physically removed,
shared request/spec/recommendation semantics move to neutral
`capability_contract.py`, and P3 query-side duplicate Architecture/spec
materialization is deleted. Core Boundary and Evolution consume the P6
Capability Authority directly; only the historical public compatibility entry
and audit bootstrap still use `existing_capability_intelligence.py`, which is
now a legacy schema/render/persistence adapter rather than a semantic writer.
P7 design: `docs/v100-p7-capability-writer-retirement-v0.1.md`.

P8/#1044 proves the supported general product surface against an unrelated
Mercury CI software-delivery fixture. Exact fixture/spec/source Git blobs are
verified first; the resulting knowledge then uses the same Architecture View,
ontology-authoritative Capability slice, L0-L3 Capability queries and
`trace_flow(...)` contract. The fixture deliberately contains conflicting
production-deployment owner evidence, which must remain
`knowledge_state=conflicting`, `existence=unknown`, with both owners visible.
P8 also freezes the general/profile boundary: `find-capability`,
`get-realizations`, `explain-authority`, `get-evidence` and `trace-flow` are
supported general query surfaces, while `before-generate` and
`.EKRI/intelligence/**` remain WFF/profile compatibility.

```bash
python3 EKRI/scripts/run_nonwff_conformance.py \
  --repository-root /path/to/repository
```

P8 design: `docs/v100-p8-nonwff-product-conformance-v0.1.md`.

P9/#1045 freezes the v1.0 Release Candidate source state and owns the final
release Gate. The RC product version is `1.0.0`; supported-general,
WFF-profile compatibility and internal/experimental surfaces are frozen in
`specs/v100-product-surface-classification.json`, while the human product
contract is `docs/v100-supported-product-contract-v1.0.md`. The machine Gate
checks the exact scanner/commit identity, v0.9 M0 writer/reconciliation
baseline, Capability writer retirement, peer-authority posture, P8 non-WFF
conformance, compatibility/rollback policy and pre-publication state.

```bash
python3 EKRI/scripts/audit_v100_release_gate.py \
  --repository-root /path/to/repository
```

P9 must stop before creating `ekri/v1.0.0` or publishing a GitHub Release until
explicit publication approval is given. Release notes:
`docs/releases/v1.0.0.md`.

Design authority:

- `docs/engineering-knowledge-reconstruction-intelligence-v0.1.md`
- `docs/phase0-observation-independence-v0.2.md`
- `docs/phase1-wff-baseline-reconstruction-v0.1.md`
- `docs/phase2-existing-capability-intelligence-v0.1.md`
- `docs/phase3-evolution-and-impact-intelligence-v0.1.md`
- `docs/v18-p0-core-boundary-reconstruction-v0.1.md`
- `docs/v18-p0-validation-and-clean-worktree-audit-20260804.md`
- `docs/v18-p1-minimal-core-contract-v0.1.md`
- `docs/v18-p1-validation-and-clean-worktree-audit-20260804.md`
- `docs/v18-p1-independent-architecture-review-20260804.md`
- `docs/v18-p2-core-extraction-v0.1.md`
- `docs/v18-p2-validation-and-clean-worktree-audit-20260804.md`
- `docs/v18-p2-independent-architecture-review-20260804.md`
- `docs/v18-p3-core-migration-v0.1.md`
- `docs/v18-p3-validation-and-clean-worktree-audit-20260805.md`
- `docs/v18-p3-independent-architecture-review-20260805.md`
