"""Controlled launcher for the frozen official-villa Spiral baseline.

ScrolIQ does not reconstruct the scroll here. It verifies the local dataset,
requires a clean exact-commit ScrollPrize/villa checkout, launches villa's
fit_spiral.py with the preregistered overrides, and writes a hash-bound receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO

from .spiral_preflight import SpiralPreflightError, audit_spiral_dataset

SCHEMA_VERSION = 1
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TRACKS_IN_ROI_RE = re.compile(
    r"^loaded (?P<count>[0-9][0-9,]*) tracks within z-roi "
    r"\[(?P<z_begin>[^,]+), (?P<z_end>[^)]+)\)$",
    re.MULTILINE,
)
FITTING_PATCHES_RE = re.compile(
    r"^fitting (?P<count>[0-9][0-9,]*) patches$",
    re.MULTILINE,
)


class SpiralRunError(ValueError):
    """A pre-launch or receipt invariant failed."""


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
        raise SpiralRunError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SpiralRunError(f"{label} must be a JSON object")
    return value


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
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
        raise SpiralRunError(f"cannot inspect villa checkout: {detail}") from exc
    return result.stdout.strip()


def verify_villa_checkout(villa_root: Path, expected_commit: str) -> dict[str, Any]:
    root = villa_root.resolve()
    if not COMMIT_RE.fullmatch(expected_commit):
        raise SpiralRunError("recipe software.villa_commit must be lowercase 40-hex")
    if not (root / ".git").exists():
        raise SpiralRunError(f"villa root is not a Git checkout: {root}")
    head = _git(root, "rev-parse", "HEAD")
    if head != expected_commit:
        raise SpiralRunError(f"villa HEAD mismatch: expected {expected_commit}, got {head}")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise SpiralRunError(
            "villa checkout is dirty; commit/stash/remove local changes before a recorded fit"
        )
    fit_script = root / "spiral-fitting" / "fit_spiral.py"
    if not fit_script.is_file() or fit_script.is_symlink():
        raise SpiralRunError(f"missing official fitter: {fit_script}")
    return {
        "repository": "https://github.com/ScrollPrize/villa",
        "commit": head,
        "spiral_fitting_tree_sha": _git(root, "rev-parse", "HEAD:spiral-fitting"),
        "fit_spiral_path": "spiral-fitting/fit_spiral.py",
        "fit_spiral_sha256": _sha256(fit_script),
        "clean": True,
    }


def _python_identity(executable: str) -> dict[str, str]:
    resolved = shutil.which(executable) if os.path.sep not in executable else executable
    if not resolved:
        raise SpiralRunError(f"python executable not found: {executable}")
    try:
        version = subprocess.run(
            [resolved, "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SpiralRunError(f"cannot execute {executable}: {exc}") from exc
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


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
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
        return_code = process.wait()
        out_thread.join()
        err_thread.join()
        return return_code


def _parse_count_token(value: str) -> int:
    return int(value.replace(",", ""))


def _audit_supervision_stdout(
    stdout_path: Path,
    recipe: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify that the recorded fit actually consumed the frozen supervision.

    The PHerc0826 baseline intentionally disables patches and relies on the
    published track DBM. Villa prints the post-ROI track count and fitted patch
    count to stdout. Those lines are part of the reproducibility contract: a
    checkpoint is not a successful baseline if the intended supervision was
    absent or drifted.
    """
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, **extra: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, **extra})

    if not stdout_path.is_file():
        check("stdout_present", False, "fit stdout log is missing")
        return {
            "status": "failed",
            "ok": False,
            "checks": checks,
            "tracks": {"observations": []},
            "patches": {"observations": []},
        }

    try:
        text = stdout_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        check("stdout_readable", False, f"cannot read fit stdout log: {exc}")
        return {
            "status": "failed",
            "ok": False,
            "checks": checks,
            "tracks": {"observations": []},
            "patches": {"observations": []},
        }

    check("stdout_present", True, "fit stdout log is present and readable")

    bounded = recipe.get("bounded_reproduction")
    if not isinstance(bounded, dict):
        check("recipe_bounded_reproduction", False, "recipe bounded_reproduction is missing")
        bounded = {}
    overrides = bounded.get("config_overrides")
    if not isinstance(overrides, dict):
        check("recipe_config_overrides", False, "recipe config_overrides is missing")
        overrides = {}

    z_range = bounded.get("z_range_half_open")
    expected_z: tuple[float, float] | None = None
    if (
        isinstance(z_range, list)
        and len(z_range) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in z_range)
    ):
        expected_z = (float(z_range[0]), float(z_range[1]))

    track_observations: list[dict[str, Any]] = []
    for match in TRACKS_IN_ROI_RE.finditer(text):
        try:
            z_begin = float(match.group("z_begin").strip())
            z_end = float(match.group("z_end").strip())
        except ValueError:
            continue
        track_observations.append(
            {
                "count": _parse_count_token(match.group("count")),
                "z_range_half_open": [z_begin, z_end],
            }
        )

    patch_observations = [
        _parse_count_token(match.group("count"))
        for match in FITTING_PATCHES_RE.finditer(text)
    ]

    tracks_required = overrides.get("input_use_tracks") is True
    patches_disabled = overrides.get("input_disable_patches") is True

    unique_track_counts = sorted({row["count"] for row in track_observations})
    unique_track_ranges = sorted(
        {tuple(row["z_range_half_open"]) for row in track_observations}
    )
    unique_patch_counts = sorted(set(patch_observations))

    if tracks_required:
        check(
            "tracks_logged",
            bool(track_observations),
            "Villa reported post-ROI track supervision",
            observations=len(track_observations),
        )
        check(
            "tracks_unique_count",
            len(unique_track_counts) == 1,
            "all Villa track-count observations agree",
            unique_counts=unique_track_counts,
        )
        track_count = unique_track_counts[0] if len(unique_track_counts) == 1 else None
        check(
            "tracks_positive",
            track_count is not None and track_count > 0,
            "frozen baseline consumed at least one track in the fit ROI",
            actual=track_count,
        )
        if expected_z is not None:
            check(
                "tracks_z_range",
                unique_track_ranges == [expected_z],
                "Villa track supervision used the frozen half-open z range",
                expected=list(expected_z),
                actual=[list(row) for row in unique_track_ranges],
            )
    else:
        track_count = unique_track_counts[0] if len(unique_track_counts) == 1 else None

    reference = bounded.get("expected_reference_context")
    reference_count = (
        reference.get("documented_tracks_loaded_with_input_use_tracks_true")
        if isinstance(reference, dict)
        else None
    )
    if tracks_required:
        reference_count_declared = (
            isinstance(reference_count, int) and not isinstance(reference_count, bool)
        )
        check(
            "tracks_reference_count_declared",
            reference_count_declared,
            "recipe declares the frozen post-ROI track-count reproduction reference",
            actual=reference_count,
        )
        if reference_count_declared:
            check(
                "tracks_reference_count",
                track_count == reference_count,
                "post-ROI track count matches the frozen reproduction reference",
                expected=reference_count,
                actual=track_count,
            )

    if patches_disabled:
        check(
            "patches_logged",
            bool(patch_observations),
            "Villa reported fitted patch supervision",
            observations=len(patch_observations),
        )
        check(
            "patches_disabled_effective",
            unique_patch_counts == [0],
            "frozen baseline fitted zero patches because input_disable_patches=true",
            actual=unique_patch_counts,
        )

    ok = all(row["ok"] for row in checks)
    return {
        "status": "pass" if ok else "failed",
        "ok": ok,
        "checks": checks,
        "tracks": {
            "required": tracks_required,
            "observations": track_observations,
            "unique_counts": unique_track_counts,
            "unique_z_ranges_half_open": [list(row) for row in unique_track_ranges],
            "expected_z_range_half_open": list(expected_z) if expected_z is not None else None,
            "reference_count": reference_count,
            "reference_count_match": (
                track_count == reference_count
                if isinstance(reference_count, int)
                and not isinstance(reference_count, bool)
                and track_count is not None
                else False
            ),
        },
        "patches": {
            "disabled_by_recipe": patches_disabled,
            "observations": patch_observations,
            "unique_counts": unique_patch_counts,
        },
    }


