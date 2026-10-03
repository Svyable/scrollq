"""Independent-evidence ledger for Grand Prize submission readiness.

This module normalizes evidence *about* a submission without pretending that
third-party tools share one native report schema. The ledger records immutable
artifact/provenance references and a small controlled vocabulary of claims.
Missing evidence stays unknown; an explicit failed claim fails closed.

The policy is a ScrolIQ pre-submission policy, not an official Scroll Prize
eligibility rule and not a papyrological legibility judgment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .package_hash import sha256_path
from .evidence_adapters import (
    APPROVED_PASS_ADAPTERS,
    ASSESSORS,
    verify_native_mesh_identity,
    verify_normalized_entry,
)

SCHEMA_VERSION = 1
DIAGNOSTIC = "grand-prize-evidence-ledger"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

MESH_CLAIMS = (
    "flattening-isometry",
    "mesh-self-intersection",
    "render-handedness",
)
VOLUME_CLAIMS = ("spiral-held-out",)
MESH_ADVISORY_CLAIMS = ("surface-sheet-identity",)
VOLUME_ADVISORY_CLAIMS = (
    "surface-ct-support",
    "cross-scan-registration",
)
ADVISORY_CLAIMS = MESH_ADVISORY_CLAIMS + VOLUME_ADVISORY_CLAIMS
KNOWN_CLAIMS = frozenset(MESH_CLAIMS + VOLUME_CLAIMS + ADVISORY_CLAIMS)
STATUSES = frozenset({"pass", "partial", "fail", "unknown"})


def _error(errors: list[dict[str, str]], code: str, path: str, message: str) -> None:
    errors.append({"code": code, "path": path, "message": message})


def _public_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def _verify_local_artifact(
    entry: dict[str, Any],
    *,
    path: str,
    root_dir: Path | None,
    errors: list[dict[str, str]],
    required: bool,
) -> Path | None:
    rel = entry.get("path")
    if root_dir is None:
        if required:
            _error(
                errors,
                "EVIDENCE_PACKAGE_ROOT_REQUIRED",
                path,
                "Grand Prize readiness requires a package root so native evidence can be re-verified",
            )
        return None
    if not isinstance(rel, str) or not rel:
        if required:
            _error(
                errors,
                "EVIDENCE_LOCAL_ARTIFACT_REQUIRED",
                f"{path}.path",
                "required evidence must include a package-relative native report path",
            )
        return None

    root = root_dir.resolve()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        _error(errors, "EVIDENCE_PATH_ESCAPE", f"{path}.path", "path escapes package root")
        return None
    if not target.is_file():
        _error(errors, "EVIDENCE_FILE_MISSING", f"{path}.path", f"file not found: {rel}")
        return None

    digest = entry.get("sha256")
    if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != digest:
            _error(
                errors,
                "EVIDENCE_HASH_MISMATCH",
                f"{path}.sha256",
                f"declared {digest}, actual {actual}",
            )
            return None
    return target


def _claim_summary(
    claim: str,
    entries: list[dict[str, Any]],
    *,
    mesh_scoped: bool,
    expected_mesh_ids: set[str],
) -> dict[str, Any]:
    relevant = [entry for entry in entries if entry.get("claim") == claim]
    failing = sorted(
        str(entry.get("id"))
        for entry in relevant
        if entry.get("status") == "fail"
    )
    passing = [entry for entry in relevant if entry.get("status") == "pass"]

    covered: set[str] = set()
    if mesh_scoped:
        for entry in passing:
            scope = entry.get("scope")
            if isinstance(scope, dict):
                mesh_ids = scope.get("mesh_ids")
                if isinstance(mesh_ids, list):
                    covered.update(str(v) for v in mesh_ids if isinstance(v, str))
        missing = sorted(expected_mesh_ids - covered)
    else:
        missing = []

    if failing:
        status = "fail"
        reason = "one or more independent evidence artifacts explicitly failed"
    elif mesh_scoped and expected_mesh_ids and not relevant:
        status = "unknown"
        reason = "no evidence supplied for this required mesh-scoped claim"
    elif mesh_scoped and expected_mesh_ids and missing:
        status = "partial"
        reason = "passing evidence does not cover every submitted mesh"
    elif mesh_scoped and not expected_mesh_ids:
        status = "unknown"
        reason = "submitted mesh set is unknown, so mesh coverage cannot be established"
    elif not mesh_scoped and not relevant:
        status = "unknown"
        reason = "no evidence supplied for this required volume-scoped claim"
    elif passing:
        status = "pass"
        reason = "required claim has passing immutable evidence"
    else:
        status = "partial"
        reason = "evidence exists, but none of it has status=pass"

    return {
        "claim": claim,
        "scope": "mesh" if mesh_scoped else "volume",
        "status": status,
        "reason": reason,
        "evidence_ids": sorted(str(entry.get("id")) for entry in relevant),
        "failed_evidence_ids": failing,
        "covered_mesh_ids": sorted(covered) if mesh_scoped else [],
        "missing_mesh_ids": missing,
    }


def validate_evidence_ledger(
    ledger: dict[str, Any],
    *,
    expected_volume_id: str | None = None,
    expected_mesh_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    expected_mesh_sha256: dict[str, str] | None = None,
    expected_mesh_paths: dict[str, str] | None = None,
    root_dir: Path | None = None,
    ledger_sha256: str | None = None,
    require_local_artifacts: bool = False,
) -> dict[str, Any]:
    """Validate a normalized independent-evidence ledger.

    Structural/provenance defects are failures. Missing required evidence is
    reported as partial/unknown rather than silently upgraded to a pass.
    """
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    normalized: list[dict[str, Any]] = []

    if not isinstance(ledger, dict):
        ledger = {}
        _error(errors, "EVIDENCE_LEDGER", "$", "ledger must be a JSON object")

    if ledger.get("schema_version") != SCHEMA_VERSION:
        _error(
            errors,
            "EVIDENCE_SCHEMA_VERSION",
            "schema_version",
            f"expected schema_version={SCHEMA_VERSION}",
        )
    if ledger.get("diagnostic") != DIAGNOSTIC:
        _error(
            errors,
            "EVIDENCE_DIAGNOSTIC",
            "diagnostic",
            f"diagnostic must be {DIAGNOSTIC!r}",
        )

    volume_id = ledger.get("volume_id")
    if not isinstance(volume_id, str) or not volume_id:
        _error(errors, "EVIDENCE_VOLUME", "volume_id", "exact eligible volume id is required")
        volume_id = None
    if expected_volume_id is not None and volume_id != expected_volume_id:
        _error(
            errors,
            "EVIDENCE_VOLUME_MISMATCH",
            "volume_id",
            "ledger volume_id does not match the submission eligible volume id",
        )

    raw_entries = ledger.get("entries")
    if not isinstance(raw_entries, list):
        _error(errors, "EVIDENCE_ENTRIES", "entries", "entries must be a list")
        raw_entries = []

    seen_ids: set[str] = set()
    expected_mesh_set = set(expected_mesh_ids or ())
    expected_mesh_digests = dict(expected_mesh_sha256 or {})
    expected_paths = dict(expected_mesh_paths or {})

    for i, raw in enumerate(raw_entries):
        path = f"entries[{i}]"
        if not isinstance(raw, dict):
            _error(errors, "EVIDENCE_RECORD", path, "entry must be an object")
            continue

        entry_id = raw.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            _error(errors, "EVIDENCE_ID", f"{path}.id", "non-empty id is required")
            entry_id = f"<invalid:{i}>"
        elif entry_id in seen_ids:
            _error(errors, "EVIDENCE_DUPLICATE_ID", f"{path}.id", f"duplicate id {entry_id!r}")
        seen_ids.add(str(entry_id))

        claim = raw.get("claim")
        if claim not in KNOWN_CLAIMS:
            _error(
                errors,
                "EVIDENCE_CLAIM",
                f"{path}.claim",
                f"claim must be one of {', '.join(sorted(KNOWN_CLAIMS))}",
            )

        status = raw.get("status")
        if status not in STATUSES:
            _error(
                errors,
                "EVIDENCE_STATUS",
                f"{path}.status",
                "status must be pass, partial, fail, or unknown",
            )

        tool = raw.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            _error(errors, "EVIDENCE_TOOL", f"{path}.tool", "tool name is required")

        if not _public_url(raw.get("artifact_url")):
            _error(
                errors,
                "EVIDENCE_ARTIFACT_URL",
                f"{path}.artifact_url",
                "public http(s) artifact URL is required",
            )

        digest = raw.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            _error(
                errors,
                "EVIDENCE_SHA256",
                f"{path}.sha256",
                "lowercase 64-hex artifact sha256 is required",
            )

        producer = raw.get("producer")
        if not isinstance(producer, dict):
            producer = {}
            _error(errors, "EVIDENCE_PRODUCER", f"{path}.producer", "producer object is required")
        if not _public_url(producer.get("repository")):
            _error(
                errors,
                "EVIDENCE_REPOSITORY",
                f"{path}.producer.repository",
                "public http(s) source repository URL is required",
            )
        commit = producer.get("commit")
        if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
            _error(
                errors,
                "EVIDENCE_COMMIT",
                f"{path}.producer.commit",
                "lowercase 40-hex producer commit is required",
            )
        command = producer.get("command")
        if not isinstance(command, str) or not command.strip():
            _error(
                errors,
                "EVIDENCE_COMMAND",
                f"{path}.producer.command",
                "reproduction command is required",
            )

        scope = raw.get("scope")
        if scope is None:
            scope = {}
        elif not isinstance(scope, dict):
            scope = {}
            _error(errors, "EVIDENCE_SCOPE", f"{path}.scope", "scope must be an object")
        mesh_ids = scope.get("mesh_ids", [])
        if not isinstance(mesh_ids, list) or not all(
            isinstance(v, str) and v for v in mesh_ids
        ):
            _error(
                errors,
                "EVIDENCE_SCOPE_MESHES",
                f"{path}.scope.mesh_ids",
                "mesh_ids must be a list of non-empty strings",
            )
            mesh_ids = []
        if len(set(mesh_ids)) != len(mesh_ids):
            _error(
                errors,
                "EVIDENCE_SCOPE_MESHES",
                f"{path}.scope.mesh_ids",
                "mesh_ids must not contain duplicates",
            )
        if claim in MESH_CLAIMS and not mesh_ids:
            _error(
                errors,
                "EVIDENCE_SCOPE_MESHES",
                f"{path}.scope.mesh_ids",
                f"{claim!r} evidence must identify at least one submitted mesh",
            )

        mesh_sha256 = scope.get("mesh_sha256", {})
        if mesh_sha256 is None:
            mesh_sha256 = {}
        if not isinstance(mesh_sha256, dict):
            _error(
                errors,
                "EVIDENCE_SCOPE_MESH_SHA256",
                f"{path}.scope.mesh_sha256",
                "mesh_sha256 must map mesh ids to lowercase 64-hex digests",
            )
            mesh_sha256 = {}
        if claim in MESH_CLAIMS:
            for mesh_id in mesh_ids:
                value = mesh_sha256.get(mesh_id)
                if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
                    _error(
                        errors,
                        "EVIDENCE_SCOPE_MESH_SHA256",
                        f"{path}.scope.mesh_sha256",
                        f"exact submitted mesh digest is required for {mesh_id!r}",
                    )
                expected = expected_mesh_digests.get(mesh_id)
                if expected is not None and value != expected:
                    _error(
                        errors,
                        "EVIDENCE_SCOPE_MESH_HASH_MISMATCH",
                        f"{path}.scope.mesh_sha256.{mesh_id}",
                        "evidence is bound to a different mesh digest than the provenance manifest",
                    )

        unknown_meshes = sorted(set(mesh_ids) - expected_mesh_set) if expected_mesh_set else []
        if unknown_meshes:
            _error(
                errors,
                "EVIDENCE_SCOPE_UNKNOWN_MESH",
                f"{path}.scope.mesh_ids",
                f"evidence names mesh ids not present in submission: {unknown_meshes}",
            )

        required_claim = claim in MESH_CLAIMS or claim in VOLUME_CLAIMS
        target = _verify_local_artifact(
            raw,
            path=path,
            root_dir=root_dir,
            errors=errors,
            required=require_local_artifacts and required_claim,
        )

        normalization = raw.get("normalization")
        adapter = (
            normalization.get("adapter")
            if isinstance(normalization, dict)
            else None
        )
        effective_status = status
        approved = APPROVED_PASS_ADAPTERS.get(str(claim), frozenset())
        if status in {"pass", "fail"} and required_claim and adapter not in approved:
            warnings.append(
                {
                    "code": "EVIDENCE_VERDICT_NOT_AUTHORIZED",
                    "path": f"{path}.normalization.adapter",
                    "message": (
                        f"{claim!r} has no approved adapter-backed verdict in this "
                        "policy version; treating the declared {status!r} as unknown"
                    ),
                }
            )
            effective_status = "unknown"

        native_report: dict[str, Any] | None = None
        if target is not None and isinstance(adapter, str) and adapter in ASSESSORS:
            try:
                native_report = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                _error(
                    errors,
                    "EVIDENCE_NATIVE_REPORT_UNREADABLE",
                    f"{path}.path",
                    f"cannot read adapter source report: {exc}",
                )
            else:
                mismatches = verify_normalized_entry(raw, native_report)
                for mismatch in mismatches:
                    _error(
                        errors,
                        "EVIDENCE_NORMALIZATION_MISMATCH",
                        path,
                        mismatch,
                    )

        # A native diagnostic may authorize a geometry verdict (PASS or FAIL)
        # only if its own format binds the measurement to the exact submitted
        # mesh bytes. The ledger's current-mesh digest alone cannot prove that
        # a stale report consumed them.
        if (
            effective_status in {"pass", "fail"}
            and claim in MESH_CLAIMS
            and adapter in APPROVED_PASS_ADAPTERS.get(str(claim), frozenset())
        ):
            if native_report is None:
                if require_local_artifacts:
                    _error(
                        errors,
                        "EVIDENCE_NATIVE_BINDING_REQUIRED",
                        path,
                        "approved mesh verdict requires a locally re-verifiable native report",
                    )
                else:
                    effective_status = "unknown"
                    warnings.append(
                        {
                            "code": "EVIDENCE_NATIVE_BINDING_UNVERIFIED",
                            "path": path,
                            "message": (
                                "approved mesh verdict was not byte-bound because local "
                                "native evidence was not re-verified"
                            ),
                        }
                    )
            else:
                bindings: list[dict[str, Any]] = []
                for mesh_id in mesh_ids:
                    rel_mesh = expected_paths.get(mesh_id)
                    if root_dir is None or not isinstance(rel_mesh, str) or not rel_mesh:
                        bindings.append(
                            {
                                "mesh_id": mesh_id,
                                "status": "unbound",
                                "reason": "submission mesh path is unavailable",
                            }
                        )
                        continue
                    mesh_target = (root_dir.resolve() / rel_mesh).resolve()
                    try:
                        mesh_target.relative_to(root_dir.resolve())
                    except ValueError:
                        bindings.append(
                            {
                                "mesh_id": mesh_id,
                                "status": "mismatch",
                                "reason": "submission mesh path escapes package root",
                            }
                        )
                        continue
                    result = verify_native_mesh_identity(
                        str(adapter), native_report, mesh_target
                    )
                    bindings.append({"mesh_id": mesh_id, **result})

                non_exact = [b for b in bindings if b.get("status") != "exact"]
                if non_exact:
                    effective_status = "unknown"
                    for binding in non_exact:
                        _error(
                            errors,
                            "EVIDENCE_NATIVE_MESH_BINDING",
                            path,
                            (
                                f"{binding.get('mesh_id')}: "
                                f"{binding.get('reason', 'native report is not byte-bound')}"
                            ),
                        )
                if isinstance(normalization, dict):
                    normalization = dict(normalization)
                    normalization["verified_mesh_binding"] = bindings

        normalized.append(
            {
                "id": entry_id,
                "claim": claim,
                "declared_status": status,
                "status": effective_status,
                "tool": tool,
                "artifact_url": raw.get("artifact_url"),
                "sha256": digest,
                "path": raw.get("path"),
                "scope": {
                    "mesh_ids": list(mesh_ids),
                    "mesh_sha256": dict(mesh_sha256),
                },
                "producer": {
                    "repository": producer.get("repository"),
                    "commit": producer.get("commit"),
                    "command": producer.get("command"),
                },
                "normalization": normalization,
                "summary": raw.get("summary"),
            }
        )

    required_claims = [
        _claim_summary(
            claim,
            normalized,
            mesh_scoped=True,
            expected_mesh_ids=expected_mesh_set,
        )
        for claim in MESH_CLAIMS
    ]
    required_claims.extend(
        _claim_summary(
            claim,
            normalized,
            mesh_scoped=False,
            expected_mesh_ids=expected_mesh_set,
        )
        for claim in VOLUME_CLAIMS
    )
    advisory_claims = [
        _claim_summary(
            claim,
            normalized,
            mesh_scoped=claim in MESH_ADVISORY_CLAIMS,
            expected_mesh_ids=expected_mesh_set,
        )
        for claim in ADVISORY_CLAIMS
    ]

    required_statuses = {item["status"] for item in required_claims}
    if errors or "fail" in required_statuses:
        status = "fail"
    elif required_statuses == {"pass"}:
        status = "pass"
    else:
        status = "partial"

    graph_sha256 = hashlib.sha256(
        json.dumps(
            ledger,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    return {
        "validator": "scrollq.evidence_ledger",
        "validator_schema_version": SCHEMA_VERSION,
        "policy": {
            "name": "ScrolIQ Grand Prize pre-submission evidence policy",
            "required_mesh_claims": list(MESH_CLAIMS),
            "required_volume_claims": list(VOLUME_CLAIMS),
            "advisory_claims": list(ADVISORY_CLAIMS),
            "official_prize_rule": False,
        },
        "volume_id": volume_id,
        "ledger_sha256": ledger_sha256,
        "graph_sha256": graph_sha256,
        "status": status,
        "ready": status == "pass",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "required_claims": required_claims,
        "advisory_claims": advisory_claims,
        "entries": normalized,
        "limitation": (
            "PASS means the submission has immutable evidence satisfying this "
            "ScrolIQ pre-submission policy. It is not an official Scroll Prize "
            "eligibility decision, does not prove papyrological legibility, and "
            "does not replace organizer evaluation."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Validate an independent Grand Prize evidence ledger"
    )
    ap.add_argument("--ledger", required=True, help="evidence ledger JSON")
    ap.add_argument("--volume-id", default=None, help="expected eligible volume id")
    ap.add_argument(
        "--mesh-id",
        action="append",
        default=[],
        help="expected submitted mesh id without local binding; repeat as needed",
    )
    ap.add_argument(
        "--mesh",
        action="append",
        default=[],
        metavar="ID=PATH",
        help=(
            "bind a submitted mesh id to its package-relative tifxyz path; "
            "repeat for every mesh when locally verifying PASS evidence"
        ),
    )
    ap.add_argument("--root-dir", default=None, help="optional local artifact root")
    ap.add_argument("--out", default=None, help="optional JSON report path")
    ap.add_argument("--format", choices=("text", "json", "github"), default="text")
    args = ap.parse_args()

    path = Path(args.ledger)
    raw = path.read_bytes()
    ledger = json.loads(raw)

    root_dir = Path(args.root_dir) if args.root_dir else None
    mesh_paths: dict[str, str] = {}
    mesh_digests: dict[str, str] = {}
    for spec in args.mesh:
        if "=" not in spec:
            ap.error("--mesh must use ID=PATH")
        mesh_id, rel = spec.split("=", 1)
        if not mesh_id or not rel:
            ap.error("--mesh must use non-empty ID=PATH")
        if mesh_id in mesh_paths:
            ap.error(f"duplicate --mesh id: {mesh_id}")
        if root_dir is None:
            ap.error("--mesh requires --root-dir")
        target = (root_dir / rel).resolve()
        try:
            target.relative_to(root_dir.resolve())
        except ValueError:
            ap.error(f"--mesh path escapes --root-dir: {rel}")
        try:
            mesh_digests[mesh_id] = sha256_path(target)
        except (OSError, ValueError) as exc:
            ap.error(f"cannot hash --mesh {mesh_id}: {exc}")
        mesh_paths[mesh_id] = rel

    mesh_ids = list(dict.fromkeys([*args.mesh_id, *mesh_paths]))
    report = validate_evidence_ledger(
        ledger,
        expected_volume_id=args.volume_id,
        expected_mesh_ids=mesh_ids,
        expected_mesh_sha256=mesh_digests,
        expected_mesh_paths=mesh_paths,
        root_dir=root_dir,
        ledger_sha256=hashlib.sha256(raw).hexdigest(),
        require_local_artifacts=bool(args.root_dir),
    )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "github":
        for item in report["errors"]:
            print(f"::error title={item['code']}::{item['path']}: {item['message']}")
        for claim in report["required_claims"]:
            if claim["status"] != "pass":
                print(
                    f"::warning title=EVIDENCE_{claim['status'].upper()}::"
                    f"{claim['claim']}: {claim['reason']}"
                )
        print(f"Independent evidence ledger: {report['status'].upper()}")
    else:
        print(f"Independent evidence ledger: {report['status'].upper()}")
        for claim in report["required_claims"]:
            print(f"- {claim['claim']}: {claim['status'].upper()} — {claim['reason']}")
        for item in report["errors"]:
            print(f"- {item['code']} {item['path']}: {item['message']}")

    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
