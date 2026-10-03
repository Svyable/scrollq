"""Deterministic Grand Prize submission package builder and verifier.

The package builder is deliberately downstream of scroliq-provenance:
nothing is archived unless the exact manifest passes the fail-closed Grand
Prize provenance gate against the package root.

Archive contract v1:
- ZIP_STORED (no compressor-version dependence)
- fixed member timestamps and POSIX file mode
- lexicographically sorted member paths
- no symlinks or special filesystem entries
- only manifest-declared local artifacts plus generated ScrolIQ evidence
- an embedded per-file SHA-256/size inventory
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .legibility import LEGIBILITY_THRESHOLD, audit_legibility
from .provenance import validate_manifest
from .submission_image import (
    SCHEMA_VERSION as SUBMISSION_IMAGE_SCHEMA_VERSION,
    TOOL as SUBMISSION_IMAGE_TOOL,
)
from .vc3d_replay import VC3D_RECEIPT_SCHEMA_VERSION, VC3D_RECEIPT_TOOL

PACKAGE_SCHEMA_VERSION = 4
PACKAGE_TOOL = "scroliq-package"
ARCHIVE_FORMAT = "zip-stored-deterministic-v1"
INDEX_PATH = "_scroliq/submission-package.json"
VALIDATION_PATH = "_scroliq/provenance.validation.json"
REVIEWER_CONTRACT_PATH = "_scroliq/reviewer-contract.json"
LEGIBILITY_VALIDATION_PATH = "_scroliq/legibility.validation.json"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644


class PackageError(ValueError):
    """The submission package cannot be built or verified safely."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_rel(raw: str, *, allow_reserved: bool = False) -> str:
    if not isinstance(raw, str) or not raw:
        raise PackageError("package path must be a non-empty string")
    if "\\" in raw:
        raise PackageError(f"package path must use '/' separators: {raw!r}")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PackageError(f"unsafe package-relative path: {raw!r}")
    normal = path.as_posix()
    if (not allow_reserved) and (
        normal == INDEX_PATH
        or normal == VALIDATION_PATH
        or normal.startswith("_scroliq/")
    ):
        raise PackageError(f"manifest artifact collides with reserved path: {normal}")
    return normal


def _declared_paths(manifest: dict[str, Any]) -> list[str]:
    """Return all package-local artifact paths declared by provenance."""
    raw: list[str] = []
    ct = manifest.get("ct_volume")
    if isinstance(ct, dict):
        audit = ct.get("zarr_audit")
        if isinstance(audit, dict) and isinstance(audit.get("path"), str):
            raw.append(audit["path"])

    for key in ("surfaces", "meshes", "renders", "held_out_validations"):
        rows = manifest.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("path"), str):
                raw.append(row["path"])
            if key == "renders" and isinstance(row, dict):
                scale_proof = row.get("scale_proof")
                if (
                    isinstance(scale_proof, dict)
                    and isinstance(scale_proof.get("path"), str)
                ):
                    raw.append(scale_proof["path"])
                vc3d_receipt = row.get("vc3d_receipt")
                if (
                    isinstance(vc3d_receipt, dict)
                    and isinstance(vc3d_receipt.get("path"), str)
                ):
                    raw.append(vc3d_receipt["path"])

    banner = manifest.get("banner")
    if isinstance(banner, dict) and isinstance(banner.get("path"), str):
        raw.append(banner["path"])
        proof = banner.get("proof")
        if isinstance(proof, dict) and isinstance(proof.get("path"), str):
            raw.append(proof["path"])

    return sorted(set(_normalise_rel(path) for path in raw))


