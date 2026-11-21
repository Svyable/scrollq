import io

import numpy as np
import pytest

from scrollq.e8_codec import BOOK, H8, decode, encode, fit, nearest
from scrollq.e8_experiment import controls, synthetic_fixture, validate_fixture


def test_root_geometry_and_orthogonal_transform():
    assert BOOK.shape == (241, 8)
    assert len(np.unique(BOOK, axis=0)) == 241
    np.testing.assert_array_equal((BOOK[1:] ** 2).sum(1), np.full(240, 2))
    np.testing.assert_array_equal(np.mod(BOOK.sum(1), 2), np.zeros(241))
    np.testing.assert_allclose(H8 @ H8.T, np.eye(8), atol=1e-15)
    np.testing.assert_array_equal(nearest(BOOK, 1), np.arange(241, dtype=np.uint8))


def test_nearest_matches_independent_coordinate_distance_oracle():
    x = np.random.default_rng(1).normal(size=(40, 8))
    expected = [min(range(241), key=lambda i: sum((float(a) - float(b) * 0.73) ** 2
                                                for a, b in zip(row, BOOK[i]))) for row in x]
    np.testing.assert_array_equal(nearest(x, 0.73), expected)


def test_closed_form_search_matches_brute_force_on_ties_and_random_vectors():
    rng = np.random.default_rng(11)
    x = np.concatenate([rng.normal(size=(4096, 8)),
                        np.array(list(__import__("itertools").product((-1, 0, 1), repeat=8)), dtype=float)])
    for start in range(0, len(x), 128):
        a = x[start:start + 128]
        oracle = ((a[:, None] - BOOK[None] * 0.75) ** 2).sum(2).argmin(1)
        np.testing.assert_array_equal(nearest(a, 0.75), oracle)


@pytest.mark.parametrize("method", ["e8", "scalar"])
@pytest.mark.parametrize("bits", [1, 2, 4])
def test_serialization_is_actual_packed_storage(method, bits):
    rng = np.random.default_rng(2)
    x = rng.normal(size=(31, 16)).astype(np.float32)
    model = fit(x, method=method, bits=bits)
    code, expected = model.quantize(x)
    payload = encode(model, x)
    restored = decode(payload)
    np.testing.assert_array_equal(restored, expected)
    assert code.nbytes == (len(x) * 16 * bits + 7) // 8
    assert len(payload) > code.nbytes  # Include metadata/model, not ideal bit counts.
    assert payload == encode(model, x)


@pytest.mark.parametrize("mode", ["escape", "projection"])
def test_multiple_probes_protect_decisions_and_scores(mode):
    rng = np.random.default_rng(3)
    model = fit(rng.normal(size=(256, 16)), bits=1)
    x = rng.normal(size=(512, 16)).astype(np.float32)
    weights = rng.normal(size=(16, 3))
    bias = np.array([0.1, -0.2, 0.3])
    restored = decode(encode(model, x, probes=weights, bias=bias,
                            protection=mode, score_tolerance=0.001))
    raw, rec = x.astype(float) @ weights + bias, restored.astype(float) @ weights + bias
    assert np.max(np.abs(raw - rec)) <= 0.001
    np.testing.assert_array_equal(rec >= 0, raw >= 0)


def test_projection_is_minimum_norm_and_accounts_for_side_channel():
    rng = np.random.default_rng(4)
    x = rng.normal(size=(100, 16)).astype(np.float32)
    model = fit(x)
    w = rng.normal(size=(16, 1))
    payload = encode(model, x, probes=w, protection="projection")
    _, raw = model.quantize(x)
    rec = decode(payload)
    correction = rec.astype(float) - raw
    orthogonal = correction - (correction @ w) @ np.linalg.pinv(w)
    np.testing.assert_allclose(orthogonal, 0, atol=3e-7)
    with np.load(io.BytesIO(payload)) as p:
        assert p["probe_values"].nbytes == 8 * len(x)
        assert len(p["escape_rows"]) == 0


def test_weak_signal_positive_control():
    c = controls()
    assert c["pass"] and c["unprotected_weak_signal_flips"] > 0
    assert c["protected_weak_signal_flips"] == 0


@pytest.mark.parametrize("bad", [np.zeros((0, 8)), np.zeros((3, 7)), np.full((3, 8), np.nan)])
def test_bad_features_rejected(bad):
    with pytest.raises(ValueError):
        fit(bad)


def test_rank_deficient_probes_and_tampered_indices_rejected():
    x = np.ones((16, 8), dtype=np.float32)
    model = fit(x)
    with pytest.raises(ValueError, match="independent"):
        encode(model, x, probes=np.ones((8, 2)), protection="projection")
    with np.load(io.BytesIO(encode(model, x))) as p:
        data = {k: p[k].copy() for k in p.files}
    data["code"][0, 0] = 255
    buf = io.BytesIO()
    np.savez(buf, **data)
    with pytest.raises(ValueError, match="indices"):
        decode(buf.getvalue())


def test_physical_and_embedding_training_leakage_rejected():
    p = synthetic_fixture()
    validate_fixture(p)
    p["embedding_training_groups"] = np.array(["eval-0"])
    with pytest.raises(ValueError, match="training groups"):
        validate_fixture(p)
    p = synthetic_fixture()
    p["groups"][-1] = p["groups"][0]
    with pytest.raises(ValueError, match="physical groups"):
        validate_fixture(p)
