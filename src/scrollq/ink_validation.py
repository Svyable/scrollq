"""Held-out ink validation and false-positive evidence for Scroll Prize submissions.

This module intentionally measures signal recovery, not reading. It compares a
model prediction against known binary ink ground truth on an explicit held-out
mask and can run the same evaluation against falsification-control predictions
(offset surfaces, adjacent windings, perturbed geometry, independent models,
etc.).

The output is deterministic and machine-readable so it can be pinned from the
Grand Prize provenance graph.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import tifffile

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_VERSION = 1


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _load_2d(path: str | Path) -> np.ndarray:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".npy":
        arr = np.load(p, allow_pickle=False)
    elif suffix in {".tif", ".tiff"}:
        arr = tifffile.imread(p)
    else:
        raise ValueError(
            f"unsupported array format for {p}; expected .npy, .tif, or .tiff"
        )
    arr = np.asarray(arr)
    if arr.ndim != 2:
        raise ValueError(f"{p} must be 2D, got shape {arr.shape}")
    return arr


def _normalize_prediction(arr: np.ndarray, scale: str = "auto") -> np.ndarray:
    x = np.asarray(arr)
    if not np.all(np.isfinite(x)):
        raise ValueError("prediction contains NaN or infinite values")

    if scale == "unit":
        denom = 1.0
    elif scale == "uint8":
        denom = 255.0
    elif scale == "uint16":
        denom = 65535.0
    elif scale == "auto":
        if np.issubdtype(x.dtype, np.floating):
            lo = float(x.min(initial=0.0))
            hi = float(x.max(initial=0.0))
            if lo < 0.0 or hi > 1.0:
                raise ValueError(
                    "floating prediction outside [0,1]; pass --prediction-scale "
                    "uint8/uint16 only when that encoding is intentional"
                )
            denom = 1.0
        elif x.dtype == np.uint8:
            denom = 255.0
        elif x.dtype == np.uint16:
            denom = 65535.0
        elif np.issubdtype(x.dtype, np.bool_):
            denom = 1.0
        else:
            raise ValueError(
                f"cannot infer prediction scale for dtype {x.dtype}; "
                "pass --prediction-scale"
            )
    else:
        raise ValueError(f"unknown prediction scale {scale!r}")

    out = x.astype(np.float32, copy=False) / denom
    if float(out.min(initial=0.0)) < 0.0 or float(out.max(initial=0.0)) > 1.0:
        raise ValueError("normalized prediction is outside [0,1]")
    return out


def _safe_div(n: int | float, d: int | float) -> float | None:
    return (float(n) / float(d)) if d else None


def _roc_auc(scores: np.ndarray, labels: np.ndarray) -> float | None:
    """Compute deterministic ROC AUC with average ranks for tied scores."""
    s = np.asarray(scores, dtype=np.float64).reshape(-1)
    y = np.asarray(labels, dtype=bool).reshape(-1)
    if s.shape != y.shape:
        raise ValueError("ROC AUC scores/labels shape mismatch")

    positives = int(np.count_nonzero(y))
    negatives = int(y.size - positives)
    if positives == 0 or negatives == 0:
        return None

    order = np.argsort(s, kind="mergesort")
    sorted_scores = s[order]
    sorted_labels = y[order]

    starts = np.flatnonzero(
        np.r_[True, sorted_scores[1:] != sorted_scores[:-1]]
    )
    ends = np.r_[starts[1:], sorted_scores.size]
    positive_counts = np.add.reduceat(
        sorted_labels.astype(np.int64, copy=False), starts
    )
    average_ranks = (starts + 1 + ends) / 2.0
    positive_rank_sum = float(
        np.sum(positive_counts * average_ranks, dtype=np.float64)
    )

    return float(
        (
            positive_rank_sum
            - (positives * (positives + 1) / 2.0)
        )
        / (positives * negatives)
    )


def evaluate_prediction(
    prediction: np.ndarray,
    labels: np.ndarray,
    validation_mask: np.ndarray | None = None,
    *,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Compute deterministic binary ink metrics on the validation mask."""
    p = np.asarray(prediction, dtype=np.float32)
    raw_labels = np.asarray(labels)
    if not np.all(np.isfinite(p)) or np.any((p < 0.0) | (p > 1.0)):
        raise ValueError("prediction must contain finite probabilities in [0,1]")
    if not np.all(np.isfinite(raw_labels)) or not np.all(
        np.isin(raw_labels, (0, 1, 255))
    ):
        raise ValueError("labels must be binary values encoded as 0/1 or 0/255")
    y = raw_labels > 0
    if validation_mask is None:
        m = np.ones(y.shape, dtype=bool)
    else:
        raw_mask = np.asarray(validation_mask)
        if not np.all(np.isfinite(raw_mask)) or not np.all(
            np.isin(raw_mask, (0, 1, 255))
        ):
            raise ValueError(
                "validation mask must be binary values encoded as 0/1 or 0/255"
            )
        m = raw_mask > 0

    if p.shape != y.shape or m.shape != y.shape:
        raise ValueError(
            f"shape mismatch: prediction={p.shape}, labels={y.shape}, mask={m.shape}"
        )
    if p.ndim != 2:
        raise ValueError(f"expected 2D arrays, got {p.ndim}D")
    if not (0.0 <= threshold <= 1.0):
        raise ValueError("threshold must be in [0,1]")

    pv = p[m]
    yv = y[m]
    if pv.size == 0:
        raise ValueError("validation mask selects zero pixels")

    pred = pv >= threshold
    tp = int(np.count_nonzero(pred & yv))
    tn = int(np.count_nonzero(~pred & ~yv))
    fp = int(np.count_nonzero(pred & ~yv))
    fn = int(np.count_nonzero(~pred & yv))
    positives = tp + fn
    negatives = tn + fp

    recall = _safe_div(tp, positives)
    specificity = _safe_div(tn, negatives)
    precision = _safe_div(tp, tp + fp)
    fpr = _safe_div(fp, negatives)
    f1 = (
        _safe_div(2 * tp, 2 * tp + fp + fn)
        if (2 * tp + fp + fn) > 0
        else None
    )
    iou = _safe_div(tp, tp + fp + fn)
    balanced = (
        (recall + specificity) / 2.0
        if recall is not None and specificity is not None
        else None
    )

    pos_values = pv[yv]
    neg_values = pv[~yv]
    pos_mean = float(pos_values.mean()) if pos_values.size else None
    neg_mean = float(neg_values.mean()) if neg_values.size else None
    margin = (
        pos_mean - neg_mean
        if pos_mean is not None and neg_mean is not None
        else None
    )
    brier = float(np.mean((pv - yv.astype(np.float32)) ** 2))
    roc_auc = _roc_auc(pv, yv)

    return {
        "threshold": float(threshold),
        "pixels": int(pv.size),
        "ground_truth_ink_pixels": int(positives),
        "ground_truth_background_pixels": int(negatives),
        "both_classes_present": bool(positives and negatives),
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "false_positive_rate": fpr,
        "f1": f1,
        "iou": iou,
        "balanced_accuracy": balanced,
        "roc_auc": roc_auc,
        "brier": brier,
        "ink_probability_mean": pos_mean,
        "background_probability_mean": neg_mean,
        "ink_background_margin": margin,
    }


