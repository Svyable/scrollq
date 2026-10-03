"""Receipt wrapper for the official Villa Spiral checkpoint flattener.

This module does not export or flatten geometry itself. It verifies a successful
ScrolIQ Spiral fit receipt, an exact clean Villa checkout, then launches Villa's
pinned flatten_spiral_checkpoint.py and records a hash-bound export receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO

from .spiral_run import SpiralRunError, verify_villa_checkout
from .tifxyz_audit import audit_tifxyz

SCHEMA_VERSION = 1
EXPECTED_SCROLL = "PHerc0826"
EXPECTED_VOLUME_ID = "20250821151701"
EXPECTED_VOXEL_SIZE_UM = 9.362
FLATTENER_REL = "spiral-fitting/flatten_spiral_checkpoint.py"
LASAGNA_SERVICE_REL = "lasagna/fit_service.py"
LASAGNA_CONFIG_REL = "lasagna/configs/flatten_fast_nofilter.json"


class SpiralExportError(ValueError):
    """The official-export provenance boundary failed closed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpiralExportError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SpiralExportError(f"{label} must be a JSON object")
    return value


def _under(root: Path, rel: str, label: str) -> Path:
    if not isinstance(rel, str) or not rel:
        raise SpiralExportError(f"{label} path is missing")
    base = root.resolve()
    candidate = (base / rel).resolve()
    if base != candidate and base not in candidate.parents:
        raise SpiralExportError(f"{label} path escapes its root: {rel}")
    return candidate


