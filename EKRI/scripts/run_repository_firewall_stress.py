#!/usr/bin/env python3
"""Compile EKRI v1.0 P4 repository authority-firewall stress View."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import sys
from typing import Any


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.repository_firewall_stress import (  # noqa: E402
    RepositoryFirewallStressError,
    compile_repository_firewall_stress_view,
    persist_repository_firewall_stress_view,
)


def _load_json(path_value: str, label: str) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve(strict=False)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RepositoryFirewallStressError(f"{label} cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise RepositoryFirewallStressError(f"{label} must be a safe regular JSON file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryFirewallStressError(f"{label} cannot be read: {exc}") from exc
    if not isinstance(value, dict):
        raise RepositoryFirewallStressError(f"{label} must contain a JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", default=str(EKRI_ROOT.parent))
    parser.add_argument("--asset-map", required=True)
    parser.add_argument("--ownership-map", required=True)
    parser.add_argument("--lifecycle-snapshot", required=True)
    parser.add_argument("--write", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = compile_repository_firewall_stress_view(
            _load_json(args.asset_map, "Repository Asset Identity map"),
            _load_json(args.ownership_map, "Repository Ownership Boundary map"),
            _load_json(args.lifecycle_snapshot, "Repository Lifecycle Observation snapshot"),
        )
        output = ""
        if args.write:
            output = str(persist_repository_firewall_stress_view(args.repository_root, payload))
        result = {
            "schema_version": "ekri.repository-firewall-stress-run.v1",
            "status": "repository-firewall-stress-complete",
            "authority_mode": payload["authority_mode"],
            "semantic_fingerprint": payload["semantic_fingerprint"],
            "structural_observation_fingerprint": payload["structural_observation_fingerprint"],
            "projection_fingerprint": payload["projection_fingerprint"],
            "summary": payload["summary"],
            "firewall_checks": payload["firewall_checks"],
            "output": output,
            "claim_ceiling": payload["claim_ceiling"],
        }
    except RepositoryFirewallStressError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "ekri.repository-firewall-stress-cli-error.v1",
                    "status": "blocked",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
