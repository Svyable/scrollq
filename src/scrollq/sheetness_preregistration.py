"""Freeze sheetness experiment choices before CT-derived response values exist."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from .sheetness import METHOD as SHEETNESS_METHOD
from .sheetness_benchmark import SCHEMA as BENCHMARK_SCHEMA
from .sheetness_benchmark import _validate_rule as validate_benchmark_rule


SCHEMA = "scroliq-sheetness-preregistration/1"
RECEIPT_SCHEMA = "scroliq-sheetness-preregistration-receipt/1"
BENCHMARK_SPEC_VERSION = int(BENCHMARK_SCHEMA.rsplit("/", 1)[1])
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_RESULT_KEYS = {
    "input_sha256",
    "cutout_manifest_sha256",
    "sheetness_report_sha256",
    "response_sha256",
    "normal_sha256",
    "metrics",
    "decision_checks",
    "result",
    "status",
}


class PreregistrationError(ValueError):
    pass


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha256(value: Any) -> str:
    blob = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise PreregistrationError(f"{name} must be lowercase 64-hex sha256")
    return value


def _int_coord(value: Any, name: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(type(v) is not int for v in value)
    ):
        raise PreregistrationError(f"{name} must be three integer ZYX coordinates")
    return int(value[0]), int(value[1]), int(value[2])


def _float_coord(value: Any, name: str) -> tuple[float, float, float]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value)
    ):
        raise PreregistrationError(f"{name} must be three finite numeric ZYX coordinates")
    out = tuple(float(v) for v in value)
    if not all(math.isfinite(v) for v in out):
        raise PreregistrationError(f"{name} must be finite")
    return out  # type: ignore[return-value]


def _unit(value: Any, name: str) -> np.ndarray:
    coord = np.asarray(_float_coord(value, name), dtype=np.float64)
    norm = float(np.linalg.norm(coord))
    if norm <= 0:
        raise PreregistrationError(f"{name} must be non-zero")
    return coord / norm


def _surface_source(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreregistrationError(f"{name} must be an object")
    surface_id = value.get("surface_id")
    source_url = value.get("source_url")
    if not isinstance(surface_id, str) or not surface_id:
        raise PreregistrationError(f"{name}.surface_id is required")
    if not isinstance(source_url, str) or not source_url.startswith(("https://", "http://")):
        raise PreregistrationError(f"{name}.source_url must be public http(s)")

    hashes = value.get("coordinate_sha256")
    if not isinstance(hashes, dict):
        raise PreregistrationError(f"{name}.coordinate_sha256 is required")
    normalized: dict[str, str] = {}
    for channel in ("x.tif", "y.tif", "z.tif"):
        normalized[channel] = _require_sha(
            hashes.get(channel), f"{name}.coordinate_sha256.{channel}"
        )

    out = {
        "surface_id": surface_id,
        "source_url": source_url.rstrip("/"),
        "coordinate_sha256": normalized,
    }
    meta = value.get("meta_sha256")
    if meta is not None:
        out["meta_sha256"] = _require_sha(meta, f"{name}.meta_sha256")
    return out


def _validate_engine(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreregistrationError("engine is required")
    allowed = {
        "method",
        "sigmas",
        "beta",
        "gamma",
        "bright_object",
        "scale_objectness",
        "normalize",
        "lower_percentile",
        "upper_percentile",
        "write_normal",
    }
    extra = sorted(set(value) - allowed)
    if extra:
        raise PreregistrationError(f"engine contains unsupported keys: {extra}")

    if value.get("method") != SHEETNESS_METHOD:
        raise PreregistrationError(f"engine.method must be {SHEETNESS_METHOD!r}")

    sigmas = value.get("sigmas")
    if (
        not isinstance(sigmas, list)
        or not sigmas
        or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(float(v))
            or float(v) <= 0
            for v in sigmas
        )
    ):
        raise PreregistrationError("engine.sigmas must be non-empty finite positive numbers")

    def positive(name: str) -> float:
        raw = value.get(name)
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not math.isfinite(float(raw))
            or float(raw) <= 0
        ):
            raise PreregistrationError(f"engine.{name} must be finite and positive")
        return float(raw)

    beta = positive("beta")
    gamma = positive("gamma")
    for name in ("bright_object", "scale_objectness", "normalize", "write_normal"):
        if type(value.get(name)) is not bool:
            raise PreregistrationError(f"engine.{name} must be boolean")
    if value["write_normal"] is not True:
        raise PreregistrationError("engine.write_normal must be true for normal validation")

    low = value.get("lower_percentile")
    high = value.get("upper_percentile")
    if (
        isinstance(low, bool)
        or isinstance(high, bool)
        or not isinstance(low, (int, float))
        or not isinstance(high, (int, float))
    ):
        raise PreregistrationError(
            "engine.lower_percentile and upper_percentile must be numeric"
        )
    low_f, high_f = float(low), float(high)
    if not (math.isfinite(low_f) and math.isfinite(high_f) and 0 <= low_f < high_f <= 100):
        raise PreregistrationError(
            "engine normalization percentiles must satisfy 0 <= low < high <= 100"
        )

    return {
        "method": SHEETNESS_METHOD,
        "sigmas": [float(v) for v in sigmas],
        "beta": beta,
        "gamma": gamma,
        "bright_object": value["bright_object"],
        "scale_objectness": value["scale_objectness"],
        "normalize": value["normalize"],
        "lower_percentile": low_f,
        "upper_percentile": high_f,
        "write_normal": True,
    }


def validate_preregistration(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreregistrationError("preregistration must be a JSON object")
    if value.get("schema") != SCHEMA:
        raise PreregistrationError(f"schema must be {SCHEMA!r}")
    if value.get("benchmark_schema") != BENCHMARK_SCHEMA:
        raise PreregistrationError(
            f"benchmark_schema must match current {BENCHMARK_SCHEMA!r}"
        )
    leaked = sorted(_FORBIDDEN_RESULT_KEYS & set(value))
    if leaked:
        raise PreregistrationError(
            f"preregistration contains result-derived keys: {leaked}"
        )

    experiment_id = value.get("experiment_id")
    phase = value.get("phase")
    if not isinstance(experiment_id, str) or not experiment_id:
        raise PreregistrationError("experiment_id is required")
    if phase not in {"reference", "transfer"}:
        raise PreregistrationError("phase must be 'reference' or 'transfer'")

    volume_root = value.get("volume_root")
    ct_url = value.get("ct_url")
    if not isinstance(volume_root, str) or not volume_root.strip("/"):
        raise PreregistrationError("volume_root is required")
    volume_root = volume_root.strip("/")
    if not isinstance(ct_url, str) or not ct_url.startswith(("https://", "http://")):
        raise PreregistrationError("ct_url must be public http(s)")
    ct_url = ct_url.rstrip("/")
    if not ct_url.endswith("/" + volume_root):
        raise PreregistrationError("ct_url must end with the exact volume_root")

    zpa_report_sha = _require_sha(value.get("zpa_report_sha256"), "zpa_report_sha256")
    attestation = value.get("source_attestation")
    if not isinstance(attestation, dict):
        raise PreregistrationError("source_attestation is required")
    if attestation.get("algorithm") != "zpa-metadata-semantics-v1":
        raise PreregistrationError(
            "source_attestation.algorithm must be zpa-metadata-semantics-v1"
        )
    if attestation.get("state") != "PRESENT":
        raise PreregistrationError("source_attestation.state must be PRESENT")
    metadata_sha = _require_sha(
        attestation.get("metadata_semantics_sha256"),
        "source_attestation.metadata_semantics_sha256",
    )
    if attestation.get("axes") != ["z", "y", "x"]:
        raise PreregistrationError("source_attestation.axes must be ['z', 'y', 'x']")

    bbox = value.get("cutout_bbox_zyx_half_open")
    if not isinstance(bbox, dict):
        raise PreregistrationError("cutout_bbox_zyx_half_open is required")
    start = _int_coord(bbox.get("start"), "cutout bbox start")
    stop = _int_coord(bbox.get("stop"), "cutout bbox stop")
    if any(a < 0 or a >= b for a, b in zip(start, stop)):
        raise PreregistrationError(
            "cutout bbox must be non-negative and increasing on every axis"
        )
    cutout_shape = tuple(b - a for a, b in zip(start, stop))
    if int(np.prod(cutout_shape)) > 2_500_000:
        raise PreregistrationError(
            "cutout exceeds the reference sheetness implementation's 2,500,000-voxel guard"
        )

    engine = _validate_engine(value.get("engine"))
    try:
        decision_rule = validate_benchmark_rule(value.get("decision_rule"))
    except ValueError as exc:
        raise PreregistrationError(str(exc)) from exc

    selection = value.get("selection_rule")
    if not isinstance(selection, dict):
        raise PreregistrationError("selection_rule is required")
    if not isinstance(selection.get("algorithm"), str) or not selection["algorithm"]:
        raise PreregistrationError("selection_rule.algorithm is required")
    if selection.get("ct_intensity_used") is not False:
        raise PreregistrationError("selection_rule.ct_intensity_used must be false")
    if selection.get("sheetness_outputs_used") is not False:
        raise PreregistrationError("selection_rule.sheetness_outputs_used must be false")

    stop_rules = value.get("stop_rules")
    if (
        not isinstance(stop_rules, list)
        or not stop_rules
        or any(not isinstance(v, str) or not v.strip() for v in stop_rules)
    ):
        raise PreregistrationError("stop_rules must be a non-empty list of strings")

    groups = value.get("groups")
    if not isinstance(groups, list) or not groups:
        raise PreregistrationError("groups must be a non-empty list")
    group_ids: set[str] = set()
    normalized_groups: list[dict[str, Any]] = []

    for i, group in enumerate(groups):
        path = f"groups[{i}]"
        if not isinstance(group, dict):
            raise PreregistrationError(f"{path} must be an object")
        gid = group.get("id")
        if not isinstance(gid, str) or not gid:
            raise PreregistrationError(f"{path}.id is required")
        if gid in group_ids:
            raise PreregistrationError(f"duplicate group id {gid!r}")
        group_ids.add(gid)

        surface = group.get("surface")
        if not isinstance(surface, dict):
            raise PreregistrationError(f"{path}.surface is required")
        surface_global = np.asarray(
            _float_coord(surface.get("global_zyx"), f"{path}.surface.global_zyx"),
            dtype=np.float64,
        )
        normal = _unit(
            surface.get("reference_normal_zyx"),
            f"{path}.surface.reference_normal_zyx",
        )
        surface_source = _surface_source(
            surface.get("source"), f"{path}.surface.source"
        )

        controls = group.get("controls")
        if not isinstance(controls, list) or not controls:
            raise PreregistrationError(f"{path}.controls must be non-empty")
        seen_control_ids: set[str] = set()
        signs: set[int] = set()
        distances: set[float] = set()
        wrong_wrap_count = 0
        normalized_controls: list[dict[str, Any]] = []

        for j, control in enumerate(controls):
            cpath = f"{path}.controls[{j}]"
            if not isinstance(control, dict):
                raise PreregistrationError(f"{cpath} must be an object")
            cid = control.get("id")
            role = control.get("role")
            if not isinstance(cid, str) or not cid:
                raise PreregistrationError(f"{cpath}.id is required")
            if cid in seen_control_ids:
                raise PreregistrationError(f"{path}: duplicate control id {cid!r}")
            seen_control_ids.add(cid)
            if role not in {"normal-offset", "wrong-wrap"}:
                raise PreregistrationError(
                    f"{cpath}.role must be normal-offset or wrong-wrap"
                )
            global_coord = np.asarray(
                _float_coord(control.get("global_zyx"), f"{cpath}.global_zyx"),
                dtype=np.float64,
            )

            normalized_control: dict[str, Any] = {
                "id": cid,
                "role": role,
                "global_zyx": [float(v) for v in global_coord],
            }
            if role == "normal-offset":
                derivation = control.get("derivation")
                if not isinstance(derivation, dict):
                    raise PreregistrationError(
                        f"{cpath}.derivation is required for normal-offset controls"
                    )
                sign = derivation.get("sign")
                distance = derivation.get("distance_voxels")
                if sign not in {-1, 1}:
                    raise PreregistrationError(f"{cpath}.derivation.sign must be -1 or 1")
                if (
                    isinstance(distance, bool)
                    or not isinstance(distance, (int, float))
                    or not math.isfinite(float(distance))
                    or float(distance) <= 0
                ):
                    raise PreregistrationError(
                        f"{cpath}.derivation.distance_voxels must be finite and positive"
                    )
                distance_f = float(distance)
                expected = surface_global + int(sign) * distance_f * normal
                if not np.allclose(global_coord, expected, rtol=0, atol=1e-6):
                    raise PreregistrationError(
                        f"{cpath}.global_zyx does not match frozen normal-offset derivation"
                    )
                signs.add(int(sign))
                distances.add(distance_f)
                normalized_control["derivation"] = {
                    "kind": "normal-offset",
                    "sign": int(sign),
                    "distance_voxels": distance_f,
                }
            else:
                wrong_wrap_count += 1
                wrong_source = _surface_source(
                    control.get("source"), f"{cpath}.source"
                )
                if wrong_source["surface_id"] == surface_source["surface_id"]:
                    raise PreregistrationError(
                        f"{cpath}.source must name a different surface"
                    )
                normalized_control["source"] = wrong_source

            normalized_controls.append(normalized_control)

        if signs != {-1, 1}:
            raise PreregistrationError(
                f"{path} must include symmetric + and - normal-offset controls"
            )
        if len(distances) != 1:
            raise PreregistrationError(
                f"{path} normal-offset controls must use one frozen distance"
            )
        if wrong_wrap_count < 1:
            raise PreregistrationError(
                f"{path} must include at least one wrong-wrap ambiguity probe"
            )

        normalized_groups.append(
            {
                "id": gid,
                "surface": {
                    "global_zyx": [float(v) for v in surface_global],
                    "reference_normal_zyx": [float(v) for v in normal],
                    "source": surface_source,
                },
                "controls": normalized_controls,
            }
        )

    return {
        "schema": SCHEMA,
        "benchmark_schema": BENCHMARK_SCHEMA,
        "experiment_id": experiment_id,
        "phase": phase,
        "volume_root": volume_root,
        "ct_url": ct_url,
        "zpa_report_sha256": zpa_report_sha,
        "source_attestation": {
            "algorithm": "zpa-metadata-semantics-v1",
            "state": "PRESENT",
            "metadata_semantics_sha256": metadata_sha,
            "axes": ["z", "y", "x"],
        },
        "cutout_bbox_zyx_half_open": {
            "start": list(start),
            "stop": list(stop),
        },
        "engine": engine,
        "decision_rule": decision_rule,
        "selection_rule": selection,
        "stop_rules": [v.strip() for v in stop_rules],
        "groups": normalized_groups,
    }


def validation_receipt(
    preregistration: dict[str, Any], *, file_sha256: str
) -> dict[str, Any]:
    normalized = validate_preregistration(preregistration)
    file_sha256 = _require_sha(file_sha256, "preregistration file sha256")
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "valid",
        "experiment_id": normalized["experiment_id"],
        "phase": normalized["phase"],
        "benchmark_schema": normalized["benchmark_schema"],
        "volume_root": normalized["volume_root"],
        "preregistration_file_sha256": file_sha256,
        "preregistration_canonical_sha256": canonical_sha256(normalized),
        "contains_ct_response_values": False,
        "claim": (
            "Scientific choices are frozen before cutout/sheetness output hashes or "
            "sheetness response values are admitted into the final evaluation spec."
        ),
    }


def _verify_cutout(
    prereg: dict[str, Any], manifest: Any, *, file_sha256: str
) -> tuple[str, tuple[int, int, int]]:
    if not isinstance(manifest, dict) or manifest.get("schema") != "scroliq-ct-cutout/1":
        raise PreregistrationError("cutout manifest must be scroliq-ct-cutout/1")
    if manifest.get("status") != "measured":
        raise PreregistrationError("cutout manifest status must be measured")
    if manifest.get("volume_root") != prereg["volume_root"]:
        raise PreregistrationError("cutout manifest volume_root drifted from preregistration")
    if str(manifest.get("ct_url", "")).rstrip("/") != prereg["ct_url"]:
        raise PreregistrationError("cutout manifest ct_url drifted from preregistration")

    zpa = manifest.get("zpa_report")
    if not isinstance(zpa, dict):
        raise PreregistrationError("cutout manifest zpa_report is required")
    if zpa.get("integrity") != "PASS":
        raise PreregistrationError("cutout manifest retained ZPA proof is not PASS")
    if zpa.get("sha256") != prereg["zpa_report_sha256"]:
        raise PreregistrationError("cutout manifest ZPA report hash drifted")

    att = manifest.get("source_attestation")
    if not isinstance(att, dict):
        raise PreregistrationError("cutout manifest source_attestation is required")
    for key in ("algorithm", "state", "metadata_semantics_sha256", "axes"):
        if att.get(key) != prereg["source_attestation"].get(key):
            raise PreregistrationError(
                f"cutout manifest source_attestation.{key} drifted"
            )

    if manifest.get("level") != 0 or manifest.get("coordinate_space") != "level0-voxel-index":
        raise PreregistrationError("cutout manifest coordinate space drifted")

    bbox = manifest.get("bbox_zyx_half_open")
    if bbox != prereg["cutout_bbox_zyx_half_open"]:
        raise PreregistrationError("cutout bbox drifted from preregistration")
    start = _int_coord(bbox.get("start"), "cutout bbox start")
    stop = _int_coord(bbox.get("stop"), "cutout bbox stop")
    shape = tuple(b - a for a, b in zip(start, stop))

    cutout = manifest.get("cutout")
    if not isinstance(cutout, dict):
        raise PreregistrationError("cutout manifest cutout record is required")
    cutout_sha = _require_sha(cutout.get("sha256"), "cutout.sha256")
    if cutout.get("shape_zyx") != list(shape):
        raise PreregistrationError("cutout shape drifted from preregistered bbox")
    if cutout.get("dtype") != "uint8":
        raise PreregistrationError("cutout dtype must remain uint8")
    chunks = manifest.get("source_chunks")
    if not isinstance(chunks, dict) or chunks.get("missing_count") != 0:
        raise PreregistrationError("cutout manifest must retain zero missing chunks")
    _require_sha(file_sha256, "cutout manifest file sha256")
    return cutout_sha, start


def _verify_sheetness_report(
    prereg: dict[str, Any], report: Any, *, cutout_sha: str
) -> None:
    if not isinstance(report, dict):
        raise PreregistrationError("sheetness report must be an object")
    if report.get("kind") != "sheetness" or report.get("schema_version") != 1:
        raise PreregistrationError("sheetness report schema drifted")

    input_rec = report.get("input")
    if not isinstance(input_rec, dict) or input_rec.get("sha256") != cutout_sha:
        raise PreregistrationError("sheetness report input hash does not match cutout")
    bbox = prereg["cutout_bbox_zyx_half_open"]
    expected_shape = [
        bbox["stop"][d] - bbox["start"][d] for d in range(3)
    ]
    if input_rec.get("shape_zyx") != expected_shape:
        raise PreregistrationError("sheetness report input shape drifted")

    engine = prereg["engine"]
    if report.get("method") != engine["method"]:
        raise PreregistrationError("sheetness method drifted from preregistration")
    params = report.get("parameters")
    expected_params = {
        "sigmas": engine["sigmas"],
        "beta": engine["beta"],
        "gamma": engine["gamma"],
        "bright_object": engine["bright_object"],
        "scale_objectness": engine["scale_objectness"],
    }
    if params != expected_params:
        raise PreregistrationError("sheetness parameters drifted from preregistration")

    normalization = report.get("normalization")
    if not isinstance(normalization, dict):
        raise PreregistrationError("sheetness normalization record is required")
    if normalization.get("enabled") is not engine["normalize"]:
        raise PreregistrationError("sheetness normalization enablement drifted")
    if engine["normalize"]:
        low = normalization.get("lower_percentile")
        high = normalization.get("upper_percentile")
        if (
            isinstance(low, bool)
            or not isinstance(low, (int, float))
            or float(low) != engine["lower_percentile"]
        ):
            raise PreregistrationError("sheetness lower normalization percentile drifted")
        if (
            isinstance(high, bool)
            or not isinstance(high, (int, float))
            or float(high) != engine["upper_percentile"]
        ):
            raise PreregistrationError("sheetness upper normalization percentile drifted")

    response = report.get("response")
    normal = report.get("normal")
    if not isinstance(response, dict):
        raise PreregistrationError("sheetness response record is required")
    _require_sha(response.get("output_sha256"), "sheetness response output_sha256")
    if not isinstance(normal, dict):
        raise PreregistrationError(
            "sheetness normal output is required by the preregistered experiment"
        )
    _require_sha(normal.get("output_sha256"), "sheetness normal output_sha256")


def finalize_spec(
    preregistration: dict[str, Any],
    *,
    preregistration_file_sha256: str,
    cutout_manifest: dict[str, Any],
    cutout_manifest_file_sha256: str,
    sheetness_report: dict[str, Any],
    sheetness_report_file_sha256: str,
) -> dict[str, Any]:
    prereg = validate_preregistration(preregistration)
    cutout_sha, start = _verify_cutout(
        prereg, cutout_manifest, file_sha256=cutout_manifest_file_sha256
    )
    _verify_sheetness_report(prereg, sheetness_report, cutout_sha=cutout_sha)
    _require_sha(sheetness_report_file_sha256, "sheetness report file sha256")

    shape = tuple(
        prereg["cutout_bbox_zyx_half_open"]["stop"][d]
        - prereg["cutout_bbox_zyx_half_open"]["start"][d]
        for d in range(3)
    )

    def local(global_coord: list[float], name: str) -> list[float]:
        g = _float_coord(global_coord, name)
        out = [float(g[d] - start[d]) for d in range(3)]
        if any(v < 0 or v > shape[d] - 1 for d, v in enumerate(out)):
            raise PreregistrationError(
                f"{name} falls outside the preregistered cutout interpolation domain"
            )
        return out

    groups: list[dict[str, Any]] = []
    for i, group in enumerate(prereg["groups"]):
        surface = group["surface"]
        final_surface = {
            "zyx": local(surface["global_zyx"], f"groups[{i}].surface.global_zyx"),
            "reference_normal_zyx": surface["reference_normal_zyx"],
            "geometry_source": surface["source"],
            "frozen_global_zyx": surface["global_zyx"],
        }
        controls: list[dict[str, Any]] = []
        for j, control in enumerate(group["controls"]):
            row = {
                "id": control["id"],
                "role": control["role"],
                "zyx": local(
                    control["global_zyx"],
                    f"groups[{i}].controls[{j}].global_zyx",
                ),
                "frozen_global_zyx": control["global_zyx"],
            }
            if "derivation" in control:
                row["derivation"] = control["derivation"]
            if "source" in control:
                row["geometry_source"] = control["source"]
            controls.append(row)
        groups.append({"id": group["id"], "surface": final_surface, "controls": controls})

    return {
        "schema_version": BENCHMARK_SPEC_VERSION,
        "preregistration": {
            "schema": SCHEMA,
            "experiment_id": prereg["experiment_id"],
            "phase": prereg["phase"],
            "file_sha256": _require_sha(
                preregistration_file_sha256, "preregistration file sha256"
            ),
            "canonical_sha256": canonical_sha256(prereg),
        },
        "volume_root": prereg["volume_root"],
        "source_attestation": prereg["source_attestation"],
        "input_sha256": cutout_sha,
        "cutout_manifest_sha256": _require_sha(
            cutout_manifest_file_sha256, "cutout manifest file sha256"
        ),
        "sheetness_report_sha256": sheetness_report_file_sha256,
        "decision_rule": prereg["decision_rule"],
        "groups": groups,
    }


def _read_json(path: str | Path, name: str) -> tuple[Path, dict[str, Any]]:
    p = Path(path)
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreregistrationError(f"cannot read {name}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreregistrationError(f"{name} must contain a JSON object")
    return p, value


def _write_new(path: str | Path, value: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser(
        "validate", help="validate a pre-result preregistration and emit its hashes"
    )
    validate.add_argument("--prereg", required=True)
    validate.add_argument("--out", help="optional create-only validation receipt")

    finalize = sub.add_parser(
        "finalize",
        help="add only measured artifact hashes and local coordinates to a frozen preregistration",
    )
    finalize.add_argument("--prereg", required=True)
    finalize.add_argument("--cutout-manifest", required=True)
    finalize.add_argument("--sheetness-report", required=True)
    finalize.add_argument("--out", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        prereg_path, prereg = _read_json(args.prereg, "preregistration")
        prereg_sha = sha256_file(prereg_path)

        if args.command == "validate":
            receipt = validation_receipt(prereg, file_sha256=prereg_sha)
            if args.out:
                _write_new(args.out, receipt)
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return 0

        cutout_path, cutout = _read_json(args.cutout_manifest, "cutout manifest")
        report_path, report = _read_json(args.sheetness_report, "sheetness report")
        spec = finalize_spec(
            prereg,
            preregistration_file_sha256=prereg_sha,
            cutout_manifest=cutout,
            cutout_manifest_file_sha256=sha256_file(cutout_path),
            sheetness_report=report,
            sheetness_report_file_sha256=sha256_file(report_path),
        )
        _write_new(args.out, spec)
        print(json.dumps(spec, indent=2, sort_keys=True))
        return 0
    except (PreregistrationError, OSError) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "invalid", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
