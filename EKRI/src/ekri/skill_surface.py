"""Validation contract for the official EKRI Skill surface."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any


SKILL_NAMES = ("using-ekri", "ekri-init", "ekri-refresh", "ekri-query")
_FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)


class EKRISkillSurfaceError(RuntimeError):
    pass


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EKRISkillSurfaceError(f"cannot read Skill file: {path}: {exc}") from exc
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise EKRISkillSurfaceError(f"Skill file lacks YAML frontmatter: {path}")
    values: dict[str, str] = {}
    for raw_line in match.group("body").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        key, separator, value = raw_line.partition(":")
        if not separator:
            raise EKRISkillSurfaceError(f"invalid Skill frontmatter line: {path}: {raw_line}")
        values[key.strip()] = value.strip()
    return values


def validate_skill_surface(ekri_root: str | Path) -> list[dict[str, Any]]:
    root = Path(ekri_root).expanduser().resolve(strict=False)
    skills_root = root / "skills"
    if not skills_root.is_dir():
        raise EKRISkillSurfaceError(f"EKRI Skill root is missing: {skills_root}")

    rows: list[dict[str, Any]] = []
    for name in SKILL_NAMES:
        skill_dir = skills_root / name
        skill_file = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_file.is_file():
            raise EKRISkillSurfaceError(f"required EKRI Skill is missing: {name}")
        if skill_dir.is_symlink() or skill_file.is_symlink():
            raise EKRISkillSurfaceError(f"EKRI Skill source must not be a symlink: {name}")
        metadata = _frontmatter(skill_file)
        if metadata.get("name") != name:
            raise EKRISkillSurfaceError(
                f"EKRI Skill frontmatter name mismatch: expected={name}, actual={metadata.get('name', '')}"
            )
        description = metadata.get("description", "")
        if len(description) < 40:
            raise EKRISkillSurfaceError(f"EKRI Skill description is too short: {name}")
        rows.append(
            {
                "name": name,
                "path": str(skill_dir),
                "skill_file": str(skill_file),
                "description": description,
            }
        )

    extras = sorted(
        path.name
        for path in skills_root.iterdir()
        if path.is_dir() and path.name not in SKILL_NAMES
    )
    if extras:
        raise EKRISkillSurfaceError(
            "unexpected EKRI Skill directories are not classified: " + ", ".join(extras)
        )
    return rows
