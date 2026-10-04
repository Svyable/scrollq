"""Sealed-truth timing for blind physical controls.

A blind control is only as credible as the order of events around it: the
prediction must be fixed *before* the truth becomes visible, and the truth
shown afterwards must be the truth that was sealed. This module records that
order as a small chain of create-only artifacts:

    manifest  ->  seal  ->  prediction commitment  ->  (anchor)  ->  reveal  ->  report

The benchmark manifest declares every truth item as ``development_truth``
(visible while building, may be used for tuning) or ``sealed_truth`` (hidden
until the prediction commitment exists) and states ``training_eligible``
explicitly. A benchmark with any sealed truth is evaluation-only.

What this does *not* do: it does not score a prediction, and it does not prove
wall-clock time. A hash commitment fixes content; the *time* is only as good as
the clock that stamped it, so the report separates self-asserted ordering from
ordering bound to a third-party-observable anchor, and records custody as an
attestation rather than a measurement. It is also not a generic artifact
provenance layer: for ink, exact evaluated-array identity stays with
``scroliq-ink-validate``; this module only adds the ordering record.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .model_eval import ValidationError
from .package_hash import sha256_path

MANIFEST_SCHEMA = "scroliq-blind-benchmark/1"
SEAL_SCHEMA = "scroliq-blind-truth-seal/1"
COMMITMENT_SCHEMA = "scroliq-blind-prediction-commitment/1"
ANCHOR_SCHEMA = "scroliq-blind-anchor/1"
REVEAL_SCHEMA = "scroliq-blind-truth-reveal/1"
REPORT_DIAGNOSTIC = "blind-control-report"
REPORT_SCHEMA = "scroliq-blind-control-report/1"
SEAL_VERSION = "scroliq-blind-truth-seal-v1"

ROLES = ("development_truth", "sealed_truth")
VERDICTS = (
    "sealed-order-anchored",
    "sealed-order-self-asserted",
    "awaiting-reveal",
    "not-blind",
)
ATTESTATION_STATEMENT = (
    "No person with access to the geometry pipeline, its outputs, or the "
    "detector outputs had access to the sealed truth before this reveal."
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
VOLUME_ID_RE = re.compile(r"^[^\s]{1,512}$")

Clock = Callable[[], str]


class BlindControlError(ValidationError):
    """Raised when a blind-control artifact or step is invalid."""


# -- small primitives ---------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(document: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            document, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BlindControlError(f"document is not canonical JSON: {exc}") from exc


def digest(document: Mapping[str, Any]) -> str:
    """Canonical SHA-256 of a JSON document."""
    return hashlib.sha256(_canonical(document)).hexdigest()


def _self_digest(document: Mapping[str, Any], key: str) -> str:
    return digest({k: v for k, v in document.items() if k != key})


def _file_bytes_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _keys(
    obj: Any, required: set[str], optional: set[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(obj, Mapping):
        raise BlindControlError(f"{label} must be an object")
    missing = sorted(required - set(obj))
    unknown = sorted(set(obj) - required - optional)
    if missing:
        raise BlindControlError(f"{label} is missing {missing}")
    if unknown:
        raise BlindControlError(f"{label} has unknown keys {unknown}")
    return obj


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BlindControlError(f"{field} must be a non-empty string")
    return value


def _nullable_text(value: Any, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise BlindControlError(f"{field} must be a boolean (no default is assumed)")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.match(value):
        raise BlindControlError(f"{field} must be 64 lowercase hex characters")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BlindControlError(f"{field} must be a positive integer")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENT_RE.match(value):
        raise BlindControlError(f"{field} must match {IDENT_RE.pattern}")
    return value


def parse_time(value: Any, field: str) -> datetime:
    """Parse a timezone-aware ISO-8601 timestamp into UTC."""
    if not isinstance(value, str):
        raise BlindControlError(f"{field} must be an ISO-8601 timestamp string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise BlindControlError(f"{field} is not an ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise BlindControlError(f"{field} must carry a UTC offset: {value!r}")
    return parsed.astimezone(timezone.utc)


def _write_new(path: Path, text: str, mode: int = 0o644) -> None:
    """Create-only write: an existing file is never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError as exc:
        raise BlindControlError(
            f"refusing to overwrite {path}; blind-control records are create-only"
        ) from exc
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def _dump(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BlindControlError(f"{label} not found: {path}") from exc
    except (OSError, ValueError) as exc:
        raise BlindControlError(f"{label} is not readable JSON: {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise BlindControlError(f"{label} must be a JSON object: {path}")
    return loaded


def _tree(path: Path, label: str) -> str:
    try:
        return sha256_path(path)
    except (OSError, ValueError) as exc:
        raise BlindControlError(f"cannot hash {label} {path}: {exc}") from exc


def _file_count(root: Path) -> int:
    return sum(1 for p in root.rglob("*") if p.is_file())


# -- manifest -----------------------------------------------------------------


def assess_manifest(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a benchmark manifest and say what is still unpinned.

    Raises ``BlindControlError`` for a malformed or self-contradictory
    manifest. A *well-formed but unpinned* manifest is valid; it simply reports
    ``pin_status: "unpinned"`` and is not ``ready_for_commit``.
    """
    top = _keys(
        document,
        {
            "schema", "benchmark_id", "as_of", "training_eligible", "volume",
            "acquisition", "truth", "sealed_truth_commitment_sha256",
            "claim_limits",
        },
        set(),
        "manifest",
    )
    if top["schema"] != MANIFEST_SCHEMA:
        raise BlindControlError(f"manifest.schema must be {MANIFEST_SCHEMA!r}")
    benchmark_id = _identifier(top["benchmark_id"], "manifest.benchmark_id")
    try:
        date.fromisoformat(_text(top["as_of"], "manifest.as_of"))
    except ValueError as exc:
        raise BlindControlError("manifest.as_of must be YYYY-MM-DD") from exc
    training_eligible = _bool(top["training_eligible"], "manifest.training_eligible")

    volume = _keys(top["volume"], {"id", "kind", "claimed"}, {"claimed_source"}, "manifest.volume")
    if not isinstance(volume["id"], str) or not VOLUME_ID_RE.match(volume["id"]):
        raise BlindControlError("manifest.volume.id must be a non-empty string without whitespace")
    _text(volume["kind"], "manifest.volume.kind")
    if not isinstance(volume["claimed"], Mapping):
        raise BlindControlError("manifest.volume.claimed must be an object")
    if volume["claimed"]:
        _text(volume.get("claimed_source"), "manifest.volume.claimed_source")

    acq = _keys(
        top["acquisition"], {"doi", "landing_url", "license", "inventory"}, set(),
        "manifest.acquisition",
    )
    doi = _nullable_text(acq["doi"], "manifest.acquisition.doi")
    if doi is not None and not DOI_RE.match(doi):
        raise BlindControlError(f"manifest.acquisition.doi is not a DOI: {doi!r}")
    _nullable_text(acq["landing_url"], "manifest.acquisition.landing_url")
    lic = _keys(
        acq["license"], {"statement", "evidence_url", "verified"}, set(),
        "manifest.acquisition.license",
    )
    _text(lic["statement"], "manifest.acquisition.license.statement")
    evidence_url = _nullable_text(lic["evidence_url"], "manifest.acquisition.license.evidence_url")
    license_verified = _bool(lic["verified"], "manifest.acquisition.license.verified")
    if license_verified and evidence_url is None:
        raise BlindControlError(
            "manifest.acquisition.license.verified is true but evidence_url is null"
        )
    inventory = acq["inventory"]
    if inventory is not None:
        inv = _keys(
            inventory, {"file_count", "total_bytes", "tree_sha256"}, set(),
            "manifest.acquisition.inventory",
        )
        _positive_int(inv["file_count"], "manifest.acquisition.inventory.file_count")
        _positive_int(inv["total_bytes"], "manifest.acquisition.inventory.total_bytes")
        _sha(inv["tree_sha256"], "manifest.acquisition.inventory.tree_sha256")

    truth = top["truth"]
    if not isinstance(truth, list) or not truth:
        raise BlindControlError("manifest.truth must be a non-empty list")
    seen: set[str] = set()
    sealed_ids: list[str] = []
    development_ids: list[str] = []
    for index, item in enumerate(truth):
        label = f"manifest.truth[{index}]"
        row = _keys(item, {"id", "role", "training_eligible", "description"}, set(), label)
        item_id = _identifier(row["id"], f"{label}.id")
        if item_id in seen:
            raise BlindControlError(f"{label}.id duplicates {item_id!r}")
        seen.add(item_id)
        if row["role"] not in ROLES:
            raise BlindControlError(f"{label}.role must be one of {list(ROLES)}")
        item_trainable = _bool(row["training_eligible"], f"{label}.training_eligible")
        _text(row["description"], f"{label}.description")
        if row["role"] == "sealed_truth":
            if item_trainable:
                raise BlindControlError(f"{label} is sealed_truth and cannot be training_eligible")
            sealed_ids.append(item_id)
        else:
            development_ids.append(item_id)
    if sealed_ids and training_eligible:
        raise BlindControlError(
            "a benchmark with sealed_truth is evaluation-only; "
            "manifest.training_eligible must be false"
        )

    commitment = top["sealed_truth_commitment_sha256"]
    if commitment is not None:
        _sha(commitment, "manifest.sealed_truth_commitment_sha256")
        if not sealed_ids:
            raise BlindControlError(
                "manifest.sealed_truth_commitment_sha256 is set but no truth item is sealed_truth"
            )
    limits = top["claim_limits"]
    if not isinstance(limits, list) or not limits:
        raise BlindControlError("manifest.claim_limits must be a non-empty list")
    for index, limit in enumerate(limits):
        _text(limit, f"manifest.claim_limits[{index}]")

    missing: list[str] = []
    if doi is None:
        missing.append("acquisition.doi")
    if not license_verified:
        missing.append("acquisition.license.verified")
    if inventory is None:
        missing.append("acquisition.inventory")
    pinned = not missing
    if not sealed_ids:
        seal_status = "no-sealed-truth"
    elif commitment is None:
        seal_status = "unsealed"
    else:
        seal_status = "sealed"

    warnings: list[str] = []
    claimed = volume["claimed"]
    if claimed and inventory is None:
        warnings.append(
            "volume.claimed facts are unverified: no acquired-bytes inventory is pinned"
        )
    elif (
        inventory is not None
        and isinstance(claimed.get("slice_count"), int)
        and claimed["slice_count"] != inventory["file_count"]
    ):
        warnings.append(
            f"volume.claimed.slice_count {claimed['slice_count']} != "
            f"inventory.file_count {inventory['file_count']}"
        )
    return {
        "benchmark_id": benchmark_id,
        "volume_id": volume["id"],
        "pin_status": "pinned" if pinned else "unpinned",
        "missing_pins": missing,
        "seal_status": seal_status,
        "ready_for_commit": pinned and seal_status == "sealed",
        "sealed_ids": sealed_ids,
        "development_ids": development_ids,
        "training_eligible": training_eligible,
        "warnings": warnings,
        "manifest_sha256": digest(document),
    }


# -- acquisition inventory ----------------------------------------------------


def inventory_tree(root: Path) -> dict[str, Any]:
    """Hash an acquired directory so its identity can be pinned in a manifest."""
    if not root.is_dir():
        raise BlindControlError(f"inventory root is not a directory: {root}")
    files = []
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if path.is_symlink():
            raise BlindControlError(f"symlinks are not supported: {path}")
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _file_bytes_sha256(path),
                }
            )
    if not files:
        raise BlindControlError(f"inventory root contains no files: {root}")
    return {
        "schema": "scroliq-blind-acquisition-inventory/1",
        "file_count": len(files),
        "total_bytes": sum(row["bytes"] for row in files),
        "tree_sha256": _tree(root, "inventory root"),
        "files": files,
    }


# -- seal ---------------------------------------------------------------------


def new_salt() -> str:
    return secrets.token_hex(32)


def _salt_bytes(salt_hex: str) -> bytes:
    if not isinstance(salt_hex, str) or not SHA256_RE.match(salt_hex):
        raise BlindControlError("commitment salt must be 64 lowercase hex characters")
    return bytes.fromhex(salt_hex)


def _seal_commitment(
    *,
    salt_hex: str,
    benchmark_id: str,
    volume_id: str,
    acquisition_tree_sha256: str,
    item_hashes: Mapping[str, str],
) -> str:
    payload = {
        "benchmark_id": benchmark_id,
        "volume_id": volume_id,
        "acquisition_tree_sha256": acquisition_tree_sha256,
        "items": [{"id": i, "sha256": item_hashes[i]} for i in sorted(item_hashes)],
    }
    h = hashlib.sha256()
    h.update(SEAL_VERSION.encode("ascii") + b"\0")
    h.update(_salt_bytes(salt_hex) + b"\0")
    h.update(_canonical(payload))
    return h.hexdigest()


def _hash_sealed_items(
    truth_root: Path, sealed_ids: Sequence[str]
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for item_id in sealed_ids:
        path = truth_root / item_id
        if not path.exists():
            raise BlindControlError(f"sealed truth item {item_id!r} not found under {truth_root}")
        hashes[item_id] = _tree(path, f"sealed truth item {item_id!r}")
    return hashes


def _current_seal(
    manifest: Mapping[str, Any], assessment: Mapping[str, Any], truth_root: Path, salt_hex: str
) -> str:
    _salt_bytes(salt_hex)  # reject a malformed salt before hashing any truth
    return _seal_commitment(
        salt_hex=salt_hex,
        benchmark_id=assessment["benchmark_id"],
        volume_id=assessment["volume_id"],
        acquisition_tree_sha256=manifest["acquisition"]["inventory"]["tree_sha256"],
        item_hashes=_hash_sealed_items(truth_root, assessment["sealed_ids"]),
    )


def seal_truth(
    manifest: Mapping[str, Any],
    truth_root: Path,
    salt_hex: str,
    *,
    clock: Clock | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Seal truth bytes under a salted commitment.

    Returns ``(public_seal, sealed_manifest)``. The salt stays private; only the
    commitment and the item ids (already public in the manifest) are published.
    The sealed manifest is a *new* document: dated manifests are never edited
    in place.
    """
    assessment = assess_manifest(manifest)
    if assessment["pin_status"] != "pinned":
        raise BlindControlError(
            "cannot seal truth against an unpinned acquisition; missing "
            f"{assessment['missing_pins']}"
        )
    if assessment["seal_status"] == "no-sealed-truth":
        raise BlindControlError("manifest declares no sealed_truth item to seal")
    if assessment["seal_status"] == "sealed":
        raise BlindControlError(
            "manifest is already sealed; create a new dated manifest to reseal"
        )
    commitment = _current_seal(manifest, assessment, truth_root, salt_hex)
    sealed = copy.deepcopy(dict(manifest))
    sealed["sealed_truth_commitment_sha256"] = commitment
    seal = {
        "schema": SEAL_SCHEMA,
        "benchmark_id": assessment["benchmark_id"],
        "volume_id": assessment["volume_id"],
        "commitment_version": SEAL_VERSION,
        "acquisition_tree_sha256": manifest["acquisition"]["inventory"]["tree_sha256"],
        "sealed_item_ids": list(assessment["sealed_ids"]),
        "sealed_truth_commitment_sha256": commitment,
        "sealed_at": (clock or utc_now)(),
    }
    return seal, sealed


# -- prediction commitment ----------------------------------------------------


def commit_prediction(
    manifest: Mapping[str, Any],
    predictions_root: Path,
    detector_spec: Path,
    *,
    pipeline_id: str,
    pipeline_config: Path | None = None,
    development_truth_used: Sequence[str] = (),
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Fix the predictions, detector spec and pipeline identity before reveal."""
    assessment = assess_manifest(manifest)
    if not assessment["ready_for_commit"]:
        raise BlindControlError(
            "manifest is not ready for a prediction commitment: "
            f"pin_status={assessment['pin_status']} missing={assessment['missing_pins']} "
            f"seal_status={assessment['seal_status']}"
        )
    _text(pipeline_id, "pipeline_id")
    if not predictions_root.is_dir() or _file_count(predictions_root) == 0:
        raise BlindControlError(f"predictions root has no files: {predictions_root}")
    if not detector_spec.is_file():
        raise BlindControlError(f"detector spec is not a file: {detector_spec}")
    used = sorted(set(development_truth_used))
    for item_id in used:
        if item_id in assessment["sealed_ids"]:
            raise BlindControlError(
                f"{item_id!r} is sealed_truth and cannot be used before the reveal"
            )
        if item_id not in assessment["development_ids"]:
            raise BlindControlError(f"{item_id!r} is not a declared development_truth item")
    pipeline: dict[str, Any] = {"id": pipeline_id, "config_sha256": None}
    if pipeline_config is not None:
        if not pipeline_config.is_file():
            raise BlindControlError(f"pipeline config is not a file: {pipeline_config}")
        pipeline["config_sha256"] = _file_bytes_sha256(pipeline_config)
    document = {
        "schema": COMMITMENT_SCHEMA,
        "benchmark_id": assessment["benchmark_id"],
        "volume_id": assessment["volume_id"],
        "manifest_sha256": assessment["manifest_sha256"],
        "sealed_truth_commitment_sha256": manifest["sealed_truth_commitment_sha256"],
        "predictions": {
            "tree_sha256": _tree(predictions_root, "predictions root"),
            "file_count": _file_count(predictions_root),
        },
        "detector_spec_sha256": _file_bytes_sha256(detector_spec),
        "pipeline": pipeline,
        "development_truth_used": used,
        "committed_at": (clock or utc_now)(),
    }
    document["commitment_sha256"] = _self_digest(document, "commitment_sha256")
    return document


def _commitment_shape(document: Mapping[str, Any]) -> None:
    _keys(
        document,
        {
            "schema", "benchmark_id", "volume_id", "manifest_sha256",
            "sealed_truth_commitment_sha256", "predictions",
            "detector_spec_sha256", "pipeline", "development_truth_used",
            "committed_at", "commitment_sha256",
        },
        set(),
        "commitment",
    )
    if document["schema"] != COMMITMENT_SCHEMA:
        raise BlindControlError(f"commitment.schema must be {COMMITMENT_SCHEMA!r}")
    _sha(document["manifest_sha256"], "commitment.manifest_sha256")
    _sha(document["sealed_truth_commitment_sha256"], "commitment.sealed_truth_commitment_sha256")
    _sha(document["detector_spec_sha256"], "commitment.detector_spec_sha256")
    _sha(document["commitment_sha256"], "commitment.commitment_sha256")
    preds = _keys(document["predictions"], {"tree_sha256", "file_count"}, set(), "commitment.predictions")
    _sha(preds["tree_sha256"], "commitment.predictions.tree_sha256")
    _positive_int(preds["file_count"], "commitment.predictions.file_count")
    parse_time(document["committed_at"], "commitment.committed_at")
    _identifier(document["benchmark_id"], "commitment.benchmark_id")
    _text(document["volume_id"], "commitment.volume_id")
    pipeline = _keys(document["pipeline"], {"id", "config_sha256"}, set(), "commitment.pipeline")
    _text(pipeline["id"], "commitment.pipeline.id")
    if pipeline["config_sha256"] is not None:
        _sha(pipeline["config_sha256"], "commitment.pipeline.config_sha256")
    used = document["development_truth_used"]
    if not isinstance(used, list):
        raise BlindControlError("commitment.development_truth_used must be a list")
    for index, item_id in enumerate(used):
        _identifier(item_id, f"commitment.development_truth_used[{index}]")


# -- anchor -------------------------------------------------------------------

_ANCHOR_NOT_VERIFIED = [
    "wall-clock time of the anchor: the tool reads it, it cannot prove it",
    "that the anchoring record is publicly observable",
]


def _git(repo: Path, *args: str) -> bytes:
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"") or b""
        raise BlindControlError(
            f"git {' '.join(args)} failed: {detail.decode('utf-8', 'replace').strip() or exc}"
        ) from exc
    return done.stdout


def anchor_git(commitment_path: Path, repo: Path) -> dict[str, Any]:
    """Bind a commitment file to a git commit that contains exactly its bytes."""
    commitment = _load_object(commitment_path, "commitment")
    _commitment_shape(commitment)
    top = Path(_git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    try:
        rel = commitment_path.resolve().relative_to(top).as_posix()
    except ValueError as exc:
        raise BlindControlError(f"{commitment_path} is not inside git repo {top}") from exc
    _git(top, "ls-files", "--error-unmatch", "--", rel)
    if _git(top, "status", "--porcelain", "--", rel).strip():
        raise BlindControlError(f"{rel} has uncommitted changes; commit it before anchoring")
    commit = _git(top, "log", "-1", "--format=%H", "--", rel).decode().strip()
    committed = _git(top, "log", "-1", "--format=%cI", "--", rel).decode().strip()
    file_sha = _file_bytes_sha256(commitment_path)
    blob_sha = hashlib.sha256(_git(top, "show", f"{commit}:{rel}")).hexdigest()
    if blob_sha != file_sha:
        raise BlindControlError("committed blob does not match the commitment file bytes")
    origin = ""
    try:
        origin = _git(top, "config", "--get", "remote.origin.url").decode().strip()
    except BlindControlError:
        pass
    return {
        "schema": ANCHOR_SCHEMA,
        "kind": "git-commit",
        "commitment_sha256": commitment["commitment_sha256"],
        "file_sha256": file_sha,
        "anchored_at": parse_time(committed, "git commit time").isoformat(timespec="seconds"),
        "git": {"commit": commit, "path": rel, "origin_url": origin or None},
        "verified_by_tool": ["commitment file bytes equal the committed blob"],
        "not_verified_by_tool": list(_ANCHOR_NOT_VERIFIED)
        + ["that the commit was pushed (committer date is author-controlled until a remote observes it)"],
    }


def anchor_external(
    commitment_path: Path, reference: str, anchored_at: str
) -> dict[str, Any]:
    """Record a third-party record (e.g. an RFC 3161 token or public post) the author vouches for."""
    commitment = _load_object(commitment_path, "commitment")
    _commitment_shape(commitment)
    return {
        "schema": ANCHOR_SCHEMA,
        "kind": "external",
        "commitment_sha256": commitment["commitment_sha256"],
        "file_sha256": _file_bytes_sha256(commitment_path),
        "anchored_at": parse_time(anchored_at, "anchored_at").isoformat(timespec="seconds"),
        "reference": _text(reference, "reference"),
        "verified_by_tool": [],
        "not_verified_by_tool": list(_ANCHOR_NOT_VERIFIED)
        + ["that the reference exists or covers this commitment"],
    }


# -- reveal -------------------------------------------------------------------


def reveal_truth(
    manifest: Mapping[str, Any],
    commitment: Mapping[str, Any],
    predictions_root: Path,
    truth_root: Path,
    salt_hex: str,
    *,
    attested_by: str | None = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Authorise the reveal, refusing unless nothing has moved since commitment.

    The predictions are re-hashed *before* any truth byte is touched, so a
    changed prediction set never gets the truth opened. Nothing is written by
    this function; a refusal leaves no reveal record.
    """
    assessment = assess_manifest(manifest)
    _commitment_shape(commitment)
    if commitment["commitment_sha256"] != _self_digest(commitment, "commitment_sha256"):
        raise BlindControlError("prediction commitment fails its own digest")
    if commitment["manifest_sha256"] != assessment["manifest_sha256"]:
        raise BlindControlError("prediction commitment was made against a different manifest")
    if not assessment["ready_for_commit"]:
        raise BlindControlError("manifest is not pinned and sealed")
    predictions_now = _tree(predictions_root, "predictions root")
    if predictions_now != commitment["predictions"]["tree_sha256"]:
        raise BlindControlError(
            "predictions changed since the commitment; truth was not opened"
        )
    if _current_seal(manifest, assessment, truth_root, salt_hex) != manifest[
        "sealed_truth_commitment_sha256"
    ]:
        raise BlindControlError("truth bytes or salt do not match the sealed commitment")
    revealed_at = (clock or utc_now)()
    if not parse_time(commitment["committed_at"], "commitment.committed_at") < parse_time(
        revealed_at, "revealed_at"
    ):
        raise BlindControlError(
            "reveal time is not strictly after the commitment time; refusing to record it"
        )
    attestation = None
    if attested_by is not None:
        attestation = {"attested_by": _text(attested_by, "attested_by"), "statement": ATTESTATION_STATEMENT}
    document = {
        "schema": REVEAL_SCHEMA,
        "benchmark_id": assessment["benchmark_id"],
        "prediction_commitment_sha256": commitment["commitment_sha256"],
        "sealed_truth_commitment_sha256": manifest["sealed_truth_commitment_sha256"],
        "predictions_tree_sha256": predictions_now,
        "revealed_at": revealed_at,
        "attestation": attestation,
    }
    document["reveal_sha256"] = _self_digest(document, "reveal_sha256")
    return document


# -- report -------------------------------------------------------------------


def _anchor_level(
    anchor: Mapping[str, Any] | None,
    commitment: Mapping[str, Any],
    commitment_file_sha256: str | None,
    revealed_at: datetime | None,
    weaknesses: list[str],
) -> tuple[str, str | None]:
    if anchor is None:
        weaknesses.append("no anchor: ordering rests on the author's own clock")
        return "self-asserted-clock", None
    _keys(
        anchor,
        {"schema", "kind", "commitment_sha256", "file_sha256", "anchored_at",
         "verified_by_tool", "not_verified_by_tool"},
        {"git", "reference"},
        "anchor",
    )
    if anchor["schema"] != ANCHOR_SCHEMA or anchor["kind"] not in {"git-commit", "external"}:
        raise BlindControlError("anchor schema/kind not recognised")
    anchored_at = parse_time(anchor["anchored_at"], "anchor.anchored_at")
    stamp = anchored_at.isoformat(timespec="seconds")
    if anchor["commitment_sha256"] != commitment["commitment_sha256"]:
        weaknesses.append("anchor binds a different commitment")
        return "self-asserted-clock", None
    if commitment_file_sha256 is None or anchor["file_sha256"] != commitment_file_sha256:
        weaknesses.append("anchor does not match the supplied commitment file bytes")
        return "self-asserted-clock", None
    if anchored_at < parse_time(commitment["committed_at"], "commitment.committed_at"):
        weaknesses.append("anchor time precedes the commitment time (clock inconsistency)")
        return "self-asserted-clock", stamp
    if revealed_at is not None and not anchored_at < revealed_at:
        weaknesses.append("anchor does not precede the reveal")
        return "self-asserted-clock", stamp
    level = "anchor-content-verified" if anchor["kind"] == "git-commit" else "anchor-declared"
    return level, stamp


def build_report(
    manifest: Mapping[str, Any],
    commitment: Mapping[str, Any],
    reveal: Mapping[str, Any] | None = None,
    anchor: Mapping[str, Any] | None = None,
    *,
    commitment_file_sha256: str | None = None,
) -> dict[str, Any]:
    """Compute the blindness verdict from the recorded chain; never from a claim."""
    assessment = assess_manifest(manifest)
    _commitment_shape(commitment)
    violations: list[str] = []
    weaknesses: list[str] = []

    if commitment["commitment_sha256"] != _self_digest(commitment, "commitment_sha256"):
        violations.append("prediction commitment fails its own digest")
    if commitment["manifest_sha256"] != assessment["manifest_sha256"]:
        violations.append("prediction commitment was made against a different manifest")
    if commitment["sealed_truth_commitment_sha256"] != manifest["sealed_truth_commitment_sha256"]:
        violations.append("prediction commitment names a different sealed-truth commitment")
    if (commitment["benchmark_id"], commitment["volume_id"]) != (
        assessment["benchmark_id"], assessment["volume_id"]
    ):
        violations.append("prediction commitment names a different benchmark or volume")
    if not assessment["ready_for_commit"]:
        violations.append("manifest is not pinned and sealed")
    if set(commitment["development_truth_used"]) & set(assessment["sealed_ids"]):
        violations.append("a sealed_truth item is listed as used before the reveal")

    committed_at = parse_time(commitment["committed_at"], "commitment.committed_at")
    revealed_at: datetime | None = None
    attested = False
    if reveal is not None:
        _keys(
            reveal,
            {"schema", "benchmark_id", "prediction_commitment_sha256",
             "sealed_truth_commitment_sha256", "predictions_tree_sha256",
             "revealed_at", "attestation", "reveal_sha256"},
            set(),
            "reveal",
        )
        if reveal["schema"] != REVEAL_SCHEMA:
            raise BlindControlError(f"reveal.schema must be {REVEAL_SCHEMA!r}")
        revealed_at = parse_time(reveal["revealed_at"], "reveal.revealed_at")
        if reveal["reveal_sha256"] != _self_digest(reveal, "reveal_sha256"):
            violations.append("reveal record fails its own digest")
        if reveal["prediction_commitment_sha256"] != commitment["commitment_sha256"]:
            violations.append("reveal belongs to a different prediction commitment")
        if reveal["sealed_truth_commitment_sha256"] != manifest["sealed_truth_commitment_sha256"]:
            violations.append("reveal names a different sealed-truth commitment")
        if reveal["predictions_tree_sha256"] != commitment["predictions"]["tree_sha256"]:
            violations.append("predictions at reveal differ from the committed predictions")
        if not committed_at < revealed_at:
            violations.append("truth became visible no later than the prediction commitment")
        attestation = reveal["attestation"]
        if attestation is not None:
            att = _keys(attestation, {"attested_by", "statement"}, set(), "reveal.attestation")
            attested = att["statement"] == ATTESTATION_STATEMENT and bool(str(att["attested_by"]).strip())
        if not attested:
            weaknesses.append("truth custody is unattested")

    ordering_evidence, anchored_at = _anchor_level(
        anchor, commitment, commitment_file_sha256, revealed_at, weaknesses
    )

    if violations:
        verdict = "not-blind"
    elif reveal is None:
        verdict = "awaiting-reveal"
    elif ordering_evidence != "self-asserted-clock" and attested:
        verdict = "sealed-order-anchored"
    else:
        verdict = "sealed-order-self-asserted"

    if reveal is None:
        order = "truth-not-yet-visible"
    elif committed_at < revealed_at:  # type: ignore[operator]
        order = "prediction-before-truth"
    else:
        order = "truth-not-after-prediction"

    return {
        "diagnostic": REPORT_DIAGNOSTIC,
        "schema": REPORT_SCHEMA,
        "volume": {
            "id": assessment["volume_id"],
            "kind": manifest["volume"]["kind"],
            "claimed": dict(manifest["volume"]["claimed"]),
            "claimed_source": manifest["volume"].get("claimed_source"),
        },
        "benchmark": {
            "id": assessment["benchmark_id"],
            "as_of": manifest["as_of"],
            "manifest_sha256": assessment["manifest_sha256"],
            "training_eligible": assessment["training_eligible"],
            "evaluation_only": not assessment["training_eligible"],
        },
        "acquisition": {
            "doi": manifest["acquisition"]["doi"],
            "landing_url": manifest["acquisition"]["landing_url"],
            "license": dict(manifest["acquisition"]["license"]),
            "inventory": manifest["acquisition"]["inventory"],
            "pin_status": assessment["pin_status"],
        },
        "truth_roles": {
            "development_truth": list(assessment["development_ids"]),
            "sealed_truth": list(assessment["sealed_ids"]),
            "development_truth_used": list(commitment["development_truth_used"]),
        },
        "commitment": {
            "sha256": commitment["commitment_sha256"],
            "predictions": dict(commitment["predictions"]),
            "detector_spec_sha256": commitment["detector_spec_sha256"],
            "pipeline": dict(commitment["pipeline"]),
        },
        "timing": {
            "prediction_committed_at": commitment["committed_at"],
            "anchored_at": anchored_at,
            "truth_first_visible_at": None if reveal is None else reveal["revealed_at"],
            "order": order,
            "ordering_evidence": ordering_evidence,
            "custody_attested": attested,
        },
        "verdict": verdict,
        "violations": violations,
        "weaknesses": weaknesses,
        "claim_limits": list(manifest["claim_limits"]),
        "interpretation": (
            "This record establishes ordering and custody only. It contains no "
            "detection or surface score, and a clean verdict is not evidence "
            "about carbon-ink detection on ancient papyrus."
        ),
    }


# -- CLI ----------------------------------------------------------------------


def _read_salt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _cmd_validate(args: argparse.Namespace) -> int:
    assessment = assess_manifest(_load_object(Path(args.manifest), "manifest"))
    print(_dump(assessment), end="")
    if args.require_pinned and assessment["pin_status"] != "pinned":
        print(f"error: unpinned: missing {assessment['missing_pins']}", file=sys.stderr)
        return 1
    if args.require_sealed and assessment["seal_status"] != "sealed":
        print(f"error: seal_status is {assessment['seal_status']}", file=sys.stderr)
        return 1
    return 0


def _cmd_inventory(args: argparse.Namespace) -> int:
    inv = inventory_tree(Path(args.root))
    _write_new(Path(args.out), _dump(inv))
    print(f"wrote {args.out}: {inv['file_count']} files, tree {inv['tree_sha256']}")
    return 0


def _cmd_seal(args: argparse.Namespace) -> int:
    manifest = _load_object(Path(args.manifest), "manifest")
    outputs = [Path(args.salt_out), Path(args.seal_out), Path(args.manifest_out)]
    for path in outputs:
        if path.exists():
            raise BlindControlError(
                f"refusing to overwrite {path}; blind-control records are create-only"
            )
    salt = new_salt()
    seal, sealed = seal_truth(manifest, Path(args.truth_root), salt)
    # The salt goes to disk first: a commitment whose salt was lost can never
    # be opened, whereas a stray salt file without a commitment is harmless.
    _write_new(outputs[0], salt + "\n", mode=0o600)
    _write_new(outputs[1], _dump(seal))
    _write_new(outputs[2], _dump(sealed))
    print(f"sealed {len(seal['sealed_item_ids'])} item(s): {seal['sealed_truth_commitment_sha256']}")
    return 0


def _cmd_commit(args: argparse.Namespace) -> int:
    manifest = _load_object(Path(args.manifest), "manifest")
    doc = commit_prediction(
        manifest,
        Path(args.predictions),
        Path(args.detector_spec),
        pipeline_id=args.pipeline_id,
        pipeline_config=Path(args.pipeline_config) if args.pipeline_config else None,
        development_truth_used=args.development_truth_used or (),
    )
    _write_new(Path(args.out), _dump(doc))
    print(f"committed {doc['commitment_sha256']} at {doc['committed_at']}")
    return 0


def _cmd_anchor(args: argparse.Namespace) -> int:
    if args.git_repo:
        doc = anchor_git(Path(args.commitment), Path(args.git_repo))
    else:
        if not (args.external_ref and args.external_time):
            raise BlindControlError("--external-ref and --external-time are required together")
        doc = anchor_external(Path(args.commitment), args.external_ref, args.external_time)
    _write_new(Path(args.out), _dump(doc))
    print(f"anchored ({doc['kind']}) at {doc['anchored_at']}")
    return 0


def _cmd_reveal(args: argparse.Namespace) -> int:
    attested_by = args.attested_by if args.attest_truth_unseen else None
    if args.attest_truth_unseen and not args.attested_by:
        raise BlindControlError("--attest-truth-unseen requires --attested-by")
    doc = reveal_truth(
        _load_object(Path(args.manifest), "manifest"),
        _load_object(Path(args.commitment), "commitment"),
        Path(args.predictions),
        Path(args.truth_root),
        _read_salt(Path(args.salt_file)),
        attested_by=attested_by,
    )
    _write_new(Path(args.out), _dump(doc))
    print(f"truth visible from {doc['revealed_at']}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    commitment_path = Path(args.commitment)
    report = build_report(
        _load_object(Path(args.manifest), "manifest"),
        _load_object(commitment_path, "commitment"),
        _load_object(Path(args.reveal), "reveal") if args.reveal else None,
        _load_object(Path(args.anchor), "anchor") if args.anchor else None,
        commitment_file_sha256=_file_bytes_sha256(commitment_path),
    )
    _write_new(Path(args.out), _dump(report))
    print(f"verdict: {report['verdict']}")
    for line in report["violations"]:
        print(f"violation: {line}", file=sys.stderr)
    return 0 if report["verdict"] != "not-blind" else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="scroliq-blind-control",
        description=(
            "Record the order of prediction commitment and sealed-truth "
            "visibility for blind physical controls. Every record is "
            "create-only. Scores are out of scope."
        ),
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="validate a benchmark manifest and list unpinned items")
    p.add_argument("--manifest", required=True)
    p.add_argument("--require-pinned", action="store_true")
    p.add_argument("--require-sealed", action="store_true")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("inventory", help="hash an acquired directory for pinning")
    p.add_argument("--root", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=_cmd_inventory)

    p = sub.add_parser("seal", help="seal truth bytes; writes seal, sealed manifest and private salt")
    p.add_argument("--manifest", required=True)
    p.add_argument("--truth-root", required=True, help="directory holding one file/dir per sealed truth id")
    p.add_argument("--seal-out", required=True)
    p.add_argument("--manifest-out", required=True)
    p.add_argument("--salt-out", required=True, help="private; keep out of the repository")
    p.set_defaults(func=_cmd_seal)

    p = sub.add_parser("commit", help="commit predictions, detector spec and pipeline identity")
    p.add_argument("--manifest", required=True)
    p.add_argument("--predictions", required=True)
    p.add_argument("--detector-spec", required=True)
    p.add_argument("--pipeline-id", required=True)
    p.add_argument("--pipeline-config")
    p.add_argument("--development-truth-used", action="append")
    p.add_argument("--out", required=True)
    p.set_defaults(func=_cmd_commit)

    p = sub.add_parser("anchor", help="bind a commitment file to a third-party-observable record")
    p.add_argument("--commitment", required=True)
    p.add_argument("--git-repo")
    p.add_argument("--external-ref")
    p.add_argument("--external-time")
    p.add_argument("--out", required=True)
    p.set_defaults(func=_cmd_anchor)

    p = sub.add_parser("reveal", help="authorise the reveal if nothing moved since commitment")
    p.add_argument("--manifest", required=True)
    p.add_argument("--commitment", required=True)
    p.add_argument("--predictions", required=True)
    p.add_argument("--truth-root", required=True)
    p.add_argument("--salt-file", required=True)
    p.add_argument("--attested-by")
    p.add_argument("--attest-truth-unseen", action="store_true",
                   help=f"attest: {ATTESTATION_STATEMENT}")
    p.add_argument("--out", required=True)
    p.set_defaults(func=_cmd_reveal)

    p = sub.add_parser("report", help="compute the blindness verdict from the recorded chain")
    p.add_argument("--manifest", required=True)
    p.add_argument("--commitment", required=True)
    p.add_argument("--reveal")
    p.add_argument("--anchor")
    p.add_argument("--out", required=True)
    p.set_defaults(func=_cmd_report)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (BlindControlError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
