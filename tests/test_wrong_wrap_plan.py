import json

import numpy as np
import pytest

from scrollq import wrong_wrap_plan as ww


VOLUME_ROOT = (
    "PHerc0139/volumes/"
    "20250728140407-9.362um-1.2m-113keV-masked.zarr"
)
BASE = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
PRED_URL = (
    BASE
    + "/PHerc0139/representations/predictions/surfaces/"
    + "20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr"
)
CT_URL = BASE + "/" + VOLUME_ROOT


def _reference_plan(tmp_path, *, groups=None):
    if groups is None:
        groups = [
            {
                "id": "surface-0001",
                "surface_global_zyx": [48.0, 48.0, 48.0],
                "reference_normal_zyx": [0.0, 0.0, 1.0],
                "wrong_wrap": {
                    "status": "pending-independent-geometry",
                    "global_zyx": None,
                },
            }
        ]
    plan = {
        "schema": "scroliq-sheetness-plan/1",
        "status": "planned",
        "volume_root": VOLUME_ROOT,
        "source_attestation": {
            "algorithm": "zpa-metadata-semantics-v1",
            "state": "PRESENT",
            "metadata_semantics_sha256": "a" * 64,
            "axes": ["z", "y", "x"],
        },
        "zpa_report": {
            "level0_shape_zyx": [96, 96, 96],
        },
        "protocol": {
            "offsets_voxels": [-8.0, -4.0, 4.0, 8.0],
        },
        "groups": groups,
    }
    path = tmp_path / "reference-plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def _freeze(tmp_path, **kw):
    ref = _reference_plan(tmp_path)
    args = {
        "reference_plan_path": ref,
        "prediction_url": PRED_URL,
        "ct_url": CT_URL,
        "model_id": "20260413222639",
        "prediction_binding_url": "https://scrollprize.org/data_browser/PHerc0139",
    }
    args.update(kw)
    return ww.freeze_spec(**args)


class FakeLevel:
    def __init__(self, array, chunks=(32, 32, 32), stored=None):
        self.array = np.asarray(array, dtype=np.uint8)
        self.shape = self.array.shape
        self.chunks = chunks
        self.stored = stored

    def chunk(self, idx):
        idx = tuple(idx)
        if self.stored is not None and idx not in self.stored:
            return None
        slices = tuple(
            slice(i * c, min((i + 1) * c, s))
            for i, c, s in zip(idx, self.chunks, self.shape)
        )
        return self.array[slices]


def _group():
    return {
        "id": "surface-0001",
        "surface_global_zyx": [48.0, 48.0, 48.0],
        "reference_normal_zyx": [0.0, 0.0, 1.0],
    }


def _samplers(pred, ct):
    return ww._NearestSampler(FakeLevel(pred)), ww._NearestSampler(FakeLevel(ct))


def test_freeze_spec_records_geometry_only_contract(tmp_path):
    spec = _freeze(tmp_path)
    assert spec["status"] == "frozen-before-geometry-read"
    assert spec["geometry_source"]["model_id"] == "20260413222639"
    assert spec["geometry_source"]["stored_value_threshold"] == 127
    assert spec["algorithm"]["min_distance_voxels"] == 12
    assert spec["algorithm"]["max_distance_voxels"] == 64
    assert spec["algorithm"]["min_gap_voxels"] == 3
    assert spec["algorithm"]["min_run_voxels"] == 2
    assert spec["algorithm"]["uses_sheetness_response"] is False
    assert spec["algorithm"]["stochastic"] is False
    assert spec["algorithm"]["seed"] is None


def test_freeze_rejects_wrong_scan_prediction_without_network(tmp_path):
    ref = _reference_plan(tmp_path)
    wrong = PRED_URL.replace("20250728140407", "20260413113053")
    with pytest.raises(ww.WrongWrapError, match="does not exactly name"):
        ww.freeze_spec(
            reference_plan_path=ref,
            prediction_url=wrong,
            ct_url=CT_URL,
            model_id="20260413222639",
            prediction_binding_url="https://scrollprize.org/data_browser/PHerc0139",
        )


def test_freeze_rejects_wrong_model_identity(tmp_path):
    ref = _reference_plan(tmp_path)
    with pytest.raises(ww.WrongWrapError, match="does not exactly name"):
        ww.freeze_spec(
            reference_plan_path=ref,
            prediction_url=PRED_URL,
            ct_url=CT_URL,
            model_id="20250701154204",
            prediction_binding_url="https://scrollprize.org/data_browser/PHerc0139",
        )


def test_freeze_requires_wrong_wrap_search_beyond_normal_offsets(tmp_path):
    with pytest.raises(ww.WrongWrapError, match="beyond every frozen normal-offset"):
        _freeze(tmp_path, min_distance_voxels=8)


@pytest.mark.parametrize("threshold", [127.0, True, -1, 255])
def test_freeze_threshold_is_strict_integer_contract(tmp_path, threshold):
    with pytest.raises(ww.WrongWrapError, match="threshold"):
        _freeze(tmp_path, threshold=threshold)


def test_first_run_requires_gap_and_minimum_run():
    hits = np.zeros(64, dtype=bool)
    # A run beginning at distance 12 is connected through the required
    # preceding gap, so it must not be used.
    hits[9:13] = True  # distances 10..13
    hits[19:21] = True  # clean separated run at distances 20..21
    run = ww._first_separated_run(
        hits,
        gap_clear=~hits,
        min_distance=12,
        min_gap=3,
        min_run=2,
    )
    assert run == {
        "start_distance_voxels": 20,
        "end_distance_voxels": 21,
        "midpoint_distance_voxels": 20.5,
    }


