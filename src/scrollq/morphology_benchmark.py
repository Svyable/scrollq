"""Run the preregistered source-only morphology benchmark.

The benchmark is intentionally simple and fail-closed:
- sampling is a deterministic interior grid chosen without labels;
- descriptors are rank-normalized within each sample;
- descriptor direction is learned only from the two training papyri;
- evaluation is leave-one-papyrus-out on the third papyrus;
- a deterministic toroidal label permutation preserves spatial label shape;
- raw profilometry NaNs are scored as an independent missingness confound.

No Grand Prize CT, OCR, candidate render, or learned classifier is consumed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import tifffile
from PIL import Image

from .morphology_control import audit_morphology_manifest

TOOL = "scroliq-morphology-benchmark"
SCHEMA_VERSION = 1
REQUIRED_COLUMNS = {
    "papyrus_id",
    "sample_id",
    "width_px",
    "height_px",
    "pixel_count",
    "raw_height_txt",
    "normalized_height_tif",
    "label_png",
}
SUPPORTED_DESCRIPTORS = {
    "local-gradient-rank",
    "curvature-rank",
    "fiber-relative-roughness",
}


class BenchmarkError(RuntimeError):
    pass


@dataclass
class SampleEvidence:
    papyrus: str
    papyrus_key: str
    sample_id: str
    shape_yx: tuple[int, int]
    stride: int
    sampled_pixels: int
    ink_pixels: int
    papyrus_pixels: int
    labels: np.ndarray
    permuted_labels: np.ndarray
    missingness: np.ndarray
    descriptors: dict[str, np.ndarray]
    hashes: dict[str, str]
    raw_data_rows: int
    permutation_shift_yx: tuple[int, int]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_json_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise BenchmarkError(f"{label} must contain a JSON object")
    return raw, value


def _canon_papyrus(value: str) -> str:
    token = re.sub(r"[^a-z0-9]", "", value.lower())
    match = re.fullmatch(r"pherc0*([0-9]+)(.*)", token)
    if match:
        return f"pherc{int(match.group(1))}{match.group(2)}"
    return token


def _read_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            names = set(reader.fieldnames or [])
            missing = sorted(REQUIRED_COLUMNS - names)
            if missing:
                raise BenchmarkError(
                    "dataset manifest missing column(s): " + ", ".join(missing)
                )
            rows = [dict(row) for row in reader]
    except OSError as exc:
        raise BenchmarkError(f"cannot read dataset manifest: {exc}") from exc
    if not rows:
        raise BenchmarkError("dataset manifest has no rows")
    return rows


def _positive_int(value: Any, label: str) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkError(f"{label} must be an integer") from exc
    if out <= 0:
        raise BenchmarkError(f"{label} must be > 0")
    return out


def _load_height(path: Path, expected: tuple[int, int]) -> np.ndarray:
    try:
        array = np.asarray(tifffile.imread(path))
    except Exception as exc:
        raise BenchmarkError(f"cannot read normalized height TIFF {path}: {exc}") from exc
    if array.ndim != 2 or array.shape != expected:
        raise BenchmarkError(
            f"normalized height shape {array.shape} != manifest {expected}: {path}"
        )
    if not np.issubdtype(array.dtype, np.number):
        raise BenchmarkError(f"normalized height TIFF must be numeric: {path}")
    if not np.isfinite(array).all():
        raise BenchmarkError(f"normalized height TIFF contains non-finite values: {path}")
    return array


def _load_label(path: Path, expected: tuple[int, int]) -> np.ndarray:
    try:
        with Image.open(path) as image:
            array = np.asarray(image)
    except Exception as exc:
        raise BenchmarkError(f"cannot read label PNG {path}: {exc}") from exc
    if array.ndim == 3:
        array = array[..., 0]
    if array.ndim != 2 or array.shape != expected:
        raise BenchmarkError(f"label shape {array.shape} != manifest {expected}: {path}")
    return np.asarray(array != 0, dtype=bool)


def _grid_indices(
    height: int,
    width: int,
    *,
    border: int,
    max_pixels: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    if border < 1:
        raise BenchmarkError("sampling border must be >= 1")
    inner_h = height - 2 * border
    inner_w = width - 2 * border
    if inner_h <= 0 or inner_w <= 0:
        raise BenchmarkError("sample is too small for the preregistered border")
    if max_pixels < 1:
        raise BenchmarkError("max_sampled_pixels_per_sample must be >= 1")
    inner = inner_h * inner_w
    stride = max(1, int(math.ceil(math.sqrt(inner / max_pixels))))
    ys = np.arange(border, height - border, stride, dtype=np.int64)
    xs = np.arange(border, width - border, stride, dtype=np.int64)
    while ys.size * xs.size > max_pixels:
        stride += 1
        ys = np.arange(border, height - border, stride, dtype=np.int64)
        xs = np.arange(border, width - border, stride, dtype=np.int64)
    if not ys.size or not xs.size:
        raise BenchmarkError("sampling grid selected no pixels")
    return ys, xs, stride


def _rank01(values: np.ndarray) -> np.ndarray:
    """Average-rank values into [0,1], tie-aware and deterministic."""
    x = np.asarray(values, dtype=np.float64).reshape(-1)
    if x.size == 0 or not np.isfinite(x).all():
        raise BenchmarkError("descriptor values must be non-empty and finite")
    if x.size == 1:
        return np.zeros(1, dtype=np.float32)

    order = np.argsort(x, kind="mergesort")
    sorted_x = x[order]
    boundaries = np.flatnonzero(sorted_x[1:] != sorted_x[:-1]) + 1
    starts = np.concatenate(([0], boundaries))
    stops = np.concatenate((boundaries, [x.size]))
    sorted_ranks = np.empty(x.size, dtype=np.float64)
    for start, stop in zip(starts, stops):
        # Zero-based average rank of the tie group.
        sorted_ranks[start:stop] = 0.5 * (start + stop - 1)
    ranks = np.empty_like(sorted_ranks)
    ranks[order] = sorted_ranks
    ranks /= float(x.size - 1)
    return ranks.astype(np.float32)


def _auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Tie-corrected ROC AUC via the Mann-Whitney rank statistic."""
    s = np.asarray(scores, dtype=np.float64).reshape(-1)
    y = np.asarray(labels, dtype=bool).reshape(-1)
    if s.shape != y.shape or not s.size:
        raise BenchmarkError("AUC scores/labels must be equal-length non-empty arrays")
    if not np.isfinite(s).all():
        raise BenchmarkError("AUC scores must be finite")
    n_pos = int(y.sum())
    n_neg = int(y.size - n_pos)
    if not n_pos or not n_neg:
        raise BenchmarkError("AUC requires both ink and papyrus pixels")

    order = np.argsort(s, kind="mergesort")
    sorted_s = s[order]
    sorted_y = y[order]
    boundaries = np.flatnonzero(sorted_s[1:] != sorted_s[:-1]) + 1
    starts = np.concatenate(([0], boundaries))
    stops = np.concatenate((boundaries, [s.size]))
    positive_rank_sum = 0.0
    for start, stop in zip(starts, stops):
        # One-based average rank.
        average_rank = 0.5 * ((start + 1) + stop)
        positive_rank_sum += average_rank * int(sorted_y[start:stop].sum())
    u = positive_rank_sum - n_pos * (n_pos + 1) / 2.0
    return float(u / (n_pos * n_neg))


