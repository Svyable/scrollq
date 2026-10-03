"""bin/winding_attach.py on a synthetic Archimedean spiral with known windings."""

import importlib.util
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("winding_attach", ROOT / "bin" / "winding_attach.py")
wa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa)

R0, PITCH = 200.0, 40.0


class Axis:
    """Umbilicus along z through the origin; returns (y, x)."""

    def __call__(self, z):
        return np.zeros((np.asarray(z).size, 2))


def spiral(t, z):
    """Point at turn t (sense +1: angle grows with t; winding floor(t))."""
    r = R0 + PITCH * t
    return np.array([r * math.cos(2 * math.pi * t), r * math.sin(2 * math.pi * t), z])


def patch(t0, t1, z0=0.0, z1=100.0, cols=None, rows=11):
    cols = cols or int((t1 - t0) * 72) + 1
    ts = np.linspace(t0, t1, cols)
    zs = np.linspace(z0, z1, rows)
    xyz = np.stack([np.stack([spiral(t, z) for t in ts]) for z in zs])
    return xyz, np.ones(xyz.shape[:2], dtype=bool)


def make_points(specs):
    """specs: (frame, point_id, t, z, offset) -> point dict, wind_a = floor(t) + offset."""
    pts = {}
    for frame, pid, t, z, off in specs:
        key = f"{frame}/{pid}"
        pts[key] = {"key": key, "frame": frame, "role": "absolute" if frame == "absolute" else "relative",
                    "point_id": pid, "xyz": spiral(t, z), "wind_a": math.floor(t) + off}
    return pts


PATCHES = {"p1/": (0.2, 1.5), "p2/": (1.2, 2.6), "p3/": (2.3, 3.4), "p4/": (0.9, 2.4)}
SPECS = [
    ("absolute", "0", 0.4, 50, 0), ("absolute", "1", 1.3, 40, 0), ("absolute", "2", 2.45, 60, 0),
    ("absolute", "3", 3.1, 30, 0), ("absolute", "4", 1.02, 70, 0),
    ("relative:a", "0", 0.7, 50, 5), ("relative:a", "1", 1.4, 20, 5), ("relative:a", "2", 2.1, 80, 5),
    ("relative:b", "0", 1.25, 50, -3), ("relative:b", "1", 2.35, 50, -3), ("relative:b", "2", 3.3, 50, -3),
    ("relative:c", "0", 1.8, 30, 11), ("relative:c", "1", 2.5, 30, 11),
]


def attachments_for(points):
    out = []
    for name, (t0, t1) in PATCHES.items():
        xyz, valid = patch(t0, t1)
        out += wa.attach_patch(name, xyz, valid, list(points.values()), Axis())["attachments"]
    return out


def test_unwrap_is_continuous_across_the_branch_cut():
    xyz, valid = patch(0.6, 1.6)
    un = wa.unwrap_patch(xyz, valid, Axis())
    phi = un["phi"][0]
    assert un["pieces"] == 1 and un["excluded"] == {"large_angular_step": 0, "encircles_axis": 0}
    assert np.all(np.diff(phi) > 0)
    assert abs((phi[-1] - phi[0]) - 2 * math.pi) < 1e-9


def test_unwrap_excludes_a_piece_that_encircles_the_axis():
    # A flat sheet around the axis with a hole at the axis: any loop around
    # the hole gains 2*pi, so the unwrap is path-dependent.
    g = np.linspace(-100, 100, 21)
    xs, ys = np.meshgrid(g, g)
    hole = np.hypot(xs, ys) < 30
    sheet = np.stack([xs + 500, ys + 500, np.full_like(xs, 50)], axis=-1)
    sheet[hole] = -1
    xyz, valid = wa.load_tifxyz(sheet[..., 0], sheet[..., 1], sheet[..., 2])
    assert (valid == ~hole).all()

    class Shifted:
        def __call__(self, z):
            return np.full((np.asarray(z).size, 2), 500.0)

    un = wa.unwrap_patch(xyz, valid, Shifted())
    assert un["excluded"]["encircles_axis"] == 1 and un["pieces"] == 0
    assert (un["piece"] == -1).all()


def test_attach_point_measures_distance_to_the_surface():
    xyz, valid = patch(0.2, 0.8)
    p = spiral(0.5, 50)
    radial = p[:2] / np.linalg.norm(p[:2])
    off = p + np.array([*radial * 5.0, 0.0])
    dist, _ = wa.attach_point(off, xyz, valid)
    assert abs(dist - 5.0) < 0.5
    assert wa.attach_point(spiral(1.5, 50), xyz, valid)[0] > 20  # next winding out