def test_nearest_supported_run_wins_and_negative_breaks_tie():
    pred = np.zeros((96, 96, 96), dtype=np.uint8)
    ct = np.ones_like(pred, dtype=np.uint8)

    # Negative normal: d=20,21 -> x=28,27.
    pred[48, 48, 27:29] = 255
    # Positive normal: equally near d=20,21 -> x=68,69.
    pred[48, 48, 68:70] = 255

    ps, cs = _samplers(pred, ct)
    row = ww._propose_group(
        _group(),
        pred_sampler=ps,
        ct_sampler=cs,
        threshold=127,
        min_distance=12,
        max_distance=64,
        min_gap=3,
        min_run=2,
    )
    assert row["status"] == "found"
    assert row["selected_sign"] == -1
    assert row["signed_distance_voxels"] == -20.5
    assert row["global_zyx"] == [48.0, 48.0, 27.5]


def test_ct_mask_cannot_manufacture_geometry_gap():
    pred = np.zeros((96, 96, 96), dtype=np.uint8)
    ct = np.ones_like(pred, dtype=np.uint8)

    # The prediction is continuously present through d=9..13. Masking the
    # three preceding samples must not turn d=12..13 into a separated sheet.
    pred[48, 48, 57:62] = 255
    ct[48, 48, 57:60] = 0

    ps, cs = _samplers(pred, ct)
    row = ww._propose_group(
        _group(),
        pred_sampler=ps,
        ct_sampler=cs,
        threshold=127,
        min_distance=12,
        max_distance=32,
        min_gap=3,
        min_run=2,
    )
    assert row["status"] == "no-independent-competing-sheet-found"


def test_masked_ct_support_can_reject_closer_prediction_run():
    pred = np.zeros((96, 96, 96), dtype=np.uint8)
    ct = np.ones_like(pred, dtype=np.uint8)

    pred[48, 48, 27:29] = 255  # negative d=20..21
    pred[48, 48, 73:75] = 255  # positive d=25..26
    ct[48, 48, 27:29] = 0

    ps, cs = _samplers(pred, ct)
    row = ww._propose_group(
        _group(),
        pred_sampler=ps,
        ct_sampler=cs,
        threshold=127,
        min_distance=12,
        max_distance=64,
        min_gap=3,
        min_run=2,
    )
    assert row["status"] == "found"
    assert row["selected_sign"] == 1
    assert row["signed_distance_voxels"] == 25.5


def test_connected_same_surface_is_not_promoted_to_wrong_wrap():
    pred = np.zeros((96, 96, 96), dtype=np.uint8)
    ct = np.ones_like(pred, dtype=np.uint8)

    # Positive ray remains active through the three-voxel gap immediately
    # before min_distance; no separated run exists later.
    pred[48, 48, 57:62] = 255  # d=9..13 from x=48

    ps, cs = _samplers(pred, ct)
    row = ww._propose_group(
        _group(),
        pred_sampler=ps,
        ct_sampler=cs,
        threshold=127,
        min_distance=12,
        max_distance=32,
        min_gap=3,
        min_run=2,
    )
    assert row["status"] == "no-independent-competing-sheet-found"
    assert row["global_zyx"] is None


def test_missing_candidate_stays_missing():
    pred = np.zeros((96, 96, 96), dtype=np.uint8)
    ct = np.ones_like(pred, dtype=np.uint8)
    ps, cs = _samplers(pred, ct)
    row = ww._propose_group(
        _group(),
        pred_sampler=ps,
        ct_sampler=cs,
        threshold=127,
        min_distance=12,
        max_distance=32,
        min_gap=3,
        min_run=2,
    )
    assert row["status"] == "no-independent-competing-sheet-found"
    assert row["global_zyx"] is None


def test_run_spec_fails_closed_on_prediction_grid_mismatch(tmp_path):
    ref = _reference_plan(tmp_path)
    spec = ww.freeze_spec(
        reference_plan_path=ref,
        prediction_url=PRED_URL,
        ct_url=CT_URL,
        model_id="20260413222639",
        prediction_binding_url="https://scrollprize.org/data_browser/PHerc0139",
    )
    spec_path = tmp_path / "wrong-wrap-spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    arrays = iter([
        np.zeros((95, 96, 96), dtype=np.uint8),
        np.zeros((96, 96, 96), dtype=np.uint8),
    ])

    class Level:
        def __init__(self, url, session):
            arr = next(arrays)
            self.array = arr
            self.shape = arr.shape
            self.chunks = (32, 32, 32)

        def chunk(self, idx):
            return None

    with pytest.raises(ww.WrongWrapError, match="prediction shape"):
        ww.run_spec(
            spec_path=spec_path,
            reference_plan_path=ref,
            level_factory=Level,
            session=object(),
        )


def test_load_spec_rejects_mutated_frozen_numeric_field(tmp_path):
    ref = _reference_plan(tmp_path)
    spec = ww.freeze_spec(
        reference_plan_path=ref,
        prediction_url=PRED_URL,
        ct_url=CT_URL,
        model_id="20260413222639",
        prediction_binding_url="https://scrollprize.org/data_browser/PHerc0139",
    )
    spec["algorithm"]["min_distance_voxels"] = "12"
    path = tmp_path / "bad-spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ww.WrongWrapError, match="min_distance_voxels"):
        ww._load_spec(path)
