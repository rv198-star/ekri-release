# EKRI Versioning, Changelog, and Release Governance v0.1

Status: adopted by Issue #1028 for EKRI v0.9 release closeout; no tag or release publication is authorized by this document alone

## 1. Purpose

EKRI is a top-level subproject in the WFF repository, but it has its own engineering capability boundary, Python package metadata, tests, schemas, design documents, runtime tools, and future product direction as a general Engineering Knowledge Reconstruction and Intelligence system.

This policy defines how EKRI evolves as an independently versioned and releasable product while remaining in the WFF repository for the foreseeable future.

```text
shared repository
  ├── WFF lifecycle/product line
  │    version/tag/release: WFF-owned
  └── EKRI subproject
       version/tag/release/changelog: EKRI-owned
```

Repository co-location does not imply release-version coupling.

## 2. Current State

`EKRI/pyproject.toml` already declares an independent Python package:

```text
name = ekri
version = 0.8.0
```

Historical package-version commits established this lineage during initial EKRI build-out:

```text
0.1.0  Phase 0 observation trust boundary
0.3.0  Existing Capability Intelligence
0.4.0  Evolution / Impact Intelligence
0.5.0  WFF Core boundary reconstruction
0.6.0  WFF minimal Core contract
0.7.0  physical Core extraction
0.8.0  Core consumer/distribution migration support
```

These were package-version increments, not a complete independent release governance system.

Since `0.8.0`, EKRI materially added Portable Project Knowledge, Repository Asset Identity, Repository Ownership Boundary, Repository Lifecycle Observation, and further evidence/authority hardening. Therefore `0.8.0` is a historical package milestone rather than the correct independent release identity for the current product surface.

## 3. Decision: Same Repository, Independent Product Version

EKRI remains in the WFF Git repository for now, while owning its own:

- semantic version;
- changelog;
- tag namespace;
- release notes;
- GitHub Release identity;
- release validation/claim ceiling;
- optional future package/distribution artifacts.

WFF and EKRI versions advance independently. For example:

```text
WFF v1.9.2
EKRI v0.9.0
```

No numerical relationship is implied.

## 4. Version Source Of Truth

The product-version source of truth is:

```text
EKRI/pyproject.toml
[project].version
```

Do not add a second manually maintained `VERSION` file unless packaging technology later requires it.

Keep separate:

```text
EKRI product version
schema_version
scanner/component implementation version
host/target version
```

## 5. Semantic Versioning Posture

Before `1.0.0`, use explicit pre-1.0 SemVer judgment.

### Patch — `0.x.Y`

Compatible correctness/hardening changes that do not materially expand the supported EKRI product model or invalidate supported consumer contracts.

### Minor — `0.X.0`

Meaningful capability expansion or architectural evolution while the independent product contract remains pre-1.0.

### `1.0.0`

Reserve for the first deliberately supported general Engineering Knowledge System architecture and product contract, including stable general Engineering Knowledge Model terminology, stable trust boundary, supported query contracts, schema/API migration policy, non-WFF conformance, independent release process, and supported-vs-experimental classification.

A shadow ontology prototype alone is insufficient for `1.0.0`.

## 6. Tag Namespace

WFF uses unqualified repository tags such as `v1.8` and `v1.9`. EKRI uses a separate namespace:

```text
ekri/v0.9.0
ekri/v0.9.1
ekri/v1.0.0-rc.1
ekri/v1.0.0
```

One Git commit may carry both WFF and EKRI tags when both products independently release from that exact repository state. Their release identities remain separate.

## 7. Independent GitHub Release

Recommended identity:

```text
Release title: EKRI v0.9.0
Tag:           ekri/v0.9.0
```

A WFF release does not automatically create an EKRI release and vice versa.

Starting with v0.9.0, an EKRI Release should also publish an audited independent release pack. The pack is a bounded source/runtime distribution, not a WFF install-pack component and not a claim that EKRI already supports non-Git scanner provenance.

Release-pack identity must separate:

```text
source_revision   = exact EKRI product tag/commit being distributed
packager_revision = exact repository commit containing the packaging implementation
```

For v0.9, `source_revision` remains the immutable `ekri/v0.9.0` product source even when packaging infrastructure is added later on `main`. Adding or improving release packaging does not require moving the EKRI product tag when runtime/product semantics are unchanged.

The v0.9 package preserves a top-level `EKRI/` directory and ships a package-root `.gitignore` so Python cache/runtime state does not dirty the scanner surface. Formal Scanner use still requires the extracted `EKRI/` surface to be committed inside a scanner-control Git repository. Wheel/sdist and a non-Git standalone-provenance mode remain future, separately governed surfaces.

## 8. Changelog

Maintain:

```text
EKRI/CHANGELOG.md
```

Include only material EKRI product changes affecting observation/trust, reconstructed knowledge semantics, identity/provenance/evidence, product-facing query/intelligence, portable knowledge, supported schemas/contracts, public CLI/Python API, or release/compatibility posture.

Do not dump every WFF registration/evolution receipt into the EKRI changelog.

## 9. Changelog And Architecture History Are Different

```text
CHANGELOG
  = consumer-visible EKRI product evolution

design/audit records
  = why architecture changed and how it was reviewed

EKRI Architecture Evolution/evidence
  = evidence-bounded source/project change knowledge

Git history
  = exact implementation history
```

The changelog summarizes important architecture changes but is not semantic authority.

## 10. Release Compatibility Matrix

