"""Freeze and run geometry-only competing-sheet controls for sheetness benchmarks.

The planner never reads a sheetness response. It traces the frozen TIFXYZ
reference normal through an independently produced surface-prediction volume,
requires masked-CT support, and selects the nearest separated prediction run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
import requests

from .support import SupportError, ZarrV2Level

SPEC_SCHEMA = "scroliq-wrong-wrap-spec/1"
RESULT_SCHEMA = "scroliq-wrong-wrap-plan/1"
METHOD = "normal-ray-supported-surface-v1"


class WrongWrapError(RuntimeError):
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


def _lower_hex_sha(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise WrongWrapError(f"{name} must be lowercase 64-hex sha256")
    return value


def _numeric_triplet(value: Any, name: str) -> np.ndarray:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(
            isinstance(v, bool) or not isinstance(v, (int, float))
            for v in value
        )
    ):
        raise WrongWrapError(f"{name} must contain three numeric ZYX values")
    out = np.asarray(value, dtype=np.float64)
    if not np.isfinite(out).all():
        raise WrongWrapError(f"{name} must be finite")
    return out


def _int_triplet(value: Any, name: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(type(v) is not int for v in value)
    ):
        raise WrongWrapError(f"{name} must contain three integer ZYX values")
    return int(value[0]), int(value[1]), int(value[2])


def _unit(value: Any, name: str) -> np.ndarray:
    out = _numeric_triplet(value, name)
    norm = float(np.linalg.norm(out))
    if norm <= 0:
        raise WrongWrapError(f"{name} must be non-zero")
    return out / norm


def _load_reference_plan(path: str | Path) -> tuple[dict[str, Any], str]:
    path = Path(path)
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WrongWrapError(f"cannot read reference plan: {exc}") from exc
    if not isinstance(plan, dict):
        raise WrongWrapError("reference plan must contain a JSON object")
    if plan.get("schema") != "scroliq-sheetness-plan/1":
        raise WrongWrapError("reference plan must be scroliq-sheetness-plan/1")
    if plan.get("status") != "planned":
        raise WrongWrapError("reference plan status must be planned")

    volume_root = plan.get("volume_root")
    if not isinstance(volume_root, str) or not volume_root.strip("/"):
        raise WrongWrapError("reference plan volume_root is required")

    source = plan.get("source_attestation")
    if not isinstance(source, dict):
        raise WrongWrapError("reference plan source_attestation is required")
    if source.get("algorithm") != "zpa-metadata-semantics-v1":
        raise WrongWrapError("reference plan source-attestation algorithm mismatch")
    if source.get("state") != "PRESENT":
        raise WrongWrapError("reference plan source-attestation state must be PRESENT")
    if source.get("axes") != ["z", "y", "x"]:
        raise WrongWrapError("reference plan source axes must be exactly ZYX")
    _lower_hex_sha(
        source.get("metadata_semantics_sha256"),
        "reference plan metadata_semantics_sha256",
    )

    zpa = plan.get("zpa_report")
    if not isinstance(zpa, dict):
        raise WrongWrapError("reference plan zpa_report is required")
    _int_triplet(zpa.get("level0_shape_zyx"), "reference plan level0 shape")

    protocol = plan.get("protocol")
    if not isinstance(protocol, dict):
        raise WrongWrapError("reference plan protocol is required")
    offsets = protocol.get("offsets_voxels")
    if (
        not isinstance(offsets, list)
        or not offsets
        or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(float(v))
            for v in offsets
        )
    ):
        raise WrongWrapError("reference plan offsets_voxels are invalid")

    groups = plan.get("groups")
    if not isinstance(groups, list) or not groups:
        raise WrongWrapError("reference plan groups must be non-empty")
    ids: set[str] = set()
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise WrongWrapError(f"reference groups[{index}] must be an object")
        gid = group.get("id")
        if not isinstance(gid, str) or not gid or gid in ids:
            raise WrongWrapError("reference group ids must be unique non-empty strings")
        ids.add(gid)
        _numeric_triplet(
            group.get("surface_global_zyx"),
            f"reference groups[{index}].surface_global_zyx",
        )
        _unit(
            group.get("reference_normal_zyx"),
            f"reference groups[{index}].reference_normal_zyx",
        )
        wrong = group.get("wrong_wrap")
        if (
            not isinstance(wrong, dict)
            or wrong.get("status") != "pending-independent-geometry"
            or wrong.get("global_zyx") is not None
        ):
            raise WrongWrapError(
                "reference plan must still have all wrong-wrap controls pending"
            )
    return plan, sha256_file(path)


def _exact_source_urls(
    *,
    volume_root: str,
    prediction_url: str,
    ct_url: str,
    model_id: str,
) -> tuple[str, str]:
    volume_root = volume_root.strip("/")
    prediction_url = prediction_url.rstrip("/")
    ct_url = ct_url.rstrip("/")
    if not prediction_url.startswith(("https://", "http://")):
        raise WrongWrapError("prediction_url must be public http(s)")
    if not ct_url.startswith(("https://", "http://")):
        raise WrongWrapError("ct_url must be public http(s)")
    if not ct_url.endswith("/" + volume_root):
        raise WrongWrapError("ct_url must end with the exact reference volume_root")

    parts = volume_root.split("/")
    if len(parts) < 3 or parts[-2] != "volumes":
        raise WrongWrapError("reference volume_root has unexpected structure")
    scroll = parts[-3]
    ct_name = parts[-1]
    volume_id = ct_name.split("-", 1)[0]
    if not volume_id:
        raise WrongWrapError("exact reference volume id is empty")
    if f"/{scroll}/representations/predictions/surfaces/" not in prediction_url:
        raise WrongWrapError("prediction_url does not name the reference scroll")
    if not isinstance(model_id, str) or not model_id:
        raise WrongWrapError("model_id must be a non-empty string")
    expected_name = (
        f"{volume_id}-surface-{model_id}-surface-m7-L0-th0.2.zarr"
    )
    if prediction_url.rsplit("/", 1)[-1] != expected_name:
        raise WrongWrapError(
            "prediction_url does not exactly name the frozen reference-volume "
            "m7 level-0 threshold-0.2 artifact"
        )
    return prediction_url, ct_url


def freeze_spec(
    *,
    reference_plan_path: str | Path,
    prediction_url: str,
    ct_url: str,
    model_id: str,
    prediction_binding_url: str,
    min_distance_voxels: int = 12,
    max_distance_voxels: int = 64,
    min_gap_voxels: int = 3,
    min_run_voxels: int = 2,
    threshold: int = 127,
) -> dict[str, Any]:
    plan, plan_sha = _load_reference_plan(reference_plan_path)
    volume_root = str(plan["volume_root"]).strip("/")
    prediction_url, ct_url = _exact_source_urls(
        volume_root=volume_root,
        prediction_url=prediction_url,
        ct_url=ct_url,
        model_id=model_id,
    )
    if not isinstance(prediction_binding_url, str) or not prediction_binding_url.startswith(
        ("https://", "http://")
    ):
        raise WrongWrapError("prediction_binding_url must be public http(s)")

    values = (
        ("min_distance_voxels", min_distance_voxels, 1),
        ("max_distance_voxels", max_distance_voxels, 1),
        ("min_gap_voxels", min_gap_voxels, 1),
        ("min_run_voxels", min_run_voxels, 1),
    )
    for name, value, lower in values:
        if type(value) is not int or value < lower:
            raise WrongWrapError(f"{name} must be an integer >= {lower}")
    if max_distance_voxels < min_distance_voxels + min_run_voxels - 1:
        raise WrongWrapError("max_distance_voxels is too small for the frozen run")
    if type(threshold) is not int or not 0 <= threshold <= 254:
        raise WrongWrapError("threshold must be an integer from 0 through 254")

    max_offset = max(abs(float(v)) for v in plan["protocol"]["offsets_voxels"])
    if min_distance_voxels <= max_offset:
        raise WrongWrapError(
            "min_distance_voxels must lie beyond every frozen normal-offset control"
        )
    if min_distance_voxels <= min_gap_voxels:
        raise WrongWrapError("min_distance_voxels must exceed min_gap_voxels")

    source = plan["source_attestation"]
    shape = _int_triplet(
        plan["zpa_report"]["level0_shape_zyx"], "reference plan level0 shape"
    )
    return {
        "schema": SPEC_SCHEMA,
        "status": "frozen-before-geometry-read",
        "volume_root": volume_root,
        "coordinate_space": "level0-voxel-index-zyx",
        "reference_plan": {
            "path": str(reference_plan_path),
            "sha256": plan_sha,
            "group_count": len(plan["groups"]),
        },
        "source_attestation": {
            "algorithm": source["algorithm"],
            "state": source["state"],
            "metadata_semantics_sha256": source["metadata_semantics_sha256"],
            "axes": source["axes"],
            "level0_shape_zyx": list(shape),
        },
        "geometry_source": {
            "kind": "published-surface-prediction",
            "url": prediction_url,
            "binding_url": prediction_binding_url,
            "model_id": model_id,
            "level": 0,
            "published_threshold": 0.2,
            "stored_value_threshold": threshold,
            "ct_support_url": ct_url,
            "ct_support_rule": "masked CT voxel value > 0",
        },
        "algorithm": {
            "name": METHOD,
            "normal_source": "frozen TIFXYZ centered-difference normal",
            "ray_step_voxels": 1,
            "min_distance_voxels": min_distance_voxels,
            "max_distance_voxels": max_distance_voxels,
            "min_gap_voxels": min_gap_voxels,
            "min_run_voxels": min_run_voxels,
            "candidate_rule": (
                "candidate run: prediction > stored_value_threshold AND masked CT > 0; "
                "separation gap: in-bounds prediction <= stored_value_threshold"
            ),
            "selection_rule": (
                "nearest run midpoint by absolute normal distance; "
                "negative-normal direction wins exact ties"
            ),
            "uses_sheetness_response": False,
            "uses_reference_ct_intensity": "mask-support only; no intensity ranking",
            "stochastic": False,
            "seed": None,
        },
        "claim_boundary": (
            "This frozen spec nominates a geometrically separate, CT-supported "
            "published surface prediction along each reference normal. It does not "
            "assert that the prediction is correct physical sheet identity and it "
            "does not use any sheetness response. Wrong-wrap probes remain "
            "descriptive controls in the downstream benchmark."
        ),
    }


class _NearestSampler:
    """Nearest-voxel sampler with a chunk cache for one ZarrV2Level."""

    def __init__(self, level: Any):
        self.level = level
        self.shape = tuple(int(v) for v in level.shape)
        self.chunks = tuple(int(v) for v in level.chunks)
        self.cache: dict[tuple[int, int, int], np.ndarray | None] = {}
        self.missing_chunks: set[tuple[int, int, int]] = set()

    def sample(self, coords_zyx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        coords = np.asarray(coords_zyx, dtype=np.float64).reshape(-1, 3)
        if not np.isfinite(coords).all():
            raise WrongWrapError("ray coordinates must be finite")
        # Explicit half-up nearest-voxel convention; all Vesuvius coordinates
        # here are non-negative, so floor(x + 0.5) is unambiguous.
        indices = np.floor(coords + 0.5).astype(np.int64)
        shape = np.asarray(self.shape, dtype=np.int64)
        valid = ((indices >= 0) & (indices < shape)).all(axis=1)
        values = np.zeros(len(indices), dtype=np.uint8)
        for i in np.flatnonzero(valid):
            idx = indices[i]
            chunk_idx = tuple(int(idx[d] // self.chunks[d]) for d in range(3))
            if chunk_idx not in self.cache:
                chunk = self.level.chunk(chunk_idx)
                self.cache[chunk_idx] = None if chunk is None else np.asarray(chunk)
                if chunk is None:
                    self.missing_chunks.add(chunk_idx)
            chunk = self.cache[chunk_idx]
            if chunk is None:
                continue
            local = tuple(
                int(idx[d] - chunk_idx[d] * self.chunks[d]) for d in range(3)
            )
            if any(local[d] >= chunk.shape[d] for d in range(3)):
                raise WrongWrapError("decoded edge chunk does not cover sampled voxel")
            values[i] = np.uint8(chunk[local])
        return values, valid


def _first_separated_run(
    run_hits: np.ndarray,
    *,
    gap_clear: np.ndarray,
    min_distance: int,
    min_gap: int,
    min_run: int,
) -> dict[str, float | int] | None:
    run_hit = np.asarray(run_hits, dtype=bool).reshape(-1)
    clear = np.asarray(gap_clear, dtype=bool).reshape(-1)
    if clear.shape != run_hit.shape:
        raise WrongWrapError("gap-clear mask must match candidate-run mask")
    max_distance = len(run_hit)
    for start in range(min_distance, max_distance - min_run + 2):
        i = start - 1
        gap_start = i - min_gap
        # Separation is defined by the independent geometry source itself:
        # every required preceding sample must be an in-bounds prediction
        # absence. CT masking can reject a candidate run but cannot create
        # an apparent separation gap.
        if gap_start < 0 or not clear[gap_start:i].all():
            continue
        if not run_hit[i : i + min_run].all():
            continue
        end = start + min_run - 1
        while end < max_distance and run_hit[end]:
            end += 1
        center = (start + end) / 2.0
        return {
            "start_distance_voxels": start,
            "end_distance_voxels": end,
            "midpoint_distance_voxels": center,
        }
    return None


def _propose_group(
    group: dict[str, Any],
    *,
    pred_sampler: _NearestSampler,
    ct_sampler: _NearestSampler,
    threshold: int,
    min_distance: int,
    max_distance: int,
    min_gap: int,
    min_run: int,
) -> dict[str, Any]:
    gid = str(group["id"])
    surface = _numeric_triplet(group["surface_global_zyx"], f"{gid}.surface")
    normal = _unit(group["reference_normal_zyx"], f"{gid}.normal")
    distances = np.arange(1, max_distance + 1, dtype=np.float64)

    candidates: list[dict[str, Any]] = []
    directions: list[dict[str, Any]] = []
    for sign in (-1, 1):
        coords = surface[None, :] + (sign * distances)[:, None] * normal[None, :]
        pred_values, pred_valid = pred_sampler.sample(coords)
        ct_values, ct_valid = ct_sampler.sample(coords)
        prediction_present = pred_valid & (pred_values > threshold)
        gap_clear = pred_valid & (pred_values <= threshold)
        supported = prediction_present & ct_valid & (ct_values > 0)
        run = _first_separated_run(
            supported,
            gap_clear=gap_clear,
            min_distance=min_distance,
            min_gap=min_gap,
            min_run=min_run,
        )
        directions.append(
            {
                "sign": sign,
                "sample_count": int(len(distances)),
                "in_bounds_count": int((pred_valid & ct_valid).sum()),
                "supported_prediction_count": int(supported.sum()),
                "first_qualifying_run": run,
            }
        )
        if run is None:
            continue
        midpoint = float(run["midpoint_distance_voxels"])
        signed = sign * midpoint
        coord = surface + signed * normal
        snapped = np.floor(coord + 0.5).astype(np.int64)
        candidates.append(
            {
                "sign": sign,
                "signed_distance_voxels": signed,
                "absolute_distance_voxels": midpoint,
                "global_zyx": [float(v) for v in coord],
                "nearest_voxel_zyx": [int(v) for v in snapped],
                "run": run,
            }
        )

    if not candidates:
        return {
            "id": gid,
            "status": "no-independent-competing-sheet-found",
            "global_zyx": None,
            "directions": directions,
        }
    candidates.sort(
        key=lambda row: (
            float(row["absolute_distance_voxels"]),
            0 if int(row["sign"]) < 0 else 1,
        )
    )
    chosen = candidates[0]
    return {
        "id": gid,
        "status": "found",
        "global_zyx": chosen["global_zyx"],
        "signed_distance_voxels": chosen["signed_distance_voxels"],
        "nearest_voxel_zyx": chosen["nearest_voxel_zyx"],
        "prediction_run": chosen["run"],
        "selected_sign": chosen["sign"],
        "directions": directions,
    }


def _load_spec(path: str | Path) -> tuple[dict[str, Any], str]:
    path = Path(path)
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WrongWrapError(f"cannot read wrong-wrap spec: {exc}") from exc
    if not isinstance(spec, dict) or spec.get("schema") != SPEC_SCHEMA:
        raise WrongWrapError(f"wrong-wrap spec must be {SPEC_SCHEMA}")
    if spec.get("status") != "frozen-before-geometry-read":
        raise WrongWrapError("wrong-wrap spec is not frozen-before-geometry-read")
    if spec.get("coordinate_space") != "level0-voxel-index-zyx":
        raise WrongWrapError("wrong-wrap spec coordinate space mismatch")
    source = spec.get("source_attestation")
    if not isinstance(source, dict) or source.get("axes") != ["z", "y", "x"]:
        raise WrongWrapError("wrong-wrap spec source attestation is invalid")
    if source.get("algorithm") != "zpa-metadata-semantics-v1":
        raise WrongWrapError("wrong-wrap spec source-attestation algorithm mismatch")
    if source.get("state") != "PRESENT":
        raise WrongWrapError("wrong-wrap spec source-attestation state must be PRESENT")
    _int_triplet(source.get("level0_shape_zyx"), "wrong-wrap spec level0 shape")
    _lower_hex_sha(
        source.get("metadata_semantics_sha256"),
        "wrong-wrap spec metadata_semantics_sha256",
    )
    geometry = spec.get("geometry_source")
    if not isinstance(geometry, dict):
        raise WrongWrapError("wrong-wrap spec geometry_source is required")
    if geometry.get("kind") != "published-surface-prediction":
        raise WrongWrapError("wrong-wrap spec geometry-source kind mismatch")
    if geometry.get("level") != 0 or geometry.get("published_threshold") != 0.2:
        raise WrongWrapError("wrong-wrap spec must use the frozen m7 L0 th0.2 artifact")
    threshold = geometry.get("stored_value_threshold")
    if type(threshold) is not int or not 0 <= threshold <= 254:
        raise WrongWrapError("wrong-wrap spec stored threshold must be integer 0..254")

    algorithm = spec.get("algorithm")
    if not isinstance(algorithm, dict) or algorithm.get("name") != METHOD:
        raise WrongWrapError("wrong-wrap spec algorithm mismatch")
    if algorithm.get("uses_sheetness_response") is not False:
        raise WrongWrapError("wrong-wrap spec must forbid sheetness-response use")
    if algorithm.get("stochastic") is not False or algorithm.get("seed") is not None:
        raise WrongWrapError("wrong-wrap spec must remain deterministic")
    if algorithm.get("ray_step_voxels") != 1:
        raise WrongWrapError("wrong-wrap spec ray step must remain exactly one voxel")
    for name in (
        "min_distance_voxels",
        "max_distance_voxels",
        "min_gap_voxels",
        "min_run_voxels",
    ):
        value = algorithm.get(name)
        if type(value) is not int or value < 1:
            raise WrongWrapError(f"wrong-wrap spec {name} must be an integer >= 1")
    if algorithm["max_distance_voxels"] < (
        algorithm["min_distance_voxels"] + algorithm["min_run_voxels"] - 1
    ):
        raise WrongWrapError("wrong-wrap spec max distance cannot contain its frozen run")
    if algorithm["min_distance_voxels"] <= algorithm["min_gap_voxels"]:
        raise WrongWrapError("wrong-wrap spec min distance must exceed its frozen gap")
    return spec, sha256_file(path)


def run_spec(
    *,
    spec_path: str | Path,
    reference_plan_path: str | Path,
    level_factory: Callable[[str, Any], Any] = ZarrV2Level,
    session: Any | None = None,
) -> dict[str, Any]:
    spec, spec_sha = _load_spec(spec_path)
    plan, plan_sha = _load_reference_plan(reference_plan_path)
    ref = spec.get("reference_plan")
    if not isinstance(ref, dict) or ref.get("sha256") != plan_sha:
        raise WrongWrapError("reference plan sha256 does not match frozen wrong-wrap spec")
    if ref.get("group_count") != len(plan["groups"]):
        raise WrongWrapError("reference plan group count does not match frozen wrong-wrap spec")
    if spec.get("volume_root") != plan.get("volume_root"):
        raise WrongWrapError("reference plan volume_root changed after wrong-wrap freeze")

    geometry = spec["geometry_source"]
    pred_url, ct_url = _exact_source_urls(
        volume_root=str(spec["volume_root"]),
        prediction_url=str(geometry["url"]),
        ct_url=str(geometry["ct_support_url"]),
        model_id=str(geometry["model_id"]),
    )
    expected_shape = _int_triplet(
        spec["source_attestation"]["level0_shape_zyx"],
        "wrong-wrap spec level0 shape",
    )

    owned_session = session is None
    sess = requests.Session() if session is None else session
    try:
        pred_level = level_factory(f"{pred_url}/0", sess)
        ct_level = level_factory(f"{ct_url}/0", sess)
        pred_shape = tuple(int(v) for v in pred_level.shape)
        ct_shape = tuple(int(v) for v in ct_level.shape)
        if pred_shape != expected_shape:
            raise WrongWrapError(
                f"prediction shape {pred_shape} != frozen CT grid {expected_shape}"
            )
        if ct_shape != expected_shape:
            raise WrongWrapError(
                f"live CT shape {ct_shape} != frozen CT grid {expected_shape}"
            )
        pred_sampler = _NearestSampler(pred_level)
        ct_sampler = _NearestSampler(ct_level)

        algorithm = spec["algorithm"]
        rows = [
            _propose_group(
                group,
                pred_sampler=pred_sampler,
                ct_sampler=ct_sampler,
                threshold=int(geometry["stored_value_threshold"]),
                min_distance=int(algorithm["min_distance_voxels"]),
                max_distance=int(algorithm["max_distance_voxels"]),
                min_gap=int(algorithm["min_gap_voxels"]),
                min_run=int(algorithm["min_run_voxels"]),
            )
            for group in plan["groups"]
        ]
    finally:
        if owned_session and hasattr(sess, "close"):
            sess.close()

    found = sum(row["status"] == "found" for row in rows)
    total = len(rows)
    return {
        "schema": RESULT_SCHEMA,
        "status": "complete" if found == total else "partial",
        "volume_root": spec["volume_root"],
        "coordinate_space": spec["coordinate_space"],
        "spec": {
            "file_sha256": spec_sha,
            "canonical_sha256": canonical_sha256(spec),
        },
        "reference_plan": {
            "file_sha256": plan_sha,
            "group_count": total,
        },
        "geometry_source": geometry,
        "algorithm": spec["algorithm"],
        "metrics": {
            "group_count": total,
            "wrong_wrap_found_count": found,
            "wrong_wrap_missing_count": total - found,
            "wrong_wrap_completeness": found / total,
            "prediction_chunks_missing_as_zero": len(pred_sampler.missing_chunks),
            "ct_chunks_missing_as_zero": len(ct_sampler.missing_chunks),
        },
        "groups": rows,
        "sheetness_response_consulted": False,
        "next_step": (
            "If completeness is acceptable under the preregistered rule, bind these "
            "coordinates into the frozen CT cutout/benchmark specs before running "
            "scroliq-sheetness. Missing controls remain missing; do not hand-pick replacements."
        ),
        "claim_boundary": (
            "A found control is a CT-supported location proposed by an independent "
            "published surface-prediction volume along the frozen mesh normal. It is "
            "not physical ground truth for winding identity. No sheetness response "
            "was consulted."
        ),
    }


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    freeze = sub.add_parser(
        "freeze",
        help="write a create-only geometry-source spec without reading prediction voxels",
    )
    freeze.add_argument("--reference-plan", required=True)
    freeze.add_argument("--prediction-url", required=True)
    freeze.add_argument("--ct-url", required=True)
    freeze.add_argument("--model-id", required=True)
    freeze.add_argument("--prediction-binding-url", required=True)
    freeze.add_argument("--min-distance", type=_positive_int, default=12)
    freeze.add_argument("--max-distance", type=_positive_int, default=64)
    freeze.add_argument("--min-gap", type=_positive_int, default=3)
    freeze.add_argument("--min-run", type=_positive_int, default=2)
    freeze.add_argument("--threshold", type=int, default=127)
    freeze.add_argument("--out", required=True)

    run = sub.add_parser(
        "run",
        help="apply one already-frozen spec to the published geometry source",
    )
    run.add_argument("--spec", required=True)
    run.add_argument("--reference-plan", required=True)
    run.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = Path(args.out)
    if out.exists():
        print(
            json.dumps(
                {
                    "schema": SPEC_SCHEMA if args.command == "freeze" else RESULT_SCHEMA,
                    "status": "invalid",
                    "error": f"refusing to overwrite existing output: {out}",
                }
            )
        )
        return 2
    try:
        if args.command == "freeze":
            result = freeze_spec(
                reference_plan_path=args.reference_plan,
                prediction_url=args.prediction_url,
                ct_url=args.ct_url,
                model_id=args.model_id,
                prediction_binding_url=args.prediction_binding_url,
                min_distance_voxels=args.min_distance,
                max_distance_voxels=args.max_distance,
                min_gap_voxels=args.min_gap,
                min_run_voxels=args.min_run,
                threshold=args.threshold,
            )
        else:
            result = run_spec(
                spec_path=args.spec,
                reference_plan_path=args.reference_plan,
            )
    except (WrongWrapError, SupportError, requests.RequestException, OSError) as exc:
        print(
            json.dumps(
                {
                    "schema": SPEC_SCHEMA if args.command == "freeze" else RESULT_SCHEMA,
                    "status": "invalid",
                    "error": str(exc),
                }
            )
        )
        return 2

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
