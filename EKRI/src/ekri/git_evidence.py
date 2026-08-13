"""Read-only Git evidence access constrained by a Phase 0 admitted corpus."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Any

from .observation_boundary import (
    ObservationBoundaryError,
    _absolute_path,
    _normalize_tree_path,
    _run_git,
    _tree_entries,
    validate_persisted_observation_manifest,
)


@dataclass(frozen=True)
class BlobReceipt:
    path: str
    mode: str
    object_type: str
    blob_oid: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AdmittedEvidenceError(RuntimeError):
    """Raised when Phase 1 attempts to read unadmitted or invalid evidence."""


class AdmittedGitReader:
    """Read exact Git blobs only when their paths were admitted by Phase 0."""

    def __init__(
        self,
        repository_root: str | Path,
        observation_manifest: dict[str, Any],
    ) -> None:
        self.repository_root = _absolute_path(repository_root)
        try:
            self.manifest = validate_persisted_observation_manifest(
                self.repository_root,
                observation_manifest,
            )
        except ObservationBoundaryError as exc:
            raise AdmittedEvidenceError(
                f"observation manifest revalidation failed: {exc}"
            ) from exc

        self.tree = str(self.manifest["source"]["tree"])
        self.commit = str(self.manifest["source"]["commit"])
        self.admitted_paths = frozenset(self.manifest["corpus"]["paths"])
        entries = _tree_entries(self.repository_root, self.tree)
        self._entry_by_path = {
            path: (mode, object_type, oid)
            for mode, object_type, oid, path in entries
        }
        missing = sorted(self.admitted_paths - set(self._entry_by_path))
        if missing:
            raise AdmittedEvidenceError(
                "admitted paths are absent from the recorded Git tree: "
                + ", ".join(missing[:10])
            )
        self._bytes_cache: dict[str, bytes] = {}
        self._receipts: dict[str, BlobReceipt] = {}

    def _entry(self, path: str) -> tuple[str, str, str, str]:
        try:
            normalized = _normalize_tree_path(path)
        except ObservationBoundaryError as exc:
            raise AdmittedEvidenceError(str(exc)) from exc
        if normalized not in self.admitted_paths:
            raise AdmittedEvidenceError(
                f"target path is not present in the Phase 0 admitted corpus: {normalized}"
            )
        entry = self._entry_by_path.get(normalized)
        if entry is None:
            raise AdmittedEvidenceError(
                f"target path is missing from the recorded Git tree: {normalized}"
            )
        mode, object_type, oid = entry
        if object_type != "blob":
            raise AdmittedEvidenceError(
                f"target evidence path is not a Git blob: {normalized} ({object_type})"
            )
        return normalized, mode, object_type, oid

    def read_bytes(self, path: str) -> bytes:
        normalized, mode, object_type, oid = self._entry(path)
        cached = self._bytes_cache.get(normalized)
        if cached is not None:
            return cached
        raw = _run_git(
            self.repository_root,
            "cat-file",
            "blob",
            oid,
            binary=True,
        )
        assert isinstance(raw, bytes)
        receipt = BlobReceipt(
            path=normalized,
            mode=mode,
            object_type=object_type,
            blob_oid=oid,
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
        )
        self._bytes_cache[normalized] = raw
        self._receipts[normalized] = receipt
        return raw

    def read_text(self, path: str) -> str:
        raw = self.read_bytes(path)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AdmittedEvidenceError(
                f"target evidence blob is not valid UTF-8 text: {path}"
            ) from exc

    def receipt(self, path: str) -> BlobReceipt:
        normalized, _, _, _ = self._entry(path)
        if normalized not in self._receipts:
            self.read_bytes(normalized)
        return self._receipts[normalized]

    def receipts(self) -> list[dict[str, Any]]:
        return [self._receipts[path].to_dict() for path in sorted(self._receipts)]

    def read_paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._receipts))
