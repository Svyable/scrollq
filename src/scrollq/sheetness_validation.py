"""Frozen, engine-agnostic evaluation for local papyrus sheetness evidence.

This module evaluates observations produced by any sheet-evidence engine. It does
not compute Hessians, fit surfaces, choose correspondences, or establish global
sheet identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median
from typing import Any


SCHEMA_VERSION = 1
TOOL = "scroliq-sheetness-validate"
_ROLES = {"surface", "normal_offset", "wrong_wrap"}


def digest(document: dict[str, Any]) -> str:
    """Canonical JSON hash used to bind observations to a frozen specification."""
    return hashlib.sha256(
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _number(value: Any, field: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{field} is outside numeric range") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def _xyz(value: Any, field: str) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(type(v) not in (int, float) for v in value)
    ):
        raise ValueError(f"{field} must contain three finite numbers")
    return [_number(v, field) for v in value]


def _unit(value: Any, field: str) -> list[float]:
    xyz = _xyz(value, field)
    norm = math.sqrt(sum(v * v for v in xyz))
    if norm <= 0:
        raise ValueError(f"{field} must be non-zero")
    return [v / norm for v in xyz]


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{field} must be lowercase 64-hex")
    return value


def _validate_spec(
    spec: dict[str, Any],
) -> tuple[str, dict[str, float], list[dict[str, Any]]]:
    if not isinstance(spec, dict):
        raise ValueError("specification must be an object")
    if type(spec.get("schema_version")) is not int or spec["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    if spec.get("coordinate_system") != "base_voxel_xyz":
        raise ValueError("coordinate_system must be base_voxel_xyz")
    volume_root = _name(spec.get("volume_root"), "volume_root")

    raw_criteria = spec.get("criteria")
    if not isinstance(raw_criteria, dict):
        raise ValueError("criteria must be an object")
    margin = _number(
        raw_criteria.get("min_surface_control_margin"),
        "criteria.min_surface_control_margin",
    )
    if margin < 0:
        raise ValueError("criteria.min_surface_control_margin must be >= 0")
    cosine = _number(
        raw_criteria.get("min_surface_normal_abs_cosine"),
        "criteria.min_surface_normal_abs_cosine",
    )
    if not 0 <= cosine <= 1:
        raise ValueError("criteria.min_surface_normal_abs_cosine must be in [0, 1]")
    criteria = {
        "min_surface_control_margin": margin,
        "min_surface_normal_abs_cosine": cosine,
    }

    raw_probes = spec.get("probes")
    if not isinstance(raw_probes, list) or not raw_probes:
        raise ValueError("probes must be a non-empty list")

    probes: list[dict[str, Any]] = []
    seen: set[str] = set()
    groups: dict[str, list[dict[str, Any]]] = {}
    for i, raw in enumerate(raw_probes):
        label = f"probes[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{label} must be an object")
        probe_id = _name(raw.get("id"), f"{label}.id")
        if probe_id in seen:
            raise ValueError(f"duplicate probe id: {probe_id}")
        seen.add(probe_id)
        group_id = _name(raw.get("group_id"), f"{label}.group_id")
        role = raw.get("role")
        if role not in _ROLES:
            raise ValueError(f"{label}.role must be one of {sorted(_ROLES)}")
        probe = {
            "id": probe_id,
            "group_id": group_id,
            "role": role,
            "xyz": _xyz(raw.get("xyz"), f"{label}.xyz"),
        }
        if role == "surface":
            probe["reference_normal_xyz"] = _unit(
                raw.get("reference_normal_xyz"),
                f"{label}.reference_normal_xyz",
            )
        else:
            probe["reference_surface_id"] = _name(
                raw.get("reference_surface_id"),
                f"{label}.reference_surface_id",
            )
            if role == "normal_offset":
                offset = _number(raw.get("offset_voxels"), f"{label}.offset_voxels")
                if offset == 0:
                    raise ValueError(f"{label}.offset_voxels must be non-zero")
                probe["offset_voxels"] = offset
        probes.append(probe)
        groups.setdefault(group_id, []).append(probe)

    by_id = {row["id"]: row for row in probes}
    for group_id, rows in groups.items():
        surfaces = [row for row in rows if row["role"] == "surface"]
        controls = [row for row in rows if row["role"] != "surface"]
        if len(surfaces) != 1:
            raise ValueError(f"group {group_id!r} must contain exactly one surface probe")
        if not controls:
            raise ValueError(f"group {group_id!r} must contain at least one control probe")
        surface_id = surfaces[0]["id"]
        for control in controls:
            reference_id = control["reference_surface_id"]
            if reference_id != surface_id:
                raise ValueError(
                    f"control {control['id']!r} must reference surface {surface_id!r} "
                    f"within group {group_id!r}"
                )
            if reference_id not in by_id:
                raise ValueError(
                    f"control {control['id']!r} references unknown surface {reference_id!r}"
                )

    return volume_root, criteria, probes


def _validate_engine(engine: Any) -> dict[str, Any]:
    if not isinstance(engine, dict):
        raise ValueError("engine must be an object")
    result: dict[str, Any] = {
        "name": _name(engine.get("name"), "engine.name"),
        "version": _name(engine.get("version"), "engine.version"),
        "config_sha256": _sha256(engine.get("config_sha256"), "engine.config_sha256"),
    }
    deterministic = engine.get("deterministic")
    if type(deterministic) is not bool:
        raise ValueError("engine.deterministic must be a boolean")
    result["deterministic"] = deterministic

    source_revision = engine.get("source_revision")
    if source_revision is not None:
        result["source_revision"] = _name(source_revision, "engine.source_revision")

    seed = engine.get("seed")
    if deterministic:
        if seed is not None and type(seed) is not int:
            raise ValueError("engine.seed must be an integer when supplied")
        result["seed"] = seed
    else:
        if type(seed) is not int:
            raise ValueError("stochastic engines must declare an integer engine.seed")
        result["seed"] = seed
    return result


def evaluate(spec: dict[str, Any], observations: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a frozen sheetness benchmark without computing sheetness itself."""
    volume_root, criteria, probes = _validate_spec(spec)
    if not isinstance(observations, dict):
        raise ValueError("observations must be an object")
    if (
        type(observations.get("schema_version")) is not int
        or observations["schema_version"] != SCHEMA_VERSION
    ):
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    if observations.get("coordinate_system") != "base_voxel_xyz":
        raise ValueError("coordinate_system must be base_voxel_xyz")
    if observations.get("volume_root") != volume_root:
        raise ValueError("exact volume_root mismatch")

    spec_sha = digest(spec)
    if observations.get("spec_sha256") != spec_sha:
        raise ValueError("spec_sha256 mismatch: evaluation specification changed")
    engine = _validate_engine(observations.get("engine"))

    raw_rows = observations.get("observations")
    if not isinstance(raw_rows, list):
        raise ValueError("observations must contain an observations list")
    expected = {probe["id"]: probe for probe in probes}
    seen: dict[str, dict[str, Any]] = {}
    for i, raw in enumerate(raw_rows):
        label = f"observations[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{label} must be an object")
        probe_id = _name(raw.get("id"), f"{label}.id")
        if probe_id not in expected or probe_id in seen:
            raise ValueError("unknown or duplicate observation id")
        status = raw.get("status")
        if status == "failed":
            if raw.get("sheetness") is not None or raw.get("normal_xyz") is not None:
                raise ValueError("failed observation cannot supply sheetness or normal_xyz")
            seen[probe_id] = {
                "status": "failed",
                "reason": _name(raw.get("reason"), f"{label}.reason"),
            }
        elif status == "ok":
            row: dict[str, Any] = {
                "status": "ok",
                "sheetness": _number(raw.get("sheetness"), f"{label}.sheetness"),
            }
            normal = raw.get("normal_xyz")
            if normal is not None:
                row["normal_xyz"] = _unit(normal, f"{label}.normal_xyz")
            scale = raw.get("scale_voxels")
            if scale is not None:
                scale_value = _number(scale, f"{label}.scale_voxels")
                if scale_value <= 0:
                    raise ValueError(f"{label}.scale_voxels must be positive")
                row["scale_voxels"] = scale_value
            seen[probe_id] = row
        else:
            raise ValueError(f"{label}.status must be ok or failed")

    probe_rows: list[dict[str, Any]] = []
    for probe in probes:
        measured = seen.get(probe["id"], {"status": "missing"})
        probe_rows.append({**probe, **measured})

    groups: list[dict[str, Any]] = []
    margins: list[float] = []
    cosines: list[float] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in probe_rows:
        grouped.setdefault(row["group_id"], []).append(row)

    for group_id in sorted(grouped):
        rows = grouped[group_id]
        surface = next(row for row in rows if row["role"] == "surface")
        controls = [row for row in rows if row["role"] != "surface"]
        group: dict[str, Any] = {
            "group_id": group_id,
            "surface_id": surface["id"],
            "control_ids": [row["id"] for row in controls],
            "complete": False,
            "surface_sheetness": None,
            "max_control_sheetness": None,
            "surface_control_margin": None,
            "surface_beats_controls": False,
            "surface_normal_abs_cosine": None,
            "surface_normal_aligned": False,
            "meets_frozen_criteria": False,
        }
        if surface["status"] == "ok" and all(row["status"] == "ok" for row in controls):
            surface_score = surface["sheetness"]
            max_control = max(row["sheetness"] for row in controls)
            margin = surface_score - max_control
            group.update(
                complete=True,
                surface_sheetness=surface_score,
                max_control_sheetness=max_control,
                surface_control_margin=margin,
                surface_beats_controls=margin >= criteria["min_surface_control_margin"],
            )
            margins.append(margin)
            predicted_normal = surface.get("normal_xyz")
            if predicted_normal is not None:
                reference_normal = surface["reference_normal_xyz"]
                cosine = abs(sum(a * b for a, b in zip(predicted_normal, reference_normal)))
                cosine = min(1.0, max(0.0, cosine))
                group["surface_normal_abs_cosine"] = cosine
                group["surface_normal_aligned"] = (
                    cosine >= criteria["min_surface_normal_abs_cosine"]
                )
                cosines.append(cosine)
            group["meets_frozen_criteria"] = (
                group["surface_beats_controls"] and group["surface_normal_aligned"]
            )
        groups.append(group)

    n_expected = len(probe_rows)
    observed_ok = sum(row["status"] == "ok" for row in probe_rows)
    missing = sum(row["status"] == "missing" for row in probe_rows)
    failed = sum(row["status"] == "failed" for row in probe_rows)
    status = "measured" if observed_ok == n_expected else "incomplete"
    groups_met = sum(row["meets_frozen_criteria"] for row in groups)
    benchmark_pass = status == "measured" and groups_met == len(groups)

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "status": status,
        "volume_root": volume_root,
        "coordinate_system": "base_voxel_xyz",
        "spec_sha256": spec_sha,
        "observation_sha256": digest(observations),
        "engine": engine,
        "criteria": criteria,
        "expected_probes": n_expected,
        "observed_ok": observed_ok,
        "missing": missing,
        "failed": failed,
        "group_count": len(groups),
        "groups_meeting_frozen_criteria": groups_met,
        "groups_meeting_frozen_criteria_rate": groups_met / len(groups),
        "surface_control_margin_median": median(margins) if margins else None,
        "surface_normal_abs_cosine_median": median(cosines) if cosines else None,
        "meets_frozen_criteria": benchmark_pass,
        "groups": groups,
        "probes": probe_rows,
        "limitations": (
            "This evaluates local sheet-evidence discrimination and normal agreement at frozen "
            "probe coordinates. It does not establish global sheet identity, topology, recto "
            "coverage, flattening quality, ink presence, readability, or Grand Prize readiness."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="frozen benchmark specification JSON")
    parser.add_argument("--observations", help="engine observations JSON; omit with --print-spec-hash")
    parser.add_argument("--print-spec-hash", action="store_true")
    parser.add_argument("--out", help="new report path; refuses overwrite")
    args = parser.parse_args(argv)

    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        if args.print_spec_hash:
            print(digest(spec))
            return 0
        if not args.observations:
            parser.error("--observations is required unless --print-spec-hash is used")
        observations = json.loads(Path(args.observations).read_text(encoding="utf-8"))
        result = evaluate(spec, observations)
        text = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.out:
            with Path(args.out).open("x", encoding="utf-8") as handle:
                handle.write(text)
        print(text, end="")
        return int(not result["meets_frozen_criteria"])
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
