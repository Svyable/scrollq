"""Deterministic SHA-256 identities for submission package artifacts.

Regular files use the ordinary SHA-256 of their bytes. Directory artifacts
(such as tifxyz) use a canonical tree hash so their identity survives archive
extraction and filesystem enumeration order.

Tree hash v1:
- recursive regular files only, sorted by POSIX relative path;
- symlinks are refused;
- each record commits to relative-path length/path, byte length, and the full
  file SHA-256 digest;
- an empty directory is refused.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

TREE_HASH_SCHEME = "scroliq-tree-sha256-v1"
_TREE_DOMAIN = b"SCROLIQ-TREE-SHA256-V1\0"


class ArtifactHashError(ValueError):
    """Artifact cannot receive a portable package identity."""


def artifact_sha256(path: str | Path) -> str:
    target = Path(path)
    if target.is_symlink():
        raise ArtifactHashError(f"symlink artifacts are not portable: {target}")
    if target.is_file():
        return hashlib.sha256(target.read_bytes()).hexdigest()
    if not target.is_dir():
        raise ArtifactHashError(f"artifact does not exist: {target}")

    files = sorted(
        (p for p in target.rglob("*") if p.is_file() or p.is_symlink()),
        key=lambda p: p.relative_to(target).as_posix(),
    )
    if not files:
        raise ArtifactHashError(f"directory artifact is empty: {target}")

    h = hashlib.sha256()
    h.update(_TREE_DOMAIN)
    for item in files:
        if item.is_symlink():
            raise ArtifactHashError(
                f"directory artifact contains symlink: "
                f"{item.relative_to(target).as_posix()}"
            )
        rel = item.relative_to(target).as_posix().encode("utf-8")
        payload = item.read_bytes()
        digest = hashlib.sha256(payload).digest()
        h.update(len(rel).to_bytes(8, "big"))
        h.update(rel)
        h.update(len(payload).to_bytes(8, "big"))
        h.update(digest)
    return h.hexdigest()
