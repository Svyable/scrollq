import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "artifacts/2026-10-01-public-fiber-audit/summary.json"
SCRIPT = ROOT / "scripts/public_fiber_campaign.py"


def _campaign_module():
    spec = importlib.util.spec_from_file_location("public_fiber_campaign", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_public_fiber_evidence_matches_pinned_inputs():
    campaign = _campaign_module()
    report = json.loads(SUMMARY.read_text(encoding="utf-8"))

    assert set(campaign.EXPECTED_SHA256) == set(campaign.FILES)
    assert report["input_count"] == len(campaign.FILES) == 8
    assert report["download_errors"] == 0
    assert report["hash_mismatches"] == 0

    frozen_hashes = {row["file"]: row["sha256"] for row in report["rows"]}
    assert frozen_hashes == campaign.EXPECTED_SHA256


def test_frozen_public_fiber_evidence_totals_are_internally_consistent():
    report = json.loads(SUMMARY.read_text(encoding="utf-8"))
    rows = report["rows"]

    assert sum(row["bytes"] for row in rows) == report["total_input_bytes"] == 5_304_973
    assert sum(row["line_points"] for row in rows) == 53_828
    assert sum(row["control_points"] for row in rows) == 377
    assert sum(row["segments"] for row in rows) == 369
    assert sum(row["native_trace_segments"] for row in rows) == 354
    assert sum(row["fallback_segments"] for row in rows) == 15

    assert report["status_counts"] == {"caution": 7, "pass": 1}
    assert report["finding_kind_totals"] == {"gap": 11, "sharp_turn": 26}
    assert sum(row["control_line_offsets"] for row in rows) == 0
    assert sum(row["control_order_inversions"] for row in rows) == 0


def test_gap_signal_is_localized_without_inferring_cause():
    report = json.loads(SUMMARY.read_text(encoding="utf-8"))
    gap_rows = [row for row in report["rows"] if row["gaps"]]

    assert [row["file"] for row in gap_rows] == [
        "lt_20260702T055841011_000320.json"
    ]
    row = gap_rows[0]
    assert row["gaps"] == 11
    assert row["fallback_segments"] == 7
    assert row["segments"] == 28
