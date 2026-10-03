"""Fail-closed preflight for the frozen PHerc0826 Spiral baseline campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA_VERSION = 1


class SpiralPreflightError(ValueError):
    pass


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpiralPreflightError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SpiralPreflightError(f"{label} must be a JSON object")
    return value


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve(root: Path, rel: str) -> Path:
    candidate = (root / rel).resolve()
    root = root.resolve()
    if root != candidate and root not in candidate.parents:
        raise SpiralPreflightError(f"path escapes dataset root: {rel}")
    return candidate


def _json_contains(value: Any, token: str) -> bool:
    if isinstance(value, dict):
        return any(_json_contains(k, token) or _json_contains(v, token) for k, v in value.items())
    if isinstance(value, list):
        return any(_json_contains(v, token) for v in value)
    return token in str(value)


def _zarray(path: Path) -> dict[str, Any]:
    meta = path / ".zarray"
    if not meta.is_file():
        raise SpiralPreflightError(f"missing Zarr v2 metadata: {meta}")
    doc = _load_json(meta, ".zarray")
    shape = doc.get("shape")
    if not isinstance(shape, list) or not shape or not all(type(v) is int and v > 0 for v in shape):
        raise SpiralPreflightError(f"{meta}: invalid shape")
    return doc


def _crossings_signature(npz_path: Path) -> list[Any]:
    try:
        with np.load(npz_path, allow_pickle=False) as archive:
            if "metadata" not in archive.files:
                raise SpiralPreflightError(f"{npz_path}: crossings archive lacks metadata")
            raw = archive["metadata"]
            text = raw.item() if getattr(raw, "shape", None) == () else str(raw.tolist())
    except (OSError, ValueError) as exc:
        raise SpiralPreflightError(f"cannot read crossings metadata {npz_path}: {exc}") from exc
    if not isinstance(text, str):
        text = str(text)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SpiralPreflightError(f"{npz_path}: crossings metadata is not JSON") from exc
    sig = doc.get("db_signature")
    if not isinstance(sig, list):
        raise SpiralPreflightError(f"{npz_path}: crossings metadata lacks db_signature")
    return sig


def audit_spiral_dataset(dataset_root: Path, recipe: Mapping[str, Any]) -> dict[str, Any]:
    root = dataset_root.resolve()
    checks: list[dict[str, Any]] = []
    inputs: dict[str, Any] = {}

    def check(name: str, ok: bool, detail: str, **extra: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, **extra})

    scroll = recipe.get("scroll")
    volume_id = recipe.get("prize_volume_id")
    expected = recipe.get("scroll_spec_expected")
    bounded = recipe.get("bounded_reproduction")
    if not isinstance(scroll, str) or not scroll:
        raise SpiralPreflightError("recipe.scroll is required")
    if not isinstance(volume_id, str) or not volume_id:
        raise SpiralPreflightError("recipe.prize_volume_id is required")
    if not isinstance(expected, dict):
        raise SpiralPreflightError("recipe.scroll_spec_expected must be an object")
    if not isinstance(bounded, dict) or not isinstance(bounded.get("config_overrides"), dict):
        raise SpiralPreflightError("recipe.bounded_reproduction.config_overrides is required")

    spec_path = root / "spiral-scroll.json"
    spec = _load_json(spec_path, "spiral-scroll")
    check("scroll_name", spec.get("name") == scroll, "scroll name matches frozen recipe",
          expected=scroll, actual=spec.get("name"))
    check("voxel_size_um", spec.get("voxel_size_um") == expected.get("voxel_size_um"),
          "voxel size matches frozen recipe", expected=expected.get("voxel_size_um"),
          actual=spec.get("voxel_size_um"))
    sense = expected.get("spiral_outward_sense_candidate")
    check("outward_sense", spec.get("spiral_outward_sense") == sense,
          "outward sense matches reproduction recipe", expected=sense,
          actual=spec.get("spiral_outward_sense"))
    check("normal_zarr_group", str(spec.get("normal_zarr_group")) == str(expected.get("normal_zarr_group")),
          "normal Zarr group matches frozen recipe",
          expected=str(expected.get("normal_zarr_group")), actual=str(spec.get("normal_zarr_group")))
    check("lasagna_scale", spec.get("lasagna_scale") == expected.get("lasagna_scale"),
          "Lasagna scale matches frozen recipe", expected=expected.get("lasagna_scale"),
          actual=spec.get("lasagna_scale"))

    umbilicus = root / "umbilicus.json"
    check("umbilicus", umbilicus.is_file() and not umbilicus.is_symlink(),
          "published umbilicus is present as a regular file")
    if umbilicus.is_file() and not umbilicus.is_symlink():
        inputs["umbilicus.json"] = {"sha256": _sha256(umbilicus), "size": umbilicus.stat().st_size}

    paths = spec.get("paths") if isinstance(spec.get("paths"), dict) else {}
    tracks_rel = paths.get("tracks_dbm")
    if not isinstance(tracks_rel, str) or not tracks_rel:
        check("tracks_path", False, "spiral-scroll.json must name paths.tracks_dbm")
        tracks = None
    else:
        try:
            tracks = _resolve(root, tracks_rel)
        except SpiralPreflightError as exc:
            check("tracks_path", False, str(exc))
            tracks = None
        if tracks is not None:
            ok = tracks.is_file() and not tracks.is_symlink()
            check("tracks_path", ok, "tracks DBM is present as a regular file", path=tracks_rel)
            if ok:
                inputs[tracks_rel] = {"sha256": _sha256(tracks), "size": tracks.stat().st_size,
                                      "mtime_ns": tracks.stat().st_mtime_ns}

    track_dir = root / "tracks"
    crossings = sorted(track_dir.glob("*.crossings.npz")) if track_dir.is_dir() else []
    extracts = sorted(track_dir.glob("*.extract.json")) if track_dir.is_dir() else []
    check("crossings_unique", len(crossings) == 1,
          "exactly one published crossings archive is present", count=len(crossings))
    check("extract_provenance_unique", len(extracts) == 1,
          "exactly one track extraction provenance file is present", count=len(extracts))

    if len(extracts) == 1:
        extract_doc = _load_json(extracts[0], "track extraction provenance")
        contains = _json_contains(extract_doc, volume_id)
        check("exact_volume_in_track_provenance", contains,
              "track provenance contains exact prize volume ID",
              volume_id=volume_id)
        rel = extracts[0].relative_to(root).as_posix()
        inputs[rel] = {"sha256": _sha256(extracts[0]), "size": extracts[0].stat().st_size}

    if len(crossings) == 1:
        rel = crossings[0].relative_to(root).as_posix()
        inputs[rel] = {"sha256": _sha256(crossings[0]), "size": crossings[0].stat().st_size}
        if tracks is not None and tracks.is_file():
            try:
                sig = _crossings_signature(crossings[0])
                entry = next((row for row in sig if isinstance(row, (list, tuple)) and len(row) >= 3
                              and row[0] == tracks.name), None)
                if entry is None:
                    check("crossings_db_signature", False,
                          "crossings metadata does not name the configured tracks DBM")
                else:
                    st = tracks.stat()
                    expected_size, expected_mtime = int(entry[1]), int(entry[2])
                    check("crossings_db_signature",
                          st.st_size == expected_size and st.st_mtime_ns == expected_mtime,
                          "tracks DBM size and nanosecond mtime match crossings cache signature",
                          expected_size=expected_size, actual_size=st.st_size,
                          expected_mtime_ns=expected_mtime, actual_mtime_ns=st.st_mtime_ns)
            except SpiralPreflightError as exc:
                check("crossings_db_signature", False, str(exc))

    group = str(expected.get("normal_zarr_group"))
    names = ["las_008_nx.ome.zarr", "las_008_ny.ome.zarr", "las_008_grad_mag.ome.zarr"]
    zmeta: dict[str, dict[str, Any]] = {}
    for name in names:
        store = root / "lasagna_inputs" / name
        group_dir = store / group
        try:
            meta = _zarray(group_dir)
        except SpiralPreflightError as exc:
            check(f"lasagna:{name}", False, str(exc))
            continue
        zmeta[name] = meta
        check(f"lasagna:{name}", True, f"group {group} is present",
              shape=meta.get("shape"), dtype=meta.get("dtype"))
        inputs[(group_dir / ".zarray").relative_to(root).as_posix()] = {
            "sha256": _sha256(group_dir / ".zarray"),
            "size": (group_dir / ".zarray").stat().st_size,
        }

    if len(zmeta) == 3:
        shapes = {tuple(meta["shape"]) for meta in zmeta.values()}
        check("lasagna_shape_agreement", len(shapes) == 1,
              "nx, ny, and grad_mag group shapes agree",
              shapes=[list(s) for s in sorted(shapes)])

    nx_store = root / "lasagna_inputs" / "las_008_nx.ome.zarr"
    grad_store = root / "lasagna_inputs" / "las_008_grad_mag.ome.zarr"
    sidecars = [
        Path(str(nx_store) + f".respool_g{group}_pair") / "meta.json",
        Path(str(grad_store) + f".respool_g{group}") / "meta.json",
    ]
    for sidecar in sidecars:
        ok = sidecar.is_file() and not sidecar.is_symlink()
        check(f"resident_pool:{sidecar.parent.name}", ok,
              "resident-pool metadata is present")
        if ok:
            _load_json(sidecar, "resident-pool metadata")
            rel = sidecar.relative_to(root).as_posix()
            inputs[rel] = {"sha256": _sha256(sidecar), "size": sidecar.stat().st_size}

    overrides = bounded["config_overrides"]
    required_overrides = {
        "z_begin": bounded.get("z_range_half_open", [None, None])[0],
        "z_end": bounded.get("z_range_half_open", [None, None])[1],
        "optimizer_num_training_steps": bounded.get("optimizer_num_training_steps"),
        "optimizer_random_seed": bounded.get("optimizer_random_seed"),
        "input_use_tracks": True,
    }
    for key, value in required_overrides.items():
        check(f"config:{key}", overrides.get(key) == value,
              f"{key} matches frozen bounded-reproduction value",
              expected=value, actual=overrides.get(key))

    canonical_overrides = json.dumps(overrides, sort_keys=True, separators=(",", ":"))
    check("input_use_tracks_enabled", overrides.get("input_use_tracks") is True,
          "published tracks are explicitly enabled")
    check("patches_disabled", overrides.get("input_disable_patches") is True,
          "verified/community patches are disabled for the baseline reproduction")

    ready = all(row["ok"] for row in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready" if ready else "blocked",
        "ready_for_fit": ready,
        "scroll": scroll,
        "prize_volume_id": volume_id,
        "dataset_root": str(root),
        "checks": checks,
        "input_files": inputs,
        "config_overrides_canonical_json": canonical_overrides,
        "fit_environment": {"FIT_SPIRAL_CONFIG_OVERRIDES": canonical_overrides},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed before launching the frozen PHerc0826 Spiral baseline fit"
    )
    parser.add_argument("--dataset", required=True, help="assembled Spiral dataset root")
    parser.add_argument("--recipe", required=True, help="frozen baseline recipe JSON")
    parser.add_argument("--out", help="optional JSON report")
    args = parser.parse_args(argv)

    try:
        recipe = _load_json(Path(args.recipe), "recipe")
        report = audit_spiral_dataset(Path(args.dataset), recipe)
    except SpiralPreflightError as exc:
        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "ready_for_fit": False,
            "error": str(exc),
        }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        out = Path(args.out)
        if out.exists():
            parser.error(f"refusing to overwrite existing output: {out}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["ready_for_fit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
