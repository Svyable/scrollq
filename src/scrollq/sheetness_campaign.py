"""Freeze and aggregate a dispersed, preregistered sheetness campaign.

The campaign layer exists because real surface probes may be far apart in one
CT volume. It freezes one bounded cutout per probe group plus one global
scientific decision rule before any sheetness response is computed.

Workflow:
  freeze -> extract cutouts -> run scroliq-sheetness -> seal-group
         -> scroliq-sheetness-eval -> aggregate

The per-group v3 benchmark specs use a measurement-only rule. The scientific
pass/fail decision is applied once, across the complete frozen campaign, so a
criterion such as "75% of groups localize" is not accidentally interpreted as
"every single group must individually pass a 75% rule."
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from . import sheetness
from .sheetness_benchmark import SCHEMA as BENCHMARK_SCHEMA

SCHEMA = "scroliq-sheetness-campaign/1"
AGGREGATE_SCHEMA = "scroliq-sheetness-campaign-result/1"
COORDINATE_SPACE = "level0-voxel-index-zyx"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

MEASUREMENT_ONLY_RULE = {
    "min_score_completeness": 1.0,
    "min_normal_offset_win_fraction": 0.0,
    "min_median_normal_offset_margin": -1.0,
    "min_normal_completeness": 1.0,
    "min_median_abs_cosine": 0.0,
}


class CampaignError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _load_json(path: str | Path, label: str) -> dict[str, Any]:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise CampaignError(f"{field} must be lowercase 64-hex sha256")
    return value


def _git_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or GIT_SHA_RE.fullmatch(value) is None:
        raise CampaignError(f"{field} must be lowercase 40-hex git sha")
    return value


def _finite(value: Any, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise CampaignError(f"{field} must be finite numeric")
    return float(value)


def _fraction(value: Any, field: str) -> float:
    out = _finite(value, field)
    if not 0.0 <= out <= 1.0:
        raise CampaignError(f"{field} must be in [0, 1]")
    return out


def _triplet(value: Any, field: str) -> np.ndarray:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(float(v))
            for v in value
        )
    ):
        raise CampaignError(f"{field} must contain three finite numeric ZYX values")
    return np.asarray(value, dtype=np.float64)


def _int_triplet(value: Any, field: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(type(v) is not int for v in value)
    ):
        raise CampaignError(f"{field} must contain three integer ZYX values")
    return int(value[0]), int(value[1]), int(value[2])


def _source_attestation(plan: Mapping[str, Any]) -> dict[str, Any]:
    source = plan.get("source_attestation")
    if not isinstance(source, dict):
        raise CampaignError("reference plan source_attestation is required")
    if source.get("algorithm") != "zpa-metadata-semantics-v1":
        raise CampaignError("reference plan source-attestation algorithm mismatch")
    if source.get("state") != "PRESENT":
        raise CampaignError("reference plan source-attestation state must be PRESENT")
    if source.get("axes") != ["z", "y", "x"]:
        raise CampaignError("reference plan source axes must be exactly ZYX")
    digest = _sha(
        source.get("metadata_semantics_sha256"),
        "reference plan metadata_semantics_sha256",
    )
    return {
        "algorithm": source["algorithm"],
        "state": source["state"],
        "metadata_semantics_sha256": digest,
        "axes": ["z", "y", "x"],
    }


def _validate_reference_plan(
    document: Mapping[str, Any], *, file_sha256: str
) -> dict[str, Any]:
    if document.get("schema") != "scroliq-sheetness-plan/1":
        raise CampaignError("reference plan must be scroliq-sheetness-plan/1")
    if document.get("status") != "planned":
        raise CampaignError("reference plan status must be planned")
    volume_root = document.get("volume_root")
    if not isinstance(volume_root, str) or not volume_root.strip("/"):
        raise CampaignError("reference plan volume_root is required")
    source = _source_attestation(document)
    zpa = document.get("zpa_report")
    if not isinstance(zpa, dict) or zpa.get("integrity") != "PASS":
        raise CampaignError("reference plan must retain a PASS ZPA report")
    source_shape = _int_triplet(
        zpa.get("level0_shape_zyx"), "reference plan level0_shape_zyx"
    )
    protocol = document.get("protocol")
    if not isinstance(protocol, dict):
        raise CampaignError("reference plan protocol is required")
    halo = protocol.get("halo_voxels")
    if type(halo) is not int or halo < 1:
        raise CampaignError("reference plan halo_voxels must be >= 1")
    offsets = protocol.get("offsets_voxels")
    if (
        not isinstance(offsets, list)
        or not offsets
        or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(float(v))
            or float(v) == 0.0
            for v in offsets
        )
    ):
        raise CampaignError("reference plan offsets_voxels are invalid")
    groups = document.get("groups")
    if not isinstance(groups, list) or not groups:
        raise CampaignError("reference plan groups must be non-empty")
    normalized_groups: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, row in enumerate(groups):
        if not isinstance(row, dict):
            raise CampaignError(f"reference group {index} must be an object")
        gid = row.get("id")
        if not isinstance(gid, str) or not gid or gid in ids:
            raise CampaignError("reference group ids must be unique non-empty strings")
        ids.add(gid)
        surface = _triplet(row.get("surface_global_zyx"), f"{gid}.surface_global_zyx")
        normal = _triplet(row.get("reference_normal_zyx"), f"{gid}.reference_normal_zyx")
        norm = float(np.linalg.norm(normal))
        if norm <= 0:
            raise CampaignError(f"{gid}.reference_normal_zyx must be non-zero")
        normal = normal / norm
        controls = row.get("normal_offsets")
        if not isinstance(controls, list) or not controls:
            raise CampaignError(f"{gid}.normal_offsets must be non-empty")
        normalized_controls: list[dict[str, Any]] = []
        observed_offsets: list[float] = []
        for cindex, control in enumerate(controls):
            if not isinstance(control, dict):
                raise CampaignError(f"{gid}.normal_offsets[{cindex}] must be an object")
            distance = _finite(
                control.get("distance_voxels"),
                f"{gid}.normal_offsets[{cindex}].distance_voxels",
            )
            coord = _triplet(
                control.get("global_zyx"),
                f"{gid}.normal_offsets[{cindex}].global_zyx",
            )
            observed_offsets.append(distance)
            normalized_controls.append(
                {"distance_voxels": distance, "global_zyx": coord.tolist()}
            )
        if observed_offsets != [float(v) for v in offsets]:
            raise CampaignError(f"{gid}: normal offsets differ from frozen protocol")
        wrong = row.get("wrong_wrap")
        if not isinstance(wrong, dict) or wrong.get("status") != "pending-independent-geometry":
            raise CampaignError(
                f"{gid}: reference plan wrong_wrap must remain pending-independent-geometry"
            )
        normalized_groups.append(
            {
                "id": gid,
                "surface_global_zyx": surface.tolist(),
                "reference_normal_zyx": normal.tolist(),
                "normal_offsets": normalized_controls,
            }
        )
    return {
        "file_sha256": file_sha256,
        "volume_root": volume_root.strip("/"),
        "source_attestation": source,
        "source_shape_zyx": list(source_shape),
        "zpa_report_sha256": _sha(zpa.get("sha256"), "reference plan zpa_report.sha256"),
        "halo_voxels": halo,
        "offsets_voxels": [float(v) for v in offsets],
        "groups": normalized_groups,
    }


def _validate_wrong_wrap_bundle(
    *,
    spec: Mapping[str, Any],
    spec_sha256: str,
    result: Mapping[str, Any],
    result_sha256: str,
    reference: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if spec.get("schema") != "scroliq-wrong-wrap-spec/1":
        raise CampaignError("wrong-wrap spec schema mismatch")
    if spec.get("status") != "frozen-before-geometry-read":
        raise CampaignError("wrong-wrap spec is not frozen")
    if spec.get("volume_root") != reference["volume_root"]:
        raise CampaignError("wrong-wrap spec volume_root mismatch")
    spec_ref = spec.get("reference_plan")
    if (
        not isinstance(spec_ref, dict)
        or spec_ref.get("sha256") != reference["file_sha256"]
    ):
        raise CampaignError("wrong-wrap spec reference-plan hash mismatch")
    algorithm = spec.get("algorithm")
    if (
        not isinstance(algorithm, dict)
        or algorithm.get("uses_sheetness_response") is not False
        or algorithm.get("stochastic") is not False
    ):
        raise CampaignError("wrong-wrap spec must be deterministic and sheetness-blind")

    if result.get("schema") != "scroliq-wrong-wrap-plan/1":
        raise CampaignError("wrong-wrap result schema mismatch")
    if result.get("status") not in {"complete", "partial"}:
        raise CampaignError("wrong-wrap result must be complete or partial")
    if result.get("volume_root") != reference["volume_root"]:
        raise CampaignError("wrong-wrap result volume_root mismatch")
    if result.get("sheetness_response_consulted") is not False:
        raise CampaignError("wrong-wrap result consulted sheetness response")
    result_ref = result.get("reference_plan")
    if (
        not isinstance(result_ref, dict)
        or result_ref.get("file_sha256") != reference["file_sha256"]
    ):
        raise CampaignError("wrong-wrap result reference-plan hash mismatch")
    result_spec = result.get("spec")
    if not isinstance(result_spec, dict):
        raise CampaignError("wrong-wrap result spec binding is required")
    if result_spec.get("file_sha256") != spec_sha256:
        raise CampaignError("wrong-wrap result does not bind supplied spec bytes")
    if result_spec.get("canonical_sha256") != canonical_sha256(spec):
        raise CampaignError("wrong-wrap result canonical spec hash mismatch")

    rows = result.get("groups")
    if not isinstance(rows, list):
        raise CampaignError("wrong-wrap result groups must be a list")
    expected = {row["id"] for row in reference["groups"]}
    seen: set[str] = set()
    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise CampaignError("wrong-wrap result group must be an object")
        gid = row.get("id")
        if not isinstance(gid, str) or gid not in expected or gid in seen:
            raise CampaignError(f"wrong-wrap result has invalid group id {gid!r}")
        seen.add(gid)
        status = row.get("status")
        if status == "found":
            normalized[gid] = {
                "status": "found",
                "global_zyx": _triplet(
                    row.get("global_zyx"), f"{gid}.wrong_wrap.global_zyx"
                ).tolist(),
                "signed_distance_voxels": _finite(
                    row.get("signed_distance_voxels"),
                    f"{gid}.wrong_wrap.signed_distance_voxels",
                ),
            }
        elif status == "no-independent-competing-sheet-found":
            normalized[gid] = {"status": status, "global_zyx": None}
        else:
            raise CampaignError(f"{gid}: unsupported wrong-wrap status {status!r}")
    if seen != expected:
        raise CampaignError(
            f"wrong-wrap result region set mismatch; missing={sorted(expected-seen)}"
        )

    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        raise CampaignError("wrong-wrap result metrics are required")
    if metrics.get("group_count") != len(expected):
        raise CampaignError("wrong-wrap result group_count mismatch")
    if metrics.get("prediction_chunks_missing_as_zero") != 0:
        raise CampaignError("wrong-wrap result had missing prediction chunks")
    if metrics.get("ct_chunks_missing_as_zero") != 0:
        raise CampaignError("wrong-wrap result had missing CT chunks")

    normalized["_provenance"] = {
        "spec_file_sha256": spec_sha256,
        "spec_canonical_sha256": canonical_sha256(spec),
        "result_file_sha256": result_sha256,
    }
    return normalized


def _validate_sigmas(values: Sequence[float]) -> list[float]:
    out = [float(v) for v in values]
    if not out or any(not math.isfinite(v) or v <= 0 for v in out):
        raise CampaignError("sigmas must be finite positive numbers")
    if len(set(out)) != len(out):
        raise CampaignError("sigmas must not contain duplicates")
    return out


def _campaign_rule(
    *,
    min_score_completeness: float,
    min_normal_offset_win_fraction: float,
    min_median_normal_offset_margin: float,
    min_normal_completeness: float,
    min_median_abs_cosine: float,
) -> dict[str, float]:
    return {
        "min_score_completeness": _fraction(
            min_score_completeness, "min_score_completeness"
        ),
        "min_normal_offset_win_fraction": _fraction(
            min_normal_offset_win_fraction, "min_normal_offset_win_fraction"
        ),
        "min_median_normal_offset_margin": _finite(
            min_median_normal_offset_margin, "min_median_normal_offset_margin"
        ),
        "min_normal_completeness": _fraction(
            min_normal_completeness, "min_normal_completeness"
        ),
        "min_median_abs_cosine": _fraction(
            min_median_abs_cosine, "min_median_abs_cosine"
        ),
    }


def _bbox(
    points: Sequence[np.ndarray],
    *,
    halo: int,
    source_shape: Sequence[int],
) -> tuple[list[int], list[int]]:
    stack = np.stack(points, axis=0)
    start = np.floor(stack.min(axis=0)).astype(np.int64) - halo
    stop = np.ceil(stack.max(axis=0)).astype(np.int64) + halo + 1
    shape = np.asarray(source_shape, dtype=np.int64)
    if np.any(start < 0) or np.any(stop > shape):
        raise CampaignError(
            f"expanded cutout bbox {start.tolist()}:{stop.tolist()} exceeds CT bounds"
        )
    return [int(v) for v in start], [int(v) for v in stop]


def _local(global_zyx: Sequence[float], start: Sequence[int]) -> list[float]:
    return [float(global_zyx[d] - start[d]) for d in range(3)]


def freeze_plan(
    *,
    reference_plan_path: str | Path,
    wrong_wrap_spec_path: str | Path,
    wrong_wrap_result_path: str | Path,
    code_revision: str,
    sigmas: Sequence[float],
    beta: float,
    gamma: float,
    bright_object: bool,
    scale_objectness: bool,
    normalize: bool,
    normalize_low: float,
    normalize_high: float,
    max_voxels: int,
    min_score_completeness: float,
    min_normal_offset_win_fraction: float,
    min_median_normal_offset_margin: float,
    min_normal_completeness: float,
    min_median_abs_cosine: float,
) -> dict[str, Any]:
    """Freeze all choices that can affect a dispersed sheetness experiment."""
    reference_path = Path(reference_plan_path)
    wrong_spec_path = Path(wrong_wrap_spec_path)
    wrong_result_path = Path(wrong_wrap_result_path)
    reference_doc = _load_json(reference_path, "reference plan")
    wrong_spec_doc = _load_json(wrong_spec_path, "wrong-wrap spec")
    wrong_result_doc = _load_json(wrong_result_path, "wrong-wrap result")
    reference = _validate_reference_plan(
        reference_doc, file_sha256=sha256_file(reference_path)
    )
    wrong = _validate_wrong_wrap_bundle(
        spec=wrong_spec_doc,
        spec_sha256=sha256_file(wrong_spec_path),
        result=wrong_result_doc,
        result_sha256=sha256_file(wrong_result_path),
        reference=reference,
    )

    revision = _git_sha(code_revision, "code_revision")
    sigma_list = _validate_sigmas(sigmas)
    beta_value = _finite(beta, "beta")
    gamma_value = _finite(gamma, "gamma")
    if beta_value <= 0 or gamma_value <= 0:
        raise CampaignError("beta and gamma must be > 0")
    low = _finite(normalize_low, "normalize_low")
    high = _finite(normalize_high, "normalize_high")
    if normalize and not (0 <= low < high <= 100):
        raise CampaignError("normalization percentiles must satisfy 0 <= low < high <= 100")
    if type(max_voxels) is not int or max_voxels < 1:
        raise CampaignError("max_voxels must be an integer >= 1")
    if not normalize and (low != 0.0 or high != 100.0):
        raise CampaignError(
            "when normalization is disabled, freeze normalize_low=0 and normalize_high=100"
        )

    # Gaussian smoothing is truncated at 3 sigma and Hessian gradients require
    # two additional local samples. Enforce enough frozen halo so control
    # measurements do not depend on reflect-padding at the cutout boundary.
    required_halo = int(math.ceil(3.0 * max(sigma_list))) + 2
    halo = int(reference["halo_voxels"])
    if halo < required_halo:
        raise CampaignError(
            f"reference halo {halo} is too small for max sigma {max(sigma_list)}; "
            f"need at least {required_halo}"
        )

    rule = _campaign_rule(
        min_score_completeness=min_score_completeness,
        min_normal_offset_win_fraction=min_normal_offset_win_fraction,
        min_median_normal_offset_margin=min_median_normal_offset_margin,
        min_normal_completeness=min_normal_completeness,
        min_median_abs_cosine=min_median_abs_cosine,
    )

    groups: list[dict[str, Any]] = []
    blocked = 0
    for ref in reference["groups"]:
        gid = ref["id"]
        wrong_row = wrong[gid]
        points = [np.asarray(ref["surface_global_zyx"], dtype=np.float64)]
        points.extend(
            np.asarray(row["global_zyx"], dtype=np.float64)
            for row in ref["normal_offsets"]
        )
        if wrong_row["status"] == "found":
            points.append(np.asarray(wrong_row["global_zyx"], dtype=np.float64))
        start, stop = _bbox(
            points, halo=halo, source_shape=reference["source_shape_zyx"]
        )
        shape = [stop[d] - start[d] for d in range(3)]
        voxels = int(np.prod(np.asarray(shape, dtype=np.int64)))
        if voxels > max_voxels:
            raise CampaignError(
                f"{gid}: expanded cutout has {voxels} voxels, above frozen "
                f"max_voxels {max_voxels}"
            )

        controls = [
            {
                "id": f"{gid}-offset-{index+1:02d}",
                "role": "normal-offset",
                "distance_voxels": row["distance_voxels"],
                "global_zyx": row["global_zyx"],
                "local_zyx": _local(row["global_zyx"], start),
            }
            for index, row in enumerate(ref["normal_offsets"])
        ]
        status = "ready"
        if wrong_row["status"] == "found":
            controls.append(
                {
                    "id": f"{gid}-wrong-wrap",
                    "role": "wrong-wrap",
                    "signed_distance_voxels": wrong_row["signed_distance_voxels"],
                    "global_zyx": wrong_row["global_zyx"],
                    "local_zyx": _local(wrong_row["global_zyx"], start),
                }
            )
        else:
            blocked += 1
            status = "blocked-missing-wrong-wrap"

        groups.append(
            {
                "id": gid,
                "status": status,
                "bbox_zyx_half_open": {"start": start, "stop": stop},
                "shape_zyx": shape,
                "voxels": voxels,
                "surface": {
                    "global_zyx": ref["surface_global_zyx"],
                    "local_zyx": _local(ref["surface_global_zyx"], start),
                    "reference_normal_zyx": ref["reference_normal_zyx"],
                },
                "controls": controls,
            }
        )

    module_dir = Path(__file__).resolve().parent
    return {
        "schema": SCHEMA,
        "status": "frozen-before-sheetness",
        "volume_root": reference["volume_root"],
        "coordinate_space": COORDINATE_SPACE,
        "source_attestation": reference["source_attestation"],
        "zpa_report_sha256": reference["zpa_report_sha256"],
        "upstream": {
            "reference_plan_sha256": reference["file_sha256"],
            "wrong_wrap_spec_sha256": wrong["_provenance"]["spec_file_sha256"],
            "wrong_wrap_spec_canonical_sha256": wrong["_provenance"][
                "spec_canonical_sha256"
            ],
            "wrong_wrap_result_sha256": wrong["_provenance"]["result_file_sha256"],
        },
        "engine": {
            "method": sheetness.METHOD,
            "parameters": {
                "sigmas": sigma_list,
                "beta": beta_value,
                "gamma": gamma_value,
                "bright_object": bool(bright_object),
                "scale_objectness": bool(scale_objectness),
            },
            "normalization": {
                "enabled": bool(normalize),
                "lower_percentile": low if normalize else None,
                "upper_percentile": high if normalize else None,
            },
            "write_normal": True,
            "max_voxels": max_voxels,
            "stochastic": False,
            "seed": None,
            "code_revision": revision,
            "sheetness_py_sha256": sha256_file(module_dir / "sheetness.py"),
            "sheetness_benchmark_py_sha256": sha256_file(
                module_dir / "sheetness_benchmark.py"
            ),
            "sheetness_campaign_py_sha256": sha256_file(Path(__file__).resolve()),
        },
        "campaign_decision_rule": rule,
        "per_group_v3_rule": dict(MEASUREMENT_ONLY_RULE),
        "geometry": {
            "halo_voxels": halo,
            "minimum_required_halo_voxels": required_halo,
            "normal_offsets_voxels": reference["offsets_voxels"],
            "source_shape_zyx": reference["source_shape_zyx"],
        },
        "groups": groups,
        "summary": {
            "group_count": len(groups),
            "ready_group_count": len(groups) - blocked,
            "blocked_group_count": blocked,
            "total_cutout_voxels": int(sum(row["voxels"] for row in groups)),
            "max_cutout_voxels": int(max(row["voxels"] for row in groups)),
        },
        "wrong_wrap_interpretation": (
            "mandatory descriptive control only: a neighboring papyrus winding "
            "is itself sheet-like and therefore is not a pass/fail negative"
        ),
        "claim_boundary": (
            "This plan freezes geometry, bounded CT boxes, engine parameters/code "
            "bytes and the campaign-level decision rule before any sheetness "
            "response is computed. It does not establish sheet identity, topology, "
            "ink or readability."
        ),
    }


def _manifest_binding(
    manifest: Mapping[str, Any],
    *,
    expected_volume: str,
    expected_bbox: Mapping[str, Any],
    expected_attestation: Mapping[str, Any],
) -> tuple[str, list[int]]:
    if manifest.get("schema") != "scroliq-ct-cutout/1":
        raise CampaignError("cutout manifest schema mismatch")
    if manifest.get("status") != "measured":
        raise CampaignError("cutout manifest must be measured")
    if manifest.get("volume_root") != expected_volume:
        raise CampaignError("cutout manifest volume_root mismatch")
    if manifest.get("level") != 0 or manifest.get("coordinate_space") != "level0-voxel-index":
        raise CampaignError("cutout manifest coordinate contract mismatch")
    att = manifest.get("source_attestation")
    if not isinstance(att, dict):
        raise CampaignError("cutout manifest source_attestation is required")
    for key in ("algorithm", "state", "metadata_semantics_sha256"):
        if att.get(key) != expected_attestation.get(key):
            raise CampaignError(f"cutout manifest source_attestation.{key} mismatch")
    if att.get("axes") != ["z", "y", "x"]:
        raise CampaignError("cutout manifest axes must be ZYX")
    bbox = manifest.get("bbox_zyx_half_open")
    if bbox != expected_bbox:
        raise CampaignError("cutout manifest bbox differs from frozen campaign")
    chunks = manifest.get("source_chunks")
    if not isinstance(chunks, dict) or chunks.get("missing_count") != 0:
        raise CampaignError("cutout manifest must prove zero missing source chunks")
    cutout = manifest.get("cutout")
    if not isinstance(cutout, dict):
        raise CampaignError("cutout manifest cutout block is required")
    cutout_sha = _sha(cutout.get("sha256"), "cutout.sha256")
    shape = _int_triplet(cutout.get("shape_zyx"), "cutout.shape_zyx")
    if cutout.get("dtype") != "uint8":
        raise CampaignError("cutout dtype must be uint8")
    return cutout_sha, list(shape)


def _engine_matches(report: Mapping[str, Any], engine: Mapping[str, Any]) -> None:
    if report.get("schema_version") != 1 or report.get("kind") != "sheetness":
        raise CampaignError("sheetness report schema mismatch")
    if report.get("status") != "measured":
        raise CampaignError("sheetness report status must be measured")
    if report.get("method") != engine["method"]:
        raise CampaignError("sheetness report method differs from frozen engine")
    params = report.get("parameters")
    if not isinstance(params, dict):
        raise CampaignError("sheetness report parameters are required")
    expected = engine["parameters"]
    for key in ("sigmas", "beta", "gamma", "bright_object", "scale_objectness"):
        if params.get(key) != expected.get(key):
            raise CampaignError(f"sheetness report parameter {key} differs from freeze")
    normalization = report.get("normalization")
    if not isinstance(normalization, dict):
        raise CampaignError("sheetness report normalization is required")
    frozen_norm = engine["normalization"]
    if normalization.get("enabled") != frozen_norm["enabled"]:
        raise CampaignError("sheetness normalization enabled state differs from freeze")
    if frozen_norm["enabled"]:
        if normalization.get("lower_percentile") != frozen_norm["lower_percentile"]:
            raise CampaignError("sheetness lower normalization percentile changed")
        if normalization.get("upper_percentile") != frozen_norm["upper_percentile"]:
            raise CampaignError("sheetness upper normalization percentile changed")
    if not isinstance(report.get("normal"), dict):
        raise CampaignError("sheetness report must include normal output")
    _sha(report["normal"].get("output_sha256"), "sheetness normal output_sha256")
    response = report.get("response")
    if not isinstance(response, dict):
        raise CampaignError("sheetness report response metadata is required")
    _sha(response.get("output_sha256"), "sheetness response output_sha256")


def seal_group(
    *,
    plan_path: str | Path,
    group_id: str,
    cutout_manifest_path: str | Path,
    sheetness_report_path: str | Path,
) -> dict[str, Any]:
    """Materialize one v3 spec after deterministic inference without moving rules."""
    plan_path = Path(plan_path)
    manifest_path = Path(cutout_manifest_path)
    report_path = Path(sheetness_report_path)
    plan = _load_json(plan_path, "campaign plan")
    if plan.get("schema") != SCHEMA or plan.get("status") != "frozen-before-sheetness":
        raise CampaignError("campaign plan is not a frozen v1 plan")
    groups = plan.get("groups")
    if not isinstance(groups, list):
        raise CampaignError("campaign plan groups are required")
    matches = [row for row in groups if isinstance(row, dict) and row.get("id") == group_id]
    if len(matches) != 1:
        raise CampaignError(f"campaign plan has no unique group {group_id!r}")
    group = matches[0]
    if group.get("status") != "ready":
        raise CampaignError(f"group {group_id} is not ready for sheetness")

    manifest = _load_json(manifest_path, "cutout manifest")
    cutout_sha, shape = _manifest_binding(
        manifest,
        expected_volume=plan["volume_root"],
        expected_bbox=group["bbox_zyx_half_open"],
        expected_attestation=plan["source_attestation"],
    )
    if shape != group["shape_zyx"]:
        raise CampaignError("cutout shape differs from frozen group shape")

    report = _load_json(report_path, "sheetness report")
    _engine_matches(report, plan["engine"])
    input_meta = report.get("input")
    if not isinstance(input_meta, dict) or input_meta.get("sha256") != cutout_sha:
        raise CampaignError("sheetness report input does not bind frozen cutout")
    if input_meta.get("shape_zyx") != shape:
        raise CampaignError("sheetness report input shape differs from cutout")

    controls = []
    for control in group["controls"]:
        if control["role"] == "normal-offset":
            controls.append(
                {
                    "id": control["id"],
                    "role": "normal-offset",
                    "zyx": control["local_zyx"],
                }
            )
        elif control["role"] == "wrong-wrap":
            controls.append(
                {
                    "id": control["id"],
                    "role": "wrong-wrap",
                    "zyx": control["local_zyx"],
                }
            )
    if not any(row["role"] == "wrong-wrap" for row in controls):
        raise CampaignError(f"group {group_id} has no frozen wrong-wrap control")

    return {
        "schema_version": 3,
        "campaign_schema": SCHEMA,
        "campaign_plan_sha256": sha256_file(plan_path),
        "campaign_plan_canonical_sha256": canonical_sha256(plan),
        "campaign_group_id": group_id,
        "volume_root": plan["volume_root"],
        "source_attestation": {
            "algorithm": plan["source_attestation"]["algorithm"],
            "state": plan["source_attestation"]["state"],
            "metadata_semantics_sha256": plan["source_attestation"][
                "metadata_semantics_sha256"
            ],
        },
        "input_sha256": cutout_sha,
        "cutout_manifest_sha256": sha256_file(manifest_path),
        "sheetness_report_sha256": sha256_file(report_path),
        "decision_rule": dict(plan["per_group_v3_rule"]),
        "campaign_decision_rule": dict(plan["campaign_decision_rule"]),
        "frozen_engine": dict(plan["engine"]),
        "groups": [
            {
                "id": group_id,
                "surface": {
                    "zyx": group["surface"]["local_zyx"],
                    "reference_normal_zyx": group["surface"][
                        "reference_normal_zyx"
                    ],
                },
                "controls": controls,
            }
        ],
        "claim_boundary": (
            "This v3 spec materializes one already-frozen campaign group against "
            "the exact deterministic sheetness report/cutout bytes. Its local "
            "decision rule checks measurement completeness only; the scientific "
            "pass/fail rule is applied across all frozen groups by "
            "scroliq-sheetness-campaign aggregate."
        ),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(np.median(np.asarray(values, dtype=np.float64)))


def aggregate(
    *,
    plan_path: str | Path,
    specs_dir: str | Path,
    results_dir: str | Path,
) -> dict[str, Any]:
    """Aggregate all frozen per-group v3 results with failures in denominator."""
    plan_path = Path(plan_path)
    specs_dir = Path(specs_dir)
    results_dir = Path(results_dir)
    plan = _load_json(plan_path, "campaign plan")
    if plan.get("schema") != SCHEMA or plan.get("status") != "frozen-before-sheetness":
        raise CampaignError("campaign plan is not frozen")
    plan_sha = sha256_file(plan_path)
    expected_groups = [
        row for row in plan.get("groups", []) if isinstance(row, dict)
    ]
    if not expected_groups:
        raise CampaignError("campaign plan has no groups")

    total = len(expected_groups)
    score_complete = 0
    normal_complete = 0
    normal_wins = 0
    wrong_wins = 0
    margins: list[float] = []
    wrong_margins: list[float] = []
    cosines: list[float] = []
    failures: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []

    for group in expected_groups:
        gid = group["id"]
        if group.get("status") != "ready":
            failures.append({"id": gid, "reason": str(group.get("status"))})
            rows.append({"id": gid, "status": "failed", "reason": str(group.get("status"))})
            continue
        spec_path = specs_dir / f"{gid}.json"
        result_path = results_dir / f"{gid}.json"
        if not spec_path.is_file() or not result_path.is_file():
            missing = []
            if not spec_path.is_file():
                missing.append("spec")
            if not result_path.is_file():
                missing.append("result")
            reason = "missing " + " and ".join(missing)
            failures.append({"id": gid, "reason": reason})
            rows.append({"id": gid, "status": "failed", "reason": reason})
            continue
        try:
            spec = _load_json(spec_path, f"{gid} v3 spec")
            result = _load_json(result_path, f"{gid} v3 result")
            if spec.get("campaign_plan_sha256") != plan_sha:
                raise CampaignError("v3 spec campaign-plan hash mismatch")
            if spec.get("campaign_group_id") != gid:
                raise CampaignError("v3 spec group id mismatch")
            if result.get("schema") != BENCHMARK_SCHEMA:
                raise CampaignError("v3 result schema mismatch")
            if result.get("volume_root") != plan["volume_root"]:
                raise CampaignError("v3 result volume_root mismatch")
            result_spec = result.get("spec")
            if (
                not isinstance(result_spec, dict)
                or result_spec.get("file_sha256") != sha256_file(spec_path)
            ):
                raise CampaignError("v3 result does not bind supplied spec")
            metrics = result.get("metrics")
            if not isinstance(metrics, dict) or metrics.get("group_count") != 1:
                raise CampaignError("v3 result must contain exactly one group")
            result_groups = result.get("groups")
            if (
                not isinstance(result_groups, list)
                or len(result_groups) != 1
                or result_groups[0].get("id") != gid
            ):
                raise CampaignError("v3 result group mismatch")
            row = result_groups[0]

            complete = bool(row.get("score_complete"))
            cosine = row.get("surface", {}).get("predicted_normal_abs_cosine")
            normal_ok = isinstance(cosine, (int, float)) and math.isfinite(float(cosine))
            if complete:
                score_complete += 1
                margin = row.get("surface_minus_best_normal_offset")
                wrong_margin = row.get("surface_minus_best_wrong_wrap")
                if not isinstance(margin, (int, float)) or not math.isfinite(float(margin)):
                    raise CampaignError("complete group has invalid normal-offset margin")
                if not isinstance(wrong_margin, (int, float)) or not math.isfinite(float(wrong_margin)):
                    raise CampaignError("complete group has invalid wrong-wrap margin")
                margins.append(float(margin))
                wrong_margins.append(float(wrong_margin))
                if row.get("surface_beats_all_normal_offsets") is True:
                    normal_wins += 1
                if row.get("surface_beats_all_wrong_wraps") is True:
                    wrong_wins += 1
            if normal_ok:
                normal_complete += 1
                cosines.append(float(cosine))

            rows.append(
                {
                    "id": gid,
                    "status": "measured",
                    "score_complete": complete,
                    "surface_beats_all_normal_offsets": bool(
                        row.get("surface_beats_all_normal_offsets")
                    ),
                    "surface_minus_best_normal_offset": row.get(
                        "surface_minus_best_normal_offset"
                    ),
                    "surface_beats_all_wrong_wraps": bool(
                        row.get("surface_beats_all_wrong_wraps")
                    ),
                    "surface_minus_best_wrong_wrap": row.get(
                        "surface_minus_best_wrong_wrap"
                    ),
                    "predicted_normal_abs_cosine": cosine,
                    "spec_sha256": sha256_file(spec_path),
                    "result_sha256": sha256_file(result_path),
                }
            )
        except (OSError, CampaignError, ValueError, json.JSONDecodeError) as exc:
            failures.append({"id": gid, "reason": str(exc)})
            rows.append({"id": gid, "status": "failed", "reason": str(exc)})

    score_completeness = score_complete / total
    normal_completeness = normal_complete / total
    win_fraction = normal_wins / total
    wrong_win_fraction = wrong_wins / total
    median_margin = _median(margins)
    median_wrong_margin = _median(wrong_margins)
    median_cosine = _median(cosines)

    metrics = {
        "group_count": total,
        "score_complete_count": score_complete,
        "score_completeness": score_completeness,
        "normal_offset_win_count": normal_wins,
        "normal_offset_win_fraction": win_fraction,
        "median_surface_minus_best_normal_offset": median_margin,
        "normal_complete_count": normal_complete,
        "normal_completeness": normal_completeness,
        "median_abs_cosine": median_cosine,
        "wrong_wrap_win_count_descriptive": wrong_wins,
        "wrong_wrap_win_fraction_descriptive": wrong_win_fraction,
        "median_surface_minus_best_wrong_wrap_descriptive": median_wrong_margin,
        "failed_group_count": len(failures),
    }
    rule = plan["campaign_decision_rule"]
    checks = {
        "score_completeness": score_completeness >= rule["min_score_completeness"],
        "normal_offset_win_fraction": (
            win_fraction >= rule["min_normal_offset_win_fraction"]
        ),
        "median_normal_offset_margin": (
            median_margin is not None
            and median_margin >= rule["min_median_normal_offset_margin"]
        ),
        "normal_completeness": (
            normal_completeness >= rule["min_normal_completeness"]
        ),
        "median_abs_cosine": (
            median_cosine is not None
            and median_cosine >= rule["min_median_abs_cosine"]
        ),
        "no_invalid_or_missing_groups": len(failures) == 0,
    }
    status = "pass" if all(checks.values()) else "fail"
    return {
        "schema": AGGREGATE_SCHEMA,
        "status": status,
        "volume_root": plan["volume_root"],
        "campaign_plan": {
            "file_sha256": plan_sha,
            "canonical_sha256": canonical_sha256(plan),
        },
        "engine": plan["engine"],
        "decision_rule": rule,
        "decision_checks": checks,
        "metrics": metrics,
        "failures": failures,
        "groups": rows,
        "wrong_wrap_interpretation": plan["wrong_wrap_interpretation"],
        "claim_boundary": (
            "This aggregate tests whether the frozen Hessian sheetness signal "
            "localizes the known reference surface relative to deliberate normal "
            "offsets and aligns with its local normal. Wrong-wrap comparison is "
            "descriptive only. A pass does not establish global sheet identity, "
            "topology, ink or readability."
        ),
    }


def _parse_sigmas(value: str) -> list[float]:
    try:
        return _validate_sigmas(
            [float(part.strip()) for part in value.split(",") if part.strip()]
        )
    except (ValueError, CampaignError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _write_create_only(path: str | Path, value: Mapping[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with out.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
    except OSError as exc:
        raise CampaignError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    freeze = sub.add_parser(
        "freeze",
        help="freeze dispersed cutouts, exact engine config and campaign decision rule",
    )
    freeze.add_argument("--reference-plan", required=True)
    freeze.add_argument("--wrong-wrap-spec", required=True)
    freeze.add_argument("--wrong-wrap-result", required=True)
    freeze.add_argument("--code-revision", required=True)
    freeze.add_argument("--sigmas", type=_parse_sigmas, required=True)
    freeze.add_argument("--beta", type=float, required=True)
    freeze.add_argument("--gamma", type=float, required=True)
    polarity = freeze.add_mutually_exclusive_group(required=True)
    polarity.add_argument("--bright-object", dest="bright_object", action="store_true")
    polarity.add_argument("--dark-object", dest="bright_object", action="store_false")
    scaling = freeze.add_mutually_exclusive_group(required=True)
    scaling.add_argument(
        "--scale-objectness", dest="scale_objectness", action="store_true"
    )
    scaling.add_argument(
        "--no-scale-objectness", dest="scale_objectness", action="store_false"
    )
    norm = freeze.add_mutually_exclusive_group(required=True)
    norm.add_argument("--normalize", dest="normalize", action="store_true")
    norm.add_argument("--no-normalize", dest="normalize", action="store_false")
    freeze.add_argument("--normalize-low", type=float, required=True)
    freeze.add_argument("--normalize-high", type=float, required=True)
    freeze.add_argument("--max-voxels", type=int, required=True)
    freeze.add_argument("--min-score-completeness", type=float, required=True)
    freeze.add_argument("--min-normal-offset-win-fraction", type=float, required=True)
    freeze.add_argument("--min-median-normal-offset-margin", type=float, required=True)
    freeze.add_argument("--min-normal-completeness", type=float, required=True)
    freeze.add_argument("--min-median-abs-cosine", type=float, required=True)
    freeze.add_argument("--out", required=True)

    seal = sub.add_parser(
        "seal-group",
        help="bind one deterministic cutout/report into a measurement-only v3 spec",
    )
    seal.add_argument("--plan", required=True)
    seal.add_argument("--group-id", required=True)
    seal.add_argument("--cutout-manifest", required=True)
    seal.add_argument("--sheetness-report", required=True)
    seal.add_argument("--out", required=True)

    agg = sub.add_parser(
        "aggregate",
        help="aggregate all per-group v3 results under the frozen campaign rule",
    )
    agg.add_argument("--plan", required=True)
    agg.add_argument("--specs-dir", required=True)
    agg.add_argument("--results-dir", required=True)
    agg.add_argument("--out", required=True)
    agg.add_argument("--require-pass", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "freeze":
            result = freeze_plan(
                reference_plan_path=args.reference_plan,
                wrong_wrap_spec_path=args.wrong_wrap_spec,
                wrong_wrap_result_path=args.wrong_wrap_result,
                code_revision=args.code_revision,
                sigmas=args.sigmas,
                beta=args.beta,
                gamma=args.gamma,
                bright_object=args.bright_object,
                scale_objectness=args.scale_objectness,
                normalize=args.normalize,
                normalize_low=args.normalize_low,
                normalize_high=args.normalize_high,
                max_voxels=args.max_voxels,
                min_score_completeness=args.min_score_completeness,
                min_normal_offset_win_fraction=args.min_normal_offset_win_fraction,
                min_median_normal_offset_margin=args.min_median_normal_offset_margin,
                min_normal_completeness=args.min_normal_completeness,
                min_median_abs_cosine=args.min_median_abs_cosine,
            )
        elif args.command == "seal-group":
            result = seal_group(
                plan_path=args.plan,
                group_id=args.group_id,
                cutout_manifest_path=args.cutout_manifest,
                sheetness_report_path=args.sheetness_report,
            )
        else:
            result = aggregate(
                plan_path=args.plan,
                specs_dir=args.specs_dir,
                results_dir=args.results_dir,
            )
        _write_create_only(args.out, result)
    except (CampaignError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "invalid", "error": str(exc)}))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    if args.command == "aggregate" and args.require_pass and result["status"] != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