def _vc3d_package_records(
    manifest: dict[str, Any],
    root: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load verified VC3D receipts and return index records + raw/log paths."""

    rows = manifest.get("renders")
    if not isinstance(rows, list) or not rows:
        raise PackageError("renders must contain VC3D receipt-bound columns")

    records: list[dict[str, Any]] = []
    extra_paths: list[str] = []
    seen_columns: set[int] = set()
    seen_assets: set[str] = set()

    for i, render in enumerate(rows):
        if not isinstance(render, dict):
            raise PackageError(f"renders[{i}] must be an object")
        column = render.get("column")
        if isinstance(column, bool) or not isinstance(column, int) or column < 1:
            raise PackageError(f"renders[{i}].column must be a positive integer")
        if column in seen_columns:
            raise PackageError(f"duplicate VC3D receipt column {column}")
        seen_columns.add(column)

        declared = render.get("vc3d_receipt")
        if not isinstance(declared, dict):
            raise PackageError(f"renders[{i}] is missing vc3d_receipt")
        receipt_rel = _normalise_rel(declared.get("path"))
        receipt_path = _path_under_root(root, receipt_rel)
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise PackageError(f"VC3D receipt must be a regular file: {receipt_rel}")
        receipt_raw = receipt_path.read_bytes()
        receipt_sha = _sha256(receipt_raw)
        if receipt_sha != declared.get("sha256"):
            raise PackageError(f"VC3D receipt hash mismatch: {receipt_rel}")
        try:
            receipt = json.loads(receipt_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackageError(f"cannot parse VC3D receipt {receipt_rel}: {exc}") from exc
        if not isinstance(receipt, dict):
            raise PackageError(f"VC3D receipt must be an object: {receipt_rel}")
        if (
            receipt.get("schema_version") != VC3D_RECEIPT_SCHEMA_VERSION
            or receipt.get("tool") != VC3D_RECEIPT_TOOL
            or receipt.get("operation") != "render-column"
            or receipt.get("column") != column
        ):
            raise PackageError(f"unsupported/mismatched VC3D receipt: {receipt_rel}")
        if receipt.get("receipt_path") != receipt_rel:
            raise PackageError(f"VC3D receipt_path mismatch: {receipt_rel}")

        output = receipt.get("output")
        log = receipt.get("log")
        if not isinstance(output, dict) or not isinstance(log, dict):
            raise PackageError(f"VC3D receipt lacks output/log records: {receipt_rel}")
        raw_rel = _normalise_rel(output.get("path"))
        log_rel = _normalise_rel(log.get("path"))
        render_call = receipt.get("render")
        if not isinstance(render_call, dict):
            raise PackageError(f"VC3D receipt lacks render record: {receipt_rel}")
        tif_dir = _normalise_rel(render_call.get("tif_output_dir"))
        if raw_rel != (PurePosixPath(tif_dir) / "00.tif").as_posix():
            raise PackageError(
                f"VC3D receipt raw output is not tif_output_dir/00.tif: {receipt_rel}"
            )

        for rel, item, label in (
            (raw_rel, output, "raw render"),
            (log_rel, log, "render log"),
        ):
            target = _path_under_root(root, rel)
            if target.is_symlink() or not target.is_file():
                raise PackageError(f"VC3D {label} must be a regular file: {rel}")
            actual_sha = _sha256_file(target)
            if actual_sha != item.get("sha256"):
                raise PackageError(f"VC3D {label} hash mismatch: {rel}")
            if target.stat().st_size != item.get("size"):
                raise PackageError(f"VC3D {label} size mismatch: {rel}")
            if rel in seen_assets:
                raise PackageError(f"VC3D artifact reused across columns: {rel}")
            seen_assets.add(rel)
            extra_paths.append(rel)

        scale = render.get("scale_proof")
        if not isinstance(scale, dict):
            raise PackageError(f"renders[{i}] is missing scale_proof")
        scale_rel = _normalise_rel(scale.get("path"))

        inputs = receipt.get("inputs")
        receipt_mesh = inputs.get("mesh") if isinstance(inputs, dict) else None
        vc3d = receipt.get("vc3d")
        binary = vc3d.get("binary") if isinstance(vc3d, dict) else None
        records.append(
            {
                "column": column,
                "receipt_path": receipt_rel,
                "receipt_sha256": receipt_sha,
                "raw_render_path": raw_rel,
                "raw_render_sha256": output.get("sha256"),
                "log_path": log_rel,
                "log_sha256": log.get("sha256"),
                "scale_proof_path": scale_rel,
                "mesh_path": (
                    receipt_mesh.get("path")
                    if isinstance(receipt_mesh, dict)
                    else None
                ),
                "mesh_sha256": (
                    receipt_mesh.get("sha256")
                    if isinstance(receipt_mesh, dict)
                    else None
                ),
                "villa_commit": (
                    vc3d.get("commit") if isinstance(vc3d, dict) else None
                ),
                "binary_sha256": (
                    binary.get("sha256") if isinstance(binary, dict) else None
                ),
            }
        )

    records.sort(key=lambda row: row["column"])
    return records, sorted(set(extra_paths))


def _numbers_match(left: Any, right: Any, *, abs_tol: float = 1e-9) -> bool:
    if (
        isinstance(left, bool)
        or isinstance(right, bool)
        or not isinstance(left, (int, float))
        or not isinstance(right, (int, float))
    ):
        return left == right
    return abs(float(left) - float(right)) <= max(
        abs_tol,
        1e-9 * max(abs(float(left)), abs(float(right)), 1.0),
    )


def _verify_embedded_vc3d_bindings(
    zf: zipfile.ZipFile,
    *,
    manifest: dict[str, Any] | None,
    index: dict[str, Any],
    actual_names: set[str],
    verified_hashes: dict[str, str],
    errors: list[str],
) -> None:
    """Recompute VC3D receipt/raw/log/scale bindings from archive contents."""

    indexed = index.get("vc3d_receipts")
    if not isinstance(indexed, list) or not indexed:
        errors.append("package index vc3d_receipts must be a non-empty list")
        indexed = []
    if not isinstance(manifest, dict):
        errors.append("cannot verify VC3D bindings without embedded manifest")
        return

    renders = manifest.get("renders")
    meshes_raw = manifest.get("meshes")
    submission = manifest.get("submission")
    if not isinstance(renders, list) or not isinstance(meshes_raw, list):
        errors.append("embedded manifest lacks render/mesh records for VC3D binding")
        return
    meshes = {
        row.get("id"): row
        for row in meshes_raw
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    eligible_volume_id = (
        submission.get("eligible_volume_id")
        if isinstance(submission, dict)
        else None
    )

    recomputed: list[dict[str, Any]] = []
    for i, render in enumerate(renders):
        if not isinstance(render, dict):
            errors.append(f"embedded renders[{i}] is not an object")
            continue
        column = render.get("column")
        declared = render.get("vc3d_receipt")
        scale_decl = render.get("scale_proof")
        if not isinstance(declared, dict) or not isinstance(scale_decl, dict):
            errors.append(f"column {column}: missing VC3D receipt or scale proof")
            continue
        try:
            receipt_rel = _normalise_rel(declared.get("path"))
            scale_rel = _normalise_rel(scale_decl.get("path"))
        except PackageError as exc:
            errors.append(f"column {column}: {exc}")
            continue
        if receipt_rel not in actual_names:
            errors.append(f"column {column}: VC3D receipt missing from archive")
            continue
        if verified_hashes.get(receipt_rel) != declared.get("sha256"):
            errors.append(f"column {column}: VC3D receipt hash differs from manifest")

        try:
            receipt = json.loads(zf.read(receipt_rel))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"column {column}: cannot parse VC3D receipt: {exc}")
            continue
        if not isinstance(receipt, dict):
            errors.append(f"column {column}: VC3D receipt is not an object")
            continue
        if (
            receipt.get("schema_version") != VC3D_RECEIPT_SCHEMA_VERSION
            or receipt.get("tool") != VC3D_RECEIPT_TOOL
            or receipt.get("operation") != "render-column"
            or receipt.get("column") != column
            or receipt.get("receipt_path") != receipt_rel
        ):
            errors.append(f"column {column}: unsupported/mismatched VC3D receipt")

        inputs = receipt.get("inputs")
        volume = inputs.get("volume") if isinstance(inputs, dict) else None
        receipt_mesh = inputs.get("mesh") if isinstance(inputs, dict) else None
        if not isinstance(volume, dict) or not isinstance(receipt_mesh, dict):
            errors.append(f"column {column}: VC3D receipt input records are missing")
            continue
        if volume.get("volume_id") != eligible_volume_id:
            errors.append(f"column {column}: VC3D receipt uses another eligible volume")

        mesh = meshes.get(render.get("mesh_id"))
        if not isinstance(mesh, dict):
            errors.append(f"column {column}: referenced mesh is missing")
        else:
            if receipt_mesh.get("path") != mesh.get("path"):
                errors.append(f"column {column}: VC3D receipt mesh path mismatch")
            if receipt_mesh.get("sha256") != mesh.get("sha256"):
                errors.append(f"column {column}: VC3D receipt mesh hash mismatch")

        render_call = receipt.get("render")
        output = receipt.get("output")
        log = receipt.get("log")
        if (
            not isinstance(render_call, dict)
            or not isinstance(output, dict)
            or not isinstance(log, dict)
        ):
            errors.append(f"column {column}: VC3D receipt render/output/log is missing")
            continue
        if render_call.get("num_slices") != 1 or render_call.get("exit_code") != 0:
            errors.append(f"column {column}: VC3D receipt is not one successful slice")
        try:
            raw_rel = _normalise_rel(output.get("path"))
            log_rel = _normalise_rel(log.get("path"))
            tif_dir = _normalise_rel(render_call.get("tif_output_dir"))
        except PackageError as exc:
            errors.append(f"column {column}: {exc}")
            continue
        if raw_rel != (PurePosixPath(tif_dir) / "00.tif").as_posix():
            errors.append(f"column {column}: raw VC3D path is not tif_output_dir/00.tif")
        for rel, item, label in (
            (raw_rel, output, "raw VC3D render"),
            (log_rel, log, "VC3D render log"),
        ):
            if rel not in actual_names:
                errors.append(f"column {column}: {label} is missing from archive")
            elif verified_hashes.get(rel) != item.get("sha256"):
                errors.append(f"column {column}: {label} hash mismatch")

        if scale_rel not in actual_names:
            errors.append(f"column {column}: scale proof is missing from archive")
            scale_proof = None
        else:
            if verified_hashes.get(scale_rel) != scale_decl.get("sha256"):
                errors.append(f"column {column}: scale proof hash differs from manifest")
            try:
                scale_proof = json.loads(zf.read(scale_rel))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"column {column}: cannot parse scale proof: {exc}")
                scale_proof = None
        if isinstance(scale_proof, dict):
            if (
                scale_proof.get("schema_version") != SUBMISSION_IMAGE_SCHEMA_VERSION
                or scale_proof.get("tool") != SUBMISSION_IMAGE_TOOL
                or scale_proof.get("operation") != "column"
                or scale_proof.get("column") != column
            ):
                errors.append(f"column {column}: unsupported/mismatched scale proof")
            scale_input = scale_proof.get("input")
            physical = scale_proof.get("vc_render_tifxyz")
            if not isinstance(scale_input, dict) or not isinstance(physical, dict):
                errors.append(f"column {column}: scale proof input/physical record missing")
            else:
                if scale_input.get("sha256") != output.get("sha256"):
                    errors.append(
                        f"column {column}: scale proof input hash differs from raw VC3D render"
                    )
                if scale_input.get("path") != PurePosixPath(raw_rel).name:
                    errors.append(
                        f"column {column}: scale proof input name differs from raw VC3D render"
                    )
                checks = (
                    (
                        volume.get("base_voxel_size_um"),
                        scale_decl.get("base_voxel_size_um"),
                        physical.get("base_voxel_size_um"),
                        "base voxel size",
                    ),
                    (
                        render_call.get("group_idx"),
                        scale_decl.get("group_idx"),
                        physical.get("group_idx"),
                        "group index",
                    ),
                    (
                        render_call.get("scale"),
                        scale_decl.get("render_scale"),
                        physical.get("render_scale"),
                        "render scale",
                    ),
                )
                for receipt_value, manifest_value, proof_value, label in checks:
                    if not (
                        _numbers_match(receipt_value, manifest_value, abs_tol=1e-6)
                        and _numbers_match(receipt_value, proof_value, abs_tol=1e-6)
                    ):
                        errors.append(
                            f"column {column}: VC3D/manifest/scale-proof {label} mismatch"
                        )

        vc3d = receipt.get("vc3d")
        binary = vc3d.get("binary") if isinstance(vc3d, dict) else None
        recomputed.append(
            {
                "column": column,
                "receipt_path": receipt_rel,
                "receipt_sha256": verified_hashes.get(receipt_rel),
                "raw_render_path": raw_rel,
                "raw_render_sha256": verified_hashes.get(raw_rel),
                "log_path": log_rel,
                "log_sha256": verified_hashes.get(log_rel),
                "scale_proof_path": scale_rel,
                "mesh_path": receipt_mesh.get("path"),
                "mesh_sha256": receipt_mesh.get("sha256"),
                "villa_commit": (
                    vc3d.get("commit") if isinstance(vc3d, dict) else None
                ),
                "binary_sha256": (
                    binary.get("sha256") if isinstance(binary, dict) else None
                ),
            }
        )

    recomputed.sort(key=lambda row: row.get("column", -1))
    normalized_indexed = sorted(
        [row for row in indexed if isinstance(row, dict)],
        key=lambda row: row.get("column", -1),
    )
    if recomputed != normalized_indexed:
        errors.append("package VC3D receipt index does not match embedded artifacts")


def _path_under_root(root: Path, rel: str) -> Path:
    target = root / rel
    resolved = target.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PackageError(f"path escapes package root: {rel}") from exc
    return target


def _iter_files(root: Path, rel: str) -> Iterable[tuple[str, Path]]:
    """Expand one declared file or directory to archive file members."""
    target = _path_under_root(root, rel)
    if target.is_symlink():
        raise PackageError(f"symlink is not permitted in submission package: {rel}")
    if not target.exists():
        raise PackageError(f"declared artifact is missing: {rel}")
    if target.is_file():
        mode = target.stat().st_mode
        if not stat.S_ISREG(mode):
            raise PackageError(f"unsupported filesystem entry: {rel}")
        yield rel, target
        return
    if not target.is_dir():
        raise PackageError(f"unsupported filesystem entry: {rel}")

    found = False
    for item in sorted(
        target.rglob("*"),
        key=lambda p: p.relative_to(root).as_posix(),
    ):
        member = item.relative_to(root).as_posix()
        if item.is_symlink():
            raise PackageError(
                f"symlink is not permitted in submission package: {member}"
            )
        if item.is_dir():
            continue
        if not item.is_file() or not stat.S_ISREG(item.stat().st_mode):
            raise PackageError(f"unsupported filesystem entry: {member}")
        found = True
        yield member, item
    if not found:
        raise PackageError(f"declared artifact directory is empty: {rel}")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (FILE_MODE & 0xFFFF) << 16
    return info


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _manifest_relative_path(manifest_path: Path, root: Path) -> str:
    resolved = manifest_path.resolve()
    try:
        rel = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise PackageError("manifest must live inside --root-dir") from exc
    return _normalise_rel(rel)


def _reviewer_text_file(
    root: Path,
    raw_path: str,
    *,
    label: str,
) -> tuple[str, Path, dict[str, Any]]:
    rel = _normalise_rel(raw_path)
    target = _path_under_root(root, rel)
    if target.is_symlink():
        raise PackageError(f"{label} may not be a symlink: {rel}")
    if not target.is_file() or not stat.S_ISREG(target.stat().st_mode):
        raise PackageError(f"{label} must be a regular file: {rel}")
    raw = target.read_bytes()
    if not raw:
        raise PackageError(f"{label} must not be empty: {rel}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackageError(f"{label} must be UTF-8 text: {rel}") from exc
    if not text.strip():
        raise PackageError(f"{label} must contain non-whitespace text: {rel}")
    return rel, target, {
        "path": rel,
        "size": len(raw),
        "sha256": _sha256(raw),
    }


def _human_input_ledger(
    root: Path,
    raw_path: str,
    *,
    declared_hours: Any,
) -> tuple[str, Path, dict[str, Any]]:
    rel = _normalise_rel(raw_path)
    target = _path_under_root(root, rel)
    if target.is_symlink():
        raise PackageError(f"human input log may not be a symlink: {rel}")
    if not target.is_file() or not stat.S_ISREG(target.stat().st_mode):
        raise PackageError(f"human input log must be a regular JSON file: {rel}")
    raw = target.read_bytes()
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"cannot parse human input log {rel}: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise PackageError("human input log must be a schema_version=1 JSON object")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise PackageError("human input log entries must be a list")
    total = 0.0
    for i, row in enumerate(entries):
        if not isinstance(row, dict):
            raise PackageError(f"human input log entry {i} must be an object")
        description = row.get("description")
        hours = row.get("hours")
        if not isinstance(description, str) or not description.strip():
            raise PackageError(
                f"human input log entry {i} needs a non-empty description"
            )
        if (
            isinstance(hours, bool)
            or not isinstance(hours, (int, float))
            or float(hours) < 0
        ):
            raise PackageError(
                f"human input log entry {i} hours must be a non-negative number"
            )
        total += float(hours)
    if total > 8.0 + 1e-9:
        raise PackageError(
            f"human input log totals {total:g} hours; Grand Prize limit is 8"
        )
    if (
        isinstance(declared_hours, bool)
        or not isinstance(declared_hours, (int, float))
    ):
        raise PackageError(
            "provenance submission.human_input_hours must be numeric"
        )
    if abs(total - float(declared_hours)) > 1e-9:
        raise PackageError(
            "human input log total does not match "
            f"submission.human_input_hours ({total:g} != {float(declared_hours):g})"
        )
    return rel, target, {
        "path": rel,
        "size": len(raw),
        "sha256": _sha256(raw),
        "entry_count": len(entries),
        "total_hours": total,
    }


def _legibility_ledger(
    root: Path,
    raw_path: str,
    *,
    manifest: dict[str, Any],
    manifest_sha256: str,
) -> tuple[str, Path, dict[str, Any], dict[str, Any]]:
    rel = _normalise_rel(raw_path)
    target = _path_under_root(root, rel)
    if target.is_symlink():
        raise PackageError(f"legibility ledger may not be a symlink: {rel}")
    if not target.is_file() or not stat.S_ISREG(target.stat().st_mode):
        raise PackageError(f"legibility ledger must be a regular JSON file: {rel}")
    raw = target.read_bytes()
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"cannot parse legibility ledger {rel}: {exc}") from exc
    if not isinstance(document, dict):
        raise PackageError("legibility ledger must be a JSON object")

    ledger_sha = _sha256(raw)
    validation = audit_legibility(
        manifest,
        document,
        manifest_sha256=manifest_sha256,
        ledger_sha256=ledger_sha,
    )
    if validation.get("passes_recorded_thresholds") is not True:
        codes = sorted(
            {
                str(item.get("code"))
                for item in validation.get("errors", [])
                if isinstance(item, dict)
            }
        )
        detail = ", ".join(codes[:8]) or "unknown legibility error"
        raise PackageError(
            f"Grand Prize legibility gate failed; package not built ({detail})"
        )
    return rel, target, {
        "path": rel,
        "size": len(raw),
        "sha256": ledger_sha,
    }, validation


def _manifest_columns(manifest: dict[str, Any], key: str) -> list[int]:
    rows = manifest.get(key)
    if not isinstance(rows, list) or not rows:
        raise PackageError(f"{key} must contain numbered submission artifacts")
    numbers: list[int] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PackageError(f"{key}[{i}] must be an object")
        value = row.get("column")
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise PackageError(f"{key}[{i}].column must be a positive integer")
        numbers.append(value)
    numbers.sort()
    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        raise PackageError(
            f"{key} columns must be consecutive starting at 1; "
            f"observed={numbers}, expected={expected}"
        )
    return numbers


def _build_reviewer_contract(
    manifest: dict[str, Any],
    root: Path,
    *,
    methodology_path: str,
    system_requirements_path: str,
    human_input_log_path: str,
    vc3d_workflow_path: str,
    false_positive_mitigation_path: str,
    docker_run_command: str | None,
) -> tuple[dict[str, Any], dict[str, Path]]:
    materials: dict[str, dict[str, Any]] = {}
    sources: dict[str, Path] = {}
    for key, raw_path, label in (
        ("methodology", methodology_path, "methodology"),
        ("system_requirements", system_requirements_path, "system requirements"),
        ("vc3d_workflow", vc3d_workflow_path, "VC3D workflow"),
        (
            "false_positive_mitigation",
            false_positive_mitigation_path,
            "false-positive mitigation",
        ),
    ):
        rel, target, info = _reviewer_text_file(root, raw_path, label=label)
        materials[key] = info
        sources[rel] = target

    submission = manifest.get("submission")
    if not isinstance(submission, dict):
        submission = {}
    rel, target, human = _human_input_ledger(
        root,
        human_input_log_path,
        declared_hours=submission.get("human_input_hours"),
    )
    materials["human_input_log"] = {
        key: value
        for key, value in human.items()
        if key in {"path", "size", "sha256"}
    }
    sources[rel] = target

    code = manifest.get("code")
    if not isinstance(code, dict):
        code = {}
    docker_image = code.get("docker_image")
    if not isinstance(docker_image, str) or "@sha256:" not in docker_image:
        raise PackageError("manifest must pin code.docker_image by sha256 digest")
    if docker_run_command is None:
        docker_run_command = f"docker run --rm {docker_image}"
    if not isinstance(docker_run_command, str) or not docker_run_command.strip():
        raise PackageError("docker run command must be non-empty")
    if docker_image not in docker_run_command:
        raise PackageError(
            "docker run command must invoke the exact digest-pinned "
            "code.docker_image from the provenance manifest"
        )

    mesh_columns = _manifest_columns(manifest, "meshes")
    render_columns = _manifest_columns(manifest, "renders")
    if mesh_columns != render_columns:
        raise PackageError(
            "mesh and render column sequences differ in the final reviewer package"
        )

    return {
        "schema_version": 2,
        "tool": PACKAGE_TOOL,
        "materials": materials,
        "reproduction": {
            "docker_image": docker_image,
            "docker_run_command": docker_run_command.strip(),
        },
        "human_input": {
            "declared_hours": float(submission["human_input_hours"]),
            "ledger_hours": human["total_hours"],
            "entry_count": human["entry_count"],
        },
        "columns": {
            "meshes": mesh_columns,
            "renders": render_columns,
        },
    }, sources


def build_package(
    *,
    manifest_path: str | Path,
    root_dir: str | Path,
    out_path: str | Path,
    methodology_path: str = "METHODOLOGY.md",
    system_requirements_path: str = "SYSTEM_REQUIREMENTS.md",
    human_input_log_path: str = "human-input.json",
    vc3d_workflow_path: str = "VC3D_WORKFLOW.md",
    false_positive_mitigation_path: str = "FALSE_POSITIVES.md",
    legibility_ledger_path: str = "legibility.json",
    docker_run_command: str | None = None,
) -> dict[str, Any]:
    """Validate provenance and build one deterministic reviewer package."""
    manifest_path = Path(manifest_path)
    root = Path(root_dir)
    out = Path(out_path)

    if not root.is_dir():
        raise PackageError(f"package root is not a directory: {root}")
    if out.suffix.lower() != ".zip":
        raise PackageError("--out must end in .zip")
    sidecar = out.with_name(out.name + ".sha256")
    if out.exists() or sidecar.exists():
        raise PackageError("refusing to overwrite existing archive or sha256 sidecar")

    if manifest_path.is_symlink():
        raise PackageError("provenance manifest may not be a symlink")
    manifest_raw = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"cannot parse provenance manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PackageError("provenance manifest must be a JSON object")

    manifest_rel = _manifest_relative_path(manifest_path, root)
    manifest_sha = _sha256(manifest_raw)
    validation = validate_manifest(
        manifest, root_dir=root, manifest_sha256=manifest_sha
    )
    if validation.get("eligible") is not True:
        codes = sorted(
            {
                str(item.get("code"))
                for item in validation.get("errors", [])
                if isinstance(item, dict)
            }
        )
        detail = ", ".join(codes[:8]) or "unknown provenance error"
        raise PackageError(
            f"Grand Prize provenance gate failed; package not built ({detail})"
        )

    reviewer_contract, reviewer_sources = _build_reviewer_contract(
        manifest,
        root,
        methodology_path=methodology_path,
        system_requirements_path=system_requirements_path,
        human_input_log_path=human_input_log_path,
        vc3d_workflow_path=vc3d_workflow_path,
        false_positive_mitigation_path=false_positive_mitigation_path,
        docker_run_command=docker_run_command,
    )
    (
        legibility_rel,
        legibility_source,
        legibility_info,
        legibility_validation,
    ) = _legibility_ledger(
        root,
        legibility_ledger_path,
        manifest=manifest,
        manifest_sha256=manifest_sha,
    )
    if legibility_rel in reviewer_sources:
        raise PackageError(
            f"legibility ledger collides with reviewer material: {legibility_rel}"
        )
    reviewer_sources[legibility_rel] = legibility_source
    reviewer_contract["materials"]["legibility_ledger"] = legibility_info
    reviewer_contract["legibility"] = {
        "validation_path": LEGIBILITY_VALIDATION_PATH,
        "threshold": LEGIBILITY_THRESHOLD,
        "counted_columns": legibility_validation["summary"]["counted_columns"],
        "excluded_columns": legibility_validation["summary"]["excluded_columns"],
    }

    vc3d_records, vc3d_extra_paths = _vc3d_package_records(manifest, root)
    declared = sorted(set(_declared_paths(manifest) + vc3d_extra_paths))
    if manifest_rel in declared:
        declared.remove(manifest_rel)

    members: dict[str, Path | bytes] = {manifest_rel: manifest_raw}
    for rel, source in reviewer_sources.items():
        if rel == manifest_rel or rel in declared:
            raise PackageError(
                f"reviewer material path collides with a manifest artifact: {rel}"
            )
        members[rel] = source
    for rel in declared:
        for member, source in _iter_files(root, rel):
            if member in members:
                raise PackageError(f"duplicate archive member: {member}")
            members[member] = source

    validation_bytes = _json_bytes(validation)
    members[VALIDATION_PATH] = validation_bytes
    reviewer_contract_bytes = _json_bytes(reviewer_contract)
    members[REVIEWER_CONTRACT_PATH] = reviewer_contract_bytes
    legibility_validation_bytes = _json_bytes(legibility_validation)
    members[LEGIBILITY_VALIDATION_PATH] = legibility_validation_bytes

    inventory: list[dict[str, Any]] = []
    for member in sorted(members):
        source = members[member]
        if isinstance(source, bytes):
            payload_sha = _sha256(source)
            size = len(source)
        else:
            payload_sha = _sha256_file(source)
            size = source.stat().st_size
        inventory.append({"path": member, "size": int(size), "sha256": payload_sha})

    index = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "tool": PACKAGE_TOOL,
        "archive_format": ARCHIVE_FORMAT,
        "manifest_path": manifest_rel,
        "manifest_sha256": manifest_sha,
        "validation_path": VALIDATION_PATH,
        "validation_sha256": _sha256(validation_bytes),
        "reviewer_contract_path": REVIEWER_CONTRACT_PATH,
        "reviewer_contract_sha256": _sha256(reviewer_contract_bytes),
        "legibility_ledger_path": legibility_rel,
        "legibility_ledger_sha256": legibility_info["sha256"],
        "legibility_validation_path": LEGIBILITY_VALIDATION_PATH,
        "legibility_validation_sha256": _sha256(legibility_validation_bytes),
        "graph_sha256": validation.get("graph_sha256"),
        "vc3d_receipts": vc3d_records,
        "file_count": len(inventory),
        "files": inventory,
    }
    index_bytes = _json_bytes(index)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    try:
        with zipfile.ZipFile(
            tmp, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True
        ) as zf:
            archive_members: dict[str, Path | bytes] = dict(members)
            archive_members[INDEX_PATH] = index_bytes
            for member in sorted(archive_members):
                source = archive_members[member]
                info = _zip_info(member)
                if isinstance(source, bytes):
                    zf.writestr(info, source)
                    continue
                with source.open("rb") as src, zf.open(
                    info, mode="w", force_zip64=True
                ) as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()

    verification = verify_package(out)
    if verification.get("valid") is not True:
        out.unlink(missing_ok=True)
        raise PackageError(
            "self-verification of the newly built archive failed: "
            + "; ".join(verification.get("errors", [])[:4])
        )

    archive_sha = verification["archive_sha256"]
    sidecar.write_text(
        f"{archive_sha}  {out.name}\n", encoding="utf-8", newline="\n"
    )

    return {
        "archive": str(out),
        "archive_sha256": archive_sha,
        "sha256_sidecar": str(sidecar),
        "graph_sha256": validation.get("graph_sha256"),
        "manifest_sha256": manifest_sha,
        "file_count": len(inventory),
        "index": index,
    }


def _zip_member_sha256(zf: zipfile.ZipFile, name: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with zf.open(name, "r") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def verify_package(archive_path: str | Path) -> dict[str, Any]:
    """Verify deterministic-package structure and every embedded file hash."""
    archive = Path(archive_path)
    errors: list[str] = []
    try:
        archive_sha = _sha256_file(archive)
    except OSError as exc:
        return {
            "valid": False,
            "archive_sha256": None,
            "errors": [f"cannot read archive: {exc}"],
        }

    try:
        with zipfile.ZipFile(archive, "r") as zf:
            names = zf.namelist()
            if len(names) != len(set(names)):
                errors.append("archive contains duplicate member names")
            if names != sorted(names):
                errors.append("archive members are not in deterministic lexicographic order")
            if INDEX_PATH not in names:
                errors.append(f"archive is missing {INDEX_PATH}")
                return {
                    "valid": False,
                    "archive_sha256": archive_sha,
                    "errors": errors,
                }
            index_info = zf.getinfo(INDEX_PATH)
            if index_info.compress_type != zipfile.ZIP_STORED:
                errors.append(f"{INDEX_PATH}: member is not ZIP_STORED")
            if index_info.date_time != FIXED_ZIP_TIME:
                errors.append(f"{INDEX_PATH}: timestamp is not deterministic")
            if (index_info.external_attr >> 16) != FILE_MODE:
                errors.append(f"{INDEX_PATH}: POSIX file mode is not deterministic")
            try:
                index = json.loads(zf.read(INDEX_PATH))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"cannot parse package index: {exc}")
                return {
                    "valid": False,
                    "archive_sha256": archive_sha,
                    "errors": errors,
                }

            if not isinstance(index, dict):
                errors.append("package index must be a JSON object")
                return {
                    "valid": False,
                    "archive_sha256": archive_sha,
                    "errors": errors,
                }
            if index.get("schema_version") != PACKAGE_SCHEMA_VERSION:
                errors.append(
                    f"unsupported package schema {index.get('schema_version')!r}"
                )
            if index.get("tool") != PACKAGE_TOOL:
                errors.append("package index tool is not scroliq-package")
            if index.get("archive_format") != ARCHIVE_FORMAT:
                errors.append("unexpected archive format contract")

            rows = index.get("files")
            if not isinstance(rows, list):
                errors.append("package index files must be a list")
                rows = []
            expected: dict[str, dict[str, Any]] = {}
            for row in rows:
                if not isinstance(row, dict):
                    errors.append("package index contains a non-object file row")
                    continue
                path = row.get("path")
                try:
                    normal = _normalise_rel(path, allow_reserved=True)
                except PackageError as exc:
                    errors.append(str(exc))
                    continue
                if normal in expected:
                    errors.append(f"package index duplicates {normal}")
                    continue
                expected[normal] = row

            actual_names = set(names) - {INDEX_PATH}
            if actual_names != set(expected):
                missing = sorted(set(expected) - actual_names)
                extra = sorted(actual_names - set(expected))
                errors.append(
                    f"archive/index member mismatch: missing={missing}, extra={extra}"
                )

            verified_hashes: dict[str, str] = {}
            for name, row in sorted(expected.items()):
                if name not in actual_names:
                    continue
                try:
                    info = zf.getinfo(name)
                    size, payload_sha = _zip_member_sha256(zf, name)
                except (KeyError, OSError, zipfile.BadZipFile) as exc:
                    errors.append(f"cannot read {name}: {exc}")
                    continue
                if info.compress_type != zipfile.ZIP_STORED:
                    errors.append(f"{name}: member is not ZIP_STORED")
                if info.date_time != FIXED_ZIP_TIME:
                    errors.append(f"{name}: timestamp is not deterministic")
                if (info.external_attr >> 16) != FILE_MODE:
                    errors.append(f"{name}: POSIX file mode is not deterministic")
                if row.get("size") != size:
                    errors.append(f"{name}: size mismatch")
                if row.get("sha256") != payload_sha:
                    errors.append(f"{name}: sha256 mismatch")
                verified_hashes[name] = payload_sha

            embedded_manifest: dict[str, Any] | None = None
            manifest_rel = index.get("manifest_path")
            if isinstance(manifest_rel, str) and manifest_rel in actual_names:
                manifest_raw = zf.read(manifest_rel)
                if verified_hashes.get(manifest_rel) != index.get("manifest_sha256"):
                    errors.append("manifest_sha256 does not match manifest bytes")
                try:
                    candidate_manifest = json.loads(manifest_raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    errors.append(f"cannot parse embedded provenance manifest: {exc}")
                else:
                    if isinstance(candidate_manifest, dict):
                        embedded_manifest = candidate_manifest
                    else:
                        errors.append("embedded provenance manifest is not an object")
            else:
                errors.append("manifest_path is missing from archive")

            validation_rel = index.get("validation_path")
            if isinstance(validation_rel, str) and validation_rel in actual_names:
                validation_raw = zf.read(validation_rel)
                if _sha256(validation_raw) != index.get("validation_sha256"):
                    errors.append(
                        "validation_sha256 does not match validation bytes"
                    )
                try:
                    validation = json.loads(validation_raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    errors.append(f"cannot parse provenance validation: {exc}")
                else:
                    if validation.get("eligible") is not True:
                        errors.append("embedded provenance validation is not eligible")
                    if validation.get("graph_sha256") != index.get("graph_sha256"):
                        errors.append("graph_sha256 differs from validation report")
            else:
                errors.append("validation_path is missing from archive")

            reviewer_rel = index.get("reviewer_contract_path")
            if isinstance(reviewer_rel, str) and reviewer_rel in actual_names:
                reviewer_raw = zf.read(reviewer_rel)
                if _sha256(reviewer_raw) != index.get("reviewer_contract_sha256"):
                    errors.append(
                        "reviewer_contract_sha256 does not match reviewer contract bytes"
                    )
                try:
                    reviewer = json.loads(reviewer_raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    errors.append(f"cannot parse reviewer contract: {exc}")
                else:
                    if (
                        reviewer.get("schema_version") != 2
                        or reviewer.get("tool") != PACKAGE_TOOL
                    ):
                        errors.append("unsupported reviewer contract")
                    materials = reviewer.get("materials")
                    if not isinstance(materials, dict):
                        errors.append("reviewer contract materials must be an object")
                    else:
                        for key in (
                            "methodology",
                            "system_requirements",
                            "human_input_log",
                            "vc3d_workflow",
                            "false_positive_mitigation",
                            "legibility_ledger",
                        ):
                            item = materials.get(key)
                            if not isinstance(item, dict):
                                errors.append(f"reviewer contract is missing {key}")
                                continue
                            path = item.get("path")
                            if (
                                not isinstance(path, str)
                                or path not in actual_names
                                or verified_hashes.get(path) != item.get("sha256")
                            ):
                                errors.append(
                                    f"reviewer material {key} is missing or hash-mismatched"
                                )
                    reproduction = reviewer.get("reproduction")
                    if not isinstance(reproduction, dict):
                        errors.append("reviewer reproduction contract is missing")
                    else:
                        image = reproduction.get("docker_image")
                        command = reproduction.get("docker_run_command")
                        if (
                            not isinstance(image, str)
                            or "@sha256:" not in image
                            or not isinstance(command, str)
                            or image not in command
                        ):
                            errors.append(
                                "reviewer reproduction command does not invoke "
                                "its digest-pinned Docker image"
                            )
                    human = reviewer.get("human_input")
                    if not isinstance(human, dict):
                        errors.append("reviewer human-input accounting is missing")
                    else:
                        declared = human.get("declared_hours")
                        ledger = human.get("ledger_hours")
                        if (
                            isinstance(declared, bool)
                            or isinstance(ledger, bool)
                            or not isinstance(declared, (int, float))
                            or not isinstance(ledger, (int, float))
                            or float(ledger) > 8.0 + 1e-9
                            or abs(float(declared) - float(ledger)) > 1e-9
                        ):
                            errors.append("reviewer human-input accounting is inconsistent")
                    columns = reviewer.get("columns")
                    if not isinstance(columns, dict):
                        errors.append("reviewer column contract is missing")
                    else:
                        meshes = columns.get("meshes")
                        renders = columns.get("renders")
                        if (
                            not isinstance(meshes, list)
                            or not meshes
                            or meshes != list(range(1, len(meshes) + 1))
                            or renders != meshes
                        ):
                            errors.append(
                                "reviewer columns are not one contiguous mesh/render "
                                "sequence starting at 1"
                            )
            else:
                errors.append("reviewer_contract_path is missing from archive")

            ledger_document: dict[str, Any] | None = None
            ledger_rel = index.get("legibility_ledger_path")
            if isinstance(ledger_rel, str) and ledger_rel in actual_names:
                ledger_raw = zf.read(ledger_rel)
                if (
                    verified_hashes.get(ledger_rel)
                    != index.get("legibility_ledger_sha256")
                ):
                    errors.append(
                        "legibility_ledger_sha256 does not match ledger bytes"
                    )
                try:
                    candidate_ledger = json.loads(ledger_raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    errors.append(f"cannot parse legibility ledger: {exc}")
                else:
                    if isinstance(candidate_ledger, dict):
                        ledger_document = candidate_ledger
                    else:
                        errors.append("legibility ledger is not an object")
            else:
                errors.append("legibility_ledger_path is missing from archive")

            legibility_rel = index.get("legibility_validation_path")
            if isinstance(legibility_rel, str) and legibility_rel in actual_names:
                legibility_raw = zf.read(legibility_rel)
                if (
                    _sha256(legibility_raw)
                    != index.get("legibility_validation_sha256")
                ):
                    errors.append(
                        "legibility_validation_sha256 does not match validation bytes"
                    )
                try:
                    legibility = json.loads(legibility_raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    errors.append(f"cannot parse legibility validation: {exc}")
                else:
                    if legibility.get("passes_recorded_thresholds") is not True:
                        errors.append(
                            "embedded legibility validation does not pass"
                        )
                    if legibility.get("threshold") != LEGIBILITY_THRESHOLD:
                        errors.append(
                            "embedded legibility threshold is not the package contract"
                        )
                    if (
                        legibility.get("manifest_sha256")
                        != index.get("manifest_sha256")
                    ):
                        errors.append(
                            "legibility validation manifest hash differs from package"
                        )
                    if (
                        legibility.get("ledger_sha256")
                        != index.get("legibility_ledger_sha256")
                    ):
                        errors.append(
                            "legibility validation ledger hash differs from package"
                        )
                    if (
                        embedded_manifest is not None
                        and ledger_document is not None
                    ):
                        recomputed = audit_legibility(
                            embedded_manifest,
                            ledger_document,
                            manifest_sha256=index.get("manifest_sha256"),
                            ledger_sha256=index.get("legibility_ledger_sha256"),
                        )
                        if _json_bytes(recomputed) != legibility_raw:
                            errors.append(
                                "embedded legibility validation does not match "
                                "a fresh audit of the embedded manifest and ledger"
                            )
            else:
                errors.append(
                    "legibility_validation_path is missing from archive"
                )

            _verify_embedded_vc3d_bindings(
                zf,
                manifest=embedded_manifest,
                index=index,
                actual_names=actual_names,
                verified_hashes=verified_hashes,
                errors=errors,
            )

            if index.get("file_count") != len(expected):
                errors.append("file_count does not match indexed file rows")

    except (OSError, zipfile.BadZipFile) as exc:
        errors.append(f"cannot open archive: {exc}")

    return {
        "valid": not errors,
        "archive_sha256": archive_sha,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build or verify a deterministic reviewer package from a passing "
            "2027 Grand Prize provenance manifest"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="validate and build a package")
    build.add_argument("--manifest", required=True)
    build.add_argument("--root-dir", required=True)
    build.add_argument("--out", required=True)
    build.add_argument("--methodology", required=True)
    build.add_argument("--system-requirements", required=True)
    build.add_argument("--human-input-log", required=True)
    build.add_argument("--vc3d-workflow", required=True)
    build.add_argument("--false-positive-mitigation", required=True)
    build.add_argument("--legibility-ledger", required=True)
    build.add_argument(
        "--docker-run-command",
        required=True,
        help="copy-paste reproduction command using the manifest's pinned image digest",
    )

    verify = sub.add_parser("verify", help="verify a built package")
    verify.add_argument("archive")

    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build_package(
                manifest_path=args.manifest,
                root_dir=args.root_dir,
                out_path=args.out,
                methodology_path=args.methodology,
                system_requirements_path=args.system_requirements,
                human_input_log_path=args.human_input_log,
                vc3d_workflow_path=args.vc3d_workflow,
                false_positive_mitigation_path=args.false_positive_mitigation,
                legibility_ledger_path=args.legibility_ledger,
                docker_run_command=args.docker_run_command,
            )
            print("Grand Prize package: PASS")
            print(f"archive: {result['archive']}")
            print(f"archive sha256: {result['archive_sha256']}")
            print(f"graph sha256: {result['graph_sha256']}")
            print(f"files: {result['file_count']}")
        else:
            result = verify_package(args.archive)
            verdict = "PASS" if result["valid"] else "FAIL"
            print(f"Grand Prize package verification: {verdict}")
            print(f"archive sha256: {result['archive_sha256']}")
            for error in result["errors"]:
                print(f"- {error}")
            if not result["valid"]:
                raise SystemExit(1)
    except (OSError, PackageError) as exc:
        print(f"Grand Prize package: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
