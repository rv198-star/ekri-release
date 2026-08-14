#!/usr/bin/env python3
"""Inspect EKRI product-version compatibility by Project Knowledge asset layout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from ekri.version_compatibility import (  # noqa: E402
    VersionCompatibilityError,
    check_version_compatibility,
    load_version_compatibility,
    version_record,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Print the complete compatibility list")
    parser.add_argument("--version", help="Print the compatibility-generation record for one version")
    parser.add_argument("--compare", nargs=2, metavar=("LEFT", "RIGHT"), help="Compare two EKRI versions")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    selected = int(args.list) + int(bool(args.version)) + int(bool(args.compare))
    if selected != 1:
        print(json.dumps({"status": "error", "error": "choose exactly one of --list, --version, or --compare"}, ensure_ascii=False))
        return 2
    try:
        if args.list:
            result = load_version_compatibility()
        elif args.version:
            record = version_record(args.version)
            result = record or {"version": args.version, "status": "unknown"}
        else:
            result = check_version_compatibility(args.compare[0], args.compare[1])
    except VersionCompatibilityError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
