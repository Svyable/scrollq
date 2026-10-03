"""Deterministic SHA-256 digests for submission package paths.

Regular files use the ordinary SHA-256 of their bytes. Directory-format
artifacts (notably VC3D TIFXYZ surfaces) use a canonical tree digest so the
manifest can bind the complete artifact without first repacking it.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

TREE_HASH_VERSION = "scroliq-directory-sha256-v1"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_path(path: str | Path) -> str:
    """Return a deterministic SHA-256 for a regular file or directory tree.

    File digests are standard SHA-256. Directory digests are SHA-256 over a
    versioned, lexicographically sorted stream of relative POSIX paths. Every
    directory entry is tagged as a directory or regular file; file entries also
    include their byte length and ordinary SHA-256. Symlinks and special files
    are rejected so a digest cannot silently depend on host filesystem state.
    """

    root = Path(path)
    if root.is_symlink():
        raise ValueError(f"symlinks are not supported: {root}")
    if root.is_file():
        return _file_sha256(root)
    if not root.is_dir():
        raise FileNotFoundError(root)

    digest = hashlib.sha256()
    digest.update(TREE_HASH_VERSION.encode("ascii") + b"\0")

    entries = sorted(
        root.rglob("*"),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    for item in entries:
        rel = item.relative_to(root).as_posix().encode("utf-8")
        if item.is_symlink():
            raise ValueError(f"symlinks are not supported: {item}")
        if item.is_dir():
            digest.update(b"D\0" + rel + b"\0")
            continue
        if not item.is_file():
            raise ValueError(f"unsupported filesystem entry: {item}")

        size = item.stat().st_size
        digest.update(b"F\0" + rel + b"\0")
        digest.update(str(size).encode("ascii") + b"\0")
        digest.update(bytes.fromhex(_file_sha256(item)))

    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute ScrolIQ submission SHA-256 digests for files or "
            "directory-format artifacts such as column_NN.tifxyz"
        )
    )
    parser.add_argument("paths", nargs="+", help="file or directory paths to hash")
    args = parser.parse_args()

    failed = False
    for raw in args.paths:
        try:
            digest = sha256_path(raw)
        except (OSError, ValueError) as exc:
            failed = True
            print(f"scroliq-hash: {raw}: {exc}", file=sys.stderr)
            continue
        print(f"{digest}  {raw}")

    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
