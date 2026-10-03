"""Fail-closed release gate for Grand Prize ML datasets and checkpoints.

The 2027 Grand Prize requires public training datasets under CC-BY-NC 4.0,
fixed seeds for stochastic work, public experiment tracking, and—when
pseudo-labeling or iterative labeling is used—public datasets and checkpoints
at every stage.  This module validates that release chain before it is consumed
by the final submission provenance manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .package_hash import sha256_path

SCHEMA_VERSION = 1
DATA_LICENSE = "CC-BY-NC-4.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DATASET_ROLES = {"training", "pseudo-label", "iterative-label", "validation"}
CHECKPOINT_ROLES = {"intermediate", "final"}
RUN_KINDS = {"training", "inference"}


class ReleaseValidationError(ValueError):
    """Raised when a release manifest violates the machine contract."""


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseValidationError(f"cannot read release manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseValidationError("release manifest must be a JSON object")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _identifier(value: Any, field: str) -> str:
    text = _nonempty(value, field)
    if not ID_RE.fullmatch(text):
        raise ReleaseValidationError(f"{field} must match {ID_RE.pattern!r}")
    return text


def _sha(value: Any, field: str) -> str:
    text = _nonempty(value, field)
    if not SHA256_RE.fullmatch(text):
        raise ReleaseValidationError(f"{field} must be lowercase 64-hex SHA-256")
    return text


def _public_url(value: Any, field: str) -> str:
    text = _nonempty(value, field)
    if not text.startswith(("https://", "http://")):
        raise ReleaseValidationError(f"{field} must be an http(s) URL")
    return text


def _relative_path(value: Any, field: str) -> str:
    text = _nonempty(value, field)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ReleaseValidationError(f"{field} must be a relative path without '..'")
    return path.as_posix()


def _unique_ids(rows: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ReleaseValidationError(f"{field} must be a non-empty list")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ReleaseValidationError(f"{field}[{index}] must be an object")
        row_id = _identifier(row.get("id"), f"{field}[{index}].id")
        if row_id in seen:
            raise ReleaseValidationError(f"duplicate {field} id: {row_id}")
        seen.add(row_id)
        normalized.append(dict(row))
    return normalized


def _string_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ReleaseValidationError(f"{field} must be a list")
    rows = [_identifier(item, field) for item in value]
    if not allow_empty and not rows:
        raise ReleaseValidationError(f"{field} must not be empty")
    if len(rows) != len(set(rows)):
        raise ReleaseValidationError(f"{field} must not contain duplicates")
    return rows


def validate_release_manifest(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one public ML release chain."""
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseValidationError(f"schema_version must be {SCHEMA_VERSION}")

    release_id = _identifier(document.get("id"), "id")
    if document.get("visibility") != "public":
        raise ReleaseValidationError("visibility must be 'public'")

    code = document.get("code")
    if not isinstance(code, dict):
        raise ReleaseValidationError("code must be an object")
    repository = _public_url(code.get("repository"), "code.repository")
    commit = _nonempty(code.get("commit"), "code.commit")
    if not COMMIT_RE.fullmatch(commit):
        raise ReleaseValidationError("code.commit must be a lowercase 40-hex Git commit")

    pseudo_labeling = document.get("pseudo_labeling")
    if type(pseudo_labeling) is not bool:
        raise ReleaseValidationError("pseudo_labeling must be boolean")

    dataset_rows = _unique_ids(document.get("datasets"), "datasets")
    datasets: list[dict[str, Any]] = []
    for index, row in enumerate(dataset_rows):
        role = _nonempty(row.get("role"), f"datasets[{index}].role")
        if role not in DATASET_ROLES:
            raise ReleaseValidationError(
                f"datasets[{index}].role must be one of {sorted(DATASET_ROLES)}"
            )
        license_name = _nonempty(row.get("license"), f"datasets[{index}].license")
        if license_name != DATA_LICENSE:
            raise ReleaseValidationError(
                f"datasets[{index}].license must be {DATA_LICENSE}"
            )
        path = row.get("path")
        if path is not None:
            path = _relative_path(path, f"datasets[{index}].path")
        producer = row.get("producer_checkpoint_id")
        if producer is not None:
            producer = _identifier(
                producer, f"datasets[{index}].producer_checkpoint_id"
            )
        if role in {"pseudo-label", "iterative-label"} and producer is None:
            raise ReleaseValidationError(
                f"datasets[{index}] role {role!r} requires producer_checkpoint_id"
            )
        datasets.append(
            {
                "id": _identifier(row.get("id"), f"datasets[{index}].id"),
                "role": role,
                "public_url": _public_url(
                    row.get("public_url"), f"datasets[{index}].public_url"
                ),
                "license": license_name,
                "sha256": _sha(row.get("sha256"), f"datasets[{index}].sha256"),
                "path": path,
                "producer_checkpoint_id": producer,
            }
        )

    checkpoint_rows = _unique_ids(document.get("checkpoints"), "checkpoints")
    checkpoints: list[dict[str, Any]] = []
    for index, row in enumerate(checkpoint_rows):
        role = _nonempty(row.get("role"), f"checkpoints[{index}].role")
        if role not in CHECKPOINT_ROLES:
            raise ReleaseValidationError(
                f"checkpoints[{index}].role must be one of {sorted(CHECKPOINT_ROLES)}"
            )
        stage = row.get("stage")
        if type(stage) is not int or stage < 0:
            raise ReleaseValidationError(f"checkpoints[{index}].stage must be >= 0")
        license_name = _nonempty(row.get("license"), f"checkpoints[{index}].license")
        if pseudo_labeling and license_name != DATA_LICENSE:
            raise ReleaseValidationError(
                "all checkpoints must be CC-BY-NC-4.0 when pseudo_labeling=true"
            )
        path = row.get("path")
        if path is not None:
            path = _relative_path(path, f"checkpoints[{index}].path")
        checkpoints.append(
            {
                "id": _identifier(row.get("id"), f"checkpoints[{index}].id"),
                "role": role,
                "stage": stage,
                "public_url": _public_url(
                    row.get("public_url"), f"checkpoints[{index}].public_url"
                ),
                "license": license_name,
                "sha256": _sha(row.get("sha256"), f"checkpoints[{index}].sha256"),
                "path": path,
                "training_dataset_ids": _string_list(
                    row.get("training_dataset_ids"),
                    f"checkpoints[{index}].training_dataset_ids",
                ),
                "parent_checkpoint_ids": _string_list(
                    row.get("parent_checkpoint_ids", []),
                    f"checkpoints[{index}].parent_checkpoint_ids",
                    allow_empty=True,
                ),
            }
        )

    final_checkpoint_id = _identifier(
        document.get("final_checkpoint_id"), "final_checkpoint_id"
    )

    run_rows = _unique_ids(document.get("runs"), "runs")
    runs: list[dict[str, Any]] = []
    for index, row in enumerate(run_rows):
        kind = _nonempty(row.get("kind"), f"runs[{index}].kind")
        if kind not in RUN_KINDS:
            raise ReleaseValidationError(
                f"runs[{index}].kind must be one of {sorted(RUN_KINDS)}"
            )
        if row.get("public") is not True:
            raise ReleaseValidationError(f"runs[{index}].public must be true")
        stochastic = row.get("stochastic", False)
        if type(stochastic) is not bool:
            raise ReleaseValidationError(f"runs[{index}].stochastic must be boolean")
        random_seed = row.get("random_seed")
        if stochastic and type(random_seed) is not int:
            raise ReleaseValidationError(
                f"runs[{index}].random_seed must be an integer when stochastic=true"
            )
        if random_seed is not None and type(random_seed) is not int:
            raise ReleaseValidationError(f"runs[{index}].random_seed must be an integer")
        runs.append(
            {
                "id": _identifier(row.get("id"), f"runs[{index}].id"),
                "kind": kind,
                "checkpoint_id": _identifier(
                    row.get("checkpoint_id"), f"runs[{index}].checkpoint_id"
                ),
                "public_url": _public_url(
                    row.get("public_url"), f"runs[{index}].public_url"
                ),
                "public": True,
                "stochastic": stochastic,
                "random_seed": random_seed,
            }
        )

    dataset_ids = {row["id"] for row in datasets}
    checkpoint_ids = {row["id"] for row in checkpoints}
    if final_checkpoint_id not in checkpoint_ids:
        raise ReleaseValidationError("final_checkpoint_id does not name a checkpoint")
    final_rows = [row for row in checkpoints if row["role"] == "final"]
    if len(final_rows) != 1 or final_rows[0]["id"] != final_checkpoint_id:
        raise ReleaseValidationError(
            "exactly one checkpoint must have role='final' and match final_checkpoint_id"
        )

    for row in datasets:
        producer = row["producer_checkpoint_id"]
        if producer is not None and producer not in checkpoint_ids:
            raise ReleaseValidationError(
                f"dataset {row['id']} references unknown producer checkpoint {producer}"
            )

    for row in checkpoints:
        unknown_data = sorted(set(row["training_dataset_ids"]) - dataset_ids)
        if unknown_data:
            raise ReleaseValidationError(
                f"checkpoint {row['id']} references unknown datasets: {unknown_data}"
            )
        unknown_parents = sorted(set(row["parent_checkpoint_ids"]) - checkpoint_ids)
        if unknown_parents:
            raise ReleaseValidationError(
                f"checkpoint {row['id']} references unknown parent checkpoints: {unknown_parents}"
            )
        if row["id"] in row["parent_checkpoint_ids"]:
            raise ReleaseValidationError(
                f"checkpoint {row['id']} cannot be its own parent"
            )

    if pseudo_labeling:
        pseudo_rows = [
            row for row in datasets if row["role"] in {"pseudo-label", "iterative-label"}
        ]
        if not pseudo_rows:
            raise ReleaseValidationError(
                "pseudo_labeling=true requires a pseudo-label or iterative-label dataset"
            )
    elif any(
        row["role"] in {"pseudo-label", "iterative-label"} for row in datasets
    ):
        raise ReleaseValidationError(
            "pseudo-label/iterative-label datasets require pseudo_labeling=true"
        )

    for row in runs:
        if row["checkpoint_id"] not in checkpoint_ids:
            raise ReleaseValidationError(
                f"run {row['id']} references unknown checkpoint {row['checkpoint_id']}"
            )

    training_run_checkpoints = {
        row["checkpoint_id"] for row in runs if row["kind"] == "training"
    }
    missing_training_runs = sorted(checkpoint_ids - training_run_checkpoints)
    if missing_training_runs:
        raise ReleaseValidationError(
            f"every checkpoint needs a public training run; missing {missing_training_runs}"
        )

    inference_run_checkpoints = {
        row["checkpoint_id"] for row in runs if row["kind"] == "inference"
    }
    required_inference = {final_checkpoint_id}
    required_inference.update(
        row["producer_checkpoint_id"]
        for row in datasets
        if row["producer_checkpoint_id"] is not None
    )
    missing_inference_runs = sorted(required_inference - inference_run_checkpoints)
    if missing_inference_runs:
        raise ReleaseValidationError(
            "final and pseudo-label-producing checkpoints need a public inference run; "
            f"missing {missing_inference_runs}"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "id": release_id,
        "visibility": "public",
        "code": {"repository": repository, "commit": commit},
        "pseudo_labeling": pseudo_labeling,
        "datasets": datasets,
        "checkpoints": checkpoints,
        "final_checkpoint_id": final_checkpoint_id,
        "runs": runs,
    }


