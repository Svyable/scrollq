"""In-situ synthetic detectability; blank output alone carries no negative evidence.

Independent implementation inspired by axiosdevs/herculaneum-scroll-tools.
No orientation search, model training, or automatic surface/window adjustment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np


class DetectabilityError(ValueError):
    pass


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _number(value, name, lo, hi):
    if type(value) not in (int, float) or not np.isfinite(value) or not lo <= value <= hi:
        raise DetectabilityError(f"invalid {name}")
    return float(value)


def validate_spec(spec):
    if not isinstance(spec, dict) or spec.get("schema_version") != 1:
        raise DetectabilityError("schema_version must be 1")
    for key in ("volume_root", "region_id"):
        if not isinstance(spec.get(key), str) or not spec[key]:
            raise DetectabilityError(f"missing {key}")
    if spec.get("orientation_source") not in ("geometry", "organizer_provenance"):
        raise DetectabilityError("orientation must descend from geometry or organizer provenance")
    if spec.get("layer_order") not in ("forward", "reverse"):
        raise DetectabilityError("declare fixed layer_order")
    if spec.get("selection_used_ink") is not False or spec.get("synthetic_used_for_training") is not False:
        raise DetectabilityError("ink-based selection and synthetic training are forbidden")
    validate_rule(spec)
    for key in ("stack", "face_depth", "surface", "checkpoint", "engine", "config"):
        item = spec.get(key, {})
        if not isinstance(item, dict):
            raise DetectabilityError(f"{key} must be an object")
        sha = item.get("sha256", "")
        if not isinstance(item.get("path"), str) or not item["path"] or not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise DetectabilityError(f"{key} needs path and lowercase SHA-256")
        if not item.get("terms") or item.get("intended_use_permitted") is not True:
            raise DetectabilityError(f"{key} requires its own terms and permitted use")
    if spec.get("uses_prohibited_higher_resolution") is not False:
        raise DetectabilityError("exclude prohibited higher-resolution ancestry")


def validate_rule(spec):
    if not isinstance(spec, dict):
        raise DetectabilityError("probe rule must be an object")
    if type(spec.get("seed")) is not int:
        raise DetectabilityError("declare integer seed")
    for key in ("contrasts", "widths_px"):
        vals = spec.get(key)
        if not isinstance(vals, list) or len(vals) < 2 or len(set(vals)) != len(vals):
            raise DetectabilityError(f"{key} requires multiple unique values")
        for v in vals:
            _number(v, key, 1, 255 if key == "contrasts" else 4096)
        if key == "widths_px" and any(type(v) is not int for v in vals):
            raise DetectabilityError("widths_px must be integers")
    if spec.get("reference_contrast") not in spec["contrasts"]:
        raise DetectabilityError("test reference_contrast directly; do not interpolate")
    _number(spec.get("threshold"), "threshold", 0, 1)
    _number(spec.get("min_lift"), "min_lift", 1e-9, 1)
    _number(spec.get("max_off_mask_lift"), "max_off_mask_lift", 0, 1)
    _number(spec.get("depth_sigma"), "depth_sigma", 0.01, 10)


def check_assets(spec):
    validate_spec(spec)
    for key in ("stack", "face_depth", "surface", "checkpoint", "engine", "config"):
        if digest(spec[key]["path"]) != spec[key]["sha256"]:
            raise DetectabilityError(f"{key} bytes changed")


def stroke_mask(shape, width, seed):
    """Fixed stroke family, separate from real output and independent of text."""
    h, w = shape
    if min(h, w) < 12 * width:
        raise DetectabilityError("window too small for preregistered stroke width")
    mask = np.zeros(shape, dtype=bool)
    rng = np.random.default_rng(seed)
    offset = int(rng.integers(width, 3 * width))
    for y in range(offset, h - 5 * width, 8 * width):
        for x in range(offset, w - 5 * width, 8 * width):
            mask[y:y + 4 * width, x:x + width] = True
            mask[y:y + 4 * width, x + 3 * width:x + 4 * width] = True
            mask[y + 2 * width:y + 3 * width, x:x + 4 * width] = True
    if min(mask.sum(), (~mask).sum()) < 16:
        raise DetectabilityError("insufficient stroke/background support")
    return mask


def _stack_face(stack, face):
    if stack.dtype != np.uint8 or stack.ndim != 3:
        raise DetectabilityError("stack must be uint8 (depth,y,x), before model normalization")
    if face.dtype.kind not in "uif" or face.shape != stack.shape[1:] or not np.isfinite(face).all():
        raise DetectabilityError("face depth must be finite and match the UV window")
    if np.any(face < 0) or np.any(face > stack.shape[0] - 1):
        raise DetectabilityError("face lies outside frozen depth window")


def plant(stack, face, mask, contrast, sigma):
    _stack_face(stack, face)
    z = np.arange(stack.shape[0])[:, None, None]
    profile = np.exp(-0.5 * ((z - face[None]) / sigma) ** 2)
    return np.clip(stack.astype(float) + contrast * profile * mask[None], 0, 255).astype(np.uint8)


def probability(value, shape):
    value = np.asarray(value)
    if value.dtype.kind not in "buif" or value.shape != shape or not np.isfinite(value).all() or np.any((value < 0) | (value > 1)):
        raise DetectabilityError("prediction must be a finite UV probability map in [0,1]")
    return value


def recovery(base, injected, mask, spec):
    base = probability(base, mask.shape)
    injected = probability(injected, mask.shape)
    delta = (injected > spec["threshold"]).astype(float) - (base > spec["threshold"])
    inside, outside = float(delta[mask].mean()), float(delta[~mask].mean())
    return {"ink_lift": inside, "off_mask_lift": outside,
            "passed": inside >= spec["min_lift"] and abs(outside) <= spec["max_off_mask_lift"]}


RULE_FIELDS = ("contrasts", "widths_px", "reference_contrast", "threshold", "min_lift",
               "max_off_mask_lift", "depth_sigma", "seed")


def validated_rows(spec, rows):
    """Require the entire frozen grid and recompute each verdict from numeric lift."""
    validate_rule(spec)
    expected = {(w, c) for w in spec["widths_px"] for c in spec["contrasts"]}
    seen, result = set(), []
    if not isinstance(rows, list):
        raise DetectabilityError("recovery rows must be a list")
    for row in rows:
        key = (row["width_px"], row["contrast"])
        if key not in expected or key in seen:
            raise DetectabilityError("duplicate or unexpected recovery row")
        seen.add(key)
        inside = _number(row["ink_lift"], "ink_lift", -1, 1)
        outside = _number(row["off_mask_lift"], "off_mask_lift", -1, 1)
        result.append({"width_px": key[0], "contrast": key[1], "ink_lift": inside,
                       "off_mask_lift": outside, "passed": inside >= spec["min_lift"] and
                       abs(outside) <= spec["max_off_mask_lift"]})
    if seen != expected:
        raise DetectabilityError("incomplete recovery grid")
    return result


def summarize(spec, base, rows):
    rows = validated_rows(spec, rows)
    passed = all(r["passed"] for r in rows if r["contrast"] == spec["reference_contrast"])
    blank = not np.any(base > spec["threshold"])
    return {"schema_version": 1, "tool": "scroliq-ink-detectability", "rows": rows,
            "rule": {key: spec[key] for key in RULE_FIELDS},
            "detectability": "PASS" if passed else "FAIL", "real_prediction_blank": bool(blank),
            "negative_evidence": ("SUPPORTED_NEGATIVE" if passed else "UNINFORMATIVE") if blank else "NOT_A_NEGATIVE",
            "scope": "Only the frozen window, tested stroke widths and reference contrast; not proof of ink absence or prize acceptance."}


def run_probe(spec, predict, out, *, spec_bytes=None):
    """One unchanged inference callable for real + synthetic; creates separate artifacts."""
    # Detach from caller-owned objects so a callback cannot retune this contract.
    spec = json.loads(json.dumps(spec, allow_nan=False))
    check_assets(spec)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    frozen = spec_bytes or (json.dumps(spec, indent=2) + "\n").encode()
    if json.loads(frozen) != spec:
        raise DetectabilityError("spec bytes disagree with supplied contract")
    (out / "spec.json").write_bytes(frozen)
    stack = np.load(spec["stack"]["path"], allow_pickle=False)
    face = np.load(spec["face_depth"]["path"], allow_pickle=False)
    _stack_face(stack, face)
    import shutil
    shutil.copyfile(spec["stack"]["path"], out / "stack.npy")
    shutil.copyfile(spec["face_depth"]["path"], out / "face.npy")
    base = probability(predict(stack.copy()), stack.shape[1:]).copy()
    check_assets(spec)
    repeated = probability(predict(stack.copy()), stack.shape[1:]).copy()
    check_assets(spec)
    if not np.array_equal(base, repeated):
        raise DetectabilityError("unchanged-input inference is not deterministic; negative evidence inadmissible")
    np.save(out / "real.npy", base)
    np.save(out / "real-repeat.npy", repeated)
    rows = []
    for wi, width in enumerate(spec["widths_px"]):
        mask = stroke_mask(stack.shape[1:], width, spec["seed"])
        for ci, contrast in enumerate(spec["contrasts"]):
            injected_stack = plant(stack, face, mask, contrast, spec["depth_sigma"])
            predicted = probability(predict(injected_stack.copy()), mask.shape)
            check_assets(spec)
            stem = f"synthetic-{wi}-{ci}"
            np.save(out / f"{stem}-input.npy", injected_stack)
            np.save(out / f"{stem}.npy", predicted)
            rows.append({"width_px": width, "contrast": contrast, **recovery(base, predicted, mask, spec)})
    result = summarize(spec, base, rows)
    files = sorted(out.glob("*.npy")) + [out / "spec.json"]
    result["files_sha256"] = {p.name: digest(p) for p in files}
    (out / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def verify_bundle(directory, expected_spec_sha256):
    """Recompute from arrays; producer verdict and rounded scores are never trusted."""
    root = Path(directory)
    if digest(root / "spec.json") != expected_spec_sha256:
        raise DetectabilityError("bundle spec differs from independently committed spec")
    spec = json.loads((root / "spec.json").read_text())
    validate_spec(spec)
    receipt = json.loads((root / "report.json").read_text())
    if not isinstance(receipt, dict) or not isinstance(receipt.get("files_sha256"), dict):
        raise DetectabilityError("receipt needs an artifact inventory")
    files = receipt["files_sha256"]
    required = {"stack.npy", "face.npy", "real.npy", "real-repeat.npy", "spec.json"}
    required |= {f"synthetic-{wi}-{ci}{suffix}.npy" for wi in range(len(spec["widths_px"]))
                 for ci in range(len(spec["contrasts"])) for suffix in ("", "-input")}
    if set(files) != required or any(digest(root / name) != sha for name, sha in files.items()):
        raise DetectabilityError("missing or altered bundle artifacts")
    stack = np.load(root / "stack.npy", allow_pickle=False)
    face = np.load(root / "face.npy", allow_pickle=False)
    if digest(root / "stack.npy") != spec["stack"]["sha256"] or digest(root / "face.npy") != spec["face_depth"]["sha256"]:
        raise DetectabilityError("stack/face do not match frozen source bytes")
    _stack_face(stack, face)
    base = probability(np.load(root / "real.npy", allow_pickle=False), face.shape)
    repeated = probability(np.load(root / "real-repeat.npy", allow_pickle=False), face.shape)
    if not np.array_equal(base, repeated):
        raise DetectabilityError("unchanged-input inference repeat differs")
    rows = []
    for wi, width in enumerate(spec["widths_px"]):
        mask = stroke_mask(face.shape, width, spec["seed"])
        for ci, contrast in enumerate(spec["contrasts"]):
            stem = f"synthetic-{wi}-{ci}"
            injected = np.load(root / f"{stem}-input.npy", allow_pickle=False)
            if not np.array_equal(injected, plant(stack, face, mask, contrast, spec["depth_sigma"])):
                raise DetectabilityError("synthetic input differs from frozen planting recipe")
            prediction = np.load(root / f"{stem}.npy", allow_pickle=False)
            rows.append({"width_px": width, "contrast": contrast, **recovery(base, prediction, mask, spec)})
    return {**summarize(spec, base, rows), "binding": {key: spec[key] for key in
            ("volume_root", "region_id", "surface", "checkpoint", "layer_order")}}


def preprocessing_gate(truth, before, after, before_probe, after_probe, threshold=0.5):
    """Paired sealed positive fixture: synthetic improvement cannot excuse real degradation."""
    _number(threshold, "threshold", 0, 1)
    truth = np.asarray(truth)
    if truth.dtype != bool or not truth.any() or truth.all():
        raise DetectabilityError("known-positive truth needs ink and physical negatives")
    scores = []
    for value in (before, after):
        predicted = probability(value, truth.shape) > threshold
        scores.append(float((predicted & truth).sum() / (predicted | truth).sum()))
    before_rule, after_rule = before_probe["rule"], after_probe["rule"]
    if before_rule != after_rule or threshold != before_rule["threshold"]:
        raise DetectabilityError("preprocessing comparison changed the frozen probe rule")
    b_rows = validated_rows(before_rule, before_probe["rows"])
    a_rows = validated_rows(after_rule, after_probe["rows"])
    b = {(r["width_px"], r["contrast"]): r for r in b_rows}
    a = {(r["width_px"], r["contrast"]): r for r in a_rows}
    preserved = all(a[k]["ink_lift"] >= b[k]["ink_lift"] and
                    abs(a[k]["off_mask_lift"]) <= abs(b[k]["off_mask_lift"]) for k in b)
    ref = before_rule["reference_contrast"]
    reference_pass = all(row["passed"] for row in b_rows + a_rows if row["contrast"] == ref)
    return {"known_positive_iou_before": scores[0], "known_positive_iou_after": scores[1],
            "verdict": "PASS" if scores[1] >= scores[0] and preserved and reference_pass else "FAIL"}



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", help="frozen JSON; asset paths relative to working directory")
    parser.add_argument("--spec-sha256", help="independently preregistered exact spec bytes")
    parser.add_argument("--out", help="create-only evidence directory")
    parser.add_argument("--verify", help="recompute existing bundle")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify_bundle(args.verify, args.spec_sha256)
        elif args.spec and args.out and args.spec_sha256:
            if digest(args.spec) != args.spec_sha256:
                raise DetectabilityError("spec does not match preregistered digest")
            spec = json.loads(Path(args.spec).read_text())
            # Adapter receives input.npy, output.npy, config path, checkpoint path, layer order.
            # It must run the exact frozen public inference path; no shell interpolation.
            def predict(stack):
                import tempfile
                with tempfile.TemporaryDirectory() as temp:
                    source, target = Path(temp) / "input.npy", Path(temp) / "output.npy"
                    np.save(source, stack)
                    subprocess.run([sys.executable, spec["engine"]["path"], str(source), str(target),
                                    spec["config"]["path"], spec["checkpoint"]["path"], spec["layer_order"]], check=True)
                    return np.load(target, allow_pickle=False)
            result = run_probe(spec, predict, args.out, spec_bytes=Path(args.spec).read_bytes())
        else:
            parser.print_help()
            return 0
        print(json.dumps(result, indent=2))
        return 0 if result["detectability"] == "PASS" else 2
    except (DetectabilityError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"scroliq-ink-detectability: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