def test_correct_annotations_are_consistent_and_the_control_detects_errors():
    points = make_points(SPECS)
    atts = attachments_for(points)
    assert len({a["point"] for a in atts}) == len(points)
    result = wa.analyse(atts, points, control_trials=50)
    assert result["primary"] == {"sense": 1, "cut_degrees": 0, "attach_distance_voxels": wa.ATTACH_DISTANCE}
    s = result["summary"]
    assert s["residual_abs_ge_2"] == 0 and s["residual_abs_1"] == 0
    assert s["relative_frames_tied_to_absolute"] == 3 and s["components"] == 1
    assert s["redundant_constraints"] > 0
    assert result["control"]["trials"] > 0
    assert result["control"]["detection_rate"] >= wa.CONTROL_MIN_DETECTION
    assert result["decision"]["verdict"] == "CONSISTENT"
    assert result["review_queue"] == []


def test_a_misnumbered_annotation_lands_in_the_review_queue():
    specs = [s if s[:2] != ("relative:b", "1") else ("relative:b", "1", 2.35, 50, 0) for s in SPECS]
    points = make_points(specs)
    result = wa.analyse(attachments_for(points), points, control_trials=20)
    assert result["decision"]["verdict"] in ("INCONSISTENT", "UNVERIFIED")
    assert result["summary"]["residual_abs_ge_2"] >= 1
    flagged = {(r["frame"], r["point_id"]) for r in result["review_queue"]}
    assert ("relative:b", "1") in flagged


def test_wrong_sense_is_not_chosen_and_both_senses_are_reported():
    points = make_points(SPECS)
    table, best = wa.choose_sense_and_cut(attachments_for(points), points)
    assert len(table) == len(wa.SENSES) * len(wa.CUT_DEGREES)
    assert best["sense"] == 1 and best["nonzero"] == 0
    assert min(t["nonzero"] for t in table if t["sense"] == -1) > 0


def test_no_redundancy_is_unverified_not_consistent():
    points = make_points([("absolute", "0", 0.4, 50, 0)])
    result = wa.analyse(attachments_for(points), points, control_trials=10)
    assert result["summary"]["redundant_constraints"] <= 0
    assert result["decision"]["verdict"] == "UNVERIFIED"


def test_run_end_to_end_with_fake_fetch(tmp_path):
    import io
    import json

    import tifffile

    points = make_points(SPECS)
    abs_doc = {"collections": {"abs": {"points": {
        p["point_id"]: {"p": p["xyz"].tolist(), "wind_a": p["wind_a"]}
        for p in points.values() if p["frame"] == "absolute"}}}}
    rel = {}
    for p in points.values():
        if p["frame"] != "absolute":
            cid = p["frame"].split(":")[1]
            rel.setdefault(cid, {"points": {}})["points"][p["point_id"]] = {"p": p["xyz"].tolist(), "wind_a": p["wind_a"]}
    (tmp_path / "abs_winding.json").write_text(json.dumps(abs_doc))
    (tmp_path / "relative_windings.json").write_text(json.dumps({"collections": rel}))
    (tmp_path / "umbilicus.json").write_text(json.dumps(
        {"control_points": [{"x": 0, "y": 0, "z": 0}, {"x": 0, "y": 0, "z": 100}]}))
    # Shift everything into positive space: x/y of the spiral are negative
    # on half the turn, which load_tifxyz would read as holes.
    shift = np.array([1000.0, 1000.0, 0.0])
    for name in ("abs_winding.json", "relative_windings.json"):
        doc = json.loads((tmp_path / name).read_text())
        for coll in doc["collections"].values():
            for pt in coll["points"].values():
                pt["p"] = (np.asarray(pt["p"]) + shift).tolist()
        (tmp_path / name).write_text(json.dumps(doc))
    (tmp_path / "umbilicus.json").write_text(json.dumps(
        {"control_points": [{"x": 1000, "y": 1000, "z": 0}, {"x": 1000, "y": 1000, "z": 100}]}))
    blobs = {}
    for name, (t0, t1) in PATCHES.items():
        xyz, _ = patch(t0, t1)
        xyz = xyz + shift
        lo, hi = xyz.reshape(-1, 3).min(axis=0), xyz.reshape(-1, 3).max(axis=0)
        blobs[f"{name}meta.json"] = json.dumps({"bbox": [lo.tolist(), hi.tolist()]}).encode()
        for i, axis in enumerate("xyz"):
            buf = io.BytesIO()
            tifffile.imwrite(buf, xyz[..., i].astype(np.float32))
            blobs[f"{name}{axis}.tif"] = buf.getvalue()
    blobs["gone/meta.json"] = json.dumps({"bbox": [[1000, 1000, 0], [1400, 1400, 100]]}).encode()

    def fetch(url):
        return blobs[url.split("/base/", 1)[1]]

    listing = "".join(f'<a href="{n}">{n}</a>' for n in list(PATCHES) + ["gone/"])
    result = wa.run(tmp_path, listing, "https://h/base", workers=2, fetch=fetch, control_trials=20)
    assert result["inputs"]["patch_read_errors"] == 1  # gone/ has a bbox but no grids
    assert result["inputs"]["points_attached_primary"] == len(points)
    assert result["decision"]["verdict"] == "CONSISTENT"
