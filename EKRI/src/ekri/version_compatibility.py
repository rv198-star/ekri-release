"""Version compatibility over Project Knowledge asset-layout generations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SPEC_RELATIVE_PATH = Path("specs/version-compatibility.json")
SPEC_SCHEMA_VERSION = "ekri.version-compatibility.v1"


class VersionCompatibilityError(RuntimeError):
    pass


def _ekri_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_version_compatibility() -> dict[str, Any]:
    path = _ekri_root() / SPEC_RELATIVE_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VersionCompatibilityError(f"version compatibility spec cannot be read: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise VersionCompatibilityError("unsupported version compatibility spec")
    generations = value.get("generations")
    if not isinstance(generations, list) or not generations:
        raise VersionCompatibilityError("version compatibility generations are missing")
    seen_versions: set[str] = set()
    seen_generations: set[str] = set()
    for raw in generations:
        if not isinstance(raw, dict):
            raise VersionCompatibilityError("compatibility generation must be an object")
        generation_id = str(raw.get("generation_id") or "").strip()
        current_schema = str(raw.get("current_asset_schema") or "").strip()
        versions = raw.get("versions")
        supported = raw.get("supported_asset_schemas")
        if not generation_id or generation_id in seen_generations:
            raise VersionCompatibilityError("compatibility generation id is missing or duplicated")
        if not current_schema:
            raise VersionCompatibilityError(f"current asset schema missing for {generation_id}")
        if not isinstance(versions, list) or not versions:
            raise VersionCompatibilityError(f"versions missing for {generation_id}")
        if not isinstance(supported, list) or current_schema not in supported:
            raise VersionCompatibilityError(f"supported asset schemas invalid for {generation_id}")
        seen_generations.add(generation_id)
        for raw_version in versions:
            version = str(raw_version).strip()
            if not version or version in seen_versions:
                raise VersionCompatibilityError("product version is missing or duplicated across generations")
            seen_versions.add(version)
    return value


def version_record(version: str) -> dict[str, Any] | None:
    requested = str(version).strip()
    spec = load_version_compatibility()
    for raw in spec["generations"]:
        versions = [str(item) for item in raw["versions"]]
        if requested in versions:
            return {
                "version": requested,
                "generation_id": raw["generation_id"],
                "current_asset_schema": raw["current_asset_schema"],
                "supported_asset_schemas": list(raw["supported_asset_schemas"]),
                "status": raw.get("status", ""),
            }
    return None


def check_version_compatibility(left_version: str, right_version: str) -> dict[str, Any]:
    left = version_record(left_version)
    right = version_record(right_version)
    if left is None or right is None:
        return {
            "schema_version": "ekri.version-compatibility-answer.v1",
            "status": "unknown",
            "left": left or {"version": str(left_version).strip(), "generation_id": "unknown"},
            "right": right or {"version": str(right_version).strip(), "generation_id": "unknown"},
            "fully_compatible": False,
            "reason": "At least one EKRI product version is not registered in the compatibility list.",
        }
    compatible = left["generation_id"] == right["generation_id"]
    return {
        "schema_version": "ekri.version-compatibility-answer.v1",
        "status": "fully-compatible" if compatible else "not-fully-compatible",
        "left": left,
        "right": right,
        "fully_compatible": compatible,
        "reason": (
            "Both versions use the same current Project Knowledge asset-layout generation."
            if compatible
            else "The versions belong to different Project Knowledge asset-layout generations. Backward readability may still exist, but full compatibility is not claimed."
        ),
    }