def audit_release(
    document: Mapping[str, Any],
    *,
    root: Path,
    require_local: bool = True,
) -> dict[str, Any]:
    """Validate release metadata and, by default, hash every local artifact."""
    normalized = validate_release_manifest(document)
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, **extra: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, **extra})

    root = root.resolve()
    for collection_name in ("datasets", "checkpoints"):
        for row in normalized[collection_name]:
            label = f"{collection_name}:{row['id']}"
            rel = row["path"]
            if rel is None:
                check(
                    f"{label}:local_hash",
                    not require_local,
                    "local path omitted; metadata-only validation"
                    if not require_local
                    else "local path required for byte verification",
                    expected_sha256=row["sha256"],
                )
                continue
            path = (root / rel).resolve()
            if root != path and root not in path.parents:
                check(
                    f"{label}:local_hash",
                    False,
                    "artifact path escapes root",
                    path=rel,
                )
                continue
            try:
                actual = sha256_path(path)
            except (OSError, ValueError) as exc:
                check(
                    f"{label}:local_hash",
                    False,
                    f"cannot hash artifact: {exc}",
                    path=rel,
                    expected_sha256=row["sha256"],
                )
                continue
            check(
                f"{label}:local_hash",
                actual == row["sha256"],
                "artifact SHA-256 matches manifest"
                if actual == row["sha256"]
                else "artifact SHA-256 mismatch",
                path=rel,
                expected_sha256=row["sha256"],
                actual_sha256=actual,
            )

    all_ok = all(row["ok"] for row in checks)
    if not checks:
        all_ok = not require_local

    canonical = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return {
        "schema_version": SCHEMA_VERSION,
        "release_id": normalized["id"],
        "status": "ready" if all_ok else "blocked",
        "release_ready": all_ok,
        "metadata_valid": True,
        "local_verification_required": require_local,
        "canonical_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "checks": checks,
        "summary": {
            "datasets": len(normalized["datasets"]),
            "checkpoints": len(normalized["checkpoints"]),
            "runs": len(normalized["runs"]),
            "pseudo_labeling": normalized["pseudo_labeling"],
        },
    }


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    if path.exists():
        raise SystemExit(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a public Grand Prize ML release chain: CC-BY-NC datasets, "
            "checkpoint lineage, fixed seeds, public runs, and artifact hashes"
        )
    )
    parser.add_argument("--manifest", required=True, help="release manifest JSON")
    parser.add_argument(
        "--root",
        default=".",
        help="root used to resolve artifact paths (default: current directory)",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="validate release metadata without requiring local artifact bytes",
    )
    parser.add_argument("--out", help="optional JSON validation report")
    parser.add_argument(
        "--format", choices=("text", "json"), default="text", help="stdout format"
    )
    args = parser.parse_args(argv)

    try:
        document = _load_object(Path(args.manifest))
        report = audit_release(
            document,
            root=Path(args.root),
            require_local=not args.metadata_only,
        )
    except ReleaseValidationError as exc:
        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "release_ready": False,
            "metadata_valid": False,
            "error": str(exc),
        }

    if args.out:
        _write_json(Path(args.out), report)

    if args.format == "json":
        print(json.dumps(report, sort_keys=True, allow_nan=False))
    else:
        print(
            f"release={report.get('release_id', '<invalid>')} "
            f"status={report['status']} "
            f"metadata_valid={str(report['metadata_valid']).lower()} "
            f"release_ready={str(report['release_ready']).lower()}"
        )
        if "error" in report:
            print(f"error: {report['error']}", file=sys.stderr)
        for row in report.get("checks", []):
            mark = "PASS" if row["ok"] else "FAIL"
            print(f"[{mark}] {row['name']}: {row['detail']}")

    return 0 if report["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