def _regular_file(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise SpiralExportError(f"{label} is not a regular file: {path}")


def _python_identity(executable: str) -> dict[str, str]:
    resolved = shutil.which(executable) if os.path.sep not in executable else executable
    if not resolved:
        raise SpiralExportError(f"python executable not found: {executable}")
    try:
        version = subprocess.run(
            [resolved, "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SpiralExportError(f"cannot execute {executable}: {exc}") from exc
    return {"executable": str(Path(resolved).resolve()), "version": version}


def _gpu_identity() -> list[str]:
    tool = shutil.which("nvidia-smi")
    if not tool:
        return []
    try:
        result = subprocess.run(
            [tool, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _tee(source: TextIO, file_out: TextIO, terminal: TextIO) -> None:
    try:
        for line in iter(source.readline, ""):
            file_out.write(line)
            file_out.flush()
            terminal.write(line)
            terminal.flush()
    finally:
        source.close()


def _run_and_tee(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> int:
    with stdout_path.open("w", encoding="utf-8") as out_file, stderr_path.open(
        "w", encoding="utf-8"
    ) as err_file:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None and process.stderr is not None
        out_thread = threading.Thread(
            target=_tee, args=(process.stdout, out_file, sys.stdout), daemon=True
        )
        err_thread = threading.Thread(
            target=_tee, args=(process.stderr, err_file, sys.stderr), daemon=True
        )
        out_thread.start()
        err_thread.start()
        code = process.wait()
        out_thread.join()
        err_thread.join()
        return code


def _inventory(root: Path) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    tree = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise SpiralExportError(f"TIFXYZ export contains symlink: {rel}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SpiralExportError(f"unsupported TIFXYZ entry: {rel}")
        size = path.stat().st_size
        sha = _sha256(path)
        rows.append({"path": rel, "size": size, "sha256": sha})
        tree.update(rel.encode("utf-8"))
        tree.update(bytes([0]))
        tree.update(str(size).encode("ascii"))
        tree.update(bytes([0]))
        tree.update(sha.encode("ascii"))
        tree.update(bytes([10]))
    return rows, tree.hexdigest()


def prepare_export(
    *,
    run_dir: Path,
    dataset: Path,
    villa_root: Path,
    output: Path,
    evidence_dir: Path,
    python_executable: str,
    device: str,
    chunk_size: int,
) -> dict[str, Any]:
    run_root = run_dir.resolve()
    dataset_root = dataset.resolve()
    villa = villa_root.resolve()
    output_abs = output.resolve()
    evidence_abs = evidence_dir.resolve()

    if output_abs.exists():
        raise SpiralExportError(f"refusing to overwrite existing TIFXYZ: {output_abs}")
    if evidence_abs.exists():
        raise SpiralExportError(f"refusing to overwrite existing export evidence: {evidence_abs}")
    if chunk_size <= 0:
        raise SpiralExportError("chunk_size must be positive")
    if not device.strip():
        raise SpiralExportError("device must be non-empty")

    run_receipt_path = run_root / "spiral-run.receipt.json"
    run_receipt = _load_json(run_receipt_path, "Spiral run receipt")
    if run_receipt.get("tool") != "scroliq-spiral-run" or run_receipt.get("success") is not True:
        raise SpiralExportError("Spiral run receipt is not a successful scroliq-spiral-run result")
    if run_receipt.get("scroll") != EXPECTED_SCROLL or run_receipt.get("prize_volume_id") != EXPECTED_VOLUME_ID:
        raise SpiralExportError("Spiral run receipt is not the frozen PHerc0826 prize volume")

    checkpoint_meta = run_receipt.get("checkpoint")
    if not isinstance(checkpoint_meta, dict) or checkpoint_meta.get("present") is not True:
        raise SpiralExportError("successful run receipt lacks a final checkpoint")
    checkpoint = _under(run_root, checkpoint_meta.get("path"), "checkpoint")
    _regular_file(checkpoint, "checkpoint")
    checkpoint_sha = _sha256(checkpoint)
    if checkpoint_sha != checkpoint_meta.get("sha256") or checkpoint.stat().st_size != checkpoint_meta.get("size"):
        raise SpiralExportError("checkpoint bytes do not match the successful run receipt")

    recipe_meta = run_receipt.get("recipe")
    if not isinstance(recipe_meta, dict):
        raise SpiralExportError("run receipt lacks recipe binding")
    recipe_copy = _under(run_root, recipe_meta.get("copy_path"), "recipe copy")
    _regular_file(recipe_copy, "recipe copy")
    if _sha256(recipe_copy) != recipe_meta.get("copy_sha256"):
        raise SpiralExportError("recipe copy hash does not match run receipt")
    recipe = _load_json(recipe_copy, "frozen baseline recipe")
    if recipe.get("scroll") != EXPECTED_SCROLL or recipe.get("prize_volume_id") != EXPECTED_VOLUME_ID:
        raise SpiralExportError("frozen recipe is not PHerc0826 exact prize volume")
    expected = recipe.get("scroll_spec_expected")
    if not isinstance(expected, dict):
        raise SpiralExportError("recipe lacks scroll_spec_expected")
    voxel_size = expected.get("voxel_size_um")
    if not isinstance(voxel_size, (int, float)) or float(voxel_size) != EXPECTED_VOXEL_SIZE_UM:
        raise SpiralExportError(
            f"PHerc0826 export must use frozen voxel size {EXPECTED_VOXEL_SIZE_UM} um"
        )

    preflight_meta = run_receipt.get("preflight")
    if not isinstance(preflight_meta, dict):
        raise SpiralExportError("run receipt lacks preflight binding")
    preflight = _under(run_root, preflight_meta.get("path"), "preflight")
    _regular_file(preflight, "preflight")
    if _sha256(preflight) != preflight_meta.get("sha256"):
        raise SpiralExportError("preflight hash does not match run receipt")
    preflight_doc = _load_json(preflight, "run preflight")
    if preflight_doc.get("prize_volume_id") != EXPECTED_VOLUME_ID:
        raise SpiralExportError("run preflight exact-volume binding changed")

    inputs = preflight_doc.get("input_files")
    umbilicus_meta = inputs.get("umbilicus.json") if isinstance(inputs, dict) else None
    if not isinstance(umbilicus_meta, dict) or not isinstance(umbilicus_meta.get("sha256"), str):
        raise SpiralExportError("run preflight lacks umbilicus byte identity")
    umbilicus = dataset_root / "umbilicus.json"
    _regular_file(umbilicus, "umbilicus")
    if _sha256(umbilicus) != umbilicus_meta["sha256"]:
        raise SpiralExportError("umbilicus bytes differ from the fitted dataset")

    run_villa = run_receipt.get("villa")
    if not isinstance(run_villa, dict) or not isinstance(run_villa.get("commit"), str):
        raise SpiralExportError("run receipt lacks Villa commit identity")
    try:
        current_villa = verify_villa_checkout(villa, run_villa["commit"])
    except SpiralRunError as exc:
        raise SpiralExportError(str(exc)) from exc
    for key in ("commit", "spiral_fitting_tree_sha", "fit_spiral_sha256"):
        if current_villa.get(key) != run_villa.get(key):
            raise SpiralExportError(f"Villa checkout differs from fit receipt at {key}")

    flattener = villa / FLATTENER_REL
    service = villa / LASAGNA_SERVICE_REL
    config = villa / LASAGNA_CONFIG_REL
    for path, label in (
        (flattener, "official checkpoint flattener"),
        (service, "Lasagna fit service"),
        (config, "Lasagna flatten config"),
    ):
        _regular_file(path, label)

    python_info = _python_identity(python_executable)
    command = [
        python_info["executable"],
        str(flattener),
        str(checkpoint),
        str(output_abs),
        "--umbilicus",
        str(umbilicus),
        "--lasagna-dir",
        str(villa / "lasagna"),
        "--device",
        device,
        "--voxel-size-um",
        str(EXPECTED_VOXEL_SIZE_UM),
        "--chunk-size",
        str(chunk_size),
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "scroll": EXPECTED_SCROLL,
        "prize_volume_id": EXPECTED_VOLUME_ID,
        "voxel_size_um": EXPECTED_VOXEL_SIZE_UM,
        "run_receipt": {
            "path": str(run_receipt_path),
            "sha256": _sha256(run_receipt_path),
        },
        "checkpoint": {
            "path": str(checkpoint),
            "sha256": checkpoint_sha,
            "size": checkpoint.stat().st_size,
        },
        "recipe": {
            "path": str(recipe_copy),
            "sha256": _sha256(recipe_copy),
        },
        "preflight": {
            "path": str(preflight),
            "sha256": _sha256(preflight),
        },
        "umbilicus": {
            "path": str(umbilicus),
            "sha256": _sha256(umbilicus),
        },
        "villa": {
            **current_villa,
            "flatten_spiral_checkpoint_path": FLATTENER_REL,
            "flatten_spiral_checkpoint_sha256": _sha256(flattener),
            "lasagna_fit_service_path": LASAGNA_SERVICE_REL,
            "lasagna_fit_service_sha256": _sha256(service),
            "lasagna_config_path": LASAGNA_CONFIG_REL,
            "lasagna_config_sha256": _sha256(config),
        },
        "python": python_info,
        "device": device,
        "chunk_size": chunk_size,
        "command": command,
        "working_directory": str((villa / "spiral-fitting").resolve()),
        "output": str(output_abs),
        "evidence_dir": str(evidence_abs),
    }


def export_checkpoint(
    *,
    run_dir: Path,
    dataset: Path,
    villa_root: Path,
    output: Path,
    evidence_dir: Path,
    python_executable: str = sys.executable,
    device: str = "cuda",
    chunk_size: int = 65536,
) -> dict[str, Any]:
    plan = prepare_export(
        run_dir=run_dir,
        dataset=dataset,
        villa_root=villa_root,
        output=output,
        evidence_dir=evidence_dir,
        python_executable=python_executable,
        device=device,
        chunk_size=chunk_size,
    )
    evidence = Path(plan["evidence_dir"])
    evidence.mkdir(parents=True, exist_ok=False)
    stdout_path = evidence / "spiral-export.stdout.log"
    stderr_path = evidence / "spiral-export.stderr.log"
    audit_path = evidence / "spiral-export.tifxyz-audit.json"
    receipt_path = evidence / "spiral-export.receipt.json"

    started = _utc_now()
    start = time.monotonic()
    return_code: int | None = None
    launch_error: str | None = None
    try:
        return_code = _run_and_tee(
            plan["command"],
            cwd=Path(plan["working_directory"]),
            env=os.environ.copy(),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        launch_error = str(exc)
    ended = _utc_now()
    wall_seconds = time.monotonic() - start

    output_path = Path(plan["output"])
    audit: dict[str, Any] | None = None
    output_files: list[dict[str, Any]] = []
    output_tree_sha256: str | None = None
    if output_path.is_dir() and not output_path.is_symlink():
        try:
            output_files, output_tree_sha256 = _inventory(output_path)
            audit = audit_tifxyz(output_path)
            _write_json(audit_path, audit)
        except (OSError, ValueError, SpiralExportError) as exc:
            launch_error = launch_error or str(exc)
    elif output_path.exists():
        launch_error = launch_error or "official exporter output is not a regular TIFXYZ directory"

    audit_ok = isinstance(audit, dict) and audit.get("status") != "fail"
    success = return_code == 0 and launch_error is None and audit_ok
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-spiral-export",
        "status": "success" if success else "failed",
        "success": success,
        "scroll": EXPECTED_SCROLL,
        "prize_volume_id": EXPECTED_VOLUME_ID,
        "voxel_size_um": EXPECTED_VOXEL_SIZE_UM,
        "started_utc": started,
        "ended_utc": ended,
        "wall_seconds": wall_seconds,
        "return_code": return_code,
        "launch_error": launch_error,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "gpu": _gpu_identity(),
        },
        "run_receipt": plan["run_receipt"],
        "checkpoint": plan["checkpoint"],
        "recipe": plan["recipe"],
        "preflight": plan["preflight"],
        "umbilicus": plan["umbilicus"],
        "villa": plan["villa"],
        "python": plan["python"],
        "device": plan["device"],
        "chunk_size": plan["chunk_size"],
        "command": plan["command"],
        "working_directory": plan["working_directory"],
        "logs": {
            "stdout": {"path": stdout_path.name, "sha256": _sha256(stdout_path)},
            "stderr": {"path": stderr_path.name, "sha256": _sha256(stderr_path)},
        },
        "output": {
            "path": plan["output"],
            "tree_sha256": output_tree_sha256,
            "files": output_files,
            "tifxyz_audit_path": audit_path.name if audit_path.exists() else None,
            "tifxyz_audit_sha256": _sha256(audit_path) if audit_path.exists() else None,
            "tifxyz_audit_status": audit.get("status") if isinstance(audit, dict) else None,
        },
        "claim_boundary": (
            "This receipt proves execution and byte-level provenance of Villa's official "
            "checkpoint-to-TIFXYZ path. It does not prove correct sheet identity, full-scroll "
            "coverage, self-intersection freedom, or readability."
        ),
    }
    _write_json(receipt_path, receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Villa's pinned official Spiral checkpoint flattener with a hash-bound receipt"
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--villa-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--chunk-size", type=int, default=65536)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="verify all fit/export bindings and print the exact official command without running it",
    )
    args = parser.parse_args(argv)
    kwargs = dict(
        run_dir=Path(args.run_dir),
        dataset=Path(args.dataset),
        villa_root=Path(args.villa_root),
        output=Path(args.output),
        evidence_dir=Path(args.evidence_dir),
        python_executable=args.python,
        device=args.device,
        chunk_size=args.chunk_size,
    )
    try:
        if args.prepare_only:
            print(json.dumps(prepare_export(**kwargs), indent=2, sort_keys=True, allow_nan=False))
            return 0
        receipt = export_checkpoint(**kwargs)
    except (OSError, SpiralExportError) as exc:
        parser.error(str(exc))
    print(
        f"Spiral official export {receipt['status']}: return_code={receipt['return_code']} "
        f"audit={receipt['output']['tifxyz_audit_status']} "
        f"receipt={Path(args.evidence_dir) / 'spiral-export.receipt.json'}"
    )
    return 0 if receipt["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
