#!/usr/bin/env python3
"""Build or compare EKRI repository lifecycle observation snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

EKRI_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = EKRI_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ekri.repository_lifecycle_observation import (  # noqa: E402
    RepositoryLifecycleObservationError,
    build_repository_lifecycle_observation_snapshot,
    compare_observation_snapshots,
    file_receipt,
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RepositoryLifecycleObservationError(f"JSON input must be an object: {path}")
    return value


def _pack_roots(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw in values:
        if "=" not in raw:
            raise RepositoryLifecycleObservationError("--formal-pack-root must use PROFILE=PATH")
        profile, raw_path = raw.split("=", 1)
        profile = profile.strip()
        path = Path(raw_path).expanduser().resolve(strict=False)
        if not profile or not path.is_dir():
            raise RepositoryLifecycleObservationError(f"invalid formal pack root: {raw}")
        result[profile] = path
    return result


def _manifest_receipt(root: Path) -> dict[str, Any]:
    manifest = root / "SKILL_INSTALL_PACK_MANIFEST.json"
    if not manifest.is_file():
        raise RepositoryLifecycleObservationError(f"pack manifest missing: {manifest}")
    value = file_receipt(manifest)
    payload = _load_json(manifest)
    value["profile_id"] = str(payload.get("profile_id") or "")
    value["source_revision"] = str(payload.get("source_revision") or "")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", default=Path(__file__).resolve().parents[2])
    parser.add_argument("--target-ref", default="HEAD")
    parser.add_argument("--p0-summary", required=True)
    parser.add_argument("--p3-plan", required=True)
    parser.add_argument("--formal-pack-root", action="append", default=[])
    parser.add_argument("--maintainer-bundle-root", default="")
    parser.add_argument("--previous-snapshot", default="")
    parser.add_argument("--no-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = Path(args.repository_root).expanduser().resolve(strict=False)
        p0_path = Path(args.p0_summary).expanduser().resolve(strict=False)
        p3_path = Path(args.p3_plan).expanduser().resolve(strict=False)
        pack_roots = _pack_roots(list(args.formal_pack_root))
        maintainer_root = (
            Path(args.maintainer_bundle_root).expanduser().resolve(strict=False)
            if str(args.maintainer_bundle_root).strip()
            else None
        )
        if maintainer_root is not None and not maintainer_root.is_dir():
            raise RepositoryLifecycleObservationError(f"invalid maintainer bundle root: {maintainer_root}")

        receipts: dict[str, Any] = {
            "p0_summary": file_receipt(p0_path),
            "p3_move_plan": file_receipt(p3_path),
            "formal_pack_manifests": sorted(
                [_manifest_receipt(path) for path in pack_roots.values()],
                key=lambda row: row.get("profile_id", ""),
            ),
            "maintainer_bundle_manifest": {},
        }
        if maintainer_root is not None:
            manifest = maintainer_root / "SKILL_BUNDLE_MANIFEST.json"
            receipts["maintainer_bundle_manifest"] = file_receipt(manifest)
            payload = _load_json(manifest)
            receipts["maintainer_bundle_manifest"]["source_revision"] = str(payload.get("source_revision") or "")

        snapshot = build_repository_lifecycle_observation_snapshot(
            root,
            target_ref=args.target_ref,
            p0_summary=_load_json(p0_path),
            p3_plan=_load_json(p3_path),
            formal_pack_roots=pack_roots,
            maintainer_bundle_root=maintainer_root,
            evidence_input_receipts=receipts,
            write_outputs=not args.no_write,
        )
        output: dict[str, Any] = {"snapshot": snapshot}
        if str(args.previous_snapshot).strip():
            previous = _load_json(Path(args.previous_snapshot).expanduser().resolve(strict=False))
            output["comparison"] = compare_observation_snapshots(previous, snapshot)
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, RepositoryLifecycleObservationError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "ekri.repository-lifecycle-observation-cli-error.v1",
                    "status": "blocked",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
