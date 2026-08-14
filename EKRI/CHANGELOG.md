# EKRI Changelog

All notable EKRI product changes are recorded here.

EKRI is versioned independently from WFF even while both products remain in the same Git repository. WFF changes that merely produce EKRI registration/evolution receipts are not EKRI product changes unless they materially change EKRI observation, reconstruction, knowledge, intelligence, API/schema, portability, or release behavior.

## [Unreleased]

### Added

### Changed

### Fixed

### Deprecated

### Removed

### Security

## [1.1.1] - 2026-08-14

### Added

- Official AI-facing EKRI Skill set: `using-ekri`, `ekri-init`, `ekri-refresh`, and `ekri-query`.
- Generic Skill installer/validator `EKRI/scripts/install_ekri_skills.py` for caller-supplied Agent skills directories.
- Machine-readable v1.1.1 Skill-surface classification and release-gate coverage.
- AI-Agent-only target-project access contract: Skills are read-only by default; only explicitly authorized EKRI knowledge persistence under `.EKRI/project/**` is allowed, with Git tracking recommended.
- Machine-readable EKRI product-version compatibility list based on Project Knowledge asset-layout generations, plus a CLI for list/lookup/compare.

### Fixed

- v1.1.0 shipped runtime/CLI/API capability without an official packaged Skill entry surface; v1.1.1 makes the four action Skills mandatory release-pack content.

### Compatibility / claim posture

- No new semantic writer or knowledge family is introduced; the Skills are non-authoritative routing/usage surfaces over existing EKRI capabilities.
- `1.1.0` and `1.1.1` are fully compatible because the current Project Knowledge asset layout remains `ekri.project-knowledge-asset.v2`; `1.0.0` belongs to the prior layout generation.

## [1.1.0] - 2026-08-14

### Added

- Project Knowledge Asset v2: a manifest-first, versioned partial-family format that separates producer EKRI identity, target identity, knowledge-model contract, stable semantic identity namespace, source-contract provenance and per-family availability/authority posture.
- First v2 asset for exact WFF v1.9.2, preserving native bounded Repository Asset Identity / Ownership / Lifecycle knowledge, bounded Evolution overlay and Flow conformance while explicitly withholding current Architecture/Capability authority where source contracts are incomplete.
- `verify_project_asset_v2(...)` / `verify_project_asset_any(...)` and automatic v1/v2 detection in `manage_project_assets.py verify`.
- Mission-oriented Adaptive Knowledge Acquisition: exact Mission Context, reuse-aware Knowledge Sufficiency assessment, disposable Mission Exploration Plans, generic exploration operators, exact acquisition Evidence Receipts, bounded WAE traces, non-authoritative Candidate Knowledge Delta and family-authority routing.
- Heterogeneous adaptive conformance across service/contract/state, interaction-client and data-pipeline shapes without a technology-stack Profile matrix.
- Planned exploration-economy audit comparing from-zero and Project-Knowledge-reuse paths on the same WFF v1.9.2 questions without upgrading the known blocked Architecture gap.

### Changed

- Existing Project Knowledge Asset v1 promotion, verification, hydration and Capability migration remain unchanged; multiple tracked assets now require explicit asset selection rather than implicit era/format choice.

### Fixed

- v1.1 release-gate lifecycle now supports the published tag state only when `ekri/v1.1.0` resolves to the frozen validated v1.1 source, while post-merge WFF-only descendant changes remain outside EKRI release scope.

### Deprecated

### Removed

### Security

## [1.0.0] - 2026-08-13

### Added

- Independent EKRI release-pack builder/auditor and packaging tests, preserving top-level `EKRI/` Git scanner-control provenance.
- Supported rich-but-shallow Engineering Knowledge Model architecture with internal Object / Occurrence / Assertion semantic normalization.
- `ekri.architecture-view.v1` with source-context/evidence/claim-ceiling preservation and exact Architecture round-trip proof.
- `ekri.capability-semantic-authority.v1` as the first ontology-authoritative semantic slice.
- General Capability L0-L3 named queries: `find_capability`, `get_realizations`, `explain_authority`, and `get_evidence`.
- Bounded `trace_flow` / Flow-Handoff query without a peer Flow truth store.
- Explicit `conflicting` epistemic posture in addition to observed, inferred and unknown.
- Full-scale Asset Identity / Ownership / Lifecycle authority-firewall stress proof over the shared model.
- Mercury CI non-WFF product conformance using the same Architecture, Capability and Flow contracts with exact Git-backed evidence.
- Machine-readable supported-general / WFF-profile / internal-experimental product-surface classification.
- v1.0 schema/API compatibility and single-authority rollback policy.

### Changed

- Capability semantic authority moved from the v0.9 Catalog writer to the ontology-authoritative Capability slice; Query Index and WFF Before Generate/Catalog outputs are derived compatibility surfaces.
- Core Boundary and Evolution consume the Capability Authority directly instead of rebuilding the legacy Capability Catalog.
- General Capability query posture no longer exposes pre-release v0.9 migration labels; realization and evidence expansion now use product-general terminology.
- EKRI release-pack language is product-version neutral and includes the bounded v1.0 supported product contract/release notes when present in the source revision.

### Fixed