def _evaluated_digest(
    prediction: np.ndarray,
    labels: np.ndarray,
    validation_mask: np.ndarray,
    controls: dict[str, np.ndarray],
) -> str:
    """Hash canonical evaluated values, shapes, and named controls."""
    h = hashlib.sha256()

    def add(name: str, array: np.ndarray, dtype: str) -> None:
        encoded = name.encode("utf-8")
        canonical = np.asarray(array, dtype=dtype)
        h.update(len(encoded).to_bytes(8, "big"))
        h.update(encoded)
        h.update(len(canonical.shape).to_bytes(8, "big"))
        for size in canonical.shape:
            h.update(int(size).to_bytes(8, "big"))
        h.update(canonical.tobytes(order="C"))

    add("prediction", prediction, "<f4")
    add("labels", np.asarray(labels) > 0, "u1")
    add("validation_mask", np.asarray(validation_mask) > 0, "u1")
    for name, control in sorted(controls.items()):
        add(f"control:{name}", control, "<f4")
    return h.hexdigest()


def build_report(
    *,
    prediction: np.ndarray,
    labels: np.ndarray,
    validation_mask: np.ndarray,
    threshold: float,
    split_id: str,
    held_out: bool,
    training_overlap: str,
    ground_truth_source_url: str,
    model_checkpoint_sha256: str,
    model_window_voxels: Sequence[int],
    controls: dict[str, np.ndarray] | None = None,
    input_records: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one deterministic held-out validation evidence record."""
    if training_overlap not in {"none", "present", "unknown"}:
        raise ValueError("training_overlap must be one of none/present/unknown")
    if not isinstance(split_id, str) or not split_id.strip():
        raise ValueError("split_id is required")
    if not isinstance(ground_truth_source_url, str) or not ground_truth_source_url.startswith(
        ("https://", "http://")
    ):
        raise ValueError("ground_truth_source_url must be public http(s)")
    if not SHA256_RE.fullmatch(model_checkpoint_sha256):
        raise ValueError("model_checkpoint_sha256 must be lowercase 64-hex")
    if len(model_window_voxels) != 3 or any(
        not isinstance(v, int) or v <= 0 for v in model_window_voxels
    ):
        raise ValueError("model_window_voxels must be positive [z,y,x] integers")

    primary = evaluate_prediction(
        prediction, labels, validation_mask, threshold=threshold
    )
    control_rows: list[dict[str, Any]] = []
    for name, control in sorted((controls or {}).items()):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("control names must be non-empty strings")
        metrics = evaluate_prediction(control, labels, validation_mask, threshold=threshold)
        delta_balanced = None
        if (
            primary["balanced_accuracy"] is not None
            and metrics["balanced_accuracy"] is not None
        ):
            delta_balanced = (
                primary["balanced_accuracy"] - metrics["balanced_accuracy"]
            )
        delta_auc = None
        if primary["roc_auc"] is not None and metrics["roc_auc"] is not None:
            delta_auc = primary["roc_auc"] - metrics["roc_auc"]
        delta_margin = None
        if (
            primary["ink_background_margin"] is not None
            and metrics["ink_background_margin"] is not None
        ):
            delta_margin = (
                primary["ink_background_margin"] - metrics["ink_background_margin"]
            )
        control_rows.append(
            {
                "name": name,
                "metrics": metrics,
                "primary_minus_control_balanced_accuracy": delta_balanced,
                "primary_minus_control_roc_auc": delta_auc,
                "primary_minus_control_ink_background_margin": delta_margin,
            }
        )

    readiness_reasons: list[str] = []
    if not held_out:
        readiness_reasons.append("validation split is not declared held-out")
    if training_overlap != "none":
        readiness_reasons.append("training/prediction overlap is not explicitly none")
    if not primary["both_classes_present"]:
        readiness_reasons.append("validation mask does not contain both ink and background")
    if not control_rows:
        readiness_reasons.append("no falsification-control prediction was evaluated")

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-ink-validate",
        "purpose": "held-out ink signal recovery / false-positive evidence",
        "split": {
            "id": split_id,
            "held_out": bool(held_out),
            "training_overlap": training_overlap,
            "known_ground_truth": True,
            "ground_truth_source_url": ground_truth_source_url,
        },
        "model": {
            "checkpoint_sha256": model_checkpoint_sha256,
            "window_voxels_zyx": list(model_window_voxels),
        },
        "evaluation": primary,
        "controls": control_rows,
        "evaluated_arrays_sha256": _evaluated_digest(
            prediction, labels, validation_mask, controls or {}
        ),
        "inputs": input_records or {},
        "prize_evidence_ready": not readiness_reasons,
        "readiness_reasons": readiness_reasons,
    }


def _parse_window(text: str) -> tuple[int, int, int]:
    parts = re.split(r"[xX,]", text)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("window must be ZxYxX, e.g. 17x256x256")
    try:
        values = tuple(int(v) for v in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("window dimensions must be integers") from exc
    if any(v <= 0 for v in values):
        raise argparse.ArgumentTypeError("window dimensions must be positive")
    return values  # type: ignore[return-value]


def _parse_control(text: str) -> tuple[str, str]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("control must be NAME=PATH")
    name, path = text.split("=", 1)
    if not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError("control must be NAME=PATH")
    return name.strip(), path.strip()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Evaluate an ink prediction on known held-out ground truth and "
            "compare falsification-control predictions."
        )
    )
    ap.add_argument("--prediction", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--validation-mask", required=True)
    ap.add_argument(
        "--prediction-scale",
        choices=("auto", "unit", "uint8", "uint16"),
        default="auto",
    )
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--split-id", required=True)
    ap.add_argument("--held-out", action="store_true")
    ap.add_argument(
        "--training-overlap",
        choices=("none", "present", "unknown"),
        default="unknown",
    )
    ap.add_argument("--ground-truth-source-url", required=True)
    ap.add_argument("--model-checkpoint-sha256", required=True)
    ap.add_argument("--model-window", type=_parse_window, required=True)
    ap.add_argument(
        "--control",
        action="append",
        default=[],
        type=_parse_control,
        metavar="NAME=PATH",
        help=(
            "falsification-control prediction evaluated against the same "
            "ground truth; repeat for +normal/-normal/adjacent winding/etc."
        ),
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--format", choices=("text", "json", "github"), default="text")
    args = ap.parse_args(argv)

    prediction_path = Path(args.prediction)
    labels_path = Path(args.labels)
    mask_path = Path(args.validation_mask)

    prediction = _normalize_prediction(
        _load_2d(prediction_path), args.prediction_scale
    )
    labels = _load_2d(labels_path)
    mask = _load_2d(mask_path)

    control_arrays: dict[str, np.ndarray] = {}
    control_inputs: list[dict[str, str]] = []
    for name, raw_path in args.control:
        if name in control_arrays:
            raise SystemExit(f"duplicate control name: {name}")
        path = Path(raw_path)
        control_arrays[name] = _normalize_prediction(
            _load_2d(path), args.prediction_scale
        )
        control_inputs.append(
            {"name": name, "path": str(path), "sha256": _sha256_file(path)}
        )

    report = build_report(
        prediction=prediction,
        labels=labels,
        validation_mask=mask,
        threshold=args.threshold,
        split_id=args.split_id,
        held_out=args.held_out,
        training_overlap=args.training_overlap,
        ground_truth_source_url=args.ground_truth_source_url,
        model_checkpoint_sha256=args.model_checkpoint_sha256,
        model_window_voxels=args.model_window,
        controls=control_arrays,
        input_records={
            "prediction": {
                "path": str(prediction_path),
                "sha256": _sha256_file(prediction_path),
            },
            "labels": {
                "path": str(labels_path),
                "sha256": _sha256_file(labels_path),
            },
            "validation_mask": {
                "path": str(mask_path),
                "sha256": _sha256_file(mask_path),
            },
            "controls": control_inputs,
        },
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "github":
        if not report["prize_evidence_ready"]:
            for reason in report["readiness_reasons"]:
                print(f"::error title=INK_VALIDATION_NOT_READY::{reason}")
        else:
            ba = report["evaluation"]["balanced_accuracy"]
            fpr = report["evaluation"]["false_positive_rate"]
            print(
                "::notice title=INK_VALIDATION_READY::"
                f"balanced_accuracy={ba:.4f} false_positive_rate={fpr:.4f}"
            )
    else:
        verdict = "READY" if report["prize_evidence_ready"] else "NOT READY"
        metrics = report["evaluation"]
        print(f"Held-out ink validation: {verdict}")
        print(
            "balanced_accuracy="
            f"{metrics['balanced_accuracy']} "
            "false_positive_rate="
            f"{metrics['false_positive_rate']} "
            f"controls={len(report['controls'])}"
        )
        for reason in report["readiness_reasons"]:
            print(f"- {reason}")

    return 0 if report["prize_evidence_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
