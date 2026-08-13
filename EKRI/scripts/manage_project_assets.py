#!/usr/bin/env python3
"""Promote, verify, or hydrate portable EKRI project knowledge assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from ekri.project_assets import (  # noqa: E402
    ProjectAssetError,
    hydrate_project_asset,
    promote_project_asset,
)
from ekri.project_assets_v2 import verify_project_asset_any  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("promote", "verify", "hydrate"))
    parser.add_argument("--repository-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--asset-id")
    parser.add_argument("--source-tree")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.action == "promote":
            if not args.asset_id or not args.source_tree:
                raise ProjectAssetError("promote requires --asset-id and --source-tree")
            result = promote_project_asset(
                args.repository_root,
                source_tree=args.source_tree,
                asset_id=args.asset_id,
            )
        elif args.action == "verify":
            verified = verify_project_asset_any(args.repository_root, asset_id=args.asset_id)
            result = {
                "status": "project-asset-verified",
                "asset_dir": str(verified.asset_dir),
                "schema_version": str(verified.manifest.get("schema_version") or ""),
                "manifest": verified.manifest,
            }
        else:
            result = hydrate_project_asset(args.repository_root, asset_id=args.asset_id)
    except ProjectAssetError as exc:
        print(json.dumps({"status": "project-asset-error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
