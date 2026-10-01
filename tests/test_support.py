import numpy as np
import pytest

from scrollq import support
from scrollq.support import (
    SupportError,
    _bootstrap_ci,
    _candidates,
    _measure,
    support_row,
    target_urls,
)


class FakeLevel:
    """In-memory stand-in for ZarrV2Level; chunks absent from `data` are unstored."""

    def __init__(self, array, chunks, stored=None):
        self.array = array
        self.shape = array.shape
        self.chunks = chunks
        self.stored = stored

    def chunk(self, idx):
        if self.stored is not None and tuple(idx) not in self.stored:
            return None
        sl = tuple(slice(i * c, min((i + 1) * c, s))
                   for i, c, s in zip(idx, self.chunks, self.shape))
        return self.array[sl]


def _pair(shape=(384, 384, 384)):
    pred = np.zeros(shape, dtype=np.uint8)
    ct = np.zeros(shape, dtype=np.uint8)
    return pred, ct


def test_phantom_counts_positives_on_zero_ct():
    pred, ct = _pair()
    # Prediction chunk (1,1,1) spans 192..384; its nested CT chunk is (2,2,2),
    # i.e. voxels 256..384.
    pred[256:266, 256:384, 256:384] = 255  # 10 planes of positives
    ct[256:262, 256:384, 256:384] = 90     # CT supports 6 of those planes
    r = _measure(FakeLevel(pred, (192,) * 3), FakeLevel(ct, (128,) * 3),
                 (1, 1, 1), 127)
    assert r["positives"] == 10 * 128 * 128
    assert r["phantom"] == 4 * 128 * 128


def test_threshold_is_strict():
    pred, ct = _pair()
    pred[0:128, 0:128, 0:128] = 127
    r = _measure(FakeLevel(pred, (192,) * 3), FakeLevel(ct, (128,) * 3),
                 (0, 0, 0), 127)
    assert r["positives"] == 0


def test_absent_ct_chunk_is_all_phantom():
    pred, ct = _pair()
    pred[0:128, 0:128, 0:128] = 200
    ct[:] = 50
    r = _measure(FakeLevel(pred, (192,) * 3),
                 FakeLevel(ct, (128,) * 3, stored=set()), (0, 0, 0), 127)
    assert r["phantom"] == r["positives"] == 128 ** 3


def test_absent_prediction_chunk_has_no_positives():
    pred, ct = _pair()
    pred[:] = 255
    r = _measure(FakeLevel(pred, (192,) * 3, stored=set()),
                 FakeLevel(ct, (128,) * 3), (0, 0, 0), 127)
    assert r == {"p": (0, 0, 0), "positives": 0, "phantom": 0}


def test_nested_ct_chunk_never_straddles_prediction_chunks():
    for p in range(8):
        c = (192 * p + 127) // 128
        lo = 128 * c
        assert 192 * p <= lo and lo + 128 <= 192 * (p + 1)


def test_candidates_are_deterministic_and_spread_per_dimension():
    a = _candidates([73, 41, 41], 12, seed=0)
    assert a == _candidates([73, 41, 41], 12, seed=0)
    assert a != _candidates([73, 41, 41], 12, seed=1)
    assert len(a) == 12 ** 3
    assert {c[0] for c in a} >= {0, 72} and {c[2] for c in a} >= {0, 40}


def test_bootstrap_ci_brackets_pooled_estimate():
    samples = [{"positives": 100, "phantom": k} for k in (10, 20, 30, 40, 50)]
    lo, hi = _bootstrap_ci(samples, seed=0)
    assert lo <= 1 - 150 / 500 <= hi


def test_shape_mismatch_fails_closed(monkeypatch):
    shapes = iter([(10, 10, 10), (20, 20, 20)])

    class Level:
        def __init__(self, url, session):
            self.shape = next(shapes)
            self.chunks = (192, 192, 192)

    monkeypatch.setattr(support, "ZarrV2Level", Level)
    with pytest.raises(SupportError, match="not the same voxel grid"):
        support.measure_support("p", "c")


def test_wrong_scan_ct_name_is_rejected_without_network(monkeypatch):
    monkeypatch.setattr(support, "measure_support",
                        lambda *a, **k: pytest.fail("must not measure"))
    target = {"scroll": "PHerc0846A", "volume_id": "20250728152254",
              "surface_prediction": "20260413222639"}
    row = support_row(target, "20260319102732-2.403um-0.2m-77keV-masked.zarr")
    assert row["usable_for_qualification"] is False
    assert row["volume_match"] == "mismatch"


def test_urls_name_the_prediction_made_on_the_exact_scan():
    pred, ct = target_urls("PHerc0846A", "20250728152254", "20260413222639",
                           "20250728152254-9.362um-1.2m-113keV-masked.zarr")
    assert "/PHerc0846A/representations/predictions/surfaces/20250728152254-" in pred
    assert pred.endswith("-m7-L0-th0.2.zarr")
    assert ct.endswith("/PHerc0846A/volumes/20250728152254-9.362um-1.2m-113keV-masked.zarr")


def test_external_survey_on_other_scan_is_excluded():
    from scrollq.support import normalize_external

    target = {"scroll": "PHerc0846A", "volume_id": "20250728152254"}
    base = "https://x/PHerc0846A"
    other = {
        "ct": f"{base}/volumes/20260319102732-2.403um-masked.zarr",
        "preds": f"{base}/representations/predictions/surfaces/"
                 "20260319102732-surface-20260413222639-surface-m7-L2-th0.2.zarr",
        "sampled_support_frac": 0.418,
    }
    row = normalize_external(target, other, "survey.json", "abc")
    assert row["usable_for_qualification"] is False
    assert row["volume_match"] == "mismatch"

    exact = {
        "ct": f"{base}/volumes/20250728152254-9.362um-masked.zarr",
        "preds": f"{base}/representations/predictions/surfaces/"
                 "20250728152254-surface-20260413222639-surface-m7-L0-th0.2.zarr",
        "sampled_support_frac": 0.6,
    }
    assert normalize_external(target, exact, "s", "a")["volume_match"] == "exact"
    assert normalize_external(target, {}, "s", "a")["volume_match"] == "unverified"


def test_native_rows_feed_the_qualifier_sensitivity_analysis():
    from scrollq.grand_prize import FIRST_LETTERS_MANIFEST, qualify

    target = next(t for t in FIRST_LETTERS_MANIFEST["targets"]
                  if t["scroll"] == "PHerc0846A")
    ct_name = "20250728152254-9.362um-1.2m-113keV-masked.zarr"
    _, ct_url = target_urls("PHerc0846A", target["volume_id"],
                            target["surface_prediction"], ct_name)
    native = {"rows": [{
        "scroll": "PHerc0846A",
        "eligible_volume_id": target["volume_id"],
        "survey_ct": ct_url,
        "volume_match": "exact",
        "usable_for_qualification": True,
        "sampled_support_frac": 0.6,
    }]}
    volumes = [{
        "root": f"x/PHerc0846A/volumes/{ct_name}", "ok": True, "score": 64.6,
    }]
    result = qualify(volumes, FIRST_LETTERS_MANIFEST, native)
    row = next(r for r in result["targets"] if r["scroll"] == "PHerc0846A")
    assert row["surface_support_frac"] == 0.6
    assert result["surface_support_analysis"]["comparable_targets"] == ["PHerc0846A"]