def _descriptors_at_grid(
    height_map: np.ndarray,
    ys: np.ndarray,
    xs: np.ndarray,
    names: list[str],
) -> dict[str, np.ndarray]:
    # The 2-D arrays stay bounded by max_sampled_pixels_per_sample. No full
    # float copy of the source TIFF is needed.
    c = height_map[np.ix_(ys, xs)].astype(np.float32)
    left = height_map[np.ix_(ys, xs - 1)].astype(np.float32)
    right = height_map[np.ix_(ys, xs + 1)].astype(np.float32)
    up = height_map[np.ix_(ys - 1, xs)].astype(np.float32)
    down = height_map[np.ix_(ys + 1, xs)].astype(np.float32)

    out: dict[str, np.ndarray] = {}
    if "local-gradient-rank" in names:
        gx = 0.5 * (right - left)
        gy = 0.5 * (down - up)
        out["local-gradient-rank"] = _rank01(np.hypot(gx, gy).reshape(-1))

    if "curvature-rank" in names:
        laplacian = np.abs(left + right + up + down - 4.0 * c)
        out["curvature-rank"] = _rank01(laplacian.reshape(-1))

    if "fiber-relative-roughness" in names:
        # Independent local proxy: discount a ridge that is smooth along
        # either image axis and retain deviations from both directional
        # continuations. This is not a fiber-orientation estimator.
        horizontal = np.abs(c - 0.5 * (left + right))
        vertical = np.abs(c - 0.5 * (up + down))
        roughness = np.minimum(horizontal, vertical)
        out["fiber-relative-roughness"] = _rank01(roughness.reshape(-1))

    missing = sorted(set(names) - set(out))
    if missing:
        raise BenchmarkError("unsupported descriptor(s): " + ", ".join(missing))
    return out


