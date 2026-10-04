"""Run an external VC3D geometry command and require semantic TIFXYZ output.

Exit code zero is not sufficient evidence of a successful geometry run. This
guard refuses stale outputs, captures immutable logs, then reuses ScrolIQ's
TIFXYZ audit to require a newly produced, non-empty, finite-area surface.

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

from .tifxyz_audit import audit_tifxyz

SCHEMA_VERSION = 1
TOOL = "scroliq-vc3d-run-guard"


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


def _semantic_gates(
    audit: Mapping[str, Any],
    *,
    voxel_size_um: float,
    min_valid_vertices: int,
    min_valid_quads: int,
    min_area_cm2: float,
    require_ct_preflight: bool,
) -> tuple[list[dict[str, Any]], float | None]:
    grid = audit.get("grid") if isinstance(audit.get("grid"), dict) else {}
    quads = audit.get("quads") if isinstance(audit.get("quads"), dict) else {}
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
    gates = [
        {
            "name": "command_output_decodes",
            "passed": audit.get("status") != "fail",
            "observed": audit.get("status"),
            "requirement": "TIFXYZ audit status must not be fail",
        },
        {
            "name": "valid_vertices",
            "passed": (
                type(valid_vertices) is int
                and valid_vertices >= min_valid_vertices
            ),
            "observed": valid_vertices,
            "requirement": f">= {min_valid_vertices}",
        },
        {
            "name": "valid_quads",
            "passed": type(valid_quads) is int and valid_quads >= min_valid_quads,
            "observed": valid_quads,
            "requirement": f">= {min_valid_quads}",
        },
        {
            "name": "finite_positive_surface_area",
            "passed": (
                area_cm2 is not None
                and math.isfinite(area_cm2)
                and area_cm2 > 0
                and area_cm2 >= min_area_cm2
            ),
            "observed_cm2": area_cm2,
            "requirement": f">= {min_area_cm2:g} cm^2 and > 0",
        },
        {
            "name": "ct_volume_binding",
            "passed": (
                ct_preflight.get("status") == "pass"
                if require_ct_preflight
                else True
            ),
            "observed": ct_preflight.get("status", "unknown"),
            "requirement": (
                "validated CT preflight required"
                if require_ct_preflight
                else "not required for execution-integrity gate"
            ),
        },
    ]
    return gates, area_cm2


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
) -> dict[str, Any]:
    """Execute one command and fail closed on missing/vacuous TIFXYZ output."""
    if not command:
        raise VC3DRunGuardError("guarded command must not be empty")
    if not isinstance(volume_root, str) or not volume_root.strip():
        raise VC3DRunGuardError("volume_root must be a non-empty string")
    if (
        not isinstance(voxel_size_um, (int, float))
        or isinstance(voxel_size_um, bool)
        or not math.isfinite(float(voxel_size_um))
        or float(voxel_size_um) <= 0
    ):
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
        )
    else:
        audit = {
            "status": "fail",
            "tifxyz_path": str(output),
            "errors": ["expected TIFXYZ output directory does not exist after command"],
        }

    gates, area_cm2 = _semantic_gates(
        audit,
        voxel_size_um=float(voxel_size_um),
        min_valid_vertices=min_valid_vertices,
        min_valid_quads=min_valid_quads,
        min_area_cm2=float(min_area_cm2),
        require_ct_preflight=require_ct_preflight,
    )
    process_gate = {
        "name": "process_exit_zero",
        "passed": return_code == 0 and launch_error is None,
        "observed": return_code,
        "launch_error": launch_error,
        "requirement": "process must launch and exit 0",
    }
    output_gate = {
        "name": "new_output_present",
        "passed": output_exists,
        "observed": str(output),
        "requirement": "expected TIFXYZ directory must be newly created",
    }
    all_gates = [process_gate, output_gate, *gates]
    passed = all(bool(gate["passed"]) for gate in all_gates)

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "status": "pass" if passed else "fail",
        "started_at": started,
        "finished_at": finished,
        "duration_seconds": duration,
        "command": list(command),
        "cwd": str(Path(cwd).resolve()) if cwd is not None else None,
        "executable": executable,
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
                "sha256": _sha256(stdout_path) if stdout_path.is_file() else None,
                "bytes": stdout_path.stat().st_size if stdout_path.is_file() else None,
            },
            "stderr": {
                "path": str(stderr_path),
                "sha256": _sha256(stderr_path) if stderr_path.is_file() else None,
                "bytes": stderr_path.stat().st_size if stderr_path.is_file() else None,
            },
        },
        "output": {
            "tifxyz_path": str(output),
            "volume_root": volume_root,
            "voxel_size_um": float(voxel_size_um),
            "surface_area_cm2": area_cm2,
            "audit": audit,
        },
        "thresholds": {
            "min_valid_vertices": min_valid_vertices,
            "min_valid_quads": min_valid_quads,
            "min_area_cm2": float(min_area_cm2),
            "require_ct_preflight": bool(require_ct_preflight),
        },
        "gates": all_gates,
        "proof_gate": "PIPELINE_EXECUTION_INTEGRITY",
        "proof_gate_pass": passed,
        "limitations": (
            "This receipt proves only that this process invocation produced a newly "
            "created TIFXYZ surface satisfying the declared semantic postconditions. "
            "It does not prove sheet identity, held-out geometry accuracy, topology, "
            "ink, or Grand Prize completeness."
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
        )
        _write_json_create_only(out, report)
    except (OSError, VC3DRunGuardError, ValueError) as exc:
        parser.error(str(exc))

    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["proof_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
