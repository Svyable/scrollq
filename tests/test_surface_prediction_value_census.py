import importlib.util
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/surface_prediction_value_census.py"


def _module():
    spec = importlib.util.spec_from_file_location("surface_prediction_value_census", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeLevel:
    shape = (4, 4, 4)
    chunks = (2, 2, 2)

    def __init__(self, chunks):
        self._chunks = chunks

    def chunk(self, idx):
        return self._chunks.get(idx)


def _cands():
    return [(z, y, x) for z in range(2) for y in range(2) for x in range(2)]


def test_binary_array_is_reported_binary():
    m = _module()
    arr = np.zeros((2, 2, 2), dtype=np.uint8)
    arr[0, 0, 0] = 255
    r = m.census(_FakeLevel({(0, 0, 0): arr, (1, 1, 1): arr}), _cands(), 8)
    assert r["verdict"] == "binary"
    assert r["distinct_nonzero_values"] == 1
    assert r["nonzero_histogram"] == {"255": 2}
    assert r["chunks_inspected"] == 2
    assert r["unstored_candidates_skipped"] == 6


def test_positive_control_graded_array_is_not_called_binary():
    m = _module()
    arr = np.array([[[0, 40], [128, 255]], [[0, 0], [7, 0]]], dtype=np.uint8)
    r = m.census(_FakeLevel({(0, 0, 0): arr}), _cands(), 8)
    assert r["verdict"] == "graded"
    assert r["distinct_nonzero_values"] == 4


def test_inspecting_nothing_is_unverified_not_binary():
    m = _module()
    zeros = np.zeros((2, 2, 2), dtype=np.uint8)
    r = m.census(_FakeLevel({(0, 0, 0): zeros}), _cands(), 8)
    assert r["verdict"] == "unverified"
    assert r["chunks_inspected"] == 0
    assert r["all_zero_chunks_skipped"] == 1
    assert r["unstored_candidates_skipped"] == 7


def test_max_chunks_bounds_the_sample():
    m = _module()
    arr = np.full((2, 2, 2), 255, dtype=np.uint8)
    level = _FakeLevel({idx: arr for idx in _cands()})
    r = m.census(level, _cands(), 3)
    assert r["chunks_inspected"] == 3


def test_output_is_create_only(tmp_path):
    m = _module()
    out = tmp_path / "result.json"
    out.write_text("{}", encoding="utf-8")
    assert m.main(["--url", "http://invalid.example/0", "--seed", "1", "--out", str(out)]) == 2
    assert out.read_text(encoding="utf-8") == "{}"
