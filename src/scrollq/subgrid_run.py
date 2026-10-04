"""Reproducible, ink-blind adapter for the Subgrid Marching Tetrahedra candidate.

This adapter does not generate edge intersections and does not choose geometry
from ink. It consumes one frozen explicit .npz edge-intersection artifact,
verifies an exact clean upstream checkout, runs the default primal extractor,
and audits the produced OBJ. The result is a candidate-generation receipt, not
a claim that Subgrid is better than the current Vesuvius geometry pipeline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .obj_audit import audit_obj

SCHEMA_VERSION = 1
TOOL = "scroliq-subgrid-run"
UPSTREAM_REPOSITORY = "https://github.com/hbaktash/subgrid-marching"
PINNED_COMMIT = "bc4a04946025d9c27eab620555bf93c611cf0d73"
UPSTREAM_LICENSE = "MIT"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
NON_EVEN_RE = re.compile(r"non-even\s+tets\s*:\s*([0-9][0-9,]*)", re.IGNORECASE)


class SubgridRunError(ValueError):
    """Raised when the frozen Subgrid candidate contract cannot be honored."""


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = (
            exc.stderr.strip()
            if isinstance(exc, subprocess.CalledProcessError) and exc.stderr
            else str(exc)
        )
        raise SubgridRunError(f"cannot inspect Subgrid checkout: {detail}") from exc
    return result.stdout.strip()


def verify_checkout(
    checkout: str | Path,
    *,
    expected_commit: str = PINNED_COMMIT,
) -> dict[str, Any]:
    root = Path(checkout).expanduser().resolve()
    if not COMMIT_RE.fullmatch(expected_commit):
        raise SubgridRunError("expected_commit must be lowercase 40-hex")
    if not (root / ".git").exists():
        raise SubgridRunError(f"Subgrid root is not a Git checkout: {root}")

    head = _git(root, "rev-parse", "HEAD")
    if head != expected_commit:
        raise SubgridRunError(
            f"Subgrid HEAD mismatch: expected {expected_commit}, got {head}"
        )
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise SubgridRunError(
            "Subgrid checkout is dirty; recorded candidate runs require exact clean bytes"
        )

    executable = root / "build" / "subgrid"
    if not executable.is_file():
        raise SubgridRunError(
            f"missing headless primal executable: {executable}; build the pinned "
            "checkout with SUBGRID_POLYSCOPE_VIEWER=OFF"
        )
    license_path = root / "LICENSE"
    if not license_path.is_file():
        raise SubgridRunError("pinned Subgrid checkout is missing LICENSE")
    license_text = license_path.read_text(encoding="utf-8", errors="replace")
    if "MIT License" not in license_text:
        raise SubgridRunError("pinned Subgrid LICENSE does not identify the MIT License")

    return {
        "repository": UPSTREAM_REPOSITORY,
        "commit": head,
        "license": UPSTREAM_LICENSE,
        "checkout": str(root),
        "tree_sha": _git(root, "rev-parse", "HEAD^{tree}"),
        "executable": str(executable),
        "executable_sha256": _sha256(executable),
        "license_sha256": _sha256(license_path),
        "clean": True,
    }


def validate_explicit_npz(path: str | Path) -> dict[str, Any]:
    """Validate the pinned upstream explicit edge-intersection interchange."""
    src = Path(path).expanduser().resolve()
    if not src.is_file():
        raise SubgridRunError(f"explicit edge-intersection input does not exist: {src}")
    if src.suffix.lower() != ".npz":
        raise SubgridRunError("input_npz must use the explicit .npz interchange format")

    required = {"vertices", "tets", "edges", "isect_offsets", "isect_ts"}
    try:
        with np.load(src, allow_pickle=False) as archive:
            missing = sorted(required - set(archive.files))
            if missing:
                raise SubgridRunError(
                    "explicit .npz is missing required array(s): " + ", ".join(missing)
                )
            vertices = np.asarray(archive["vertices"])
            tets = np.asarray(archive["tets"])
            edges = np.asarray(archive["edges"])
            offsets = np.asarray(archive["isect_offsets"])
            ts = np.asarray(archive["isect_ts"])
            normals = (
                np.asarray(archive["isect_normals"])
                if "isect_normals" in archive.files
                else None
            )
    except (OSError, ValueError) as exc:
        raise SubgridRunError(f"cannot read explicit .npz input: {exc}") from exc

    if vertices.ndim != 2 or vertices.shape[1:] != (3,) or len(vertices) < 4:
        raise SubgridRunError("vertices must have shape (V,3) with V >= 4")
    if not np.issubdtype(vertices.dtype, np.number) or not np.isfinite(vertices).all():
        raise SubgridRunError("vertices must contain finite numeric coordinates")
    if tets.ndim != 2 or tets.shape[1:] != (4,) or len(tets) < 1:
        raise SubgridRunError("tets must have shape (T,4) with T >= 1")
    if not np.issubdtype(tets.dtype, np.integer):
        raise SubgridRunError("tets must use an integer dtype")
    if int(tets.min()) < 0 or int(tets.max()) >= len(vertices):
        raise SubgridRunError("tets reference vertex indices outside vertices")
    if any(len(set(map(int, row))) != 4 for row in tets):
        raise SubgridRunError("each tet must reference four distinct vertices")

    if edges.ndim != 2 or edges.shape[1:] != (2,) or len(edges) < 1:
        raise SubgridRunError("edges must have shape (E,2) with E >= 1")
    if not np.issubdtype(edges.dtype, np.integer):
        raise SubgridRunError("edges must use an integer dtype")
    if int(edges.min()) < 0 or int(edges.max()) >= len(vertices):
        raise SubgridRunError("edges reference vertex indices outside vertices")
    if np.any(edges[:, 0] >= edges[:, 1]):
        raise SubgridRunError("every explicit edge must be stored with i < j")
    edge_pairs = [tuple(map(int, row)) for row in edges]
    if len(edge_pairs) != len(set(edge_pairs)):
        raise SubgridRunError("explicit edges contain duplicate vertex pairs")

    if offsets.ndim != 1 or len(offsets) != len(edges) + 1:
        raise SubgridRunError("isect_offsets must have shape (E+1,)")
    if not np.issubdtype(offsets.dtype, np.integer):
        raise SubgridRunError("isect_offsets must use an integer dtype")
    offsets64 = offsets.astype(np.int64, copy=False)
    if int(offsets64[0]) != 0 or np.any(np.diff(offsets64) <= 0):
        raise SubgridRunError(
            "isect_offsets must start at zero and give every stored edge >=1 intersection"
        )

    if ts.ndim != 1 or not np.issubdtype(ts.dtype, np.number):
        raise SubgridRunError("isect_ts must be a one-dimensional numeric array")
    if int(offsets64[-1]) != len(ts):
        raise SubgridRunError("isect_offsets final value must equal len(isect_ts)")
    if len(ts) < 1 or not np.isfinite(ts).all() or np.any((ts < 0) | (ts > 1)):
        raise SubgridRunError("isect_ts must be finite values in [0,1]")
    for edge_index in range(len(edges)):
        values = ts[offsets64[edge_index] : offsets64[edge_index + 1]]
        if np.any(values[1:] < values[:-1]):
            raise SubgridRunError(
                f"isect_ts for edge {edge_index} are not sorted ascending"
            )

    if normals is not None:
        if (
            normals.ndim != 2
            or normals.shape != (len(ts), 3)
            or not np.issubdtype(normals.dtype, np.number)
            or not np.isfinite(normals).all()
        ):
            raise SubgridRunError(
                "optional isect_normals must have finite numeric shape (N_total,3)"
            )

    return {
        "path": str(src),
        "sha256": _sha256(src),
        "bytes": src.stat().st_size,
        "vertices": int(len(vertices)),
        "tets": int(len(tets)),
        "edges_with_intersections": int(len(edges)),
        "intersections": int(len(ts)),
        "normals_present": normals is not None,
        "contract": (
            "hbaktash/subgrid-marching explicit_input_format.md at "
            f"{PINNED_COMMIT}"
        ),
    }


def _non_even_tets(stdout_path: Path) -> dict[str, Any]:
    try:
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"status": "unknown", "observations": []}
    values = [int(match.group(1).replace(",", "")) for match in NON_EVEN_RE.finditer(text)]
    unique = sorted(set(values))
    return {
        "status": "measured" if values else "unknown",
        "observations": values,
        "unique_values": unique,
        "consistent": len(unique) <= 1,
        "value": unique[0] if len(unique) == 1 else None,
        "interpretation": (
            "A nonzero count can be expected for open input surfaces; it is recorded "
            "as a diagnostic and is not an automatic correctness verdict."
        ),
    }


def _semantic_gates(audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    mesh = audit.get("mesh") if isinstance(audit.get("mesh"), dict) else {}
    vertices = mesh.get("vertices")
    triangles = mesh.get("triangles")
    area = mesh.get("surface_area")
    return [
        {
            "name": "obj_audit_decodes",
            "passed": audit.get("status") != "fail",
            "observed": audit.get("status"),
            "requirement": "scroliq-obj status must not be fail",
        },
        {
            "name": "nonempty_vertices",
            "passed": type(vertices) is int and vertices > 0,
            "observed": vertices,
            "requirement": "> 0",
        },
        {
            "name": "nonempty_triangles",
            "passed": type(triangles) is int and triangles > 0,
            "observed": triangles,
            "requirement": "> 0",
        },
        {
            "name": "finite_positive_surface_area",
            "passed": (
                isinstance(area, (int, float))
                and not isinstance(area, bool)
                and float(area) > 0
                and float(area) < float("inf")
            ),
            "observed": area,
            "requirement": "finite and > 0",
        },
    ]


def run_candidate(
    *,
    checkout: str | Path,
    input_npz: str | Path,
    output_obj: str | Path,
    stdout_log: str | Path,
    stderr_log: str | Path,
    expected_commit: str = PINNED_COMMIT,
) -> dict[str, Any]:
    """Run the frozen default primal Subgrid candidate on explicit intersections."""
    upstream = verify_checkout(checkout, expected_commit=expected_commit)
    input_evidence = validate_explicit_npz(input_npz)
    input_path = Path(input_evidence["path"])
    output_path = Path(output_obj).expanduser().resolve()
    stdout_path = Path(stdout_log).expanduser().resolve()
    stderr_path = Path(stderr_log).expanduser().resolve()
    for path, label in (
        (output_path, "output OBJ"),
        (stdout_path, "stdout log"),
        (stderr_path, "stderr log"),
    ):
        if path.exists():
            raise SubgridRunError(
                f"{label} already exists before launch: {path}; refusing stale evidence"
            )
        path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        upstream["executable"],
        "--npz",
        str(input_path),
        "-o",
        str(output_path),
        "--noViz",
        "--noPBar",
    ]
    started = _utc_now()
    t0 = time.monotonic()
    launch_error: str | None = None
    return_code: int | None = None
    try:
        with stdout_path.open("x", encoding="utf-8") as out, stderr_path.open(
            "x", encoding="utf-8"
        ) as err:
            result = subprocess.run(
                command,
                cwd=upstream["checkout"],
                stdout=out,
                stderr=err,
                text=True,
                check=False,
            )
            return_code = int(result.returncode)
    except OSError as exc:
        launch_error = str(exc)
        if not stdout_path.exists():
            stdout_path.touch()
        if not stderr_path.exists():
            stderr_path.write_text(launch_error + "\n", encoding="utf-8")

    finished = _utc_now()
    duration = time.monotonic() - t0
    output_exists = output_path.is_file()
    audit = (
        audit_obj(output_path)
        if output_exists
        else {
            "status": "fail",
            "obj_path": str(output_path),
            "errors": ["expected OBJ output does not exist after Subgrid command"],
        }
    )

    gates = [
        {
            "name": "process_exit_zero",
            "passed": return_code == 0 and launch_error is None,
            "observed": return_code,
            "launch_error": launch_error,
            "requirement": "process must launch and exit 0",
        },
        {
            "name": "new_output_present",
            "passed": output_exists,
            "observed": str(output_path),
            "requirement": "expected OBJ must be newly created",
        },
        *_semantic_gates(audit),
    ]
    passed = all(bool(gate["passed"]) for gate in gates)
    non_even = _non_even_tets(stdout_path)

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "status": "pass" if passed else "fail",
        "experiment_role": "geometry_candidate_only",
        "ink_blind": True,
        "selection_policy": (
            "Do not inspect ink while selecting this candidate. Compare against the "
            "baseline only on preregistered held-out geometry/topology/flattening evidence."
        ),
        "started_at": started,
        "finished_at": finished,
        "duration_seconds": duration,
        "upstream": upstream,
        "input": {
            "format": "subgrid-explicit-edge-intersections-npz",
            **input_evidence,
        },
        "command": command,
        "process": {
            "return_code": return_code,
            "launch_error": launch_error,
            "exit_zero_but_postcondition_failed": (
                return_code == 0 and launch_error is None and not passed
            ),
        },
        "logs": {
            "stdout": {
                "path": str(stdout_path),
                "sha256": _sha256(stdout_path),
                "bytes": stdout_path.stat().st_size,
            },
            "stderr": {
                "path": str(stderr_path),
                "sha256": _sha256(stderr_path),
                "bytes": stderr_path.stat().st_size,
            },
        },
        "output": {
            "path": str(output_path),
            "sha256": _sha256(output_path) if output_exists else None,
            "bytes": output_path.stat().st_size if output_exists else None,
            "audit": audit,
        },
        "non_even_tets": non_even,
        "gates": gates,
        "proof_gate": "SUBGRID_CANDIDATE_EXECUTION_INTEGRITY",
        "proof_gate_pass": passed,
        "limitations": (
            "This receipt establishes reproducible execution of one Subgrid candidate "
            "from frozen edge intersections. It does not establish that the edge "
            "intersections are correct, that the mesh follows the intended papyrus "
            "sheet, that the upstream mathematical self-intersection guarantee covers "
            "numerical/integration mistakes, or that this candidate beats the baseline."
        ),
    }


def _write_json_create_only(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--input-npz", required=True)
    parser.add_argument("--output-obj", required=True)
    parser.add_argument("--stdout-log", required=True)
    parser.add_argument("--stderr-log", required=True)
    parser.add_argument("--out", required=True, help="create-only JSON receipt")
    parser.add_argument(
        "--expected-commit",
        default=PINNED_COMMIT,
        help="exact upstream commit; defaults to the ScrollQ-reviewed candidate pin",
    )
    args = parser.parse_args(argv)

    try:
        out = Path(args.out)
        if out.exists():
            parser.error(f"receipt already exists: {out}")
        report = run_candidate(
            checkout=args.checkout,
            input_npz=args.input_npz,
            output_obj=args.output_obj,
            stdout_log=args.stdout_log,
            stderr_log=args.stderr_log,
            expected_commit=args.expected_commit,
        )
        _write_json_create_only(out, report)
    except (OSError, SubgridRunError, ValueError) as exc:
        parser.error(str(exc))

    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["proof_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
