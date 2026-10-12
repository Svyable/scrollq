"""Frozen, group-disjoint E8/scalar rate-versus-signal experiment."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

from .e8_codec import decode, encode, features, fit

RULE = {"bits": [1, 2, 4], "score_tolerance": 0.05,
        "min_compression": 4.0, "max_group_auroc_drop": 0.01,
        "min_raw_group_auroc": 0.60, "min_byte_advantage": 0.05,
        "min_mse_advantage": 0.10, "max_byte_premium_for_mse_comparison": 0.02}


def auroc(y, score):
    pos, neg = int(np.sum(y == 1)), int(np.sum(y == 0))
    if not pos or not neg:
        return None
    return float((rankdata(score)[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def metrics(y, score):
    pred = score >= 0
    return {"auroc": auroc(y, score),
            "recall": float(pred[y == 1].mean()) if np.any(y == 1) else None,
            "false_positive_rate": float(pred[y == 0].mean()) if np.any(y == 0) else None}


def validate_fixture(p):
    x = features(p["embeddings"])
    y, split, groups, ids = (np.asarray(p[k]) for k in ("labels", "split", "groups", "sample_ids"))
    if any(a.shape != (len(x),) for a in (y, split, groups, ids)):
        raise ValueError("fixture arrays must have one entry per feature row")
    if not np.isin(y, [0, 1]).all() or not np.isin(split, ["calibration", "evaluation"]).all():
        raise ValueError("binary labels and explicit calibration/evaluation required")
    if len(np.unique(ids)) != len(ids) or any(not str(v) for v in groups):
        raise ValueError("sample IDs must be unique; groups nonempty")
    cal, ev = split == "calibration", split == "evaluation"
    if cal.sum() < 16 or ev.sum() < 16 or len(np.unique(y[cal])) != 2:
        raise ValueError("need >=16 rows per split and both calibration classes")
    if set(groups[cal]) & set(groups[ev]):
        raise ValueError("physical groups overlap calibration/evaluation")
    training = np.asarray(p["embedding_training_groups"])
    if training.ndim != 1 or set(training) & set(groups[ev]):
        raise ValueError("embedding training groups overlap evaluation")
    source = str(p["source_kind"])
    pin = str(p["checkpoint_sha256"])
    if source not in ("synthetic", "real") or len(pin) != 64 or any(c not in "0123456789abcdef" for c in pin):
        raise ValueError("source kind and checkpoint SHA-256 required")
    if source == "real" and pin == "0" * 64:
        raise ValueError("real embeddings require a non-placeholder checkpoint pin")
    return x, y, groups, cal, ev, source


def run_fixture(p):
    x, y, groups, cal, ev, source = validate_fixture(p)
    train, test = x[cal], x[ev]
    # One frozen binary ridge probe. No evaluation labels enter the fit or escapes.
    mean = train.astype(float).mean(0)
    std = np.maximum(train.astype(float).std(0), 1e-8)
    z = (train - mean) / std
    target = y[cal].astype(float) * 2 - 1
    intercept = target.mean()
    w = np.linalg.solve(z.T @ z + np.eye(x.shape[1]), z.T @ (target - intercept)) / std
    bias = np.array([intercept - mean @ w])
    raw_score = test.astype(float) @ w + bias[0]
    egroups = groups[ev]
    raw = {str(g): metrics(y[ev][egroups == g], raw_score[egroups == g]) for g in np.unique(egroups)}
    arms = []
    for bits in RULE["bits"]:
        for method in ("e8", "scalar"):
            model = fit(train, method=method, bits=bits)
            for mode in ("none", "escape", "projection"):
                protected = mode != "none"
                payload = encode(model, test, probes=w if protected else None, bias=bias,
                                 score_tolerance=RULE["score_tolerance"],
                                 protection="escape" if mode == "none" else mode)
                restored = decode(payload)
                score = restored.astype(float) @ w + bias[0]
                with np.load(io.BytesIO(payload), allow_pickle=False) as bank:
                    escapes = len(bank["escape_rows"])
                    index_bytes = int(bank["code"].nbytes)
                gm = {str(g): metrics(y[ev][egroups == g], score[egroups == g]) for g in np.unique(egroups)}
                drops = [raw[g]["auroc"] - gm[g]["auroc"] for g in raw
                         if raw[g]["auroc"] is not None and gm[g]["auroc"] is not None]
                compression = test.nbytes / len(payload)
                flips = int(np.count_nonzero((score >= 0) != (raw_score >= 0)))
                error = float(np.max(np.abs(score - raw_score)))
                informative = all(v["auroc"] is not None and v["auroc"] >= RULE["min_raw_group_auroc"] for v in raw.values())
                quality = informative and flips == 0 and error <= RULE["score_tolerance"] + 1e-12 and max(drops, default=1) <= RULE["max_group_auroc_drop"]
                arms.append({"method": method, "bits_per_channel_indices": bits, "protected": protected,
                             "protection": mode,
                             "archive_bytes_including_model_and_escapes": len(payload),
                             "index_bytes": index_bytes, "raw_float32_bytes": test.nbytes,
                             "compression": compression, "escape_rows": escapes,
                             "escape_fraction": escapes / len(test), "mse": float(np.mean((restored.astype(float) - test) ** 2)),
                             "max_probe_score_error": error, "probe_decision_flips": flips,
                             "worst_group_auroc_drop": max(drops) if drops else None,
                             "quality_gate": bool(quality), "groups": gm})
    for arm in arms:
        control = next(a for a in arms if a["method"] == "scalar" and a["protection"] == arm["protection"] and a["bits_per_channel_indices"] == arm["bits_per_channel_indices"])
        gain = 1 - arm["archive_bytes_including_model_and_escapes"] / control["archive_bytes_including_model_and_escapes"]
        arm["byte_advantage_vs_matched_scalar"] = gain
        mse_gain = 1 - arm["mse"] / max(control["mse"], 1e-300)
        arm["mse_advantage_vs_matched_scalar"] = mse_gain
        efficient = gain >= RULE["min_byte_advantage"] or (gain >= -RULE["max_byte_premium_for_mse_comparison"] and mse_gain >= RULE["min_mse_advantage"])
        passes = arm["method"] == "e8" and arm["protected"] and arm["quality_gate"] and arm["compression"] >= RULE["min_compression"] and efficient
        arm["verdict"] = "TEST_ON_REAL_DATA" if passes and source == "synthetic" else ("CANDIDATE_FOR_DOWNSTREAM_VALIDATION" if passes else "NO_MATERIAL_GAIN")
    return {"schema_version": 1, "tool": "scroliq-e8-moonshot", "source_kind": source,
            "rule": RULE, "calibration_rows": int(cal.sum()), "evaluation_rows": int(ev.sum()),
            "raw_groups": raw, "arms": arms,
            "scope": "Frozen binary linear probe only; no nonlinear-head, segmentation, ink or runtime guarantee.",
            "provenance_scope": "Declared physical/training groups and checkpoint pin; upstream extraction lineage not independently verified."}


def synthetic_fixture(seed=1729, scenario="isotropic"):
    rng = np.random.default_rng(seed)
    n, d = 1536, 32
    x = rng.normal(size=(2 * n, d))
    direction = rng.normal(size=d)
    direction /= np.linalg.norm(direction)
    label = (x @ direction > 0).astype(np.uint8)
    if scenario == "anisotropic":
        x *= np.geomspace(0.1, 10, d)
    elif scenario == "shifted":
        x[n:] += np.linspace(-0.4, 0.4, d)
    elif scenario != "isotropic":
        raise ValueError("unknown synthetic scenario")
    return {"embeddings": x.astype(np.float32), "labels": label,
            "split": np.array(["calibration"] * n + ["evaluation"] * n),
            "groups": np.array([f"cal-{i // 512}" for i in range(n)] + [f"eval-{i // 512}" for i in range(n)]),
            "sample_ids": np.array([f"{seed}-{scenario}-{i}" for i in range(2 * n)]),
            "source_kind": np.array("synthetic"), "checkpoint_sha256": np.array("0" * 64),
            "embedding_training_groups": np.array([], dtype="U1")}


def controls():
    # Weak coordinate evidence against large nuisance coordinates. A damaged
    # decoder must not be rewarded for the lower bulk reconstruction error.
    rng = np.random.default_rng(911)
    model = fit(rng.normal(size=(512, 16)).astype(np.float32), bits=2)
    x = rng.normal(size=(512, 16)).astype(np.float32)
    x[:, 0] = np.where(np.arange(512) % 2, 0.01, -0.01)
    w = np.zeros(16)
    w[0] = 1
    raw = decode(encode(model, x))
    protected = decode(encode(model, x, probes=w, score_tolerance=0.001))
    projected = decode(encode(model, x, probes=w, score_tolerance=0.001, protection="projection"))
    lost = int(np.count_nonzero((raw[:, 0] >= 0) != (x[:, 0] >= 0)))
    remaining = int(np.count_nonzero((protected[:, 0] >= 0) != (x[:, 0] >= 0)))
    error = float(np.max(np.abs(protected[:, 0] - x[:, 0])))
    projected_flips = int(np.count_nonzero((projected[:, 0] >= 0) != (x[:, 0] >= 0)))
    projected_error = float(np.max(np.abs(projected[:, 0] - x[:, 0])))
    return {"unprotected_weak_signal_flips": lost, "protected_weak_signal_flips": remaining,
            "protected_max_score_error": error,
            "projection_weak_signal_flips": projected_flips, "projection_max_score_error": projected_error,
            "pass": bool(lost > 0 and remaining == 0 and error <= 0.001 and projected_flips == 0 and projected_error <= 0.001)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="group-disjoint NPZ embeddings; allow_pickle=False")
    parser.add_argument("--synthetic", action="store_true", help="run frozen three-scenario stress suite")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if bool(args.fixture) == args.synthetic:
        parser.error("choose exactly one of --fixture or --synthetic")
    ctrl = controls()
    if not ctrl["pass"]:
        raise ValueError("weak-signal positive control failed")
    if args.synthetic:
        results = []
        for scenario in ("isotropic", "anisotropic", "shifted"):
            result = run_fixture(synthetic_fixture(scenario=scenario))
            result["scenario"] = scenario
            results.append(result)
        input_pin = "deterministic generated fixtures, seed 1729; separate control seed 911"
    else:
        data = args.fixture.read_bytes()
        input_pin = hashlib.sha256(data).hexdigest()
        with np.load(io.BytesIO(data), allow_pickle=False) as fixture:
            results = [run_fixture(fixture)]
    import scipy
    report = {"controls": ctrl, "input": input_pin, "results": results,
              "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
              "implementation_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                        for name in ("e8_codec.py", "e8_experiment.py")}}
    text = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x") as handle:
            handle.write(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
