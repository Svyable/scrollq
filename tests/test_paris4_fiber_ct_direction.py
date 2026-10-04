import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "artifacts/2026-10-04-paris4-fiber-ct-direction-prereg/spec.json"


def _m():
    s = importlib.util.spec_from_file_location("ctd", ROOT / "scripts/paris4_fiber_ct_direction.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_spec_pinned():
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest() == _m().SPEC_SHA256


def _sheets(axis_zyx: int, period: int = 6, size: int = 25) -> np.ndarray:
    idx = np.indices((size, size, size))[axis_zyx]
    return (np.sin(2 * np.pi * idx / period) > 0).astype(np.uint8) * 200


def test_structure_tensor_recovers_sheet_normal_in_xyz():
    m = _m()
    # Layers stacked along z (array axis 0) -> normal is +-z in (x, y, z).
    n, k = m.sheet_normal(_sheets(0), 1.0, 4.0)
    assert abs(n[2]) > 0.99 and k > 0.5
    # Layers stacked along x (array axis 2) -> normal is +-x.
    n, _ = m.sheet_normal(_sheets(2), 1.0, 4.0)
    assert abs(n[0]) > 0.99


def test_in_plane_tangent_beats_random_and_decision_rules():
    m = _m()
    spec = json.loads(SPEC.read_text())
    spec["decision"]["bootstrap_reps"] = 300
    rng = np.random.default_rng(0)
    fiber = [np.abs(rng.normal(0, 0.1, 8)).clip(0, 1) for _ in range(50)]
    rand = [rng.random(8) for _ in range(50)]
    out = m.decide(fiber, rand, rand, [rng.random(8) for _ in range(50)], spec)
    assert out["verdict"] == "SUPPORTED" and out["D_ci95"][0] > 0.1
    out = m.decide(rand, [rng.random(8) for _ in range(50)], rand, [rng.random(8) for _ in range(50)], spec)
    assert out["verdict"] == "NOT SUPPORTED"
    out = m.decide(fiber, rand, fiber, [rng.random(8) for _ in range(50)], spec)
    assert out["verdict"] == "CONTROL FAILURE"


def test_cube_assembly_across_chunk_borders():
    m = _m()
    c = m.ChunkCache("x", 1, (4, 4, 4), (8, 8, 8))
    full = np.arange(512, dtype=np.uint8).reshape(8, 8, 8)
    for z in range(2):
        for y in range(2):
            for x in range(2):
                c.cache[(z, y, x)] = full[z*4:(z+1)*4, y*4:(y+1)*4, x*4:(x+1)*4]
    assert np.array_equal(c.cube((4, 4, 4), 2), full[2:7, 2:7, 2:7])
    assert c.cube((1, 4, 4), 2) is None  # leaves the volume


def test_sampling_and_tangent():
    m = _m()
    line = np.stack([np.arange(100.0), np.zeros(100), np.zeros(100)], axis=1)
    idx = m.sample_indices(100, 8, 5)
    assert len(idx) == 8 and idx[0] == 5 and idx[-1] == 94
    assert np.allclose(m.tangent(line, 50, 5), [1, 0, 0])
    assert m.sample_indices(9, 8, 5) == []
