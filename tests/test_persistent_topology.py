import json

import numpy as np
import pytest
from PIL import Image

from scrollq import persistent_topology as pt


def _two_plateaus(saddle=0.2):
    """Two high plateaus joined by a one-column weak neck."""
    s = np.full((9, 21), 0.9)
    s[:, 10] = 0.0
    s[4, 10] = saddle
    s[2, 3] = 1.0  # left peak
    s[6, 16] = 0.95  # right peak
    return s


def test_h0_pairs_the_younger_plateau_at_the_saddle():
    s = _two_plateaus()
    valid = s > 0  # the zero column is outside the surface except the neck
    valid[4, 10] = True
    diagrams = pt.persistence(s, valid)
    finite = [p for p in diagrams["h0"] if p["death"] is not None]
    essential = [p for p in diagrams["h0"] if p["death"] is None]
    long = [p for p in finite if p["birth"] - p["death"] > 0.5]
    assert len(essential) == 1 and essential[0]["birth"] == 1.0
    assert len(long) == 1
    assert long[0]["birth"] == pytest.approx(0.95)
    assert long[0]["death"] == pytest.approx(0.2)
    assert divmod(long[0]["saddle_vertex"], 21) == (4, 10)


def test_h1_hole_lives_between_ring_and_centre():
    s = np.full((11, 11), 0.2)
    s[2:9, 2:9] = 0.9  # ring ...
    s[4:7, 4:7] = 0.3  # ... around a weak centre
    diagrams = pt.persistence(s, np.ones_like(s, dtype=bool))
    holes = [p for p in diagrams["h1"] if p["death"] is not None and p["birth"] - p["death"] > 0.5]
    assert len(holes) == 1
    assert holes[0]["birth"] == pytest.approx(0.9)
    assert holes[0]["death"] == pytest.approx(0.3)


def test_genuine_tear_is_an_essential_hole():
    s = np.full((9, 9), 0.8)
    valid = np.ones((9, 9), dtype=bool)
    valid[3:6, 3:6] = False
    diagrams = pt.persistence(s, valid)
    assert [p["death"] for p in diagrams["h1"]] == [None]
    assert diagrams["h1"][0]["birth"] == pytest.approx(0.8)


def test_diagram_distances():
    a = np.array([[1.0, 0.2]])
    assert pt.wasserstein1(a, a) == 0.0
    assert pt.bottleneck(a, a) == 0.0
    # A lone point is matched to the diagonal at half its persistence.
    assert pt.wasserstein1(a, np.empty((0, 2))) == pytest.approx(0.4)
    assert pt.bottleneck(a, np.empty((0, 2))) == pytest.approx(0.4)
    b = np.array([[0.9, 0.2], [0.5, 0.4]])
    assert pt.wasserstein1(a, b) == pytest.approx(0.1 + 0.05)
    assert pt.bottleneck(a, b) == pytest.approx(0.1)


def test_bridge_witness_names_the_weak_neck():
    s = _two_plateaus(saddle=0.1)
    valid = s > 0
    valid[4, 10] = True
    witnesses = pt.bridge_witnesses(pt.persistence(s, valid), valid)
    assert len(witnesses) == 1
    assert witnesses[0]["saddle_rc"] == [4, 10]
    # A strongly supported neck is not a witness.
    s2 = _two_plateaus(saddle=0.85)
    assert pt.bridge_witnesses(pt.persistence(s2, valid), valid) == []


def test_orientation_reversal_leaves_topology_unchanged():
    rng = np.random.default_rng(0)
    s = rng.random((20, 30))
    valid = np.ones_like(s, dtype=bool)
    valid[5:9, 5:12] = False
    d1 = pt.persistence(s, valid)
    d2 = pt.persistence(s[:, ::-1], valid[:, ::-1])
    dist = pt.diagram_distance(d1, d2, 0.0)
    assert all(v == pytest.approx(0.0) for v in dist.values())


def test_planted_edits_touch_only_their_region():
    xyz, valid = pt.synthetic_patch()
    for kind in pt.FAULTS + pt.BENIGN:
        exyz, evalid, faint, truth = pt.plant(kind, xyz, valid, np.random.default_rng(1))
        if kind == "orientation_reversal":
            continue
        changed = (evalid != valid) | np.any(exyz != xyz, axis=-1)
        if faint is not None:
            changed |= faint != 1.0
        if kind.startswith("bridge"):
            # Columns past the strip stay on the next winding, by design.
            first = np.flatnonzero(truth.any(axis=0))[0]
            assert not changed[:, :first].any()
        else:
            assert not (changed & ~truth).any(), kind
        assert changed.any(), kind


def test_benchmark_is_deterministic_and_reports_every_edit():
    first = pt.benchmark(seeds=1)
    second = pt.benchmark(seeds=1)
    assert first == second
    assert set(first["summary"]) == set(pt.FAULTS + pt.BENIGN)
    assert first["summary"]["bridge"]["bridge_witness_rate"] == 1.0
    assert first["summary"]["orientation_reversal"]["bridge_witness_rate"] == 0.0


def _surface(tmp_path, n=12):
    root = tmp_path / "surface"
    root.mkdir()
    rr, cc = np.mgrid[0:n, 0:n]
    for name, arr in (("x.tif", cc * 2.0), ("y.tif", rr * 2.0), ("z.tif", np.full((n, n), 5.0))):
        Image.fromarray(arr.astype(np.float32)).save(root / name)
    return root


def test_cli_measure_binds_inputs_and_is_create_only(tmp_path):
    surface = _surface(tmp_path)
    support = np.full((12, 12), 0.9, dtype=np.float32)
    support[:, 6] = 0.1
    path = tmp_path / "support.npy"
    np.save(path, support)
    out = tmp_path / "topology.json"
    argv = ["measure", "--surface", str(surface), "--support", str(path),
            "--support-source", "synthetic", "--out", str(out)]
    assert pt.main(argv) == 0
    report = json.loads(out.read_text())
    assert report["status"] == "measured"
    assert report["support"]["source"] == "synthetic"
    assert len(report["surface"]["coordinate_sha256"]) == 64
    assert report["bridge_witnesses"][0]["saddle_rc"][1] == 6
    with pytest.raises(SystemExit):
        pt.main(argv)
    bad = tmp_path / "bad.npy"
    np.save(bad, np.zeros((3, 3)))
    with pytest.raises(SystemExit):
        pt.main(["measure", "--surface", str(surface), "--support", str(bad),
                 "--support-source", "x", "--out", str(tmp_path / "o2.json")])


def test_help_needs_no_arguments():
    with pytest.raises(SystemExit) as exc:
        pt.main(["--help"])
    assert exc.value.code == 0