- Semantic identity is separated from physical/materialization projection identity so portable and local equivalent knowledge does not appear as semantic evolution.
- Conflicting owner evidence remains explicit and cannot be silently collapsed into one owner or upgraded to confirmed capability existence.
- High-cardinality structural observations remain raw/rebuildable evidence instead of being inflated into semantic authority assertions.
- Stable repository asset identity survives accepted moves while compatibility-surface identity remains separate.

### Deprecated

- The v0.9 Capability Catalog as a semantic-authority writer is retired from the v1.0 internal architecture. Its output schema remains available as WFF/profile compatibility projection.

### Removed

- Retired private Capability Catalog builder/evaluator and duplicate query-side Architecture/spec reconciliation logic.

### Security

- Preserved exact Git scanner identity, No Active Self-Scan, safe `.EKRI/**` write boundaries, tracked secret scanning, evidence trust-root verification and release-pack secret/path audits.

### Compatibility / claim posture

- WFF remains a validated host/stress profile rather than the general semantic definition of EKRI.
- Supported general surfaces, WFF-profile compatibility and internal/experimental surfaces are explicitly classified in `EKRI/specs/v100-product-surface-classification.json`.
- v1.0 supports one completed semantic-authority cutover/retirement chain; it does not claim universal ontology completeness, exhaustive absence/dependency proof, autonomous ownership/retirement/deletion governance, production approval, or full future Flow/Decision/Claim/Code Graph/distributed-trace/domain-profile coverage.

## [0.9.0] - 2026-08-12

### Added

- Independent EKRI product version, changelog, `ekri/vX.Y.Z` tag namespace policy, release notes, release Gate, claim ceiling, and compatibility metadata separate from WFF's product lifecycle.
- Independent EKRI Python 3.12 CI covering compile checks, the full EKRI regression suite, and clean bootstrap validation on EKRI changes.
- Portable Project Knowledge assets that preserve content-addressed, evidence-linked project knowledge across clean worktrees without admitting `.EKRI/**` into the formal observation corpus.
- Repository Asset Identity reconstruction with stable asset identities, evidence-bounded ownership observations, mixed lifecycle roles, and explicit unknown preservation.
- Repository Ownership Boundary reconstruction that keeps structural dependency evidence distinct from semantic ownership authority.
- Repository Lifecycle Observation snapshots and comparison semantics that record observable usage/reference signals without autonomously creating deprecation, retirement, removal, or deletion authority.
- EKRI v0.9 M0 semantic/query/complexity baseline for measuring the later v1.0 Engineering Knowledge System transition.
- Formalized Engineering Knowledge Ontology / Engineering Knowledge Model problem exploration, Rounds 1–12 audits, and synthesis as accepted **v1.0 design direction only**.

### Changed

- Product metadata now identifies EKRI as general evidence-bounded Engineering Knowledge Reconstruction and Intelligence rather than describing the package primarily through WFF Core analysis.
- WFF is explicitly treated as EKRI's first host/stress/conformance corpus rather than the semantic definition of EKRI.
- EKRI product version, schema version, scanner/component implementation version, and host/target version are explicitly separate identities.
- Product release governance is now independent from WFF while remaining in the same repository.
- The v1.0 target architecture is defined as a rich but shallow Engineering Knowledge Model with named Query/View contracts and progressive disclosure, backed internally by `Object / Occurrence / Assertion`; this does **not** change v0.9 runtime authority.

### Fixed

- Repository ownership reconstruction preserves multi-owner/unresolved evidence instead of manufacturing one semantic owner.
- Structural import/reference evidence remains structurally scoped and cannot become semantic ownership or absence proof.
- Portable project-knowledge verification preserves exact target/evidence identity and rejects self-certifying or machine-local authority leakage.
- Repository lifecycle observation keeps observation absence separate from retirement/removal/deletion governance authority.

### Compatibility / claim posture

- First validated host baseline: WFF V1.9.2 Pre-Release candidate `7c491ea7c6ca4fd086820c1dd2ef62096af24b22` / tree `cc9cfa2ed13aa4ac68de4be6d6051ee601399fb6`.
- Host evidence includes Python 3.12.13 EKRI bootstrap 4/4 PASS, EKRI suite 177/177 PASS, 3,299 repository assets, 12,793 structural ownership-boundary edges, 1,417 exact internal Python import edges, 23/23 tracked lifecycle assets, 13/13 compatibility surfaces, zero required pending registrations, and preserved No Active Self-Scan.
- v0.9 does not claim ontology-native runtime/storage/query authority, full general Engineering Knowledge System implementation, exhaustive absence/dependency proof, autonomous governance authority, or standalone repository/distribution maturity.

## Historical package-version milestones

The following versions existed as package-version milestones during EKRI's formation inside the WFF repository. They were not governed as independent EKRI GitHub Releases and no retroactive support/release claim is implied.

### [0.8.0] — 2026-08-04

- Added WFF Core consumer/distribution migration analysis support.

### [0.7.0] — 2026-08-04

- Added physical WFF Core extraction analysis/audit support.

### [0.6.0] — 2026-08-04

- Added the versioned WFF Minimal Core Contract analysis surface.

### [0.5.0] — 2026-08-04

- Added WFF Core boundary reconstruction.

### [0.4.0] — 2026-08-04

- Added Architecture Evolution and Change Impact Intelligence.

### [0.3.0] — 2026-08-04

- Added Existing Capability Intelligence and Before Generate checks.

### [0.1.0] — 2026-08-03

- Established the initial Git-tree observation trust boundary and Engineering Knowledge Reconstruction foundation.
