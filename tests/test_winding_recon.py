"""bin/winding_recon.py on synthetic inputs with known linkage."""

import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("winding_recon", ROOT / "bin" / "winding_recon.py")
recon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recon)


def _doc(collections):
    return {"vc_pointcollections_json_version": "1",
            "collections": {cid: {"name": cid, "points": pts} for cid, pts in collections.items()}}


def _write(tmp_path):
    # Relative collection 1 and 2 share a location (1 voxel apart); collection 3
    # is isolated; a same-winding chain goes a quarter turn around the axis.
    rel = _doc({
        "1": {"0": {"p": [100, 0, 50], "wind_a": 0}, "1": {"p": [130, 0, 50], "wind_a": 1}},
        "2": {"0": {"p": [101, 0, 50], "wind_a": 5}, "1": {"p": [0, 300, 50], "wind_a": 6}},
        "3": {"0": {"p": [900, 900, 50], "wind_a": 0}, "1": {"p": [950, 900, 50], "wind_a": 2}},
    })
    chain = {str(i): {"p": [100 * math.cos(t), 100 * math.sin(t), 50]}
             for i, t in enumerate([k * math.pi / 40 for k in range(21)])}
    (tmp_path / "relative_windings.json").write_text(json.dumps(rel))
    (tmp_path / "same_windings.json").write_text(json.dumps(_doc({"7": chain})))
    (tmp_path / "umbilicus.json").write_text(json.dumps(
        {"control_points": [{"x": 0, "y": 0, "z": 0}, {"x": 0, "y": 0, "z": 100}]}))


def test_proximity_links_only_close_points_from_different_frames(tmp_path):
    _write(tmp_path)
    rows = recon.load_points(tmp_path)
    prox = recon.proximity(rows, distances=(2.0, 16.0))
    two = prox["2.0"]
    # relative:1 <-> relative:2 (1 voxel), and the chain's first point
    # (100, 0, 50) coincides with relative:1 point 0 and is 1 voxel from relative:2.
    assert two["linked_relative_collections"] == 2
    assert two["linked_same_winding_collections"] == 1
    assert two["frame_pairs"] == 3 and two["components"] == 1 and two["independent_cycles"] == 1
    assert prox["16.0"]["point_pairs"] >= two["point_pairs"]


def test_chain_stats_measure_spacing_and_turns(tmp_path):
    _write(tmp_path)
    rows = recon.load_points(tmp_path)
    umb = recon.load_umbilicus(tmp_path / "umbilicus.json")
    stats = recon.chain_stats(rows, umb)
    assert stats["chains"] == 1
    assert stats["consecutive_abs_dtheta_radians"]["max"] == round(math.pi / 40, 3)
    assert stats["net_turns_per_chain"]["max"] == 0.25
    assert stats["steps_over_half_turn"] == 0
    assert abs(stats["consecutive_spacing_voxels"]["median"] - 2 * 100 * math.sin(math.pi / 80)) < 1e-2
