# EKRI v1.1.0 Release Pack

This is the independent EKRI source/runtime distribution for product version `1.1.0`.

Source identity: `d45dc12d0777d5c7f6651f3564dea63b1dded8a6` (the formal release tag, when published, is `ekri/v1.1.0`).

## Layout

The package preserves a top-level `EKRI/` directory because EKRI Formal Scanner provenance requires the active implementation to live at `EKRI/` in its scanner-control Git repository.

## Install / activate the Formal Scanner

1. Extract this package into a directory that will act as the EKRI scanner-control repository.
2. Initialize Git if needed: `git init`.
3. Keep the package-root `.gitignore`; it excludes `.EKRI/` and Python cache artifacts that must not make the scanner surface dirty.
4. Add and commit the extracted `EKRI/` surface (and package metadata if desired).
5. Run EKRI against a target Git repository, for example:

```bash
python3 EKRI/scripts/validate_observation_boundary.py \
  --repository-root /path/to/target-repository \
  --target-ref HEAD
```

The scanner intentionally fails closed if its `EKRI/` implementation surface is dirty, uncommitted, outside a Git repository, or not rooted at top-level `EKRI/`.

This package preserves the Git-backed scanner-control trust model. It does not add a standalone-provenance fallback.

## Included

- Python implementation under `EKRI/src/ekri/`
- EKRI command-line scripts
- schemas and product/profile specs required by the selected EKRI version
- committed audit/conformance fixtures required by current supported capabilities
- bounded product/operation/release documentation
- `EKRI/README.md`, `EKRI/CHANGELOG.md`, and `EKRI/pyproject.toml`

## Excluded

- EKRI tests
- WFF change-registration history
- ontology exploration/audit history not listed as bounded product documentation
- repository-local runtime state (`.EKRI/**`)
- WFF runtime/install-pack content

See `EKRI_RELEASE_PACK_MANIFEST.json` for exact file identities and the release claim ceiling.
