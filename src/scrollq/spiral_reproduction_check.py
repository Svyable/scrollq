"""Post-fit reproduction sanity gate for the frozen PHerc0826 Spiral baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1
TOOL = "scroliq-spiral-reproduction-check"
EXPECTED_SCROLL = "PHerc0826"
EXPECTED_VOLUME_ID = "20250821151701"
TRACK_LINE_RE = re.compile(
    r"loaded\s+([0-9,]+)\s+tracks\s+within\s+z-roi\s+\[\s*(\d+)\s*,\s*(\d+)\s*\)",
    re.IGNORECASE,
)


class ReproductionCheckError(ValueError):
    """The run bundle cannot support a baseline-reproduction claim."""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReproductionCheckError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReproductionCheckError(f"{label} must be a JSON object")
    return value


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _under(root: Path, rel: Any, label: str) -> Path:
    if not isinstance(rel, str) or not rel:
        raise ReproductionCheckError(f"{label} path is missing")
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ReproductionCheckError(f"{label} path must stay inside run directory")
    root = root.resolve()
    out = (root / p).resolve()
    if root != out and root not in out.parents:
        raise ReproductionCheckError(f"{label} path escapes run directory")
    return out


def _regular(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ReproductionCheckError(f"{label} must be a regular file: {path}")


def _same_rounded_percent(fraction: Any, expected_percent: Any) -> tuple[bool, float | None]:
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
        return False, None
    value = float(fraction)
    if not math.isfinite(value):
        return False, None
    if isinstance(expected_percent, bool) or not isinstance(expected_percent, (int, float)):
        return False, value * 100.0
    actual_percent = value * 100.0
    return round(actual_percent, 1) == round(float(expected_percent), 1), actual_percent


def _inventory_entry(receipt: Mapping[str, Any], suffix: str) -> dict[str, Any]:
    rows = receipt.get("outputs")
    if not isinstance(rows, list):
        raise ReproductionCheckError("run receipt outputs inventory is missing")
    matches = [
        row for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("path"), str)
        and row["path"].endswith(suffix)
    ]
    if len(matches) != 1:
        raise ReproductionCheckError(
            f"expected exactly one output ending {suffix!r}; found {len(matches)}"
        )
    return matches[0]


def evaluate_run(run_dir: Path) -> dict[str, Any]:
    root = run_dir.resolve()
    receipt_path = root / "spiral-run.receipt.json"
    receipt = _load_json(receipt_path, "Spiral run receipt")
    if receipt.get("tool") != "scroliq-spiral-run" or receipt.get("success") is not True:
        raise ReproductionCheckError("run receipt is not a successful scroliq-spiral-run result")
    if receipt.get("scroll") != EXPECTED_SCROLL or receipt.get("prize_volume_id") != EXPECTED_VOLUME_ID:
        raise ReproductionCheckError("run receipt is not the frozen PHerc0826 prize volume")

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, **extra: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, **extra})

    recipe_meta = receipt.get("recipe")
    if not isinstance(recipe_meta, dict):
        raise ReproductionCheckError("run receipt recipe binding is missing")
    recipe_path = _under(root, recipe_meta.get("copy_path"), "recipe copy")
    _regular(recipe_path, "recipe copy")
    recipe_sha = _sha256(recipe_path)
    check(
        "recipe_hash",
        recipe_sha == recipe_meta.get("copy_sha256"),
        "frozen recipe bytes match run receipt",
        expected_sha256=recipe_meta.get("copy_sha256"),
        actual_sha256=recipe_sha,
    )
    recipe = _load_json(recipe_path, "frozen recipe")
    bounded = recipe.get("bounded_reproduction")
    if not isinstance(bounded, dict):
        raise ReproductionCheckError("recipe bounded_reproduction is required")
    context = bounded.get("expected_reference_context")
    if not isinstance(context, dict):
        raise ReproductionCheckError(
            "recipe bounded_reproduction.expected_reference_context is required"
        )
    expected_z = bounded.get("z_range_half_open")
    if (
        not isinstance(expected_z, list)
        or len(expected_z) != 2
        or not all(type(v) is int for v in expected_z)
    ):
        raise ReproductionCheckError("recipe bounded z range is invalid")

    logs = receipt.get("logs")
    stdout_meta = logs.get("stdout") if isinstance(logs, dict) else None
    if not isinstance(stdout_meta, dict):
        raise ReproductionCheckError("run receipt stdout binding is missing")
    stdout_path = _under(root, stdout_meta.get("path"), "stdout log")
    _regular(stdout_path, "stdout log")
    stdout_sha = _sha256(stdout_path)
    check(
        "stdout_hash",
        stdout_sha == stdout_meta.get("sha256"),
        "stdout bytes match run receipt",
        expected_sha256=stdout_meta.get("sha256"),
        actual_sha256=stdout_sha,
    )
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    track_rows = {
        (int(count.replace(",", "")), int(z0), int(z1))
        for count, z0, z1 in TRACK_LINE_RE.findall(stdout)
    }
    check(
        "unique_track_load_record",
        len(track_rows) == 1,
        "stdout contains one unique official track-load record"
        if len(track_rows) == 1
        else f"stdout contains {len(track_rows)} unique track-load records",
        records=[list(row) for row in sorted(track_rows)],
    )

    expected_tracks = context.get("documented_tracks_loaded_with_input_use_tracks_true")
    loaded_tracks: int | None = None
    if len(track_rows) == 1:
        loaded_tracks, z0, z1 = next(iter(track_rows))
        check(
            "track_count",
            type(expected_tracks) is int and loaded_tracks == expected_tracks,
            "loaded track count matches published PHerc0826 baseline",
            expected=expected_tracks,
            actual=loaded_tracks,
        )
        check(
            "track_z_range",
            [z0, z1] == expected_z,
            "track-load z ROI matches frozen bounded range",
            expected=expected_z,
            actual=[z0, z1],
        )
    else:
        check(
            "track_count",
            False,
            "track count cannot be verified without a unique load record",
            expected=expected_tracks,
            actual=None,
        )
        check(
            "track_z_range",
            False,
            "track z ROI cannot be verified without a unique load record",
            expected=expected_z,
            actual=None,
        )

    metrics_entry = _inventory_entry(receipt, "satisfaction_metrics_fitted.json")
    metrics_path = _under(root, metrics_entry.get("path"), "satisfaction metrics")
    _regular(metrics_path, "satisfaction metrics")
    metrics_sha = _sha256(metrics_path)
    check(
        "satisfaction_metrics_hash",
        metrics_sha == metrics_entry.get("sha256"),
        "structured satisfaction metrics bytes match run inventory",
        expected_sha256=metrics_entry.get("sha256"),
        actual_sha256=metrics_sha,
    )
    metrics = _load_json(metrics_path, "satisfaction metrics")
    summary = metrics.get("summary")
    if not isinstance(summary, dict):
        raise ReproductionCheckError("satisfaction metrics summary is missing")

    reference_metrics = context.get("comparison_only_not_correctness_metrics")
    if not isinstance(reference_metrics, dict):
        raise ReproductionCheckError("recipe comparison-only reference metrics are missing")

    actual_total_tracks = summary.get("total_tracks")
    check(
        "metrics_track_count_consistency",
        loaded_tracks is not None
        and type(actual_total_tracks) is int
        and actual_total_tracks == loaded_tracks,
        "structured total_tracks matches the stdout-loaded track count",
        stdout_loaded_tracks=loaded_tracks,
        metrics_total_tracks=actual_total_tracks,
    )

    sat_ok, sat_percent = _same_rounded_percent(
        summary.get("satisfied_tracks_fraction"),
        reference_metrics.get("satisfied_tracks_percent"),
    )
    check(
        "satisfied_tracks_percent",
        sat_ok,
        "satisfied-track fraction matches the published one-decimal sanity value",
        expected_percent=reference_metrics.get("satisfied_tracks_percent"),
        actual_percent=sat_percent,
    )
    point_ok, point_percent = _same_rounded_percent(
        summary.get("satisfied_track_points_fraction"),
        reference_metrics.get("satisfied_track_points_percent"),
    )
    check(
        "satisfied_track_points_percent",
        point_ok,
        "satisfied-track-point fraction matches the published one-decimal sanity value",
        expected_percent=reference_metrics.get("satisfied_track_points_percent"),
        actual_percent=point_percent,
    )

    all_ok = all(row["ok"] for row in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "status": "sanity-match" if all_ok else "drift",
        "baseline_reproduction_ready_for_export": all_ok,
        "scroll": EXPECTED_SCROLL,
        "prize_volume_id": EXPECTED_VOLUME_ID,
        "run_receipt": {
            "path": str(receipt_path),
            "sha256": _sha256(receipt_path),
        },
        "recipe": {
            "path": str(recipe_path),
            "sha256": recipe_sha,
        },
        "satisfaction_metrics": {
            "path": str(metrics_path),
            "sha256": metrics_sha,
        },
        "checks": checks,
        "reference_context": {
            "documented_gpu": context.get("documented_gpu"),
            "tracks_loaded": expected_tracks,
            "satisfied_tracks_percent": reference_metrics.get("satisfied_tracks_percent"),
            "satisfied_track_points_percent": reference_metrics.get(
                "satisfied_track_points_percent"
            ),
            "dr_per_winding_voxels": reference_metrics.get("dr_per_winding_voxels"),
        },
        "mechanically_unverified_reference_fields": ["dr_per_winding_voxels"],
        "claim_boundary": (
            "A sanity-match means this successful official-villa run reproduces the "
            "frozen track-loading and structured track-satisfaction context. These "
            "measurements are comparison diagnostics, not reconstruction correctness. "
            "dr_per_winding is retained as published context but is not read from the "
            "PyTorch checkpoint by this dependency-light gate."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that a successful PHerc0826 scroliq-spiral-run matches the "
            "published bounded-baseline track sanity context"
        )
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        parser.error(f"refusing to overwrite existing output: {out}")
    try:
        report = evaluate_run(Path(args.run_dir))
    except (OSError, ReproductionCheckError) as exc:
        parser.error(str(exc))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"PHerc0826 reproduction check: {report['status']} "
        f"ready_for_export={str(report['baseline_reproduction_ready_for_export']).lower()}"
    )
    return 0 if report["baseline_reproduction_ready_for_export"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
