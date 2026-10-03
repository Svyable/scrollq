"""Execute and verify hash-bound VC3D column renders.

This module is the executable bridge between a Grand Prize TIFXYZ mesh and the
raw TIFF consumed by scroliq-submission-image.  It deliberately controls the
VC3D arguments that affect artifact identity and physical scale, records the
exact vc_render_tifxyz binary, and emits a self-contained JSON receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image

from .package_hash import sha256_path

VC3D_RECEIPT_SCHEMA_VERSION = 1
VC3D_RECEIPT_TOOL = "scroliq-vc3d"
VC3D_REPOSITORY = "https://github.com/ScrollPrize/villa"
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
COLUMN_RE = re.compile(r"^column_(\d+)\.tifxyz$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_CONTROLLED_FLAGS = {
    "--volume",
    "-v",
    "--segmentation",
    "-s",
    "--scale",
    "--group-idx",
    "-g",
    "--num-slices",
    "-n",
    "--tif-output",
    "--voxel-size",
    "--voxel-unit",
    "--log-path",
    "--zarr-output",
    "--num-parts",
    "--part-id",
    "--merge-tiff-parts",
}


class VC3DError(ValueError):
    """A VC3D execution or receipt contract was violated."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _relative_under(root: Path, path: Path, *, label: str) -> str:
    root_resolved = root.resolve()
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise VC3DError(f"{label} must live under --root-dir") from exc
    posix = rel.as_posix()
    pure = PurePosixPath(posix)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise VC3DError(f"unsafe {label} path: {posix!r}")
    return posix