Each EKRI release records validated hosts/targets without coupling them to the product version.

For v0.9:

```text
validated first host:
  WFF V1.9.2 Pre-Release candidate
  commit 7c491ea7c6ca4fd086820c1dd2ef62096af24b22
  tree   cc9cfa2ed13aa4ac68de4be6d6051ee601399fb6

not implied:
  EKRI v0.9.0 requires WFF v1.9.2 as its semantic model
```

## 11. Independent EKRI Release Gate

Minimum release checks:

1. `EKRI/pyproject.toml` version matches intended release identity;
2. `EKRI/CHANGELOG.md` contains the release entry;
3. Python 3.12 EKRI tests pass in declared environment;
4. schema/API compatibility changes are documented;
5. clean bootstrap/observation trust checks pass;
6. package/source surface has no unintended WFF install-pack/release dependency;
7. supported, WFF-specific, experimental, and historical surfaces are explicit;
8. release claim ceiling is explicit;
9. release candidate is an exact clean commit/tree;
10. independent EKRI release state does not alter WFF release state;
11. two independent release closeout audits pass;
12. downloadable release pack, when published, passes its independent package audit, contains no WFF runtime/install-pack payload, and proves an extracted-and-committed scanner-control repository can run Phase 0 without weakening No Active Self-Scan.

## 12. Historical `0.1.0`–`0.8.0` Treatment

Treat them as **historical package-version milestones**. Do not retroactively manufacture Releases, dates, or support guarantees unless a concrete archival need later justifies it.

## 13. Two-Step Product Transition: v0.9 Baseline, v1.0 Architecture

```text
EKRI v0.9.x
  = independent-product baseline and stabilization

EKRI v1.0.0
  = Engineering Knowledge System architecture release
```

### 13.1 EKRI v0.9.0 — Independent Product Baseline Release

Mission:

> **Freeze and release the current evidence-bounded EKRI capability baseline under independent version, changelog, tag, release, compatibility, and claim-ceiling governance.**

Required scope:

- audit the delta since historical package milestone `0.8.0`;
- include proven Portable Project Knowledge, Repository Asset Identity, Repository Ownership Boundary, and Repository Lifecycle Observation;
- preserve Observation/Evidence/No Active Self-Scan boundaries;
- classify WFF-specific Core-era analysis separately from general EKRI capabilities;
- establish `CHANGELOG`, tag namespace, EKRI-owned Release Gate, and claim ceiling;
- freeze exact semantic/query/complexity M0 for v1.0;
- carry the Engineering Knowledge Model/Ontology work as **accepted architecture design direction**, not v0.9 runtime capability.

v0.9 must not claim ontology-native storage/authority, new shared-substrate Flow, semantic cutover, standalone repository split, or unsupported standalone-install maturity.

### 13.2 EKRI v1.0.0 — Engineering Knowledge System Architecture Release

Mission:

> **Make EKRI's primary product model a rich but shallow Engineering Knowledge Model, backed internally by the `Object / Occurrence / Assertion` semantic meta-kernel, with governed qualification contracts, named Query/View surfaces, progressive disclosure, and bounded single-authority migration from legacy semantic stores.**

Minimum obligations:

```text
M0  consume frozen v0.9 semantic/query/complexity baseline
M1  read-only shadow semantic substrate + governed Engineering Knowledge Model
M2  Architecture Memory -> substrate -> derived Architecture View parity
M3  Existing Capability / Capability Query parity
M4  Repository Asset Identity + Ownership + Lifecycle authority-firewall parity
M5  bounded Flow/Handoff query without a parallel Flow authority store
M6  bounded general semantic authority cutover
M7  derived legacy output + duplicate semantic writer retirement/demotion
M8  non-WFF conformance through the same general Engineering Knowledge Model
```

### 13.3 v1.0 Stability Threshold

Stabilize supported Engineering Knowledge Model terminology, internal meta-kernel semantics, identity/version/lineage, context/validity, evidence/provenance, normative/authority qualification, typed state dimensions, named query/view contracts, view provenance/staleness/rebuild, schema/API migration policy, single-authority cutover/rollback, supported-vs-experimental classification, and at least one WFF plus one non-WFF conformance corpus.

Not every future Flow/Decision/Claim depth, Code Graph adapter, distributed trace, domain profile, or distribution technology must be feature-complete at 1.0.

### 13.4 v1.0 Stop Conditions

Remain on `0.9.x` and reassess rather than forcing `1.0` if the architecture requires raw meta-kernel traversal by normal consumers, peer semantic stores, weakened identity/ownership/lifecycle firewalls, dual-write/bidirectional synchronization, WFF-specific concepts in the general meta-kernel, storage-only semantic ID reallocation, or permanent architecture growth without retirement/demotion of duplicated semantic logic.

## 14. Relationship To Future Repository Separation

If EKRI later moves to a separate repository, preserve product versions, changelog lineage, schema identities, API compatibility, release notes lineage, and product identity. Repository separation is logistics, not a version reset.

## 15. Decision Summary

```text
same Git repository
+ independent EKRI semantic version
+ EKRI/CHANGELOG.md
+ ekri/vX.Y.Z tag namespace
+ independent EKRI GitHub Releases
+ EKRI-owned release gate/claim ceiling
+ WFF compatibility metadata, not version coupling

version transition:
  0.9.x = independent-product baseline and stabilization
  1.0.0 = Engineering Knowledge System architecture release
```
