"""O1 mesh review: the committed sample regenerates exactly, the reviewer
sheet is blind, and the scorer applies the pre-registered rules."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "artifacts" / "2026-10-01-mesh-review-sample"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "bin" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sampler = _load("mesh_review_sample")
scorer = _load("mesh_review_score")


def test_committed_sample_regenerates_byte_for_byte(tmp_path):
    rows = json.loads((sampler.AUDIT / "summary.json").read_bytes())["rows"]
    sampler.write(tmp_path, sampler.draw(rows), seed=sampler.SEED)
    for name in ("review-sheet.csv", "key.json", "manifest.json"):
        assert (tmp_path / name).read_bytes() == (SAMPLE_DIR / name).read_bytes(), name


def test_sheet_is_blind_and_key_matches_protocol():
    with (SAMPLE_DIR / "review-sheet.csv").open(newline="") as fh:
        sheet = list(csv.DictReader(fh))
    assert list(sheet[0]) == sampler.SHEET_FIELDS
    text = (SAMPLE_DIR / "review-sheet.csv").read_text()
    for leak in ("multi-defect", "flagged", "stratum", "normal-reversal", "edge-jump"):
        assert leak not in text
    assert all(not row["label"] for row in sheet)

    key = json.loads((SAMPLE_DIR / "key.json").read_text())
    sizes = {s: sum(1 for k in key if k["stratum"] == s) for s in "FDC"}
    assert sizes == {"F": 30, "D": 4, "C": 20}
    assert len({k["segment"] for k in key}) == len(key)
    assert any(k["segment"] == sampler.KNOWN_BROKEN for k in key if k["stratum"] == "D")
    assert all("z_dbg" not in k["segment"] for k in key if k["stratum"] != "D")
    assert all(k["tier"] == "multi-defect" for k in key if k["stratum"] in "FD")
    assert all(k["tier"] == "clean" for k in key if k["stratum"] == "C")
    # Shuffled across strata: the first ten ids are not a single stratum.
    assert len({k["stratum"] for k in key[:10]}) > 1


def test_allocation_is_proportional_with_floor_of_one():
    assert sampler.allocate({"a": 27, "b": 12, "c": 11, "d": 1}, 30) == {"a": 15, "b": 7, "c": 7, "d": 1}
    assert sampler.allocate({"a": 3, "b": 2}, 10) == {"a": 3, "b": 2}
    with pytest.raises(ValueError):
        sampler.allocate({"a": 3, "b": 2, "c": 2}, 2)


def test_wilson_matches_known_values():
    lo, hi = scorer.wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-4) and hi == pytest.approx(0.7634, abs=1e-4)
    lo, hi = scorer.wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-4)
    assert scorer.wilson(0, 0) is None


def _labelled(f, d, c):
    key, sheet = [], []
    for stratum, labels in (("F", f), ("D", d), ("C", c)):
        for label in labels:
            rid = f"R{len(key):02d}"
            key.append({"review_id": rid, "stratum": stratum, "findings": ["hole"]})
            sheet.append({"review_id": rid, "label": label})
    return sheet, key


def test_enrichment_requires_calibration_and_separated_intervals():
    sheet, key = _labelled(["defect"] * 25 + ["not_defect"] * 5, ["defect"] * 4, ["not_defect"] * 19 + ["defect"])
    result = scorer.score(sheet, key)
    assert result["status"] == "calibrated"
    assert result["flag_precision"]["rate"] == pytest.approx(25 / 30)
    assert result["flag_enriched_for_defects"] is True

    sheet, key = _labelled(["defect"] * 25 + ["not_defect"] * 5, ["defect"] * 2 + ["not_defect"] * 2, ["not_defect"] * 20)
    result = scorer.score(sheet, key)
    assert result["status"] == "uncalibrated"
    assert result["flag_enriched_for_defects"] is False

    sheet, key = _labelled(["defect"] * 6 + ["not_defect"] * 4, ["defect"] * 4, ["defect"] * 4 + ["not_defect"] * 6)
    assert scorer.score(sheet, key)["flag_enriched_for_defects"] is False


def test_unclear_is_bounded_not_counted_and_missing_labels_fail_closed():
    sheet, key = _labelled(["defect", "not_defect", "unclear"], ["defect"] * 4, ["not_defect"])
    flagged = scorer.score(sheet, key)["flag_precision"]
    assert flagged["rate"] == 0.5
    assert flagged["bounds_with_unclear"] == [1 / 3, 2 / 3]

    sheet[0]["label"] = ""
    assert scorer.score(sheet, key)["status"] == "incomplete"
    sheet[0]["label"] = "maybe"
    assert scorer.score(sheet, key)["invalid_labels"] == ["maybe"]
    assert scorer.score(sheet[1:], key)["missing_review_ids"] == ["R00"]
