import json

import numpy as np
import pytest

from scrollq.prediction_support import (
    PredictionSupportError,
    audit_arrays,
    gate_seeds,
    main,
    positive_control,
    read_box,
    supported_prediction,
)


class FakeLevel:
    def __init__(self, array, chunks, stored=None):
        self.array, self.shape, self.chunks = array, array.shape, chunks
        self.stored = stored

    def chunk(self, idx):
        if self.stored is not None and tuple(idx) not in self.stored:
            return None
        sl = tuple(slice(i * c, min((i + 1) * c, s))
                   for i, c, s in zip(idx, self.chunks, self.shape))
        return self.array[sl]


def _pair(shape=(32, 32, 32)):
    return np.zeros(shape, np.uint8), np.zeros(shape, np.uint8)


def test_positive_control_passes():
    ctl = positive_control()
    assert ctl["passed"], ctl


def test_counts_split_supported_and_ct_zero():
    pred, ct = _pair()
    pred[5] = 200
    pred[6] = 127  # threshold is strict
    ct[:, :, :16] = 1
    r = audit_arrays(pred, ct, chunk=(8, 8, 8))
    c = r["counts"]
    assert c["pred_positive"] == 32 * 32
    assert c["pred_positive_ct_supported"] == 32 * 16
    assert c["pred_positive_ct_zero"] == 32 * 16
    assert r["status"] == "requires_support_filter"
    assert r["raw_prediction_seed_safe"] is False
    assert r["fractions"]["phantom"] == 0.5


def test_fully_supported_prediction_is_seed_safe():
    pred, ct = _pair()
    pred[5] = 255
    ct[:] = 7
    r = audit_arrays(pred, ct, chunk=(8, 8, 8))
    assert r["status"] == "seed_safe"
    assert r["phantom_distance_to_ct_support"] is None


def test_no_positives_is_unverified_not_clean():
    pred, ct = _pair()
    ct[:] = 50
    r = audit_arrays(pred, ct, chunk=(8, 8, 8))
    assert r["status"] == "unverified"
    assert r["fractions"]["phantom"] is None


def test_shape_mismatch_fails_closed():
    with pytest.raises(PredictionSupportError, match="same voxel grid"):
        audit_arrays(np.zeros((4, 4, 4), np.uint8),
                     np.zeros((4, 4, 5), np.uint8))


def test_no_support_anywhere_has_no_distance():
    pred, ct = _pair()
    pred[3] = 255
    r = audit_arrays(pred, ct, chunk=(8, 8, 8))
    assert r["phantom_distance_to_ct_support"] == {
        "unit": "voxel", "no_ct_support_in_region": True}
    assert r["chunk_classes"]["classes"]["beyond"]["chunks"] == 16


def test_partial_region_neighbourhood_is_unresolved_not_beyond():
    # Region is the top half of a 64^3 volume; the halo chunk's support
    # could lie in the unaudited half, so it must not be called beyond.
    pred, ct = _pair((32, 64, 64))
    pred[28] = 255
    r = audit_arrays(pred, ct, chunk=(16, 16, 16), volume_shape=(64, 64, 64))
    cls = r["chunk_classes"]["classes"]
    assert cls["beyond"]["chunks"] == 0
    assert cls["unresolved"]["chunks"] == 16


def test_clipped_chunk_without_support_is_unresolved():
    pred, ct = _pair((10, 16, 16))
    pred[2] = 255
    r = audit_arrays(pred, ct, chunk=(16, 16, 16), volume_shape=(16, 16, 16))
    assert r["chunk_classes"]["classes"]["unresolved"]["chunks"] == 1


def test_origin_places_region_on_global_chunk_grid():
    pred, ct = _pair((16, 16, 16))
    pred[:] = 255
    ct[:] = 1
    r = audit_arrays(pred, ct, chunk=(8, 8, 8), origin=(4, 0, 0),
                     volume_shape=(24, 16, 16))
    # z 4..20 touches global chunks z=0,1,2; the outer two are clipped
    assert r["chunk_classes"]["chunks_with_positives"] == 3 * 2 * 2


def test_blend_boundary_enrichment_flags_chunk_margin():
    pred, ct = _pair()
    ct[:, :, :] = 0
    ct[0:2] = 1
    # phantoms only on the chunk-face planes z = 7 and 8
    pred[7] = pred[8] = 255
    r = audit_arrays(pred, ct, chunk=(8, 8, 8), blend_margin=1)
    b = r["blend_boundary"]
    assert b["observed_frac"] == 1.0
    assert b["enrichment"] > 1.0


def test_supported_prediction_zeroes_ct_zero_voxels():
    pred, ct = _pair()
    pred[:] = 255
    ct[:16] = 3
    f = supported_prediction(pred, ct)
    assert f[:16].min() == 255 and f[16:].max() == 0
    r = audit_arrays(f, ct, chunk=(8, 8, 8))
    assert r["status"] == "seed_safe"


def test_gate_seeds_rejects_ct_zero_and_flags_outside():
    ct = np.zeros((8, 8, 8), np.uint8)
    ct[0] = 9
    g = gate_seeds([[10, 0, 0], [11, 0, 0], [99, 0, 0]], ct, origin=(10, 0, 0))
    assert [s["status"] for s in g["seeds"]] == [
        "accepted", "rejected_ct_zero", "unverified"]
    assert g["counts"] == {"accepted": 1, "rejected_ct_zero": 1,
                           "unverified": 1}


def test_read_box_treats_unstored_chunks_as_zero():
    arr = np.full((16, 16, 16), 5, np.uint8)
    lvl = FakeLevel(arr, (8, 8, 8), stored={(0, 0, 0), (1, 1, 1)})
    out = read_box(lvl, ((4, 12), (4, 12), (4, 12)))
    assert out.shape == (8, 8, 8)
    assert out[:4, :4, :4].min() == 5
    assert out[4:, 4:, 4:].min() == 5
    assert out[:4, 4:, :4].max() == 0


def test_cli_local_round_trip(tmp_path):
    pred, ct = _pair()
    pred[20] = 255
    ct[:12] = 1
    np.save(tmp_path / "p.npy", pred)
    np.save(tmp_path / "c.npy", ct)
    (tmp_path / "seeds.json").write_text(json.dumps([[5, 0, 0], [20, 0, 0]]))
    out = tmp_path / "r.json"
    rc = main(["--pred", str(tmp_path / "p.npy"), "--ct",
               str(tmp_path / "c.npy"), "--chunk", "8,8,8",
               "--seeds", str(tmp_path / "seeds.json"),
               "--write-filtered", str(tmp_path / "f.npy"),
               "--out", str(out)])
    assert rc == 0
    r = json.loads(out.read_text())
    assert r["status"] == "requires_support_filter"
    assert r["chunk_classes"]["classes"]["halo"]["chunks"] == 16
    assert r["seed_gate"]["counts"]["rejected_ct_zero"] == 1
    assert len(r["sources"]["prediction"]["sha256"]) == 64
    assert np.load(tmp_path / "f.npy").max() == 0
    assert main(["--pred", str(tmp_path / "p.npy"), "--ct",
                 str(tmp_path / "c.npy"), "--strict"]) == 2


def test_cli_self_test():
    assert main(["--self-test"]) == 0
