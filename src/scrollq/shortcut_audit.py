"""Diagnostic linear provenance probes; never an ink acceptance certificate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

NUISANCES = ("fragment_id", "scroll_id", "acquisition_id", "reconstruction_variant",
             "depth_convention", "segment_id")


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _association(confidence, errors):
    if len(errors) < 4 or np.ptp(confidence) == 0 or np.ptp(errors) == 0:
        return {"status": "unverified", "n": len(errors), "pearson_r": None}
    return {"status": "measured_descriptive_only", "n": len(errors),
            "pearson_r": float(np.corrcoef(confidence, errors)[0, 1])}


def audit(embeddings, manifest, *, seed=0, ridge=1.0):
    """Fit probes on balanced train rows, evaluate on disjoint balanced test rows.

    Group IDs must represent physical blocks (including overlapping/adjacent patches).
    This checks declared groups, not geometric overlap; upstream custody remains required.
    """
    x = np.asarray(embeddings, dtype=float)
    rows = manifest["samples"]
    if x.ndim != 2 or not x.shape[0] or not x.shape[1] or len(rows) != len(x):
        raise ValueError("nonempty 2-D embeddings must align with manifest samples")
    if not np.isfinite(x).all() or not np.isfinite(ridge) or ridge <= 0:
        raise ValueError("finite embeddings and positive finite ridge required")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    for key in ("embedding_layer", "label_evidence", "training_domains"):
        if not manifest.get(key):
            raise ValueError(f"missing {key}")
    domains = manifest["training_domains"]
    for key in ("fragment_id", "scroll_id", "acquisition_id"):
        if key not in domains or not isinstance(domains[key], list):
            raise ValueError(f"training_domains.{key} must be an explicit list")
        if any(not isinstance(v, str) or not v for v in domains[key]):
            raise ValueError("training domain identifiers must be nonempty strings")
    ids, groups, vectors = set(), {}, {}
    for row, vector in zip(rows, x):
        for key in ("sample_id", "group_id", "fragment_id", "scroll_id", "acquisition_id"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(f"missing nonempty {key}")
        if row["sample_id"] in ids:
            raise ValueError("duplicate sample identity")
        ids.add(row["sample_id"])
        split = row.get("probe_split")
        if split not in ("train", "test"):
            raise ValueError("probe_split must be train or test")
        group = row["group_id"]
        if groups.setdefault(group, split) != split:
            raise ValueError("physical group crosses probe splits")
        digest = hashlib.sha256(vector.tobytes()).hexdigest()
        if vectors.setdefault(digest, split) != split:
            raise ValueError("identical embedding crosses probe splits")
        if type(row.get("ink_label")) is not int or row["ink_label"] not in (0, 1):
            raise ValueError("verified binary ink_label required")
        probability = row.get("ink_probability")
        if isinstance(probability, bool) or not isinstance(probability, (float, int)) or not np.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("finite ink_probability in [0,1] required")
    report = {"schema": "scroliq-shortcut-passport-v1", "status": "diagnostic_only",
              "promotional": False, "causal_shortcut_demonstrated": False,
              "seed": seed, "ridge": ridge, "embedding_layer": manifest["embedding_layer"],
              "training_domains": domains, "label_evidence": manifest["label_evidence"],
              "probes": {}, "held_out_ink": {},
              "absolute_xyz": {"status": "not_measured", "reason": "continuous spatial probe deferred"}}
    for key in ("fragment_id", "scroll_id", "acquisition_id"):
        metrics = {}
        for value in sorted({r[key] for r in rows} - set(domains[key])):
            selected = [r for r in rows if r[key] == value and r["probe_split"] == "test"]
            if selected:
                metrics[value] = {"n": len(selected), "ink_count": sum(r["ink_label"] for r in selected),
                                  "error_rate": float(np.mean([(r["ink_probability"] >= .5) != r["ink_label"] for r in selected]))}
        report["held_out_ink"][key] = {"status": "measured" if metrics else "unverified",
                                           "domains": metrics, "basis": "declared complete checkpoint training inventory"}
    for nuisance in NUISANCES:
        values = [r.get(nuisance) for r in rows]
        if any(not isinstance(v, str) or not v for v in values):
            report["probes"][nuisance] = {"status": "unverified", "reason": "missing nuisance labels"}
            continue
        classes = sorted(set(values))
        cells = {(split, cls, ink): [i for i, r in enumerate(rows)
                 if r["probe_split"] == split and r[nuisance] == cls and r["ink_label"] == ink]
                 for split in ("train", "test") for cls in classes for ink in (0, 1)}
        if len(classes) < 2 or min(map(len, cells.values())) < 2:
            report["probes"][nuisance] = {"status": "unverified", "reason": "need two rows per nuisance × ink × split cell and two classes"}
            continue
        rng = np.random.default_rng(seed)
        indices = {}
        for split in ("train", "test"):
            count = min(len(cell) for (s, _, _), cell in cells.items() if s == split)
            indices[split] = np.array([i for cls in classes for ink in (0, 1)
                for i in rng.permutation(cells[split, cls, ink])[:count]])
        train, test = indices["train"], indices["test"]
        mean, std = x[train].mean(axis=0), x[train].std(axis=0)
        std[std == 0] = 1
        a, b = (x[train] - mean) / std, (x[test] - mean) / std
        labels = np.array([classes.index(v) for v in values])
        # Balanced targets need no intercept; solve in the smaller feature/sample space.
        target = np.eye(len(classes))[labels[train]]
        if a.shape[1] <= len(train):
            weights = np.linalg.solve(a.T @ a + ridge * np.eye(a.shape[1]), a.T @ target)
        else:
            weights = a.T @ np.linalg.solve(a @ a.T + ridge * np.eye(len(train)), target)
        scores = b @ weights
        accuracy = float(np.mean(scores.argmax(axis=1) == labels[test]))
        correct_score = scores[np.arange(len(test)), labels[test]]
        other_scores = scores.copy()
        other_scores[np.arange(len(test)), labels[test]] = -np.inf
        margin = correct_score - other_scores.max(axis=1)
        errors = np.array([(rows[i]["ink_probability"] >= .5) != rows[i]["ink_label"] for i in test], dtype=float)
        associations = {}
        for heldout in ("fragment_id", "scroll_id"):
            mask = np.array([rows[i][heldout] not in domains[heldout] for i in test])
            associations[heldout] = _association(margin[mask], errors[mask])
        report["probes"][nuisance] = {"status": "measured", "classes": classes,
            "train_n": len(train), "test_n": len(test), "balanced_accuracy": accuracy,
            "balanced_chance": 1 / len(classes), "above_chance": accuracy - 1 / len(classes),
            "selected_train_ids": [rows[i]["sample_id"] for i in train],
            "selected_test_ids": [rows[i]["sample_id"] for i in test],
            "held_out_error_association": associations}
    report["measured_probe_count"] = sum(p["status"] == "measured" for p in report["probes"].values())
    if not report["measured_probe_count"]:
        report["status"] = "unverified"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embeddings", type=Path, required=True, help="NPY, rows aligned to manifest; no pickle")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True, help="Exact frozen checkpoint bytes to hash")
    parser.add_argument("--out", type=Path, required=True, help="Create-only JSON passport")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--ridge", type=float, default=1.)
    args = parser.parse_args(argv)
    try:
        report = audit(np.load(args.embeddings, allow_pickle=False),
                       json.loads(args.manifest.read_text()), seed=args.seed, ridge=args.ridge)
        report["sha256"] = {"embeddings": _hash(args.embeddings), "manifest": _hash(args.manifest),
                            "checkpoint": _hash(args.checkpoint)}
        report["numpy_version"] = np.__version__
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"shortcut audit refused: {exc}\n")


if __name__ == "__main__":
    main()
