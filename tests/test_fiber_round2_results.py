import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / "artifacts"


def _j(p):
    return json.loads((A / p).read_text())


def _sha(p):
    return hashlib.sha256((A / p).read_bytes()).hexdigest()


def test_pherc0139_census_is_complete_and_controls_detected():
    c = _j("2026-10-04-pherc0139-fiber-census/summary.json")
    assert c["verdict"] == "complete" and c["listed"] == c["audited"] == len(c["rows"]) == 411
    assert c["detector_control"] == {"detected": 411}
    assert sum(r["gaps"] for r in c["rows"]) == c["totals"]["gaps"] == 1622
    assert c["gaps_in_fibers_without_fallback"] == 0
    assert c["volume_range_check"]["verdict"] == "NONE COMPATIBLE"
    manifest = "".join(f"{r['file']}\t{r['sha256']}\n" for r in sorted(c["rows"], key=lambda r: r["file"]))
    assert hashlib.sha256(manifest.encode()).hexdigest() == c["manifest_sha256"]


def test_results_are_bound_to_their_frozen_specs():
    pairs = {
        "2026-10-04-paris4-fiber-ct-direction-run/result.json": "2026-10-04-paris4-fiber-ct-direction-prereg/spec.json",
        "2026-10-04-fiber-gap-rule-run/result.json": "2026-10-04-fiber-gap-rule-prereg/spec.json",
        "2026-10-04-fiber-gap-rule-v2-pherc0139-run/result.json": "2026-10-04-fiber-gap-rule-v2-pherc0139-prereg/spec.json",
        "2026-10-04-pherc0139-fiber-ct-support-run/result.json": "2026-10-04-pherc0139-fiber-ct-support-prereg/spec.json",
        "2026-10-04-pherc0139-fiber-ct-direction-run/result.json": "2026-10-04-pherc0139-fiber-ct-direction-prereg/spec.json",
    }
    for result, spec in pairs.items():
        assert _j(result)["spec_sha256"] == _sha(spec), result


def test_published_verdicts_and_numbers():
    d = _j("2026-10-04-paris4-fiber-ct-direction-run/result.json")
    assert d["verdict"] == "SUPPORTED" and round(d["D"], 3) == 0.418 and d["D_swapped_ci95"][0] < 0.1
    g1 = _j("2026-10-04-fiber-gap-rule-run/result.json")
    assert g1["verdict"] == "INSUFFICIENT" and g1["planted_recall"]["span_relative"]["fallback"]["n"] == 24
    assert g1["real_candidates"]["old"]["fallback"] == 386 and g1["real_candidates"]["span"]["fallback"] == 189
    g2 = _j("2026-10-04-fiber-gap-rule-v2-pherc0139-run/result.json")
    assert g2["verdict"] == "KEEP" and g2["checks"]["fallback_reduction"] is False
    assert (g2["real_candidates"]["old"]["fallback"], g2["real_candidates"]["span"]["fallback"]) == (1622, 1088)
    s = _j("2026-10-04-pherc0139-fiber-ct-support-run/result.json")
    assert s["verdict"] == "SUPPORTED" and round(s["auc_F_vs_R"], 3) == 0.760
    assert len(s["per_fiber"]["flagged"]) == 4 and s["reads"]["out_of_bounds"] == 12
    c = _j("2026-10-04-pherc0139-fiber-ct-direction-run/result.json")
    assert c["verdict"] == "SUPPORTED" and round(c["D"], 3) == 0.414 and c["D_swapped_ci95"][0] < 0.1
