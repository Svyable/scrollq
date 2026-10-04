"""Run an external VC3D geometry command and require semantic TIFXYZ output.

Exit code zero is not sufficient evidence of a successful geometry run. This
guard refuses stale outputs, captures immutable logs, then reuses ScrolIQ's
TIFXYZ audit to require a newly produced, non-empty, physically plausible
surface whose spatial metadata agrees with its own vertices and which is not a
no-op copy of a declared input.

A producer that exits 0 while a postcondition fails is reported as
``PRODUCER_SEMANTIC_FAILURE``, never as success.

The guard records execution integrity only. It does not prove sheet identity,
CT support, held-out accuracy, or Grand Prize readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .tifxyz_audit import audit_tifxyz, geometry_digest

SCHEMA_VERSION = 2
TOOL = "scroliq-vc3d-run-guard"

VERDICT_OK = "PRODUCER_OK"
VERDICT_SEMANTIC_FAILURE = "PRODUCER_SEMANTIC_FAILURE"
VERDICT_PROCESS_FAILURE = "PRODUCER_PROCESS_FAILURE"
INPUT_RELATIONS = ("differs", "grows")
# Producers quantize bounds to integer voxels, so a sub-voxel excess is rounding
# rather than staleness. The 654-slice defect that motivated this gate is far
# outside it. Frozen here; widening it is a protocol change, not a tuning knob.
DEFAULT_BBOX_TOLERANCE_VOXELS = 1.0


class VC3DRunGuardError(ValueError):
    """Raised when the guarded run contract is invalid."""


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


def _write_json_create_only(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")


def _resolve_executable(command: Sequence[str]) -> dict[str, Any]:
    if not command:
        raise VC3DRunGuardError("guarded command must not be empty")
    token = command[0]
    if os.path.sep in token:
        candidate = Path(token).expanduser()
    else:
        discovered = shutil.which(token)
        if discovered is None:
            return {"requested": token, "resolved": None, "sha256": None}
        candidate = Path(discovered)
    try:
        resolved = candidate.resolve()
    except OSError:
        return {"requested": token, "resolved": str(candidate), "sha256": None}
    return {
        "requested": token,
        "resolved": str(resolved),
        "sha256": _sha256(resolved) if resolved.is_file() else None,
    }


def _gate(
    name: str,
    passed: bool,
    requirement: str,
    *,
    evaluated: bool = True,
    **observed: Any,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "evaluated": bool(evaluated),
        "requirement": requirement,
        **observed,
    }


def _positive_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def read_volume_meta(path: str | Path) -> dict[str, Any]:
    """Read operator-supplied VC3D-style volume metadata for cross-checking.

    The file must carry ``voxelsize`` (micrometres; ``voxel_size_um`` is also
    accepted). ``width``/``height``/``slices`` (x, y, z extent in voxels) are
    optional and enable the volume-bounds gate. The guard never fetches this
    itself: the reported failure was precisely a producer reading voxel-size
    metadata through a path that cannot work on ``s3://``, so the operator
    supplies a local copy and the receipt hashes it.
    """
    meta_path = Path(path)
    if not meta_path.is_file():
        raise VC3DRunGuardError(f"volume metadata is not a file: {meta_path}")
    raw = meta_path.read_bytes()
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise VC3DRunGuardError(f"volume metadata is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise VC3DRunGuardError("volume metadata must be a JSON object")
    voxel = document.get("voxelsize", document.get("voxel_size_um"))
    if not _positive_finite(voxel):
        raise VC3DRunGuardError(
            "volume metadata must carry a finite positive voxelsize (or voxel_size_um)"
        )
    dims = [document.get(key) for key in ("width", "height", "slices")]
    dimensions = (
        [int(d) for d in dims]
        if all(type(d) is int and d > 0 for d in dims)
        else None
    )
    return {
        "path": str(meta_path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "voxelsize_um": float(voxel),
        "dimensions_xyz": dimensions,
    }


def _snapshot_inputs(inputs: Sequence[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in inputs:
        path = Path(item)
        if not path.is_dir():
            raise VC3DRunGuardError(f"input TIFXYZ is not a directory: {path}")
        try:
            digest = geometry_digest(path)
        except ValueError as exc:
            raise VC3DRunGuardError(
                f"input TIFXYZ is unreadable ({exc}): {path}; refusing to launch"
            ) from exc
        rows.append({"path": str(path), **digest})
    return rows


def evaluate_postconditions(
    audit: Mapping[str, Any],
    *,
    output: Path | None,
    voxel_size_um: float,
    min_valid_vertices: int,
    min_valid_quads: int,
    min_area_cm2: float,
    require_ct_preflight: bool,
    input_snapshots: Sequence[Mapping[str, Any]] = (),
    inputs_after: Sequence[Mapping[str, Any]] = (),
    input_relation: str = "differs",
    volume_meta: Mapping[str, Any] | None = None,
    require_verified_voxel_spacing: bool = False,
    bbox_tolerance_voxels: float = DEFAULT_BBOX_TOLERANCE_VOXELS,
) -> dict[str, Any]:
    """Evaluate every geometry postcondition for one produced TIFXYZ surface.

    Pure with respect to the process: it takes an audit of the produced
    surface and returns gates plus the physical/extent facts they rest on.
    Every number comes from the vertex coordinates; nothing here reads an
    area, extent or bbox the producer claims about itself, except to compare
    it against the recomputed value.
    """
    grid = audit.get("grid") if isinstance(audit.get("grid"), dict) else {}
    quads = audit.get("quads") if isinstance(audit.get("quads"), dict) else {}
    bbox = audit.get("bbox") if isinstance(audit.get("bbox"), dict) else {}
    valid_vertices = grid.get("valid_vertices")
    valid_quads = quads.get("valid_quads")
    area_voxels2 = quads.get("surface_area_voxels2")

    area_cm2: float | None = None
    if (
        isinstance(area_voxels2, (int, float))
        and not isinstance(area_voxels2, bool)
        and math.isfinite(float(area_voxels2))
        and float(area_voxels2) >= 0
    ):
        cm_per_voxel = float(voxel_size_um) / 10_000.0
        area_cm2 = float(area_voxels2) * cm_per_voxel * cm_per_voxel

    ct_preflight = (
        audit.get("ct_preflight")
        if isinstance(audit.get("ct_preflight"), dict)
        else {}
    )

    # -- voxel spacing: declared value vs an independent, hashed source -----
    sources: list[dict[str, Any]] = []
    if volume_meta is not None:
        sources.append(
            {
                "kind": "volume-meta",
                "path": volume_meta["path"],
                "sha256": volume_meta["sha256"],
                "voxelsize_um": volume_meta["voxelsize_um"],
                "agrees": math.isclose(
                    float(voxel_size_um),
                    float(volume_meta["voxelsize_um"]),
                    rel_tol=1e-6,
                    abs_tol=1e-9,
                ),
            }
        )
    contradicted = any(not row["agrees"] for row in sources)
    verified = bool(sources) and not contradicted
    spacing_state = (
        "contradicted" if contradicted else "verified" if verified else "declared-only"
    )

    # -- spatial extent, recomputed from vertices ---------------------------
    observed_box = bbox.get("observed_bbox_xyz")
    extent: dict[str, Any] = {
        "observed_bbox_xyz": observed_box,
        "extent_voxels_xyz": None,
        "extent_um_xyz": None,
        "declared_bbox": {
            key: bbox.get(key)
            for key in (
                "status",
                "metadata_bbox_xyz",
                "stale_axes",
                "excess_voxels_xyz",
                "max_excess_voxels",
                "max_slack_voxels",
                "tolerance_voxels",
                "reason",
            )
            if key in bbox
        },
    }
    if (
        isinstance(observed_box, list)
        and len(observed_box) == 2
        and all(isinstance(r, list) and len(r) == 3 for r in observed_box)
    ):
        span = [float(hi) - float(lo) for lo, hi in zip(*observed_box)]
        extent["extent_voxels_xyz"] = span
        extent["extent_um_xyz"] = [s * float(voxel_size_um) for s in span]

    bbox_status = bbox.get("status")
    dimensions = volume_meta.get("dimensions_xyz") if volume_meta else None
    inside_volume: bool | None = None
    if dimensions and isinstance(observed_box, list) and extent["extent_voxels_xyz"]:
        inside_volume = all(
            float(lo) >= -bbox_tolerance_voxels
            and float(hi) <= float(dim) + bbox_tolerance_voxels
            for lo, hi, dim in zip(observed_box[0], observed_box[1], dimensions)
        )

    ct_evaluated = bool(require_ct_preflight) or ct_preflight.get("status") == "pass"
    gates = [
        _gate(
            "command_output_decodes",
            audit.get("status") != "fail",
            "TIFXYZ audit status must not be fail",
            observed=audit.get("status"),
        ),
        _gate(
            "valid_vertices",
            type(valid_vertices) is int and valid_vertices >= min_valid_vertices,
            f">= {min_valid_vertices}",
            observed=valid_vertices,
        ),
        _gate(
            "valid_quads",
            type(valid_quads) is int and valid_quads >= min_valid_quads,
            f">= {min_valid_quads}",
            observed=valid_quads,
        ),
        _gate(
            "finite_positive_surface_area",
            area_cm2 is not None
            and math.isfinite(area_cm2)
            and area_cm2 > 0
            and area_cm2 >= min_area_cm2,
            f">= {min_area_cm2:g} cm^2 and > 0",
            observed_cm2=area_cm2,
        ),
        _gate(
            "voxel_spacing_verified",
            not contradicted and (verified or not require_verified_voxel_spacing),
            (
                "declared voxel size must agree with an independent hashed source"
                if require_verified_voxel_spacing
                else "declared voxel size must not contradict an independent source"
            ),
            evaluated=bool(sources),
            observed=spacing_state,
        ),
        _gate(
            "spatial_metadata_consistent",
            bbox_status in ("consistent", "undeclared"),
            "extent must be recomputable and any declared bbox must contain "
            f"all valid vertices within {bbox_tolerance_voxels:g} voxel",
            observed=bbox_status,
            max_excess_voxels=bbox.get("max_excess_voxels"),
            stale_axes=bbox.get("stale_axes"),
        ),
        _gate(
            "extent_within_volume",
            inside_volume is True if dimensions else True,
            "recomputed extent must lie inside the declared volume dimensions",
            evaluated=bool(dimensions),
            observed=inside_volume,
            volume_dimensions_xyz=dimensions,
        ),
        _gate(
            "ct_volume_binding",
            ct_preflight.get("status") == "pass" if require_ct_preflight else True,
            (
                "validated CT preflight required"
                if require_ct_preflight
                else "not required for execution-integrity gate"
            ),
            evaluated=ct_evaluated,
            observed=ct_preflight.get("status", "unknown"),
        ),
    ]

    # -- artifact relation to declared inputs -------------------------------
    relation_rows: list[dict[str, Any]] = []
    output_digest: dict[str, Any] | None = None
    if input_snapshots:
        if output is not None and audit.get("status") != "fail":
            try:
                output_digest = geometry_digest(output)
            except ValueError:
                output_digest = None
        for before in input_snapshots:
            identical = (
                output_digest is not None
                and output_digest["coordinate_sha256"] == before["coordinate_sha256"]
            )
            grew = (
                output_digest is not None
                and output_digest["valid_vertices"] > before["valid_vertices"]
            )
            relation_rows.append(
                {
                    "path": before["path"],
                    "input_coordinate_sha256": before["coordinate_sha256"],
                    "input_valid_vertices": before["valid_vertices"],
                    "identical_geometry": identical,
                    "relation_ok": (
                        output_digest is not None
                        and not identical
                        and (grew if input_relation == "grows" else True)
                    ),
                }
            )
        after_by_path = {row["path"]: row["coordinate_sha256"] for row in inputs_after}
        unmodified = all(
            after_by_path.get(row["path"]) == row["coordinate_sha256"]
            for row in input_snapshots
        )
        gates.append(
            _gate(
                "output_differs_from_inputs",
                bool(relation_rows) and all(r["relation_ok"] for r in relation_rows),
                (
                    "output geometry digest must differ from every input"
                    if input_relation == "differs"
                    else "output must differ from every input and have more valid vertices"
                ),
                observed=relation_rows,
                relation=input_relation,
                output_coordinate_sha256=(
                    output_digest["coordinate_sha256"] if output_digest else None
                ),
            )
        )
        gates.append(
            _gate(
                "inputs_unmodified",
                unmodified,
                "declared inputs must be byte-for-byte geometry-identical after the run",
                observed=list(inputs_after),
            )
        )
    else:
        gates.append(
            _gate(
                "output_differs_from_inputs",
                True,
                "no --input-tifxyz declared; a no-op copy cannot be detected",
                evaluated=False,
                observed=None,
                relation=input_relation,
            )
        )

    return {
        "gates": gates,
        "area_cm2": area_cm2,
        "physical": {
            "voxel_size_um": float(voxel_size_um),
            "voxel_spacing": {
                "declared_um": float(voxel_size_um),
                "state": spacing_state,
                "sources": sources,
            },
            "surface_area_voxels2": area_voxels2,
            "surface_area_cm2": area_cm2,
            "area_basis": (
                "quad areas recomputed from x/y/z vertex coordinates; no area, "
                "bbox or voxel-size field in the producer's meta.json is read"
            ),
        },
        "extent": extent,
        "output_geometry": output_digest,
    }


def run_guarded(
    command: Sequence[str],
    *,
    output_tifxyz: str | Path,
    volume_root: str,
    voxel_size_um: float,
    stdout_log: str | Path,
    stderr_log: str | Path,
    min_valid_vertices: int = 1,
    min_valid_quads: int = 1,
    min_area_cm2: float = 0.0,
    surface_preflight_report: str | Path | None = None,
    require_ct_preflight: bool = False,
    cwd: str | Path | None = None,
    input_tifxyz: Sequence[str | Path] | str | Path = (),
    input_relation: str = "differs",
    volume_meta: str | Path | None = None,
    require_verified_voxel_spacing: bool = False,
    bbox_tolerance_voxels: float = DEFAULT_BBOX_TOLERANCE_VOXELS,
) -> dict[str, Any]:
    """Execute one command and fail closed on missing/vacuous TIFXYZ output."""
    if not command:
        raise VC3DRunGuardError("guarded command must not be empty")
    if not isinstance(volume_root, str) or not volume_root.strip():
        raise VC3DRunGuardError("volume_root must be a non-empty string")
    if not _positive_finite(voxel_size_um):
        raise VC3DRunGuardError("voxel_size_um must be finite and positive")
    if type(min_valid_vertices) is not int or min_valid_vertices < 1:
        raise VC3DRunGuardError("min_valid_vertices must be an integer >= 1")
    if type(min_valid_quads) is not int or min_valid_quads < 1:
        raise VC3DRunGuardError("min_valid_quads must be an integer >= 1")
    if (
        not isinstance(min_area_cm2, (int, float))
        or isinstance(min_area_cm2, bool)
        or not math.isfinite(float(min_area_cm2))
        or float(min_area_cm2) < 0
    ):
        raise VC3DRunGuardError("min_area_cm2 must be finite and >= 0")
    if input_relation not in INPUT_RELATIONS:
        raise VC3DRunGuardError(f"input_relation must be one of {INPUT_RELATIONS}")
    if (
        not isinstance(bbox_tolerance_voxels, (int, float))
        or isinstance(bbox_tolerance_voxels, bool)
        or not math.isfinite(float(bbox_tolerance_voxels))
        or float(bbox_tolerance_voxels) < 0
    ):
        raise VC3DRunGuardError("bbox_tolerance_voxels must be finite and >= 0")
    if require_verified_voxel_spacing and volume_meta is None:
        raise VC3DRunGuardError(
            "require_verified_voxel_spacing needs volume_meta as an independent source"
        )

    output = Path(output_tifxyz)
    stdout_path = Path(stdout_log)
    stderr_path = Path(stderr_log)
    if output.exists():
        raise VC3DRunGuardError(
            f"expected output already exists before launch: {output}; "
            "refusing to validate stale geometry"
        )
    for path in (stdout_path, stderr_path):
        if path.exists():
            raise VC3DRunGuardError(
                f"log already exists before launch: {path}; refusing overwrite"
            )
        path.parent.mkdir(parents=True, exist_ok=True)

    inputs = [input_tifxyz] if isinstance(input_tifxyz, (str, Path)) else list(input_tifxyz)
    volume = read_volume_meta(volume_meta) if volume_meta is not None else None
    # Digest inputs before launch: a producer that edits its input in place
    # must not be able to redefine what "the input" was.
    snapshots = _snapshot_inputs(inputs)

    executable = _resolve_executable(command)
    started = _utc_now()
    t0 = time.monotonic()
    launch_error: str | None = None
    return_code: int | None = None
    try:
        with stdout_path.open("x", encoding="utf-8") as out, stderr_path.open(
            "x", encoding="utf-8"
        ) as err:
            result = subprocess.run(
                list(command),
                cwd=str(Path(cwd).resolve()) if cwd is not None else None,
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

    duration = time.monotonic() - t0
    finished = _utc_now()
    output_exists = output.is_dir()

    audit: dict[str, Any]
    if output_exists:
        audit = audit_tifxyz(
            output,
            volume_root=volume_root,
            review_limit_per_kind=0,
            surface_preflight_report=surface_preflight_report,
            bbox_tolerance_voxels=float(bbox_tolerance_voxels),
        )
    else:
        audit = {
            "status": "fail",
            "tifxyz_path": str(output),
            "errors": ["expected TIFXYZ output directory does not exist after command"],
        }

    inputs_after: list[dict[str, Any]] = []
    for before in snapshots:
        try:
            inputs_after.append({"path": before["path"], **geometry_digest(before["path"])})
        except ValueError:
            inputs_after.append({"path": before["path"], "coordinate_sha256": None})

    evaluated = evaluate_postconditions(
        audit,
        output=output if output_exists else None,
        voxel_size_um=float(voxel_size_um),
        min_valid_vertices=min_valid_vertices,
        min_valid_quads=min_valid_quads,
        min_area_cm2=float(min_area_cm2),
        require_ct_preflight=require_ct_preflight,
        input_snapshots=snapshots,
        inputs_after=inputs_after,
        input_relation=input_relation,
        volume_meta=volume,
        require_verified_voxel_spacing=require_verified_voxel_spacing,
        bbox_tolerance_voxels=float(bbox_tolerance_voxels),
    )
    process_gate = _gate(
        "process_exit_zero",
        return_code == 0 and launch_error is None,
        "process must launch and exit 0",
        observed=return_code,
        launch_error=launch_error,
    )
    output_gate = _gate(
        "new_output_present",
        output_exists,
        "expected TIFXYZ directory must be newly created",
        observed=str(output),
    )
    all_gates = [process_gate, output_gate, *evaluated["gates"]]
    passed = all(bool(gate["passed"]) for gate in all_gates)
    exit_zero = return_code == 0 and launch_error is None
    if passed:
        verdict = VERDICT_OK
    elif exit_zero:
        verdict = VERDICT_SEMANTIC_FAILURE
    else:
        verdict = VERDICT_PROCESS_FAILURE

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "status": "pass" if passed else "fail",
        "verdict": verdict,
        "failed_gates": [g["name"] for g in all_gates if not g["passed"]],
        "unevaluated_gates": [g["name"] for g in all_gates if not g["evaluated"]],
        "started_at": started,
        "finished_at": finished,
        "duration_seconds": duration,
        "command": list(command),
        "cwd": str(Path(cwd).resolve()) if cwd is not None else None,
        "executable": executable,
        "process": {
            "return_code": return_code,
            "launch_error": launch_error,
            "exit_zero_but_postcondition_failed": exit_zero and not passed,
        },
        "logs": {
            "stdout": {
                "path": str(stdout_path),
                "sha256": _sha256(stdout_path) if stdout_path.is_file() else None,
                "bytes": stdout_path.stat().st_size if stdout_path.is_file() else None,
            },
            "stderr": {
                "path": str(stderr_path),
                "sha256": _sha256(stderr_path) if stderr_path.is_file() else None,
                "bytes": stderr_path.stat().st_size if stderr_path.is_file() else None,
            },
        },
        "inputs": {
            "tifxyz": snapshots,
            "tifxyz_after_run": inputs_after,
            "relation": input_relation,
            "volume_meta": volume,
        },
        "output": {
            "tifxyz_path": str(output),
            "volume_root": volume_root,
            "voxel_size_um": float(voxel_size_um),
            "surface_area_cm2": evaluated["area_cm2"],
            "physical": evaluated["physical"],
            "extent": evaluated["extent"],
            "geometry": evaluated["output_geometry"],
            "audit": audit,
        },
        "thresholds": {
            "min_valid_vertices": min_valid_vertices,
            "min_valid_quads": min_valid_quads,
            "min_area_cm2": float(min_area_cm2),
            "require_ct_preflight": bool(require_ct_preflight),
            "require_verified_voxel_spacing": bool(require_verified_voxel_spacing),
            "bbox_tolerance_voxels": float(bbox_tolerance_voxels),
            "input_relation": input_relation,
        },
        "gates": all_gates,
        "proof_gate": "PIPELINE_EXECUTION_INTEGRITY",
        "proof_gate_pass": passed,
        "limitations": (
            "This receipt proves only that this process invocation produced a newly "
            "created TIFXYZ surface satisfying the declared semantic postconditions. "
            "Gates listed in unevaluated_gates were not exercised (no independent "
            "voxel-size source, volume dimensions, or declared input was supplied), "
            "so a pass does not cover them. It does not prove sheet identity, "
            "held-out geometry accuracy, topology, ink, or Grand Prize completeness."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-tifxyz", required=True)
    parser.add_argument("--volume-root", required=True)
    parser.add_argument("--voxel-size-um", type=float, required=True)
    parser.add_argument("--stdout-log", required=True)
    parser.add_argument("--stderr-log", required=True)
    parser.add_argument("--out", required=True, help="create-only JSON receipt")
    parser.add_argument("--cwd")
    parser.add_argument("--min-valid-vertices", type=int, default=1)
    parser.add_argument("--min-valid-quads", type=int, default=1)
    parser.add_argument("--min-area-cm2", type=float, default=0.0)
    parser.add_argument("--surface-preflight-report")
    parser.add_argument("--require-ct-preflight", action="store_true")
    parser.add_argument(
        "--input-tifxyz",
        action="append",
        default=[],
        help="TIFXYZ the producer consumes; repeatable. The output geometry must "
        "differ from each, and each must be unmodified after the run",
    )
    parser.add_argument(
        "--input-relation",
        choices=INPUT_RELATIONS,
        default="differs",
        help="'differs' (default) rejects a no-op copy; 'grows' also requires "
        "more valid vertices than every input (growth producers)",
    )
    parser.add_argument(
        "--volume-meta",
        help="local VC3D-style volume meta.json (voxelsize; optional "
        "width/height/slices) used to verify --voxel-size-um and bound the extent",
    )
    parser.add_argument(
        "--require-verified-voxel-spacing",
        action="store_true",
        help="fail unless --volume-meta independently agrees with --voxel-size-um",
    )
    parser.add_argument(
        "--bbox-tolerance-voxels",
        type=float,
        default=DEFAULT_BBOX_TOLERANCE_VOXELS,
        help="voxels a declared bbox may miss recomputed vertices by (default 1)",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="command after --, for example: -- vc_grow_seg_from_seed ...",
    )
    args = parser.parse_args(argv)

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("guarded command is required after --")

    try:
        out = Path(args.out)
        if out.exists():
            parser.error(f"receipt already exists: {out}")
        report = run_guarded(
            command,
            output_tifxyz=args.output_tifxyz,
            volume_root=args.volume_root,
            voxel_size_um=args.voxel_size_um,
            stdout_log=args.stdout_log,
            stderr_log=args.stderr_log,
            min_valid_vertices=args.min_valid_vertices,
            min_valid_quads=args.min_valid_quads,
            min_area_cm2=args.min_area_cm2,
            surface_preflight_report=args.surface_preflight_report,
            require_ct_preflight=args.require_ct_preflight,
            cwd=args.cwd,
            input_tifxyz=args.input_tifxyz,
            input_relation=args.input_relation,
            volume_meta=args.volume_meta,
            require_verified_voxel_spacing=args.require_verified_voxel_spacing,
            bbox_tolerance_voxels=args.bbox_tolerance_voxels,
        )
        _write_json_create_only(out, report)
    except (OSError, VC3DRunGuardError, ValueError) as exc:
        parser.error(str(exc))

    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["proof_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