def _permutation_shift(
    sample_id: str,
    height: int,
    width: int,
    seed: int,
) -> tuple[int, int]:
    digest = hashlib.sha256(f"{seed}:{sample_id}".encode("utf-8")).digest()

    def choose(size: int, raw: bytes) -> int:
        if size < 2:
            raise BenchmarkError("cannot permute labels for dimension < 2")
        low = max(1, size // 4)
        high = max(low + 1, (3 * size) // 4)
        return low + (int.from_bytes(raw, "big") % (high - low))

    return choose(height, digest[:8]), choose(width, digest[8:16])


def _labels_at_grid(
    label: np.ndarray,
    ys: np.ndarray,
    xs: np.ndarray,
    *,
    shift_yx: tuple[int, int] | None = None,
) -> np.ndarray:
    if shift_yx is None:
        return label[np.ix_(ys, xs)].reshape(-1)
    dy, dx = shift_yx
    yy = (ys + dy) % label.shape[0]
    xx = (xs + dx) % label.shape[1]
    return label[np.ix_(yy, xx)].reshape(-1)


def _selected_linear_indices(
    ys: np.ndarray,
    xs: np.ndarray,
    width: int,
) -> np.ndarray:
    # np.ix_ flattening is row-major, matching image raster order.
    return (ys[:, None] * width + xs[None, :]).reshape(-1).astype(np.int64)


def _read_missingness_selected(
    path: Path,
    selected_linear: np.ndarray,
    *,
    expected_rows: int,
) -> tuple[np.ndarray, str, int]:
    """Read only missingness at selected raster positions while hashing raw bytes.

    The public data card states that raw TXT, normalized height, brightfield,
    and label files share identical dimensions and a top-left origin. This
    reader treats parseable X;Y;Z rows as raster-ordered data rows and verifies
    the total count against width*height. Non-data/header lines are ignored.
    """
    targets = np.asarray(selected_linear, dtype=np.int64)
    if targets.ndim != 1 or not targets.size or np.any(targets[1:] <= targets[:-1]):
        raise BenchmarkError("selected raw raster indices must be strictly increasing")
    if targets[0] < 0 or targets[-1] >= expected_rows:
        raise BenchmarkError("selected raw raster index outside expected image")

    result = np.empty(targets.size, dtype=bool)
    target_pos = 0
    data_row = 0
    hasher = hashlib.sha256()

    try:
        with path.open("rb") as handle:
            for raw_line in handle:
                hasher.update(raw_line)
                try:
                    line = raw_line.decode("utf-8").strip()
                except UnicodeDecodeError as exc:
                    raise BenchmarkError(f"raw TXT is not UTF-8: {path}") from exc
                if not line:
                    continue
                parts = line.split(";")
                if len(parts) < 3:
                    continue
                try:
                    x = float(parts[0].strip())
                    y = float(parts[1].strip())
                    z = float(parts[2].strip())
                except ValueError:
                    continue
                if not math.isfinite(x) or not math.isfinite(y):
                    continue

                if target_pos < targets.size and data_row == int(targets[target_pos]):
                    result[target_pos] = not math.isfinite(z)
                    target_pos += 1
                data_row += 1
    except OSError as exc:
        raise BenchmarkError(f"cannot read raw height TXT {path}: {exc}") from exc

    if data_row != expected_rows:
        raise BenchmarkError(
            f"raw TXT data-row count {data_row} != manifest pixel count {expected_rows}: {path}"
        )
    if target_pos != targets.size:
        raise BenchmarkError(
            f"raw TXT ended before all selected raster positions were observed: {path}"
        )
    return result, hasher.hexdigest(), data_row


def _validate_spec(
    spec: dict[str, Any],
    *,
    control_sha256: str,
    control: dict[str, Any],
) -> dict[str, Any]:
    if spec.get("schema_version") != SCHEMA_VERSION or spec.get("tool") != TOOL:
        raise BenchmarkError(f"spec must be {TOOL} schema_version {SCHEMA_VERSION}")
    if spec.get("control_manifest_sha256") != control_sha256:
        raise BenchmarkError("control manifest SHA-256 differs from preregistered spec")
    if spec.get("source_revision") != control.get("source", {}).get("revision"):
        raise BenchmarkError("spec source_revision differs from control manifest")
    if spec.get("source_split") != "leave-one-papyrus-out":
        raise BenchmarkError("spec source_split must be leave-one-papyrus-out")

    expected_sample_count = _positive_int(
        spec.get("expected_sample_count"), "expected_sample_count"
    )

    names = spec.get("descriptors")
    if (
        not isinstance(names, list)
        or not names
        or any(name not in SUPPORTED_DESCRIPTORS for name in names)
        or len(set(names)) != len(names)
    ):
        raise BenchmarkError("spec descriptors are missing, duplicated, or unsupported")
    control_names = control.get("design", {}).get("descriptors")
    if names != control_names:
        raise BenchmarkError("spec descriptors differ from frozen control manifest")

    sampling = spec.get("sampling")
    if not isinstance(sampling, dict):
        raise BenchmarkError("spec sampling must be an object")
    if sampling.get("policy") != "label-blind-interior-grid-v1":
        raise BenchmarkError("unsupported sampling policy")
    max_pixels = _positive_int(
        sampling.get("max_sampled_pixels_per_sample"),
        "max_sampled_pixels_per_sample",
    )
    border = _positive_int(sampling.get("border_pixels"), "border_pixels")
    min_ink = _positive_int(sampling.get("min_sampled_ink_pixels"), "min_sampled_ink_pixels")
    min_bg = _positive_int(
        sampling.get("min_sampled_papyrus_pixels"),
        "min_sampled_papyrus_pixels",
    )

    if spec.get("direction_rule") != "median-training-sample-mean-rank-delta":
        raise BenchmarkError("unsupported direction_rule")
    if spec.get("heldout_metric") != "pooled-pixel-auroc":
        raise BenchmarkError("unsupported heldout_metric")

    controls = spec.get("controls")
    if not isinstance(controls, dict):
        raise BenchmarkError("spec controls must be an object")
    perm = controls.get("label_permutation")
    missingness = controls.get("missingness")
    if not isinstance(perm, dict) or perm.get("method") != "deterministic-toroidal-label-roll-v1":
        raise BenchmarkError("unsupported label-permutation control")
    seed = perm.get("seed")
    if type(seed) is not int:
        raise BenchmarkError("label-permutation seed must be an integer")
    if not isinstance(missingness, dict) or missingness.get("source") != "raw-height-nonfinite-z":
        raise BenchmarkError("missingness control must use raw-height-nonfinite-z")

    rule = spec.get("advance_rule")
    if not isinstance(rule, dict):
        raise BenchmarkError("spec advance_rule must be an object")
    try:
        min_auc = float(rule["min_heldout_auc_each_papyrus"])
        max_perm = float(rule["max_label_permutation_abs_auc_from_chance"])
        max_missing = float(rule["max_missingness_discriminative_auc"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BenchmarkError(f"invalid advance rule: {exc}") from exc
    if not 0.5 <= min_auc <= 1.0:
        raise BenchmarkError("min held-out AUC must be in [0.5,1]")
    if not 0 <= max_perm <= 0.5:
        raise BenchmarkError("max permutation AUC distance must be in [0,0.5]")
    if not 0.5 <= max_missing <= 1.0:
        raise BenchmarkError("max missingness discriminative AUC must be in [0.5,1]")

    contract = spec.get("selection_contract")
    if not isinstance(contract, dict):
        raise BenchmarkError("spec selection_contract must be an object")
    required_false = (
        "learned_classifier",
        "uses_absolute_micron_thresholds",
        "heldout_labels_choose_descriptor_direction",
        "candidate_renders_or_ocr_consumed",
        "target_ct_consumed",
    )
    for key in required_false:
        if contract.get(key) is not False:
            raise BenchmarkError(f"selection_contract.{key} must be false")

    return {
        "expected_sample_count": expected_sample_count,
        "descriptors": list(names),
        "max_pixels": max_pixels,
        "border": border,
        "min_ink": min_ink,
        "min_bg": min_bg,
        "permutation_seed": seed,
        "min_auc": min_auc,
        "max_perm": max_perm,
        "max_missingness": max_missing,
    }


def _prepare_sample(
    row: dict[str, str],
    *,
    data_root: Path,
    config: dict[str, Any],
) -> SampleEvidence:
    sample_id = (row.get("sample_id") or "").strip()
    papyrus = (row.get("papyrus_id") or "").strip()
    if not sample_id or not papyrus:
        raise BenchmarkError("every dataset row needs non-empty papyrus_id and sample_id")
    height = _positive_int(row.get("height_px"), f"{sample_id}.height_px")
    width = _positive_int(row.get("width_px"), f"{sample_id}.width_px")
    shape = (height, width)
    pixel_count = _positive_int(row.get("pixel_count"), f"{sample_id}.pixel_count")
    if pixel_count != height * width:
        raise BenchmarkError(
            f"{sample_id}: pixel_count {pixel_count} != width*height {width * height}"
        )

    norm_path = data_root / row["normalized_height_tif"]
    label_path = data_root / row["label_png"]
    raw_path = data_root / row["raw_height_txt"]
    for path in (norm_path, label_path, raw_path):
        if not path.is_file():
            raise BenchmarkError(f"required source file missing: {path}")

    height_map = _load_height(norm_path, shape)
    label = _load_label(label_path, shape)
    ys, xs, stride = _grid_indices(
        height,
        width,
        border=config["border"],
        max_pixels=config["max_pixels"],
    )
    labels = _labels_at_grid(label, ys, xs)
    ink = int(labels.sum())
    background = int(labels.size - ink)
    if ink < config["min_ink"] or background < config["min_bg"]:
        raise BenchmarkError(
            f"{sample_id}: sampled classes below preregistered minimum "
            f"(ink={ink}, papyrus={background})"
        )

    shift = _permutation_shift(
        sample_id,
        height,
        width,
        config["permutation_seed"],
    )
    permuted = _labels_at_grid(label, ys, xs, shift_yx=shift)
    desc = _descriptors_at_grid(height_map, ys, xs, config["descriptors"])
    linear = _selected_linear_indices(ys, xs, width)
    missingness, raw_sha, raw_rows = _read_missingness_selected(
        raw_path,
        linear,
        expected_rows=height * width,
    )

    return SampleEvidence(
        papyrus=papyrus,
        papyrus_key=_canon_papyrus(papyrus),
        sample_id=sample_id,
        shape_yx=shape,
        stride=stride,
        sampled_pixels=int(labels.size),
        ink_pixels=ink,
        papyrus_pixels=background,
        labels=labels,
        permuted_labels=permuted,
        missingness=missingness.astype(np.float32),
        descriptors=desc,
        hashes={
            "normalized_height_tif": _sha256(norm_path),
            "label_png": _sha256(label_path),
            "raw_height_txt": raw_sha,
        },
        raw_data_rows=raw_rows,
        permutation_shift_yx=shift,
    )


def _mean_rank_delta(scores: np.ndarray, labels: np.ndarray) -> float:
    ink = scores[labels]
    background = scores[~labels]
    if not ink.size or not background.size:
        raise BenchmarkError("direction estimation requires both classes")
    return float(ink.mean() - background.mean())


def _fold_descriptor(
    descriptor: str,
    *,
    training: list[SampleEvidence],
    heldout: list[SampleEvidence],
) -> dict[str, Any]:
    train_deltas = [
        _mean_rank_delta(sample.descriptors[descriptor], sample.labels)
        for sample in training
    ]
    direction_delta = float(np.median(np.asarray(train_deltas, dtype=np.float64)))
    direction = 1 if direction_delta >= 0 else -1

    held_scores = np.concatenate(
        [direction * sample.descriptors[descriptor] for sample in heldout]
    )
    held_labels = np.concatenate([sample.labels for sample in heldout])
    held_auc = _auc(held_scores, held_labels)
    per_sample_auc = {
        sample.sample_id: _auc(
            direction * sample.descriptors[descriptor],
            sample.labels,
        )
        for sample in heldout
    }

    perm_train_deltas = [
        _mean_rank_delta(sample.descriptors[descriptor], sample.permuted_labels)
        for sample in training
    ]
    perm_delta = float(np.median(np.asarray(perm_train_deltas, dtype=np.float64)))
    perm_direction = 1 if perm_delta >= 0 else -1
    perm_scores = np.concatenate(
        [perm_direction * sample.descriptors[descriptor] for sample in heldout]
    )
    perm_labels = np.concatenate([sample.permuted_labels for sample in heldout])
    perm_auc = _auc(perm_scores, perm_labels)

    return {
        "training_sample_mean_rank_deltas": train_deltas,
        "direction_delta": direction_delta,
        "direction": direction,
        "heldout_auc": held_auc,
        "heldout_sample_auc": per_sample_auc,
        "permutation_direction_delta": perm_delta,
        "permutation_direction": perm_direction,
        "permutation_auc": perm_auc,
        "permutation_abs_auc_from_chance": abs(perm_auc - 0.5),
    }


def _fold_missingness(heldout: list[SampleEvidence]) -> dict[str, Any]:
    scores = np.concatenate([sample.missingness for sample in heldout])
    labels = np.concatenate([sample.labels for sample in heldout])
    auc = _auc(scores, labels)
    return {
        "auc": auc,
        "discriminative_auc": max(auc, 1.0 - auc),
        "missing_fraction": float(scores.mean()),
    }


def run_benchmark(
    *,
    spec_path: str | Path,
    control_manifest_path: str | Path,
    dataset_manifest_path: str | Path,
    data_root: str | Path,
) -> dict[str, Any]:
    spec_path = Path(spec_path)
    control_path = Path(control_manifest_path)
    dataset_manifest_path = Path(dataset_manifest_path)
    data_root = Path(data_root)

    spec_raw, spec = _load_json_bytes(spec_path, "benchmark spec")
    control_raw, control = _load_json_bytes(control_path, "morphology control manifest")
    control_sha = _sha256_bytes(control_raw)

    control_audit = audit_morphology_manifest(control)
    if control_audit.get("status") == "fail":
        raise BenchmarkError(
            "morphology control manifest fails its provenance/design audit: "
            + "; ".join(control_audit.get("errors", [])[:3])
        )
    if control.get("mode") != "source_benchmark":
        raise BenchmarkError("benchmark requires a source_benchmark control manifest")

    config = _validate_spec(spec, control_sha256=control_sha, control=control)
    rows = _read_rows(dataset_manifest_path)
    dataset_manifest_sha = _sha256(dataset_manifest_path)
    if len(rows) != config["expected_sample_count"]:
        raise BenchmarkError(
            f"dataset manifest has {len(rows)} samples; "
            f"expected {config['expected_sample_count']}"
        )

    expected_keys = {
        _canon_papyrus(name)
        for name in control.get("source", {}).get("source_papyri", [])
    }
    row_keys = {_canon_papyrus((row.get("papyrus_id") or "").strip()) for row in rows}
    if row_keys != expected_keys:
        raise BenchmarkError(
            f"dataset papyri {sorted(row_keys)} != frozen source papyri {sorted(expected_keys)}"
        )

    sample_ids = [(row.get("sample_id") or "").strip() for row in rows]
    if len(sample_ids) != len(set(sample_ids)):
        raise BenchmarkError("dataset manifest contains duplicate sample_id values")

    samples = [
        _prepare_sample(row, data_root=data_root, config=config)
        for row in rows
    ]
    groups = {
        key: [sample for sample in samples if sample.papyrus_key == key]
        for key in sorted(expected_keys)
    }
    if any(not group for group in groups.values()):
        raise BenchmarkError("each frozen source papyrus must have at least one sample")

    folds: dict[str, Any] = {}
    for held_key, heldout in groups.items():
        training = [
            sample
            for key, group in groups.items()
            if key != held_key
            for sample in group
        ]
        fold_name = heldout[0].papyrus
        folds[fold_name] = {
            "heldout_papyrus_key": held_key,
            "training_papyri": sorted({sample.papyrus for sample in training}),
            "heldout_samples": [sample.sample_id for sample in heldout],
            "missingness_control": _fold_missingness(heldout),
            "descriptors": {
                descriptor: _fold_descriptor(
                    descriptor,
                    training=training,
                    heldout=heldout,
                )
                for descriptor in config["descriptors"]
            },
        }

    max_missingness = max(
        fold["missingness_control"]["discriminative_auc"]
        for fold in folds.values()
    )
    decisions: dict[str, Any] = {}
    for descriptor in config["descriptors"]:
        held_aucs = [
            fold["descriptors"][descriptor]["heldout_auc"]
            for fold in folds.values()
        ]
        perm_deltas = [
            fold["descriptors"][descriptor]["permutation_abs_auc_from_chance"]
            for fold in folds.values()
        ]
        min_held = min(held_aucs)
        max_perm = max(perm_deltas)
        gates = {
            "all_papyri_heldout_auc": {
                "passed": min_held >= config["min_auc"],
                "observed_min": min_held,
                "required_min": config["min_auc"],
            },
            "label_permutation_near_chance": {
                "passed": max_perm <= config["max_perm"],
                "observed_max_abs_auc_from_chance": max_perm,
                "required_max": config["max_perm"],
            },
            "missingness_not_strongly_discriminative": {
                "passed": max_missingness <= config["max_missingness"],
                "observed_max_discriminative_auc": max_missingness,
                "required_max": config["max_missingness"],
            },
        }
        passed = all(gate["passed"] for gate in gates.values())
        decisions[descriptor] = {
            "verdict": "RETAIN_SOURCE_ONLY" if passed else "DO_NOT_PROMOTE",
            "gates": gates,
        }

    retained = [
        descriptor
        for descriptor, decision in decisions.items()
        if decision["verdict"] == "RETAIN_SOURCE_ONLY"
    ]

    sample_records = [
        {
            "papyrus_id": sample.papyrus,
            "papyrus_key": sample.papyrus_key,
            "sample_id": sample.sample_id,
            "shape_yx": list(sample.shape_yx),
            "stride": sample.stride,
            "sampled_pixels": sample.sampled_pixels,
            "ink_pixels": sample.ink_pixels,
            "papyrus_pixels": sample.papyrus_pixels,
            "raw_data_rows": sample.raw_data_rows,
            "permutation_shift_yx": list(sample.permutation_shift_yx),
            "hashes": sample.hashes,
            "missing_fraction_sampled": float(sample.missingness.mean()),
        }
        for sample in samples
    ]

    # The unresolved source sampling discrepancy intentionally propagates the
    # control audit's PARTIAL state even when a descriptor passes all source
    # benchmark gates.
    status = control_audit["status"]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "status": status,
        "experiment_id": spec.get("experiment_id"),
        "provenance": {
            "spec_sha256": _sha256_bytes(spec_raw),
            "control_manifest_sha256": control_sha,
            "dataset_manifest_sha256": dataset_manifest_sha,
            "source_revision": control.get("source", {}).get("revision"),
            "source_dataset": control.get("source", {}).get("dataset_id"),
            "dataset_license": control.get("source", {}).get("dataset_license"),
            "data_root_recorded": str(data_root),
        },
        "selection_contract": spec.get("selection_contract"),
        "sampling": {
            **spec["sampling"],
            "actual_sample_count": len(samples),
            "total_sampled_pixels": sum(sample.sampled_pixels for sample in samples),
        },
        "folds": folds,
        "decisions": decisions,
        "retained_source_only_descriptors": retained,
        "target_transfer_authorized": False,
        "control_audit_status": control_audit["status"],
        "control_audit_warnings": control_audit.get("warnings", []),
        "samples": sample_records,
        "limitation": (
            "This source-only benchmark tests simple optical-profilometry descriptors "
            "under papyrus-level holdout. It does not establish transfer to X-ray CT, "
            "ink identity in a sealed scroll, or readability. The public source sampling "
            "discrepancy continues to block target transfer regardless of this result."
        ),
    }


def _write_json_create_only(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise BenchmarkError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog=TOOL,
        description="Run the preregistered source-only profilometry morphology benchmark.",
    )
    ap.add_argument("--spec", required=True)
    ap.add_argument("--control-manifest", required=True)
    ap.add_argument("--dataset-manifest", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    try:
        result = run_benchmark(
            spec_path=args.spec,
            control_manifest_path=args.control_manifest,
            dataset_manifest_path=args.dataset_manifest,
            data_root=args.data_root,
        )
        _write_json_create_only(Path(args.out), result)
    except BenchmarkError as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2

    retained = result["retained_source_only_descriptors"]
    print(
        f"{TOOL}: {result['status']} "
        f"retained_source_only={','.join(retained) if retained else 'none'}"
    )
    return 1 if result["status"] == "partial" else 0


if __name__ == "__main__":
    raise SystemExit(main())
