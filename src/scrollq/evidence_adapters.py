"""Deterministic adapters from native community diagnostics to ScrolIQ evidence.

Only adapters with a crisp native decision rule may authorize PASS. Ambiguous
or purely descriptive diagnostics belong in the ledger as partial/unknown until
a separate, pre-registered acceptance policy exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from .package_hash import sha256_path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

FLATCHECK_ADAPTER = "flatcheck-grid/v1"
WINDCHECK_ADAPTER = "windcheck-check/v1"

ADAPTER_REPOSITORIES = {
    FLATCHECK_ADAPTER: "https://github.com/abundantjoe/flatcheck",
    WINDCHECK_ADAPTER: "https://github.com/joe-carr-data/windcheck",
}

# These are the only adapter/claim pairs allowed to turn a required claim into
# PASS in evidence policy v1.
APPROVED_PASS_ADAPTERS = {
    # flatcheck/v1 is intentionally evidence-only for now: its native JSON
    # names a path but does not content-bind the tifxyz bytes it scored.
    "flattening-isometry": frozenset(),
    # windcheck_check/v1 embeds a full semantic TIFXYZ content manifest. The
    # readiness gate independently compares that manifest with the submitted
    # mesh before allowing PASS.
    "mesh-self-intersection": frozenset({WINDCHECK_ADAPTER}),
}


class NativeEvidenceError(ValueError):
    """Native report is missing the semantics required by an adapter."""


SEMANTIC_TIFXYZ_FILES = (
    "x.tif",
    "y.tif",
    "z.tif",
    "mask.tif",
    "mask.png",
    "meta.json",
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _windcheck_manifest_digest(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in sorted(rows, key=lambda item: str(item.get("path"))):
        path = row.get("path")
        if not isinstance(path, str):
            raise NativeEvidenceError("windcheck mesh manifest row.path must be a string")
        if row.get("present") is True and isinstance(row.get("sha256"), str):
            size = row.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise NativeEvidenceError(
                    f"windcheck mesh manifest {path!r} size must be a non-negative integer"
                )
            lines.append(f"{path}\0{size}\0{row['sha256']}")
        else:
            lines.append(f"{path}\0absent\0absent")
    blob = ("\n".join(lines) + "\n").encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def verify_native_mesh_identity(
    adapter: str,
    report: dict[str, Any],
    mesh_path: str | Path,
) -> dict[str, Any]:
    """Verify that a native report is about the exact submitted mesh bytes.

    A path/name match is not sufficient. Adapters may authorize PASS only when
    the native format exposes enough content identity to reproduce this check.
    """
    mesh = Path(mesh_path)
    if not mesh.is_dir():
        return {
            "status": "mismatch",
            "reason": f"submitted mesh is not a directory: {mesh}",
        }

    if adapter == FLATCHECK_ADAPTER:
        return {
            "status": "unbound",
            "reason": (
                "flatcheck native JSON does not content-hash its input tifxyz; "
                "path equality cannot prove the report scored the submitted bytes"
            ),
        }

    if adapter != WINDCHECK_ADAPTER:
        return {
            "status": "unbound",
            "reason": f"adapter {adapter!r} has no exact mesh-identity verifier",
        }

    mesh_block = report.get("mesh")
    hashes = mesh_block.get("hashes") if isinstance(mesh_block, dict) else None
    if not isinstance(hashes, dict):
        return {
            "status": "unbound",
            "reason": "windcheck certificate does not contain mesh.hashes",
        }
    if hashes.get("schema") != "windcheck_mesh_manifest/v1":
        return {
            "status": "unbound",
            "reason": "unsupported windcheck mesh manifest schema",
        }
    rows = hashes.get("files")
    if not isinstance(rows, list):
        return {
            "status": "unbound",
            "reason": "windcheck mesh manifest has no files list",
        }

    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            return {
                "status": "mismatch",
                "reason": "windcheck mesh manifest contains a malformed row",
            }
        name = row["path"]
        if name in by_name:
            return {
                "status": "mismatch",
                "reason": f"windcheck mesh manifest duplicates {name!r}",
            }
        by_name[name] = row

    if set(by_name) != set(SEMANTIC_TIFXYZ_FILES):
        return {
            "status": "unbound",
            "reason": (
                "windcheck mesh manifest does not declare exactly the semantic "
                "tifxyz file set expected by windcheck_mesh_manifest/v1"
            ),
        }

    try:
        computed_manifest_digest = _windcheck_manifest_digest(rows)
    except NativeEvidenceError as exc:
        return {"status": "mismatch", "reason": str(exc)}
    if hashes.get("digest") != computed_manifest_digest:
        return {
            "status": "mismatch",
            "reason": "windcheck mesh manifest digest contradicts its file rows",
        }

    mismatches: list[str] = []
    for name in SEMANTIC_TIFXYZ_FILES:
        row = by_name[name]
        path = mesh / name
        present = path.is_file()
        if row.get("present") is not present:
            mismatches.append(f"{name}: presence differs")
            continue
        if not present:
            continue
        expected_size = row.get("size")
        expected_sha = row.get("sha256")
        if path.stat().st_size != expected_size:
            mismatches.append(f"{name}: byte length differs")
            continue
        if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
            mismatches.append(f"{name}: certificate sha256 is invalid")
            continue
        if _sha256_file(path) != expected_sha:
            mismatches.append(f"{name}: sha256 differs")

    if mismatches:
        return {
            "status": "mismatch",
            "reason": "; ".join(mismatches),
            "manifest_digest": computed_manifest_digest,
        }
    return {
        "status": "exact",
        "reason": (
            "windcheck semantic manifest exactly matches x/y/z, masks, and meta.json "
            "in the submitted tifxyz"
        ),
        "manifest_digest": computed_manifest_digest,
    }


def assess_flatcheck(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise NativeEvidenceError("flatcheck report must be a JSON object")
    window = report.get("window")
    if not isinstance(window, dict):
        raise NativeEvidenceError("flatcheck report.window is required")
    if window.get("rows") is not None or window.get("cols") is not None:
        raise NativeEvidenceError(
            "flattening-isometry requires a whole-mesh report, not a row/column window"
        )

    results = report.get("results")
    if not isinstance(results, dict) or not isinstance(results.get("grid"), dict):
        raise NativeEvidenceError(
            "flatcheck report.results.grid is required; the submitted tifxyz grid "
            "is the render canvas"
        )
    grid = results["grid"]
    passes_bar = grid.get("passes_bar")
    collapse = grid.get("collapse")
    fold_overs = grid.get("fold_overs")
    pct = grid.get("pct_quads_within_5pct")
    bar = grid.get("bar_pct")
    if not isinstance(passes_bar, bool):
        raise NativeEvidenceError("flatcheck grid.passes_bar must be boolean")
    if not isinstance(collapse, dict) or not isinstance(collapse.get("collapsed"), bool):
        raise NativeEvidenceError("flatcheck grid.collapse.collapsed must be boolean")
    if not isinstance(fold_overs, int) or isinstance(fold_overs, bool) or fold_overs < 0:
        raise NativeEvidenceError("flatcheck grid.fold_overs must be a non-negative integer")
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        raise NativeEvidenceError("flatcheck grid.pct_quads_within_5pct must be numeric")
    if not isinstance(bar, (int, float)) or isinstance(bar, bool):
        raise NativeEvidenceError("flatcheck grid.bar_pct must be numeric")

    clean = passes_bar and not collapse["collapsed"] and fold_overs == 0
    return {
        "claim": "flattening-isometry",
        "status": "pass" if clean else "fail",
        "tool": "flatcheck",
        "summary": {
            "whole_mesh": True,
            "grid_pct_quads_within_5pct": float(pct),
            "bar_pct": float(bar),
            "fold_overs": fold_overs,
            "collapsed": collapse["collapsed"],
            "passes_bar": passes_bar,
        },
    }


def assess_windcheck(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise NativeEvidenceError("windcheck certificate must be a JSON object")
    if report.get("tool") != "windcheck check":
        raise NativeEvidenceError("windcheck certificate tool must be 'windcheck check'")
    if report.get("schema") != "windcheck_check/v1":
        raise NativeEvidenceError("unsupported windcheck certificate schema")
    if report.get("report_only") is not True:
        raise NativeEvidenceError("windcheck check evidence must be report-only")

    measurements = report.get("measurements")
    if not isinstance(measurements, dict):
        raise NativeEvidenceError("windcheck measurements are required")
    d0 = measurements.get("transverse_d0")
    d1 = measurements.get("transverse_d1")
    if not all(
        isinstance(v, int) and not isinstance(v, bool) and v >= 0
        for v in (d0, d1)
    ):
        raise NativeEvidenceError(
            "windcheck transverse_d0/transverse_d1 must be non-negative integers"
        )
    clean = report.get("clean")
    if not isinstance(clean, bool):
        raise NativeEvidenceError("windcheck clean must be boolean")
    expected_clean = d0 == 0 and d1 == 0
    if clean != expected_clean:
        raise NativeEvidenceError(
            "windcheck clean flag contradicts the two transverse-contact counts"
        )
    definition = report.get("clean_definition")
    if not isinstance(definition, str) or not definition:
        raise NativeEvidenceError("windcheck clean_definition is required")

    events = measurements.get("crossing_events")
    if not isinstance(events, int) or isinstance(events, bool) or events < 0:
        raise NativeEvidenceError("windcheck crossing_events must be a non-negative integer")

    return {
        "claim": "mesh-self-intersection",
        "status": "pass" if clean else "fail",
        "tool": "windcheck",
        "summary": {
            "clean": clean,
            "transverse_d0": d0,
            "transverse_d1": d1,
            "crossing_events": events,
            "clean_definition": definition,
        },
    }


ASSESSORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    FLATCHECK_ADAPTER: assess_flatcheck,
    WINDCHECK_ADAPTER: assess_windcheck,
}


def assess_native(adapter: str, report: dict[str, Any]) -> dict[str, Any]:
    fn = ASSESSORS.get(adapter)
    if fn is None:
        raise NativeEvidenceError(f"unsupported evidence adapter: {adapter}")
    return fn(report)


def normalize_native_report(
    *,
    adapter: str,
    report: dict[str, Any],
    entry_id: str,
    mesh_id: str,
    artifact_url: str,
    sha256: str,
    path: str,
    mesh_sha256: str,
    producer_commit: str,
    command: str,
) -> dict[str, Any]:
    assessment = assess_native(adapter, report)
    if not isinstance(entry_id, str) or not entry_id:
        raise NativeEvidenceError("entry_id is required")
    if not isinstance(mesh_id, str) or not mesh_id:
        raise NativeEvidenceError("mesh_id is required")
    if not isinstance(artifact_url, str) or not artifact_url.startswith(("https://", "http://")):
        raise NativeEvidenceError("artifact_url must be public http(s)")
    if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
        raise NativeEvidenceError("sha256 must be lowercase 64-hex")
    if not isinstance(mesh_sha256, str) or not SHA256_RE.fullmatch(mesh_sha256):
        raise NativeEvidenceError("mesh_sha256 must be lowercase 64-hex")
    if not isinstance(producer_commit, str) or not COMMIT_RE.fullmatch(producer_commit):
        raise NativeEvidenceError("producer_commit must be lowercase 40-hex")
    if not isinstance(command, str) or not command.strip():
        raise NativeEvidenceError("reproduction command is required")
    if not isinstance(path, str) or not path:
        raise NativeEvidenceError("package-relative report path is required")

    return {
        "id": entry_id,
        "claim": assessment["claim"],
        "status": assessment["status"],
        "tool": assessment["tool"],
        "artifact_url": artifact_url,
        "sha256": sha256,
        "path": path,
        "scope": {
            "mesh_ids": [mesh_id],
            "mesh_sha256": {mesh_id: mesh_sha256},
        },
        "producer": {
            "repository": ADAPTER_REPOSITORIES[adapter],
            "commit": producer_commit,
            "command": command,
        },
        "normalization": {
            "adapter": adapter,
            "assessment": assessment["summary"],
        },
        "summary": assessment["summary"],
    }


def verify_normalized_entry(
    entry: dict[str, Any], native_report: dict[str, Any]
) -> list[str]:
    normalization = entry.get("normalization")
    if not isinstance(normalization, dict):
        return ["normalization object is required for an adapter-backed entry"]
    adapter = normalization.get("adapter")
    if not isinstance(adapter, str):
        return ["normalization.adapter is required"]
    try:
        assessment = assess_native(adapter, native_report)
    except NativeEvidenceError as exc:
        return [str(exc)]

    mismatches: list[str] = []
    for field in ("claim", "status", "tool"):
        if entry.get(field) != assessment[field]:
            mismatches.append(
                f"{field}={entry.get(field)!r} does not match adapter result "
                f"{assessment[field]!r}"
            )
    if normalization.get("assessment") != assessment["summary"]:
        mismatches.append("normalization.assessment does not match native report")
    if entry.get("summary") != assessment["summary"]:
        mismatches.append("summary does not match native report")
    return mismatches


def _main() -> int:
    ap = argparse.ArgumentParser(
        prog="scroliq-evidence-import",
        description="Normalize a native independent diagnostic into one ledger entry",
    )
    sub = ap.add_subparsers(dest="kind", required=True)
    for kind in ("flatcheck", "windcheck"):
        p = sub.add_parser(kind)
        p.add_argument("--report", required=True)
        p.add_argument("--mesh-id", required=True)
        p.add_argument("--artifact-url", required=True)
        p.add_argument(
            "--mesh-path",
            required=True,
            help="exact submitted tifxyz directory; its canonical tree digest is recorded",
        )
        p.add_argument("--producer-commit", required=True)
        p.add_argument("--command", required=True)
        p.add_argument("--entry-id", default=None)
        p.add_argument("--out", default=None)

    args = ap.parse_args()
    adapter = FLATCHECK_ADAPTER if args.kind == "flatcheck" else WINDCHECK_ADAPTER
    path = Path(args.report)
    raw = path.read_bytes()
    report = json.loads(raw)
    mesh_path = Path(args.mesh_path)
    native_mesh = (
        report.get("mesh")
        if adapter == FLATCHECK_ADAPTER
        else (report.get("mesh") or {}).get("path")
    )
    if not isinstance(native_mesh, str) or Path(native_mesh).name != mesh_path.name:
        raise NativeEvidenceError(
            "native report mesh path does not match --mesh-path basename"
        )
    entry = normalize_native_report(
        adapter=adapter,
        report=report,
        entry_id=args.entry_id or f"{args.kind}:{args.mesh_id}",
        mesh_id=args.mesh_id,
        artifact_url=args.artifact_url,
        sha256=hashlib.sha256(raw).hexdigest(),
        path=args.report,
        mesh_sha256=sha256_path(mesh_path),
        producer_commit=args.producer_commit,
        command=args.command,
    )
    payload = json.dumps(entry, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


def main() -> None:
    raise SystemExit(_main())


if __name__ == "__main__":
    main()
