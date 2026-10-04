"""Immutable Hugging Face release pinning for external model/dataset evidence.

The Hub's branch names are moving references. Prize evidence must instead bind
the exact repository commit and, where the Hub exposes it, per-file content
identities. This module resolves a requested model/dataset revision through the
public Hugging Face API and writes a deterministic JSON snapshot.

It does not download artifacts and does not claim that a Git blob id is a
SHA-256 of file bytes. Git-LFS SHA-256 values are surfaced only when the API
explicitly provides a 64-hex object id.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote

import requests

SCHEMA_VERSION = 1
TOOL = "scroliq-hf-pin"
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
REPO_TYPES = {"model": "models", "dataset": "datasets"}


class HubPinError(ValueError):
    """Raised when a Hub snapshot cannot be made prize-auditable."""


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HubPinError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_file(row: Mapping[str, Any]) -> dict[str, Any]:
    name = row.get("rfilename", row.get("path"))
    if not isinstance(name, str) or not name:
        raise HubPinError("Hub sibling entry is missing rfilename/path")

    size = row.get("size")
    if size is not None and (type(size) is not int or size < 0):
        raise HubPinError(f"invalid size for {name}")

    blob_id = row.get("blobId", row.get("blob_id"))
    if blob_id is not None and not isinstance(blob_id, str):
        raise HubPinError(f"invalid blob id for {name}")

    content_sha256 = None
    lfs = row.get("lfs")
    if isinstance(lfs, Mapping):
        for key in ("sha256", "oid"):
            value = lfs.get(key)
            if isinstance(value, str):
                candidate = value.removeprefix("sha256:")
                if SHA64_RE.fullmatch(candidate):
                    content_sha256 = candidate
                    break

    return {
        "path": name,
        "size": size,
        "git_blob_id": blob_id,
        "content_sha256": content_sha256,
    }


def pin_repo(
    *,
    repo_id: str,
    repo_type: str,
    revision: str = "main",
    require_files: Sequence[str] = (),
    require_sha256: Sequence[str] = (),
    timeout: float = 20.0,
    request_get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Resolve one Hub revision and return a deterministic immutable snapshot."""
    repo_id = _nonempty(repo_id, "repo_id")
    revision = _nonempty(revision, "revision")
    if not REPO_RE.fullmatch(repo_id):
        raise HubPinError("repo_id must be namespace/name")
    if repo_type not in REPO_TYPES:
        raise HubPinError(f"repo_type must be one of {sorted(REPO_TYPES)}")
    if timeout <= 0:
        raise HubPinError("timeout must be positive")

    kind_path = REPO_TYPES[repo_type]
    encoded_repo = "/".join(quote(part, safe="") for part in repo_id.split("/"))
    encoded_revision = quote(revision, safe="")
    endpoint = (
        f"https://huggingface.co/api/{kind_path}/{encoded_repo}"
        f"/revision/{encoded_revision}"
    )
    get = requests.get if request_get is None else request_get
    try:
        response = get(
            endpoint,
            params={"files_metadata": "true"},
            timeout=timeout,
            headers={"User-Agent": "ScrolIQ/0.1 scroliq-hf-pin"},
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise HubPinError(f"Hub API request failed: {exc}") from exc

    if not isinstance(payload, Mapping):
        raise HubPinError("Hub API response must be an object")
    resolved = payload.get("sha")
    if not isinstance(resolved, str) or not SHA40_RE.fullmatch(resolved):
        raise HubPinError("Hub API response lacks an immutable 40-hex repo sha")

    siblings = payload.get("siblings")
    if not isinstance(siblings, list):
        raise HubPinError("Hub API response lacks file inventory (siblings)")
    files = sorted(
        (_normalize_file(row) for row in siblings if isinstance(row, Mapping)),
        key=lambda row: row["path"],
    )
    if len(files) != len(siblings):
        raise HubPinError("Hub file inventory contains a non-object entry")
    by_path = {row["path"]: row for row in files}
    if len(by_path) != len(files):
        raise HubPinError("Hub file inventory contains duplicate paths")

    missing = sorted(set(require_files) - set(by_path))
    if missing:
        raise HubPinError(f"required Hub files are missing: {missing}")

    no_sha = sorted(
        path
        for path in set(require_sha256)
        if path not in by_path or by_path[path]["content_sha256"] is None
    )
    if no_sha:
        raise HubPinError(
            "required files lack Hub-exposed content SHA-256: "
            f"{no_sha}; download and hash the bytes instead"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "repo_type": repo_type,
        "repo_id": repo_id,
        "requested_revision": revision,
        "resolved_revision": resolved,
        "immutable_repo_url": (
            f"https://huggingface.co/"
            f"{'datasets/' if repo_type == 'dataset' else ''}"
            f"{repo_id}/tree/{resolved}"
        ),
        "api_endpoint": endpoint,
        "last_modified": payload.get("lastModified", payload.get("last_modified")),
        "private": bool(payload.get("private", False)),
        "gated": payload.get("gated", False),
        "files": files,
        "required_files": sorted(set(require_files)),
        "required_sha256_files": sorted(set(require_sha256)),
        "summary": {
            "files": len(files),
            "files_with_content_sha256": sum(
                row["content_sha256"] is not None for row in files
            ),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve a Hugging Face model/dataset revision to an immutable "
            "commit and record its exact file inventory."
        )
    )
    parser.add_argument("--repo", required=True, help="namespace/name")
    parser.add_argument(
        "--repo-type", required=True, choices=sorted(REPO_TYPES)
    )
    parser.add_argument("--revision", default="main")
    parser.add_argument(
        "--require-file",
        action="append",
        default=[],
        help="file that must exist; repeatable",
    )
    parser.add_argument(
        "--require-sha256",
        action="append",
        default=[],
        help=(
            "file that must have an explicit Hub-exposed content SHA-256; "
            "repeatable"
        ),
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    try:
        report = pin_repo(
            repo_id=args.repo,
            repo_type=args.repo_type,
            revision=args.revision,
            require_files=args.require_file,
            require_sha256=args.require_sha256,
            timeout=args.timeout,
        )
    except HubPinError as exc:
        parser.error(str(exc))

    out = Path(args.out)
    if out.exists():
        parser.error(f"refusing to overwrite existing output: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