def _resolve_under(root: Path, rel: str, *, label: str) -> Path:
    pure = PurePosixPath(rel)
    if (
        not rel
        or pure.is_absolute()
        or "\\" in rel
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise VC3DError(f"unsafe {label} path: {rel!r}")
    path = root / Path(*pure.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise VC3DError(f"{label} escapes --root-dir: {rel!r}") from exc
    return path


def _binary_path(raw: str) -> Path:
    found = shutil.which(raw)
    candidate = Path(found) if found else Path(raw)
    if not candidate.is_file():
        raise VC3DError(f"vc_render_tifxyz binary not found: {raw}")
    return candidate.resolve()


def _help_fingerprint(binary: Path) -> tuple[str, str]:
    run = subprocess.run(
        [str(binary), "--help"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    payload = run.stdout
    if run.returncode != 0:
        raise VC3DError(
            f"{binary.name} --help exited with status {run.returncode}"
        )
    first = payload.decode("utf-8", errors="replace").splitlines()
    headline = first[0].strip() if first else ""
    return hashlib.sha256(payload).hexdigest(), headline


def _validate_extra_args(extra_args: list[str]) -> None:
    for token in extra_args:
        if "\x00" in token:
            raise VC3DError("VC3D argument contains NUL byte")
        flag = token.split("=", 1)[0]
        if flag in _CONTROLLED_FLAGS:
            raise VC3DError(
                f"{flag} is controlled by scroliq-vc3d and may not be overridden"
            )


def _mesh_context(mesh: Path, volume_id: str) -> dict[str, Any]:
    match = COLUMN_RE.fullmatch(mesh.name)
    if match is None:
        raise VC3DError("mesh must be named column_NN.tifxyz")
    if mesh.is_symlink() or not mesh.is_dir():
        raise VC3DError("mesh must be an unpacked TIFXYZ directory")

    meta_path = mesh / "meta.json"
    if not meta_path.is_file() or meta_path.is_symlink():
        raise VC3DError("TIFXYZ mesh must contain a regular meta.json")
    raw = meta_path.read_bytes()
    try:
        meta = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VC3DError(f"cannot parse TIFXYZ meta.json: {exc}") from exc
    if not isinstance(meta, dict) or meta.get("format") != "tifxyz":
        raise VC3DError("TIFXYZ meta.json must declare format='tifxyz'")
    target = meta.get("target_volume")
    if not isinstance(target, str) or volume_id not in target:
        raise VC3DError(
            "TIFXYZ meta.json target_volume does not identify the exact "
            f"eligible volume {volume_id!r}"
        )
    scale = meta.get("scale")
    if not (
        isinstance(scale, list)
        and len(scale) == 2
        and all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) > 0
            for value in scale
        )
    ):
        raise VC3DError("TIFXYZ meta.json must contain a positive finite 2D scale")
    return {
        "column_from_name": int(match.group(1)),
        "meta_sha256": hashlib.sha256(raw).hexdigest(),
        "target_volume": target,
        "scroll_source": meta.get("scroll_source"),
        "scale": scale,
    }


def _image_info(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise VC3DError(f"VC3D output is not a regular TIFF: {path}")
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            mode = image.mode
            fmt = image.format
    except Exception as exc:
        raise VC3DError(f"cannot decode VC3D output TIFF {path}: {exc}") from exc
    if fmt != "TIFF":
        raise VC3DError(f"VC3D output is not TIFF: {path}")
    return {
        "size": path.stat().st_size,
        "sha256": _sha256_file(path),
        "width": width,
        "height": height,
        "mode": mode,
    }


def _critical_argv(receipt: dict[str, Any]) -> list[str]:
    inputs = receipt["inputs"]
    render = receipt["render"]
    return [
        "--volume",
        inputs["volume"]["path"],
        "--segmentation",
        inputs["mesh"]["path"],
        "--scale",
        str(render["scale"]),
        "--group-idx",
        str(render["group_idx"]),
        "--num-slices",
        "1",
        "--tif-output",
        render["tif_output_dir"],
        "--voxel-size",
        str(inputs["volume"]["base_voxel_size_um"]),
        "--voxel-unit",
        "micrometer",
    ]


def render_column(
    *,
    root_dir: str | Path,
    binary: str,
    vc_commit: str,
    volume: str,
    volume_id: str,
    mesh: str | Path,
    column: int,
    base_voxel_size_um: float,
    group_idx: int,
    scale: float,
    tif_output_dir: str | Path,
    receipt_path: str | Path,
    log_path: str | Path,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """Run one controlled VC3D single-slice render and write its receipt."""

    root = Path(root_dir)
    if not root.is_dir():
        raise VC3DError(f"--root-dir is not a directory: {root}")
    if not COMMIT_RE.fullmatch(vc_commit):
        raise VC3DError("--vc-commit must be an exact 40-hex Git commit")
    vc_commit = vc_commit.lower()
    if not volume_id:
        raise VC3DError("--volume-id is required")
    if isinstance(column, bool) or not isinstance(column, int) or column < 1:
        raise VC3DError("--column must be a positive integer")
    if (
        isinstance(group_idx, bool)
        or not isinstance(group_idx, int)
        or group_idx < 0
    ):
        raise VC3DError("--group-idx must be a non-negative integer")
    for label, value in (
        ("--base-voxel-um", base_voxel_size_um),
        ("--scale", scale),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            raise VC3DError(f"{label} must be positive and finite")

    mesh_path = Path(mesh)
    if not mesh_path.is_absolute():
        mesh_path = root / mesh_path
    mesh_rel = _relative_under(root, mesh_path, label="mesh")
    mesh_info = _mesh_context(mesh_path, volume_id)
    if mesh_info["column_from_name"] != column:
        raise VC3DError(
            f"--column={column} does not match mesh name {mesh_path.name!r}"
        )

    out_dir = Path(tif_output_dir)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_rel = _relative_under(root, out_dir, label="TIFF output directory")
    if out_dir.exists():
        if not out_dir.is_dir() or any(out_dir.iterdir()):
            raise VC3DError("--tif-output-dir must not exist or must be empty")
    else:
        out_dir.parent.mkdir(parents=True, exist_ok=True)

    receipt = Path(receipt_path)
    if not receipt.is_absolute():
        receipt = root / receipt
    receipt_rel = _relative_under(root, receipt, label="receipt")
    if receipt.exists():
        raise VC3DError("refusing to overwrite existing receipt")
    receipt.parent.mkdir(parents=True, exist_ok=True)

    log = Path(log_path)
    if not log.is_absolute():
        log = root / log
    log_rel = _relative_under(root, log, label="log")
    if log.exists():
        raise VC3DError("refusing to overwrite existing log")
    log.parent.mkdir(parents=True, exist_ok=True)

    extras = list(extra_args or [])
    _validate_extra_args(extras)

    executable = _binary_path(binary)
    binary_sha = _sha256_file(executable)
    help_sha, help_headline = _help_fingerprint(executable)

    critical = [
        "--volume",
        volume,
        "--segmentation",
        mesh_rel,
        "--scale",
        str(float(scale)),
        "--group-idx",
        str(group_idx),
        "--num-slices",
        "1",
        "--tif-output",
        out_rel,
        "--voxel-size",
        str(float(base_voxel_size_um)),
        "--voxel-unit",
        "micrometer",
    ]
    argv = [executable.name, *critical, *extras]

    with log.open("wb") as fh:
        completed = subprocess.run(
            [str(executable), *critical, *extras],
            cwd=root,
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if completed.returncode != 0:
        raise VC3DError(
            f"vc_render_tifxyz exited with status {completed.returncode}; "
            f"see {log_rel}"
        )

    output = out_dir / "00.tif"
    image = _image_info(output)
    unexpected = sorted(
        item.relative_to(out_dir).as_posix()
        for item in out_dir.rglob("*")
        if item.is_file() and item.name != "00.tif"
    )
    if unexpected:
        raise VC3DError(
            "single-slice VC3D render produced unexpected extra files: "
            + ", ".join(unexpected[:8])
        )

    log_info = {
        "path": log_rel,
        "size": log.stat().st_size,
        "sha256": _sha256_file(log),
    }
    output_rel = _relative_under(root, output, label="raw render")
    document: dict[str, Any] = {
        "schema_version": VC3D_RECEIPT_SCHEMA_VERSION,
        "tool": VC3D_RECEIPT_TOOL,
        "operation": "render-column",
        "column": column,
        "vc3d": {
            "repository": VC3D_REPOSITORY,
            "commit": vc_commit,
            "binary": {
                "name": executable.name,
                "size": executable.stat().st_size,
                "sha256": binary_sha,
                "help_sha256": help_sha,
                "help_headline": help_headline,
            },
        },
        "inputs": {
            "volume": {
                "path": volume,
                "volume_id": volume_id,
                "base_voxel_size_um": float(base_voxel_size_um),
            },
            "mesh": {
                "path": mesh_rel,
                "sha256": sha256_path(mesh_path),
                "meta_sha256": mesh_info["meta_sha256"],
                "target_volume": mesh_info["target_volume"],
                "scale": mesh_info["scale"],
            },
        },
        "render": {
            "group_idx": group_idx,
            "scale": float(scale),
            "num_slices": 1,
            "tif_output_dir": out_rel,
            "argv": argv,
            "extra_args": extras,
            "exit_code": completed.returncode,
        },
        "output": {
            "path": output_rel,
            **image,
        },
        "log": log_info,
        "receipt_path": receipt_rel,
    }
    receipt.write_bytes(_json_bytes(document))
    return document


def verify_receipt(
    receipt_path: str | Path,
    *,
    root_dir: str | Path,
    binary: str | None = None,
) -> dict[str, Any]:
    """Verify a VC3D receipt against the exact local artifacts it binds."""

    root = Path(root_dir)
    receipt = Path(receipt_path)
    if not receipt.is_absolute():
        receipt = root / receipt
    errors: list[str] = []
    try:
        raw = receipt.read_bytes()
        document = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"cannot read receipt: {exc}"]}

    if not isinstance(document, dict):
        return {"valid": False, "errors": ["receipt must be a JSON object"]}
    if document.get("schema_version") != VC3D_RECEIPT_SCHEMA_VERSION:
        errors.append("unsupported receipt schema_version")
    if document.get("tool") != VC3D_RECEIPT_TOOL:
        errors.append("receipt tool is not scroliq-vc3d")
    if document.get("operation") != "render-column":
        errors.append("receipt operation is not render-column")

    column = document.get("column")
    if isinstance(column, bool) or not isinstance(column, int) or column < 1:
        errors.append("column must be a positive integer")

    vc3d = document.get("vc3d")
    if not isinstance(vc3d, dict):
        errors.append("vc3d section is missing")
        vc3d = {}
    if vc3d.get("repository") != VC3D_REPOSITORY:
        errors.append("unexpected VC3D repository")
    commit = vc3d.get("commit")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        errors.append("VC3D commit is not exact 40-hex")

    inputs = document.get("inputs")
    if not isinstance(inputs, dict):
        errors.append("inputs section is missing")
        inputs = {}
    volume = inputs.get("volume")
    mesh = inputs.get("mesh")
    if not isinstance(volume, dict):
        errors.append("volume input is missing")
        volume = {}
    if not isinstance(mesh, dict):
        errors.append("mesh input is missing")
        mesh = {}

    volume_id = volume.get("volume_id")
    base_voxel = volume.get("base_voxel_size_um")
    if not isinstance(volume.get("path"), str) or not volume.get("path"):
        errors.append("volume path is missing")
    if not isinstance(volume_id, str) or not volume_id:
        errors.append("volume_id is missing")
        volume_id = ""
    if (
        isinstance(base_voxel, bool)
        or not isinstance(base_voxel, (int, float))
        or not math.isfinite(float(base_voxel))
        or float(base_voxel) <= 0
    ):
        errors.append("base_voxel_size_um must be positive and finite")

    mesh_rel = mesh.get("path")
    if isinstance(mesh_rel, str):
        try:
            mesh_path = _resolve_under(root, mesh_rel, label="mesh")
            context = _mesh_context(mesh_path, volume_id)
            if context["column_from_name"] != column:
                errors.append("mesh filename column differs from receipt column")
            if sha256_path(mesh_path) != mesh.get("sha256"):
                errors.append("mesh sha256 mismatch")
            if context["meta_sha256"] != mesh.get("meta_sha256"):
                errors.append("mesh meta.json sha256 mismatch")
            if context["target_volume"] != mesh.get("target_volume"):
                errors.append("mesh target_volume mismatch")
            if context["scale"] != mesh.get("scale"):
                errors.append("mesh scale mismatch")
        except (OSError, ValueError, VC3DError) as exc:
            errors.append(f"mesh verification failed: {exc}")
    else:
        errors.append("mesh path is missing")

    render = document.get("render")
    if not isinstance(render, dict):
        errors.append("render section is missing")
        render = {}
    group_idx = render.get("group_idx")
    render_scale = render.get("scale")
    if (
        isinstance(group_idx, bool)
        or not isinstance(group_idx, int)
        or group_idx < 0
    ):
        errors.append("group_idx must be a non-negative integer")
    if (
        isinstance(render_scale, bool)
        or not isinstance(render_scale, (int, float))
        or not math.isfinite(float(render_scale))
        or float(render_scale) <= 0
    ):
        errors.append("render scale must be positive and finite")
    if render.get("num_slices") != 1:
        errors.append("receipt must describe exactly one rendered slice")
    if render.get("exit_code") != 0:
        errors.append("receipt render exit_code is not zero")

    extras = render.get("extra_args")
    if not isinstance(extras, list) or not all(isinstance(x, str) for x in extras):
        errors.append("extra_args must be a list of strings")
        extras = []
    else:
        try:
            _validate_extra_args(extras)
        except VC3DError as exc:
            errors.append(str(exc))

    argv = render.get("argv")
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        errors.append("argv must be a list of strings")
    else:
        expected_name = vc3d.get("binary", {}).get("name") if isinstance(vc3d.get("binary"), dict) else None
        try:
            expected_critical = _critical_argv(document)
        except (KeyError, TypeError, ValueError):
            errors.append("cannot reconstruct critical VC3D argv")
        else:
            if argv != [expected_name, *expected_critical, *extras]:
                errors.append("argv does not match receipt-controlled VC3D arguments")

    output = document.get("output")
    if not isinstance(output, dict):
        errors.append("output section is missing")
        output = {}
    output_rel = output.get("path")
    if isinstance(output_rel, str):
        try:
            output_path = _resolve_under(root, output_rel, label="raw render")
            info = _image_info(output_path)
            for key in ("size", "sha256", "width", "height", "mode"):
                if info.get(key) != output.get(key):
                    errors.append(f"raw render {key} mismatch")
        except (OSError, VC3DError) as exc:
            errors.append(f"raw render verification failed: {exc}")
    else:
        errors.append("raw render path is missing")

    log = document.get("log")
    if not isinstance(log, dict):
        errors.append("log section is missing")
        log = {}
    log_rel = log.get("path")
    if isinstance(log_rel, str):
        try:
            log_file = _resolve_under(root, log_rel, label="log")
            if not log_file.is_file() or log_file.is_symlink():
                errors.append("render log is missing or not regular")
            else:
                if log_file.stat().st_size != log.get("size"):
                    errors.append("render log size mismatch")
                if _sha256_file(log_file) != log.get("sha256"):
                    errors.append("render log sha256 mismatch")
        except VC3DError as exc:
            errors.append(str(exc))
    else:
        errors.append("render log path is missing")

    if binary is not None:
        try:
            executable = _binary_path(binary)
            binary_info = vc3d.get("binary")
            if not isinstance(binary_info, dict):
                errors.append("binary section is missing")
            else:
                if executable.name != binary_info.get("name"):
                    errors.append("VC3D binary name mismatch")
                if executable.stat().st_size != binary_info.get("size"):
                    errors.append("VC3D binary size mismatch")
                if _sha256_file(executable) != binary_info.get("sha256"):
                    errors.append("VC3D binary sha256 mismatch")
                help_sha, _ = _help_fingerprint(executable)
                if help_sha != binary_info.get("help_sha256"):
                    errors.append("VC3D binary --help fingerprint mismatch")
        except (OSError, VC3DError) as exc:
            errors.append(f"binary verification failed: {exc}")

    return {
        "valid": not errors,
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "column": column,
        "output_sha256": output.get("sha256"),
        "mesh_sha256": mesh.get("sha256"),
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run or verify a hash-bound vc_render_tifxyz column render for "
            "the 2027 Grand Prize workflow"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render", help="run one controlled single-slice VC3D render")
    render.add_argument("--root-dir", required=True)
    render.add_argument("--binary", default="vc_render_tifxyz")
    render.add_argument("--vc-commit", required=True)
    render.add_argument("--volume", required=True)
    render.add_argument("--volume-id", required=True)
    render.add_argument("--mesh", required=True)
    render.add_argument("--column", type=int, required=True)
    render.add_argument("--base-voxel-um", type=float, required=True)
    render.add_argument("--group-idx", type=int, required=True)
    render.add_argument("--scale", type=float, required=True)
    render.add_argument("--tif-output-dir", required=True)
    render.add_argument("--receipt", required=True)
    render.add_argument("--log", required=True)
    render.add_argument(
        "--vc-arg",
        action="append",
        default=[],
        help=(
            "extra vc_render_tifxyz token; repeat for each token. Critical "
            "volume/mesh/scale/output flags cannot be overridden"
        ),
    )

    verify = sub.add_parser("verify", help="verify a receipt and bound local artifacts")
    verify.add_argument("--root-dir", required=True)
    verify.add_argument("--receipt", required=True)
    verify.add_argument(
        "--binary",
        help="optionally verify the local vc_render_tifxyz binary fingerprint too",
    )

    args = parser.parse_args()
    try:
        if args.command == "render":
            result = render_column(
                root_dir=args.root_dir,
                binary=args.binary,
                vc_commit=args.vc_commit,
                volume=args.volume,
                volume_id=args.volume_id,
                mesh=args.mesh,
                column=args.column,
                base_voxel_size_um=args.base_voxel_um,
                group_idx=args.group_idx,
                scale=args.scale,
                tif_output_dir=args.tif_output_dir,
                receipt_path=args.receipt,
                log_path=args.log,
                extra_args=args.vc_arg,
            )
            print("VC3D render receipt: PASS")
            print(f"column: {result['column']}")
            print(f"mesh sha256: {result['inputs']['mesh']['sha256']}")
            print(f"raw render sha256: {result['output']['sha256']}")
            print(f"receipt: {result['receipt_path']}")
        else:
            report = verify_receipt(
                args.receipt,
                root_dir=args.root_dir,
                binary=args.binary,
            )
            verdict = "PASS" if report["valid"] else "FAIL"
            print(f"VC3D render receipt verification: {verdict}")
            print(f"receipt sha256: {report.get('receipt_sha256', '')}")
            for error in report["errors"]:
                print(f"- {error}")
            if not report["valid"]:
                raise SystemExit(1)
    except (OSError, VC3DError) as exc:
        print(f"scroliq-vc3d: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
