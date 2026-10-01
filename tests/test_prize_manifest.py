import copy
import json
from pathlib import Path

import pytest

from scrollq import prize_manifest as pm
from scrollq.grand_prize import DEFAULT_MANIFEST, qualify
from scrollq.bucket import load_json_maybe_gz

ART = Path(__file__).resolve().parents[1] / "artifacts"
SNAP = ART / "2026-10-01-prize-targets"          # eligibility snapshot
INDEX = ART / "2026-10-01-bucket-index" / "metadata.min.json.gz"
KW = dict(as_of="2026-10-01", eligibility_source="test",
          eligibility_sha256="e", index_sha256="i")


def _vol(px, kev, surf=("S1",), lasagna=("L1",), fibers=("F1",)):
    data = [{"type": "ome-zarr", "origins": [{"path": "x/", "access_roots": []}]}]
    for m in surf:
        data.append({"type": "surface-prediction-zarr",
                     "origins": [{"path": f"s/{m}/"}],
                     "parameters": {"model_id": m}})
    for m in lasagna:
        data.append({"type": "lasagna",
                     "origins": [{"path": f"A/representations/predictions/"
                                          f"lasagna/{m}-L2/"}],
                     "parameters": {"model_id": m}})
    for m in fibers:  # same type, different path: must not count as lasagna
        data.append({"type": "lasagna",
                     "origins": [{"path": f"A/representations/predictions/"
                                          f"fibers/{m}-L1/"}],
                     "parameters": {"model_id": m}})
    return {"properties": {"pixel_size_um": px, "energy_keV": kev},
            "data": data}


def _index():
    return {"samples": {
        "PHerc0001": {"volumes": {
            "20250101000000": _vol(9.362, 113.0, surf=("S1", "S2"),
                                   lasagna=("L1", "L9")),
            "20260101000000": _vol(2.403, 77.0)}, "segments": {"a": {}}},
        "PHerc0002": {"volumes": {
            "20250202000000": _vol(8.64, 116.0, lasagna=())},
            "segments": {}},
    }}


def _elig():
    return {"grand-prize-2027": [
        {"scroll": "PHerc0001", "volume": "20250101000000"}],
        "first-letters-2027": [
            {"scroll": "PHerc0001", "volume": "20250101000000"},
            {"scroll": "PHerc0002", "volume": "20250202000000"},
            {"scroll": "PHerc0003", "volume": "20250303000000"}]}


def test_derive_picks_latest_predictions_and_ignores_fiber_dirs():
    m = pm.derive_manifest("grand-prize-2027", _elig(), _index(), **KW)
    t = m["targets"][0]
    assert t["surface_prediction"] == "S2" and t["lasagna_prediction"] == "L9"
    assert t["all_lasagna_predictions"] == ["L1", "L9"]  # F1 excluded
    assert t["segments"] == 1 and t["voxel_size_um"] == 9.362
    assert m["required_assets"] == ["surface_prediction",
                                    "lasagna_prediction"]


def test_higher_res_goes_to_the_prize_specific_key():
    gp = pm.derive_manifest("grand-prize-2027", _elig(), _index(), **KW)
    fl = pm.derive_manifest("first-letters-2027", _elig(), _index(), **KW)
    g = gp["targets"][0]["excluded_same_scroll_higher_res"]
    assert [h["volume_id"] for h in g] == ["20260101000000"]
    assert "prohibit" in g[0]["reason"]
    t = fl["targets"][0]
    assert "excluded_same_scroll_higher_res" not in t
    assert [h["volume_id"] for h in t["same_scroll_higher_res_scans"]] == \
        ["20260101000000"]
    assert "confirm with the organizers" in \
        t["same_scroll_higher_res_scans"][0]["reason"]


def test_missing_eligible_volume_is_reported_not_dropped_silently():
    fl = pm.derive_manifest("first-letters-2027", _elig(), _index(), **KW)
    assert [p["scroll"] for p in fl["problems"]] == ["PHerc0003"]
    assert len(fl["targets"]) == 2


def test_unknown_prize_rejected():
    with pytest.raises(ValueError, match="unknown prize"):
        pm.derive_manifest("nope", _elig(), _index(), **KW)


