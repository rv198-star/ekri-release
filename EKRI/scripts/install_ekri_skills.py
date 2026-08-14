#!/usr/bin/env python3
"""Validate or install the official EKRI Skill directories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from typing import Any


# Validation/install must not dirty a committed scanner-control repository.
sys.dont_write_bytecode = True

EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.skill_surface import (  # noqa: E402
    EKRISkillSurfaceError,
    SKILL_NAMES,
    validate_skill_surface,
)

SKILLS_ROOT = EKRI_ROOT / "skills"


class EKRISkillInstallError(RuntimeError):
    pass


def validate_skills() -> list[dict[str, Any]]:
    try:
        return validate_skill_surface(EKRI_ROOT)
    except EKRISkillSurfaceError as exc:
        raise EKRISkillInstallError(str(exc)) from exc


def install_skills(target_dir: Path, *, force: bool = False) -> dict[str, Any]:
    rows = validate_skills()
    target = target_dir.expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    for row in rows:
        name = str(row["name"])
        source = SKILLS_ROOT / name
        destination = target / name
        if destination.exists():
            if not force:
                raise EKRISkillInstallError(
                    f"target Skill already exists: {destination}; use --force to replace it"
                )
            if destination.is_symlink() or not destination.is_dir():
                raise EKRISkillInstallError(
                    f"refusing to replace non-directory or symlink target: {destination}"
                )
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=False)
        installed.append(str(destination))
    return {
        "status": "installed",
        "target_dir": str(target),
        "skill_count": len(installed),
        "skills": installed,
        "ekri_home": str(EKRI_ROOT.parent),
        "recommended_environment": f"EKRI_HOME={EKRI_ROOT.parent}",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or install the official EKRI Skills")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true", help="list official EKRI Skills")
    action.add_argument("--check", action="store_true", help="validate bundled EKRI Skills")
    action.add_argument("--target-dir", help="install all EKRI Skills into this Agent skills directory")
    parser.add_argument("--force", action="store_true", help="replace existing EKRI Skill directories")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        rows = validate_skills()
        if args.list:
            result: dict[str, Any] = {
                "status": "listed",
                "skill_count": len(rows),
                "skills": [{"name": row["name"], "description": row["description"]} for row in rows],
            }
        elif args.check:
            result = {
                "status": "valid",
                "skill_count": len(rows),
                "skills": [row["name"] for row in rows],
            }
        else:
            result = install_skills(Path(args.target_dir), force=args.force)
    except EKRISkillInstallError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
