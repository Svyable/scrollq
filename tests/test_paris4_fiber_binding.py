import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import paris4_fiber_binding as b  # noqa: E402


def test_compatibility_uses_zyx_shape_against_xyz_points():
    shape = [100, 50, 20]  # z, y, x
    assert b.compatible([0, 0, 0], [19, 49, 99], shape)
    assert not b.compatible([0, 0, 0], [20, 49, 99], shape)  # x out
    assert not b.compatible([0, 0, 0], [19, 50, 99], shape)  # y out
    assert not b.compatible([0, 0, 0], [19, 49, 100], shape)  # z out
    assert not b.compatible([-1, 0, 0], [1, 1, 1], shape)


def test_candidates_come_from_the_pinned_bucket_index():
    vols = b.candidate_volumes()
    assert len(vols) == 7 and all(v.startswith("PHercParis4/volumes/") for v in vols)
