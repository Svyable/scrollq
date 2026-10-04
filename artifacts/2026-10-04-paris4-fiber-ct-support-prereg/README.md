# PHercParis4 fiber CT support — pre-registration (October stretch goal O9)

**Status: frozen before any CT voxel is read at a fiber position.**

The public spiral dataset names no CT volume. The 2026-10-04 range check
(`../2026-10-04-paris4-fiber-binding/`) found exactly one readable public
PHercParis4 volume that can contain every census fiber point:
`20260411134726` (2.400 µm, 78 keV). This test asks whether the fibers, placed in
that volume, actually sit on material.

`spec.json` freezes:

- **Groups:** 16 points per fiber; the same points displaced by ±272 µm (the
  positive control: support must drop); random background points in each fiber's
  own bounding box; and an axis-swapped copy (the wrong-frame control).
- **The read:** one uint8 voxel per point at level 1, read by range request.
- **The decision rule:** fiber-cluster bootstrap CIs on AUC(F vs R) and on the
  drop F − S. If the axis-swapped control also comes out supported, the verdict
  is `CONTROL FAILURE`.

`scripts/paris4_fiber_ct_support.py` pins this file's SHA-256 and checks the
volume's level-1 scale, dtype and compression before reading. Its statistics are
unit-tested on synthetic data (`tests/test_paris4_fiber_ct_support.py`).
