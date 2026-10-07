#!/usr/bin/env python3
"""Deterministic PHerc1447 ROI selection and pinned v8-in reproduction scoring.

Selection is allowed to inspect only the released certainty mask and layer geometry.
It must not inspect ink labels or any model prediction before roi-manifest.json exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_inventory(path: Path, repo_id: str) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    for repo in doc["repos"]:
        if repo["repo_id"] == repo_id:
            return repo
    raise SystemExit(f"inventory missing {repo_id}")


def verify_files(root: Path, repo: dict, required: list[str]) -> dict[str, str]:
    inventory = {row["path"]: row for row in repo["files"]}
    out = {}
    for relative in required:
        row = inventory.get(relative)
        if not row or row.get("status") != "hashed":
            raise SystemExit(f"inventory missing hashed file {relative}")
        path = root / relative
        observed = sha256(path)
        if observed != row["sha256"]:
            raise SystemExit(f"SHA-256 mismatch for {relative}: {observed} != {row['sha256']}")
        out[relative] = observed
    return out


def grayscale(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"))


def integral_sum(mask: np.ndarray) -> np.ndarray:
    return np.pad(mask.astype(np.int64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)


def rect_sum(ii: np.ndarray, y: int, x: int, h: int, w: int) -> int:
    y2, x2 = y + h, x + w
    return int(ii[y2, x2] - ii[y, x2] - ii[y2, x] + ii[y, x])


def select_origin(mask: np.ndarray, window: int, stride: int) -> tuple[int, int, int]:
    if mask.ndim != 2 or min(mask.shape) < window:
        raise SystemExit("mask too small for requested window")
    ii = integral_sum(mask > 0)
    best = None
    for y in range(0, mask.shape[0] - window + 1, stride):
        for x in range(0, mask.shape[1] - window + 1, stride):
            score = rect_sum(ii, y, x, window, window)
            key = (-score, y, x)
            if best is None or key < best[0]:
                best = (key, y, x, score)
    assert best is not None
    return best[1], best[2], best[3]


def cmd_select(args) -> None:
    inventory_path = Path(args.inventory)
    surfaces_root = Path(args.surfaces_root)
    repo = load_inventory(inventory_path, args.repo_id)
    if repo["resolved_revision"] != args.revision:
        raise SystemExit("surfaces revision differs from frozen inventory")

    winding = args.winding
    layer_paths = [f"{winding}/layers/{i:02d}.tif" for i in range(24)]
    mask_rel = f"{winding}/labels/mask.png"
    verified = verify_files(surfaces_root, repo, layer_paths + [mask_rel])

    mask = grayscale(surfaces_root / mask_rel)
    y, x, mask_pixels = select_origin(mask, args.window, args.stride)

    out = Path(args.out_dir)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    (out / "layers").mkdir(parents=True)

    layer_shapes = []
    cropped_hashes = {}
    for i, rel in enumerate(layer_paths):
        arr = tifffile.imread(surfaces_root / rel)
        if arr.ndim != 2:
            raise SystemExit(f"{rel}: expected 2D layer, got {arr.shape}")
        if arr.shape != mask.shape:
            raise SystemExit(f"{rel}: shape {arr.shape} != mask {mask.shape}")
        crop = arr[y:y + args.window, x:x + args.window]
        target = out / "layers" / f"{i:02d}.tif"
        tifffile.imwrite(target, crop)
        cropped_hashes[target.name] = sha256(target)
        layer_shapes.append(list(arr.shape))

    manifest = {
        "schema_version": 1,
        "purpose": "PHerc1447 v8-in CPU ROI checkpoint/code reproduction gate",
        "selection_contract": {
            "selection_inputs": ["certainty mask", "layer dimensions"],
            "selection_forbidden_inputs": ["ink labels", "released predictions", "rerun predictions"],
            "rule": "highest certainty-mask pixel count among stride-aligned square windows; ties lexicographic y,x",
            "window": args.window,
            "stride": args.stride,
        },
        "source": {
            "repo_id": args.repo_id,
            "resolved_revision": args.revision,
            "winding": winding,
            "eligible_volume_id": args.volume_id,
            "verified_source_sha256": verified,
        },
        "roi": {
            "y": y,
            "x": x,
            "height": args.window,
            "width": args.window,
            "mask_pixels": mask_pixels,
            "mask_fraction": mask_pixels / float(args.window * args.window),
            "full_shape": list(mask.shape),
            "layer_shapes": layer_shapes,
        },
        "cropped_layers_sha256": cropped_hashes,
        "comparison_contract": {
            "interior_margin_px": args.interior_margin,
            "released_match_mae_max": 0.03,
            "released_match_pearson_min": 0.95,
            "orientation_control_is_descriptive": True,
        },
    }
    (out / "roi-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


def auc(scores: np.ndarray, labels: np.ndarray) -> float | None:
    labels = labels.astype(bool)
    n_pos = int(labels.sum())
    n_neg = int((~labels).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    order = np.argsort(scores, kind="mergesort")
    sorted_scores = scores[order]
    ranks = np.empty(len(scores), dtype=float)
    i = 0
    while i < len(scores):
        j = i + 1
        while j < len(scores) and sorted_scores[j] == sorted_scores[i]:
            j += 1
        ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    rank_sum = float(ranks[labels].sum())
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def pearson(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.size < 2 or np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def cmd_score(args) -> None:
    root = Path(args.roi_dir)
    manifest_path = root / "roi-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    winding = manifest["source"]["winding"]
    y = manifest["roi"]["y"]
    x = manifest["roi"]["x"]
    h = manifest["roi"]["height"]
    w = manifest["roi"]["width"]
    margin = manifest["comparison_contract"]["interior_margin_px"]
    if h <= 2 * margin or w <= 2 * margin:
        raise SystemExit("interior margin removes the entire ROI")

    inventory_path = Path(args.inventory)
    surfaces_root = Path(args.surfaces_root)
    repo = load_inventory(inventory_path, manifest["source"]["repo_id"])
    required = [
        f"{winding}/predictions/v8in.png",
        f"{winding}/labels/inklabels.png",
        f"{winding}/labels/mask.png",
    ]
    verified = verify_files(surfaces_root, repo, required)

    correct = np.load(args.correct, allow_pickle=False).astype(np.float64)
    reversed_order = np.load(args.reversed, allow_pickle=False).astype(np.float64)
    if correct.shape != (h, w) or reversed_order.shape != (h, w):
        raise SystemExit(f"unexpected prediction shapes {correct.shape}, {reversed_order.shape}")

    released_full = grayscale(surfaces_root / required[0]).astype(np.float64) / 255.0
    labels_full = grayscale(surfaces_root / required[1])
    mask_full = grayscale(surfaces_root / required[2]) > 0
    released = released_full[y:y+h, x:x+w]
    labels = labels_full[y:y+h, x:x+w] > 127
    mask = mask_full[y:y+h, x:x+w]

    interior = np.zeros((h, w), dtype=bool)
    interior[margin:h-margin, margin:w-margin] = True
    eval_mask = interior & mask
    if int(eval_mask.sum()) < 64:
        raise SystemExit(f"insufficient frozen interior validation pixels: {int(eval_mask.sum())}")

    def distance(pred):
        diff = pred[eval_mask] - released[eval_mask]
        return {
            "mae": float(np.mean(np.abs(diff))),
            "rmse": float(np.sqrt(np.mean(diff ** 2))),
            "max_abs": float(np.max(np.abs(diff))),
            "pearson": pearson(pred[eval_mask], released[eval_mask]),
        }

    def label_metrics(pred):
        return {
            "roc_auc": auc(pred[eval_mask], labels[eval_mask]),
            "positive_pixels": int(labels[eval_mask].sum()),
            "negative_pixels": int((~labels[eval_mask]).sum()),
        }

    correct_dist = distance(correct)
    reversed_dist = distance(reversed_order)
    correct_label = label_metrics(correct)
    reversed_label = label_metrics(reversed_order)

    match = (
        correct_dist["mae"] <= manifest["comparison_contract"]["released_match_mae_max"]
        and correct_dist["pearson"] is not None
        and correct_dist["pearson"] >= manifest["comparison_contract"]["released_match_pearson_min"]
    )

    result = {
        "schema_version": 1,
        "purpose": "actual pinned base-checkpoint/code ROI reproduction before full GPU campaign",
        "roi_manifest_sha256": sha256(manifest_path),
        "verified_scoring_input_sha256": verified,
        "prediction_sha256": {
            "correct_reverse": sha256(Path(args.correct)),
            "wrong_layer_order": sha256(Path(args.reversed)),
        },
        "evaluation_pixels": int(eval_mask.sum()),
        "correct_vs_released": correct_dist,
        "wrong_order_vs_released": reversed_dist,
        "correct_vs_labels": correct_label,
        "wrong_order_vs_labels": reversed_label,
        "verdict": "REPRODUCED" if match else "NOT_REPRODUCED",
        "interpretation": (
            "ROI was selected before labels/predictions were downloaded. Correct-order reproduction "
            "is a checkpoint/code execution gate only; it is not full-surface, held-out legibility, "
            "or Grand Prize evidence. Wrong-order results are retained as an adverse input control."
        ),
    }
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("select")
    s.add_argument("--inventory", required=True)
    s.add_argument("--surfaces-root", required=True)
    s.add_argument("--repo-id", default="YoussefMoNader/ink-8um-pherc1447-surfaces")
    s.add_argument("--revision", required=True)
    s.add_argument("--winding", default="w058")
    s.add_argument("--volume-id", default="20250521151220")
    s.add_argument("--window", type=int, default=169)
    s.add_argument("--stride", type=int, default=21)
    s.add_argument("--interior-margin", type=int, default=63)
    s.add_argument("--out-dir", required=True)
    s.set_defaults(func=cmd_select)

    q = sub.add_parser("score")
    q.add_argument("--inventory", required=True)
    q.add_argument("--surfaces-root", required=True)
    q.add_argument("--roi-dir", required=True)
    q.add_argument("--correct", required=True)
    q.add_argument("--reversed", required=True)
    q.add_argument("--out", required=True)
    q.set_defaults(func=cmd_score)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
