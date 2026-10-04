#!/usr/bin/env python3
"""Hash the exact bytes of every file in ``scroliq-hf-pin`` snapshots.

A pin proves which Hub tree was observed. It does not prove the bytes a later
campaign step downloads are the bytes the Hub listed. This script closes that
gap for the PHerc1447 v8-in protocol ("download every checkpoint, script,
label, mask and prediction from the resolved commit; hash the local bytes"):

* each file is streamed from the immutable ``resolve/<40-hex sha>/<path>`` URL
  and hashed on the fly, so nothing is written to disk;
* the byte count must equal the size the pin recorded;
* when the Hub exposed a content SHA-256 (Git-LFS files) the streamed digest
  must equal it, otherwise the run fails rather than recording a mismatch as
  evidence;
* a file with no recorded size cannot be checked against the download guard,
  so it is refused (fail closed);
* a repository whose pinned total exceeds the guard is recorded as
  ``blocked_exceeds_guard`` and not downloaded, never silently truncated;
* a repository skipped by policy (for example a training corpus that is not a
  scoring input) is recorded as ``skipped_by_policy`` with its pinned metadata.

The output is create-only and carries no timestamps, so the same pins and the
same bytes always yield the same JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

SCHEMA = "scrollq-hf-byte-inventory/1"
DIGEST_VERSION = "scrollq-hf-byte-inventory-digest-v1"
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
CHUNK_BYTES = 1 << 20
DEFAULT_MAX_REPO_BYTES = 4 * 1024**3
REPO_TYPES = ("model", "dataset")

Fetch = Callable[[str], Iterable[bytes]]


class InventoryError(RuntimeError):
    """Raised when pinned bytes cannot be verified."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pin(path: str | Path) -> tuple[dict[str, Any], str]:
    """Return a validated ``scroliq-hf-pin`` report and its file SHA-256."""
    try:
        pin = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryError(f"cannot read pin {path}: {exc}") from exc
    if not isinstance(pin, dict):
        raise InventoryError(f"{path}: pin must be a JSON object")
    if pin.get("repo_type") not in REPO_TYPES:
        raise InventoryError(f"{path}: repo_type must be one of {REPO_TYPES}")
    repo_id = pin.get("repo_id")
    if not isinstance(repo_id, str) or repo_id.count("/") != 1:
        raise InventoryError(f"{path}: repo_id must be namespace/name")
    revision = pin.get("resolved_revision")
    if not isinstance(revision, str) or not SHA40_RE.fullmatch(revision):
        raise InventoryError(f"{path}: resolved_revision must be a 40-hex sha")
    if pin.get("private") is not False:
        raise InventoryError(f"{repo_id}: pin is not marked public")
    if pin.get("gated") not in (False, None):
        raise InventoryError(f"{repo_id}: gated repositories cannot be fetched anonymously")
    files = pin.get("files")
    if not isinstance(files, list) or not files:
        raise InventoryError(f"{repo_id}: pin has no file inventory")
    seen: set[str] = set()
    for row in files:
        name = row.get("path") if isinstance(row, dict) else None
        if not isinstance(name, str) or not name or name in seen:
            raise InventoryError(f"{repo_id}: invalid or duplicate pinned path {name!r}")
        seen.add(name)
        digest = row.get("content_sha256")
        if digest is not None and not SHA64_RE.fullmatch(str(digest)):
            raise InventoryError(f"{repo_id}:{name}: malformed Hub content_sha256")
    return pin, sha256_file(path)


def resolve_url(pin: dict[str, Any], path: str) -> str:
    kind = "datasets/" if pin["repo_type"] == "dataset" else ""
    return (
        f"https://huggingface.co/{kind}{pin['repo_id']}"
        f"/resolve/{pin['resolved_revision']}/{quote(path, safe='/')}"
    )


def http_fetch(url: str) -> Iterable[bytes]:
    with requests.get(
        url,
        stream=True,
        timeout=(20, 120),
        headers={"User-Agent": "ScrolIQ/0.1 hf-byte-inventory"},
    ) as response:
        response.raise_for_status()
        yield from response.iter_content(CHUNK_BYTES)


def _stream_digest(url: str, fetch: Fetch) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for block in fetch(url):
        digest.update(block)
        count += len(block)
    return digest.hexdigest(), count


def _read_with_retries(
    url: str,
    fetch: Fetch,
    retries: int,
    sleep: Callable[[float], None],
) -> tuple[str, int]:
    for attempt in range(retries + 1):
        try:
            return _stream_digest(url, fetch)
        except (requests.RequestException, OSError) as exc:
            if attempt == retries:
                raise InventoryError(f"cannot read {url}: {exc}") from exc
            sleep(2.0 * (attempt + 1))
    raise AssertionError("unreachable")  # pragma: no cover


def _metadata_row(row: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "path": row["path"],
        "size": row.get("size"),
        "sha256": None,
        "hub_content_sha256": row.get("content_sha256"),
        "hub_sha256_verified": False,
        "status": status,
    }


