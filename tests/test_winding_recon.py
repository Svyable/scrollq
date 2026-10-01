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


spec2 = importlib.util.spec_from_file_location("winding_patch_index", ROOT / "bin" / "winding_patch_index.py")
pidx = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(pidx)


def test_patch_entries_and_bbox_parsing():
    html = '<a href="../">..</a><a href="p1/">p1/</a><a href="p2/">p2/</a><a href="x.txt">x</a><a href="p1/">p1/</a>'
    assert pidx.patch_entries(html) == ["p1/", "p2/"]
    assert pidx.parse_bbox({"bbox": [[10, 0, 5], [0, 20, 1]]}) == [[0, 0, 1], [10, 20, 5]]
    assert pidx.parse_bbox({"bbox": [[0, 0], [1, 1]]}) is None
    assert pidx.parse_bbox({"bbox": [[0, 0, float("nan")], [1, 1, 1]]}) is None
    assert pidx.parse_bbox([]) is None


def test_fetch_index_records_errors_and_missing_bbox():
    def fake(url):
        if "bad/" in url:
            raise OSError("boom")
        if "nobox/" in url:
            return {"format": "tifxyz"}
        return {"bbox": [[0, 0, 0], [1, 1, 1]]}

    index = pidx.fetch_index("https://h/x", ["ok/", "bad/", "nobox/"], workers=2, fetch=fake)
    assert list(index["bbox"]) == ["ok/"]
    assert index["no_bbox"] == ["nobox/"]
    assert "boom" in index["errors"]["bad/"]


def test_reach_links_frames_through_a_shared_patch_and_counts_cycles():
    rows = [
        {"role": "relative", "frame": "relative:1", "xyz": [5, 5, 5]},
        {"role": "relative", "frame": "relative:2", "xyz": [6, 5, 5]},
        {"role": "same_winding", "frame": "same_winding:9", "xyz": [7, 5, 5]},
        {"role": "absolute", "frame": "absolute", "xyz": [500, 500, 500]},
    ]
    bboxes = {"a/": [[0, 0, 0], [10, 10, 10]]}
    r = pidx.reach(rows, bboxes, margin=0)
    assert r["points_inside_a_bbox"] == 3
    assert r["by_role"]["absolute"]["inside_a_bbox"] == 0
    g = r["frame_graph"]
    assert g["frames_linked"] == 3 and g["edges"] == 3 and g["components"] == 1 and g["independent_cycles"] == 1
    assert pidx.reach(rows, {}, margin=0)["points_inside_a_bbox"] == 0


def test_patches_touching_and_size_sample():
    rows = [{"role": "relative", "frame": "relative:1", "xyz": [5, 5, 5]},
            {"role": "same_winding", "frame": "same_winding:2", "xyz": [50, 50, 50]}]
    bboxes = {"a/": [[0, 0, 0], [10, 10, 10]], "b/": [[45, 45, 45], [55, 55, 55]]}
    assert pidx.patches_touching(rows, bboxes, margin=0) == ["a/"]
    sizes = {"x.tif": 100, "y.tif": 100, "z.tif": 100, "meta.json": 10}
    est = pidx.size_sample("https://h", ["a/", "b/", "c/", "d/"], n=2,
                           head=lambda url: sizes[url.rsplit("/", 1)[1]])
    assert est["sampled"] == 2 and est["complete_samples"] == 2
    assert est["mean_bytes_per_patch"] == 310
    assert est["estimated_total_gb"] == round(310 * 4 / 1e9, 2)