def test_first_letters_does_not_demand_lasagna_but_grand_prize_does():
    volumes = [{"root": f"x/{s}/volumes/{v}-masked.zarr", "ok": True,
                "score": 50.0}
               for s, v in (("PHerc0001", "20250101000000"),
                            ("PHerc0002", "20250202000000"))]
    fl = qualify(volumes, pm.derive_manifest(
        "first-letters-2027", _elig(), _index(), **KW))
    rows = {r["scroll"]: r for r in fl["targets"]}
    # PHerc0002 has no lasagna, but First Letters only requires the surface
    assert rows["PHerc0002"]["qualification"] != "missing-geometry-prior"
    assert fl["method"]["required_assets"] == ["surface_prediction"]
    assert fl["prize_label"] == "2027 First Letters"
    assert "First Letters success" in fl["method"]["warning"]
    gp_like = copy.deepcopy(pm.derive_manifest(
        "first-letters-2027", _elig(), _index(), **KW))
    gp_like["required_assets"] = ["surface_prediction", "lasagna_prediction"]
    gp = qualify(volumes, gp_like)
    assert {r["scroll"]: r["qualification"] for r in gp["targets"]}[
        "PHerc0002"] == "missing-geometry-prior"


def test_compare_targets_flags_each_kind_of_drift():
    ref = pm.derive_manifest("grand-prize-2027", _elig(), _index(), **KW)
    same = copy.deepcopy(ref)
    assert pm.compare_targets(ref, same) == []
    drift = copy.deepcopy(ref)
    drift["targets"][0]["segments"] = 7
    drift["targets"][0]["energy_kev"] = 99
    drift["targets"][0].pop("excluded_same_scroll_higher_res")
    drift["targets"][0]["surface_prediction"] = "NEW"
    out = pm.compare_targets(drift, ref)
    joined = " | ".join(out)
    assert "segments 7 != 1" in joined and "energy_kev" in joined
    assert "higher-resolution exclusions" in joined
    assert "surface_prediction 'NEW' not among" in joined
    extra = copy.deepcopy(ref)
    extra["targets"].append({"scroll": "PHerc0009", "volume_id": "x"})
    assert any("missing from reference" in l or "not eligible" in l
               for l in pm.compare_targets(ref, extra) +
               pm.compare_targets(extra, ref))


def test_builtin_grand_prize_manifest_matches_pinned_official_sources():
    assert SNAP.exists() and INDEX.exists(), "pinned snapshots must be committed"
    """Regression for the verified claim in artifacts/2026-10-01-prize-targets.

    The hand-copied DEFAULT_MANIFEST agrees with the pinned villa eligibility
    list and bucket index on volume id, voxel size, energy, segment count,
    released predictions, and prohibited higher-resolution scans.
    """
    elig, esha = load_json_maybe_gz(str(SNAP / "prizeEligibility.json"))
    index, isha = load_json_maybe_gz(str(INDEX))
    derived = pm.derive_manifest("grand-prize-2027", elig, index,
                                 as_of="2026-10-01", eligibility_source="snap",
                                 eligibility_sha256=esha, index_sha256=isha)
    assert derived["problems"] == []
    assert len(derived["targets"]) == 13
    assert pm.compare_targets(DEFAULT_MANIFEST, derived) == []


def test_first_letters_snapshot_derivation_is_complete_and_flags_0846a():
    assert SNAP.exists() and INDEX.exists(), "pinned snapshots must be committed"
    elig, esha = load_json_maybe_gz(str(SNAP / "prizeEligibility.json"))
    index, isha = load_json_maybe_gz(str(INDEX))
    fl = pm.derive_manifest("first-letters-2027", elig, index,
                            as_of="2026-10-01", eligibility_source="snap",
                            eligibility_sha256=esha, index_sha256=isha)
    assert fl["problems"] == [] and len(fl["targets"]) == 22
    by = {t["scroll"]: t for t in fl["targets"]}
    flagged = sorted(s for s, t in by.items()
                     if t.get("same_scroll_higher_res_scans"))
    assert flagged == ["PHerc0846A", "PHerc1203"]
    assert all(t["surface_prediction"] for t in fl["targets"])


def test_cli_roundtrip(tmp_path, capsys):
    e, i = tmp_path / "e.json", tmp_path / "i.json"
    e.write_text(json.dumps(_elig()))
    i.write_text(json.dumps(_index()))
    out = tmp_path / "m.json"
    rc = pm.main(["--eligibility", str(e), "--index", str(i), "--prize",
                  "first-letters-2027", "--as-of", "2026-10-01",
                  "--out", str(out)])
    assert rc == 0
    m = json.loads(out.read_text())
    assert m["provenance"]["eligibility_sha256"] and len(m["targets"]) == 2
    assert pm.main(["--eligibility", str(e), "--index", str(i), "--prize",
                    "first-letters-2027", "--as-of", "2026-10-01", "--out",
                    str(out), "--compare-builtin"]) == 2
