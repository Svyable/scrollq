"""Fail-closed target-freeze gate for the 2027 Grand Prize proof campaign.

The gate does not rank scrolls. It verifies exact prize-volume identity from the
frozen ScrolIQ manifest and requires traceable evidence for the prerequisite
stages that must exist before a target is frozen for the proof campaign.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .grand_prize import DEFAULT_MANIFEST

SCHEMA = "scroliq-target-gate/1"
TOOL = "scroliq-target-gate"
REQUIRED_STAGES = (
    "input_integrity",
    "surface_foothold",
    "heldout_geometry",
    "ink_validation",
    "vc3d_handoff",
)
_ALLOWED_STATES = {"pass", "fail", "unknown"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class TargetGateError(ValueError):
    """The target-gate input document is malformed."""


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _nonempty(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _safe_artifact_location(value: Any) -> str | None:
    location = _nonempty(value)
    if location is None:
        return None
    if location.startswith(("https://", "http://")):
        return location
    if "\\" in location:
        return None
    path = PurePosixPath(location)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return location


def _target_for_scroll(manifest: dict[str, Any], scroll: str) -> dict[str, Any] | None:
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise TargetGateError("Grand Prize manifest targets must be a list")
    matches = [
        row for row in targets
        if isinstance(row, dict) and row.get("scroll") == scroll
    ]
    if len(matches) > 1:
        raise TargetGateError(f"Grand Prize manifest has duplicate scroll {scroll}")
    return matches[0] if matches else None


def _identity_check(
    candidate: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    scroll = _nonempty(candidate.get("scroll"))
    volume_id = _nonempty(candidate.get("volume_id"))
    volume_root = _nonempty(candidate.get("volume_root"))
    if scroll is None or volume_id is None or volume_root is None:
        raise TargetGateError(
            "candidate.scroll, candidate.volume_id and candidate.volume_root are required"
        )

    target = _target_for_scroll(manifest, scroll)
    reasons: list[str] = []
    if target is None:
        reasons.append("scroll is not present in the frozen Grand Prize manifest")
        expected_volume_id = None
    else:
        expected_volume_id = target.get("volume_id")
        if volume_id != expected_volume_id:
            reasons.append(
                f"candidate volume_id {volume_id} does not equal eligible "
                f"volume_id {expected_volume_id}"
            )
        needle = f"/{scroll}/volumes/{volume_id}"
        if needle not in f"/{volume_root.lstrip('/')}":
            reasons.append(
                "candidate volume_root does not contain the exact "
                "scroll/volumes/volume_id path"
            )
        excluded = {
            str(row.get("volume_id"))
            for row in target.get("excluded_same_scroll_higher_res", [])
            if isinstance(row, dict) and row.get("volume_id")
        }
        if any(token in volume_root for token in excluded):
            reasons.append(
                "candidate volume_root contains a prohibited same-scroll higher-resolution "
                "volume ID"
            )

    return {
        "id": "exact_volume_identity",
        "state": "pass" if not reasons else "fail",
        "eligible_volume_id": expected_volume_id,
        "candidate_volume_id": volume_id,
        "volume_root": volume_root,
        "reasons": reasons,
    }


def _artifact_errors(
    artifact: Any,
    *,
    candidate_volume_id: str,
    index: int,
    repo_root: Path,
) -> list[str]:
    prefix = f"artifact[{index}]"
    if not isinstance(artifact, dict):
        return [f"{prefix} must be an object"]

    errors: list[str] = []
    if _nonempty(artifact.get("kind")) is None:
        errors.append(f"{prefix}.kind must be a non-empty string")
    if _safe_artifact_location(artifact.get("uri")) is None:
        errors.append(
            f"{prefix}.uri must be a public http(s) URL or safe repository-relative path"
        )
    digest = artifact.get("sha256")
    if not isinstance(digest, str) or _HEX64.fullmatch(digest) is None:
        errors.append(f"{prefix}.sha256 must be lowercase 64-hex")
    location = _safe_artifact_location(artifact.get("uri"))
    if (
        location is not None
        and not location.startswith(("https://", "http://"))
        and isinstance(digest, str)
        and _HEX64.fullmatch(digest) is not None
    ):
        root = repo_root.resolve()
        evidence_path = (root / location).resolve()
        try:
            evidence_path.relative_to(root)
        except ValueError:
            errors.append(f"{prefix}.uri resolves outside repository root")
        else:
            try:
                actual_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            except OSError as exc:
                errors.append(f"{prefix}.uri repository artifact is unreadable: {exc}")
            else:
                if actual_digest != digest:
                    errors.append(
                        f"{prefix}.sha256 does not match repository artifact bytes "
                        f"(actual {actual_digest})"
                    )
    if artifact.get("volume_id") != candidate_volume_id:
        errors.append(
            f"{prefix}.volume_id must equal candidate volume_id "
            f"{candidate_volume_id}"
        )
    if _nonempty(artifact.get("claim")) is None:
        errors.append(f"{prefix}.claim must be a non-empty string")
    return errors


def _stage_check(
    stage_id: str,
    raw: Any,
    *,
    candidate_volume_id: str,
    repo_root: Path,
) -> dict[str, Any]:
    if raw is None:
        return {
            "id": stage_id,
            "state": "unknown",
            "reasons": ["prerequisite is missing from the input document"],
            "artifacts": [],
        }
    if not isinstance(raw, dict):
        return {
            "id": stage_id,
            "state": "fail",
            "reasons": ["prerequisite must be an object"],
            "artifacts": [],
        }

    state = raw.get("state")
    if state not in _ALLOWED_STATES:
        return {
            "id": stage_id,
            "state": "fail",
            "reasons": ["state must be one of pass, fail, unknown"],
            "artifacts": [],
        }

    rationale = _nonempty(raw.get("rationale"))
    artifacts_raw = raw.get("artifacts", [])
    reasons: list[str] = []
    artifacts_valid_shape = isinstance(artifacts_raw, list)
    artifacts = artifacts_raw if artifacts_valid_shape else []
    if not artifacts_valid_shape:
        reasons.append("artifacts must be a list")

    artifact_reasons: list[str] = []
    for index, artifact in enumerate(artifacts):
        artifact_reasons.extend(
            _artifact_errors(
                artifact,
                candidate_volume_id=candidate_volume_id,
                index=index,
                repo_root=repo_root,
            )
        )
    reasons.extend(artifact_reasons)

    if state == "pass":
        if not artifacts:
            reasons.append("pass requires at least one hash-pinned evidence artifact")
        effective = "pass" if not reasons else "fail"
    elif state == "fail":
        effective = "fail"
        if rationale is None:
            reasons.append("fail requires a non-empty rationale")
    else:
        if rationale is None:
            reasons.append("unknown should explain what evidence is missing")
        structural = (not artifacts_valid_shape) or bool(artifact_reasons)
        effective = "fail" if structural else "unknown"

    return {
        "id": stage_id,
        "state": effective,
        "declared_state": state,
        "rationale": rationale,
        "reasons": reasons,
        "artifacts": artifacts,
    }


def evaluate_target_gate(
    document: dict[str, Any],
    *,
    manifest: dict[str, Any] = DEFAULT_MANIFEST,
    repo_root: Path | str = Path("."),
) -> dict[str, Any]:
    """Evaluate one target without ranking it against other candidates."""
    if not isinstance(document, dict):
        raise TargetGateError("input must be a JSON object")
    if document.get("schema_version") != 1:
        raise TargetGateError("schema_version must be 1")

    candidate = document.get("candidate")
    if not isinstance(candidate, dict):
        raise TargetGateError("candidate must be an object")
    identity = _identity_check(candidate, manifest)
    candidate_volume_id = str(candidate["volume_id"])

    prerequisites = document.get("prerequisites")
    if prerequisites is None:
        prerequisites = {}
    if not isinstance(prerequisites, dict):
        raise TargetGateError("prerequisites must be an object")

    repository_root = Path(repo_root)
    stage_checks = [
        _stage_check(
            stage_id,
            prerequisites.get(stage_id),
            candidate_volume_id=candidate_volume_id,
            repo_root=repository_root,
        )
        for stage_id in REQUIRED_STAGES
    ]
    checks = [identity, *stage_checks]

    failed = [row["id"] for row in checks if row["state"] == "fail"]
    unknown = [row["id"] for row in checks if row["state"] == "unknown"]
    if failed:
        status = "blocked"
    elif unknown:
        status = "provisional"
    else:
        status = "ready-to-freeze"

    target = _target_for_scroll(manifest, str(candidate["scroll"]))
    return {
        "schema": SCHEMA,
        "tool": TOOL,
        "status": status,
        "manifest_as_of": manifest.get("as_of"),
        "manifest_sha256": _canonical_sha256(manifest),
        "manifest_target_sha256": _canonical_sha256(target) if target is not None else None,
        "input_as_of": document.get("as_of"),
        "candidate": {
            "scroll": candidate["scroll"],
            "volume_id": candidate["volume_id"],
            "volume_root": candidate["volume_root"],
        },
        "input_sha256": _canonical_sha256(document),
        "required_prerequisites": [
            "exact_volume_identity",
            *REQUIRED_STAGES,
        ],
        "checks": checks,
        "blocking_checks": failed,
        "unknown_checks": unknown,
        "ranking": None,
        "claim_boundary": (
            "This gate verifies exact-volume identity and the declared provenance "
            "contract needed to freeze a proof target. It does not rank scrolls, "
            "validate scientific correctness inside third-party artifacts, prove "
            "readability, or predict Grand Prize success."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="input_path", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo-root", default=".", help="repository root used to verify repository-relative evidence bytes")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = Path(args.out)
    if out.exists():
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "status": "invalid",
                    "error": f"refusing to overwrite {out}",
                }
            )
        )
        return 2

    try:
        raw = Path(args.input_path).read_text(encoding="utf-8")
        document = json.loads(raw)
        report = evaluate_target_gate(document, repo_root=args.repo_root)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TargetGateError) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "invalid", "error": str(exc)}))
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ready-to-freeze" else 1


if __name__ == "__main__":
    raise SystemExit(main())