def _inventory(run_dir: Path) -> list[dict[str, Any]]:
    runner_owned = {
        "spiral-run.preflight.json",
        "spiral-run.recipe.json",
        "spiral-run.stdout.log",
        "spiral-run.stderr.log",
        "spiral-run.receipt.json",
    }
    rows: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*"), key=lambda p: p.relative_to(run_dir).as_posix()):
        rel = path.relative_to(run_dir).as_posix()
        if rel in runner_owned:
            continue
        if path.is_symlink():
            raise SpiralRunError(f"official fit output contains symlink: {rel}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SpiralRunError(f"unsupported fit output entry: {rel}")
        rows.append({"path": rel, "size": path.stat().st_size, "sha256": _sha256(path)})
    return rows


def _smoke_contract(recipe: Mapping[str, Any], recipe_bytes: bytes) -> dict[str, Any] | None:
    """Validate a derived smoke recipe (``scroliq-spiral-cloud smoke-recipe``).

    A smoke run executes the same frozen recipe with fewer steps to prove the
    environment works. Its receipt is marked non-promotional so that the
    reproduction check and export refuse it.
    """
    smoke = recipe.get("smoke")
    if smoke is None:
        return None
    bounded = recipe.get("bounded_reproduction")
    steps = bounded.get("optimizer_num_training_steps") if isinstance(bounded, dict) else None
    base = smoke.get("base_optimizer_num_training_steps") if isinstance(smoke, dict) else None
    if (
        not isinstance(smoke, dict)
        or smoke.get("promotional") is not False
        or not isinstance(smoke.get("base_recipe_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", smoke["base_recipe_sha256"])
        or not isinstance(steps, int)
        or not isinstance(base, int)
        or not 0 < steps < base
    ):
        raise SpiralRunError(
            "recipe.smoke must be non-promotional, name its base recipe hash and run "
            "strictly fewer steps than the base recipe"
        )
    return {
        "promotional": False,
        "base_recipe_sha256": smoke["base_recipe_sha256"],
        "base_optimizer_num_training_steps": base,
        "optimizer_num_training_steps": steps,
        "recipe_sha256": hashlib.sha256(recipe_bytes).hexdigest(),
    }


def prepare_run(
    *,
    dataset: Path,
    recipe_path: Path,
    villa_root: Path,
    run_dir: Path,
    python_executable: str,
    cache_dir: Path | None,
) -> dict[str, Any]:
    if run_dir.exists():
        raise SpiralRunError(f"run directory already exists: {run_dir}")
    recipe_bytes = recipe_path.read_bytes()
    recipe = _load_json(recipe_path, "baseline recipe")
    software = recipe.get("software")
    if not isinstance(software, dict) or not isinstance(software.get("villa_commit"), str):
        raise SpiralRunError("recipe.software.villa_commit is required")

    smoke = _smoke_contract(recipe, recipe_bytes)

    try:
        preflight = audit_spiral_dataset(dataset, recipe)
    except SpiralPreflightError as exc:
        raise SpiralRunError(str(exc)) from exc
    if not preflight.get("ready_for_fit"):
        failed = [
            row.get("name", "<unnamed>")
            for row in preflight.get("checks", [])
            if isinstance(row, dict) and not row.get("ok")
        ]
        suffix = ": " + ", ".join(failed) if failed else ""
        raise SpiralRunError("Spiral dataset preflight blocked fit" + suffix)

    villa = verify_villa_checkout(villa_root, software["villa_commit"])
    python_info = _python_identity(python_executable)
    command = [
        python_info["executable"],
        "fit_spiral.py",
        "--dataset",
        str(dataset.resolve()),
    ]
    if cache_dir is not None:
        command += ["--cache", str(cache_dir.resolve())]

    env_overrides = {
        "FIT_SPIRAL_CONFIG_OVERRIDES": preflight["config_overrides_canonical_json"],
        "FIT_SPIRAL_RUN_DIR": str(run_dir.resolve()),
        "PYTHONUNBUFFERED": "1",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "smoke" if smoke else "baseline",
        "smoke": smoke,
        "recipe": recipe,
        "recipe_sha256": hashlib.sha256(recipe_bytes).hexdigest(),
        "preflight": preflight,
        "villa": villa,
        "python": python_info,
        "command": command,
        "working_directory": str(villa_root.resolve() / "spiral-fitting"),
        "environment_overrides": env_overrides,
    }


def run_baseline(
    *,
    dataset: Path,
    recipe_path: Path,
    villa_root: Path,
    run_dir: Path,
    python_executable: str = sys.executable,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    plan = prepare_run(
        dataset=dataset,
        recipe_path=recipe_path,
        villa_root=villa_root,
        run_dir=run_dir,
        python_executable=python_executable,
        cache_dir=cache_dir,
    )

    run_dir.mkdir(parents=True, exist_ok=False)
    preflight_path = run_dir / "spiral-run.preflight.json"
    recipe_copy = run_dir / "spiral-run.recipe.json"
    stdout_path = run_dir / "spiral-run.stdout.log"
    stderr_path = run_dir / "spiral-run.stderr.log"
    receipt_path = run_dir / "spiral-run.receipt.json"
    _write_json(preflight_path, plan["preflight"])
    recipe_copy.write_bytes(recipe_path.read_bytes())

    env = os.environ.copy()
    env.update(plan["environment_overrides"])
    safe_env = {
        key: env[key]
        for key in (
            "FIT_SPIRAL_CONFIG_OVERRIDES",
            "FIT_SPIRAL_RUN_DIR",
            "FIT_SPIRAL_CACHE_DIR",
            "FIT_SPIRAL_RENDER_VOLUME_SCALE",
            "CUDA_VISIBLE_DEVICES",
            "WANDB_MODE",
            "PYTHONHASHSEED",
            "PYTHONUNBUFFERED",
        )
        if key in env
    }

    started_utc = _utc_now()
    start = time.monotonic()
    return_code: int | None = None
    launch_error: str | None = None
    try:
        return_code = _run_and_tee(
            plan["command"],
            cwd=Path(plan["working_directory"]),
            env=env,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        launch_error = str(exc)
    ended_utc = _utc_now()
    wall_seconds = time.monotonic() - start

    try:
        outputs = _inventory(run_dir)
    except SpiralRunError as exc:
        outputs = []
        launch_error = launch_error or str(exc)

    supervision = _audit_supervision_stdout(stdout_path, plan["recipe"])
    checkpoint = run_dir / "checkpoint_fitted.ckpt"
    checkpoint_ok = checkpoint.is_file() and not checkpoint.is_symlink()
    success = (
        return_code == 0
        and launch_error is None
        and checkpoint_ok
        and supervision["ok"]
    )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-spiral-run",
        "status": "success" if success else "failed",
        "success": success,
        "mode": plan["mode"],
        "promotional": plan["mode"] != "smoke",
        "scroll": plan["preflight"]["scroll"],
        "prize_volume_id": plan["preflight"]["prize_volume_id"],
        "started_utc": started_utc,
        "ended_utc": ended_utc,
        "wall_seconds": wall_seconds,
        "return_code": return_code,
        "launch_error": launch_error,
        "recipe": {
            "source_path": str(recipe_path.resolve()),
            "sha256": plan["recipe_sha256"],
            "copy_path": recipe_copy.name,
            "copy_sha256": _sha256(recipe_copy),
        },
        "preflight": {"path": preflight_path.name, "sha256": _sha256(preflight_path)},
        "villa": plan["villa"],
        "python": plan["python"],
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "gpu": _gpu_identity(),
        },
        "command": plan["command"],
        "working_directory": plan["working_directory"],
        "environment": safe_env,
        "supervision": supervision,
        "logs": {
            "stdout": {
                "path": stdout_path.name,
                "sha256": _sha256(stdout_path) if stdout_path.exists() else None,
            },
            "stderr": {
                "path": stderr_path.name,
                "sha256": _sha256(stderr_path) if stderr_path.exists() else None,
            },
        },
        "checkpoint": {
            "path": "checkpoint_fitted.ckpt",
            "present": checkpoint_ok,
            "sha256": _sha256(checkpoint) if checkpoint_ok else None,
            "size": checkpoint.stat().st_size if checkpoint_ok else None,
        },
        "outputs": outputs,
    }
    _write_json(receipt_path, receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen PHerc0826 Spiral baseline through an exact clean "
            "ScrollPrize/villa checkout and emit a hash-bound receipt"
        )
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--villa-root", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--cache-dir")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="verify preflight and pinned villa checkout, print plan, do not launch",
    )
    args = parser.parse_args(argv)

    try:
        if args.prepare_only:
            plan = prepare_run(
                dataset=Path(args.dataset),
                recipe_path=Path(args.recipe),
                villa_root=Path(args.villa_root),
                run_dir=Path(args.run_dir),
                python_executable=args.python,
                cache_dir=Path(args.cache_dir) if args.cache_dir else None,
            )
            print(json.dumps(plan, indent=2, sort_keys=True, allow_nan=False))
            return 0
        receipt = run_baseline(
            dataset=Path(args.dataset),
            recipe_path=Path(args.recipe),
            villa_root=Path(args.villa_root),
            run_dir=Path(args.run_dir),
            python_executable=args.python,
            cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        )
    except (OSError, SpiralRunError) as exc:
        parser.error(str(exc))

    print(
        f"Spiral baseline {receipt['status']}: return_code={receipt['return_code']} "
        f"checkpoint={receipt['checkpoint']['present']} "
        f"supervision={receipt['supervision']['status']} "
        f"receipt={Path(args.run_dir) / 'spiral-run.receipt.json'}"
    )
    return 0 if receipt["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