def _inventory_digest(rows: Sequence[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    digest.update(DIGEST_VERSION.encode("ascii") + b"\0")
    for row in rows:
        digest.update(f"{row['path']}\0{row['size']}\0{row['sha256']}\n".encode())
    return digest.hexdigest()


def inventory_repo(
    pin: dict[str, Any],
    *,
    fetch: Fetch,
    max_repo_bytes: int = DEFAULT_MAX_REPO_BYTES,
    skip_download: bool = False,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    files = sorted(pin["files"], key=lambda row: row["path"])
    out: dict[str, Any] = {
        "repo_type": pin["repo_type"],
        "repo_id": pin["repo_id"],
        "resolved_revision": pin["resolved_revision"],
        "immutable_repo_url": pin.get("immutable_repo_url"),
        "pinned_file_count": len(files),
        "max_repo_bytes": max_repo_bytes,
    }
    if skip_download:
        out.update(
            status="skipped_by_policy",
            total_bytes=None,
            inventory_sha256=None,
            files=[_metadata_row(row, "skipped_by_policy") for row in files],
        )
        return out

    sizes = [row.get("size") for row in files]
    if any(type(size) is not int or size < 0 for size in sizes):
        raise InventoryError(
            f"{pin['repo_id']}: a pinned file has no known size; "
            "the download guard cannot be enforced"
        )
    total = sum(sizes)
    out["total_bytes"] = total
    if total > max_repo_bytes:
        out.update(
            status="blocked_exceeds_guard",
            inventory_sha256=None,
            files=[_metadata_row(row, "blocked_exceeds_guard") for row in files],
        )
        return out

    rows: list[dict[str, Any]] = []
    for row in files:
        name = row["path"]
        sha, count = _read_with_retries(resolve_url(pin, name), fetch, retries, sleep)
        if count != row["size"]:
            raise InventoryError(
                f"{pin['repo_id']}:{name}: read {count} bytes, pin recorded {row['size']}"
            )
        hub = row.get("content_sha256")
        if hub is not None and sha != hub:
            raise InventoryError(
                f"{pin['repo_id']}:{name}: SHA-256 {sha} differs from "
                f"Hub-exposed {hub}"
            )
        rows.append(
            {
                "path": name,
                "size": count,
                "sha256": sha,
                "hub_content_sha256": hub,
                "hub_sha256_verified": hub is not None,
                "status": "hashed",
            }
        )
    out.update(
        status="hashed",
        inventory_sha256=_inventory_digest(rows),
        files=rows,
    )
    return out


def build_inventory(
    pins: Sequence[tuple[str, dict[str, Any], str]],
    *,
    fetch: Fetch,
    skip_download: Sequence[str] = (),
    max_repo_bytes: int = DEFAULT_MAX_REPO_BYTES,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    ids = [pin["repo_id"] for _, pin, _ in pins]
    if len(set(ids)) != len(ids):
        raise InventoryError("the same repository was pinned more than once")
    unknown = sorted(set(skip_download) - set(ids))
    if unknown:
        raise InventoryError(f"--skip-download names unpinned repositories: {unknown}")
    repos = []
    for path, pin, pin_sha in sorted(pins, key=lambda item: item[1]["repo_id"]):
        repo = inventory_repo(
            pin,
            fetch=fetch,
            max_repo_bytes=max_repo_bytes,
            skip_download=pin["repo_id"] in skip_download,
            retries=retries,
            sleep=sleep,
        )
        repo["pin_file"] = Path(path).name
        repo["pin_file_sha256"] = pin_sha
        repos.append(repo)
    return {
        "schema": SCHEMA,
        "repos": repos,
        "summary": {
            "repos": len(repos),
            "hashed": sum(r["status"] == "hashed" for r in repos),
            "skipped_by_policy": sum(r["status"] == "skipped_by_policy" for r in repos),
            "blocked_exceeds_guard": sum(
                r["status"] == "blocked_exceeds_guard" for r in repos
            ),
            "files_hashed": sum(
                len(r["files"]) for r in repos if r["status"] == "hashed"
            ),
            "bytes_hashed": sum(
                r["total_bytes"] for r in repos if r["status"] == "hashed"
            ),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pin", action="append", required=True, help="scroliq-hf-pin JSON")
    parser.add_argument("--out", required=True, help="create-only inventory JSON")
    parser.add_argument("--max-repo-bytes", type=int, default=DEFAULT_MAX_REPO_BYTES)
    parser.add_argument(
        "--skip-download",
        action="append",
        default=[],
        metavar="REPO_ID",
        help="record this pinned repo without downloading (policy skip)",
    )
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists():
        parser.error(f"refusing to overwrite {out}")
    if args.max_repo_bytes <= 0:
        parser.error("--max-repo-bytes must be positive")
    try:
        pins = [(path, *load_pin(path)) for path in args.pin]
        report = build_inventory(
            pins,
            fetch=http_fetch,
            skip_download=args.skip_download,
            max_repo_bytes=args.max_repo_bytes,
        )
    except InventoryError as exc:
        print(json.dumps({"schema": SCHEMA, "status": "invalid", "error": str(exc)}))
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"schema": SCHEMA, **report["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
