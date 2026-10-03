# PHerc0139 Mesh IQ → VC3D review queue (reproducible) — 2026-10-03

This directory supersedes [`../2026-10-02-pherc0139-review-queue/`](../2026-10-02-pherc0139-review-queue/).
That directory is kept frozen and unedited. Its review queue, counts and all 35 coordinates are unchanged here.

## Why a new directory

The 2026-10-02 campaign could not be reproduced byte for byte, for two reasons:

- `scripts/pherc0139_mesh_review_queue.py` audited a copy of the surface in a randomly named temp directory. It then wrote that path (`/tmp/scroliq-pherc0139-XXXX/surface.tifxyz`) into every collection's `metadata.source_tifxyz`. Each run therefore produced a different `review-points.json`, and `pherc0139-review-queue.yml` failed its frozen-hash diff (`c0c8a86d…` frozen, `3f53bfdf…` on 2026-10-03).
- The frozen `review-points.json` had also been re-serialized after generation. It writes `1` and `0` where Python writes `1.0` and `0.0`, and it hashes to `2bef6aba…`, which matches neither run.

The script now records the pinned public source URL as `source_tifxyz`. Two consecutive local runs gave byte-identical outputs.
Compared semantically with the 2026-10-02 files, the only differences are `source_tifxyz` and the PointCollections hash. The review points and summary are otherwise identical.

## Result (unchanged)

- 15 edge-jump candidates and 173 severe neighbouring-normal-reversal pairs.
- `review-points.json` holds **35 points** in two VC3D collections (`vc_pointcollections_json_version: "1"`):
  - **15 / 15** edge-jump sites;
  - the **top 20 / 173** normal-reversal sites.

Frozen PointCollections SHA-256: `a20935bd428d940f70ddf62836cbf92f5a2d2eaa8db4c923e5a4782d88a6ba93`

## Reproduce

```bash
python -m pip install .
python scripts/pherc0139_mesh_review_queue.py --out-dir /tmp/pherc0139-review
diff -u artifacts/2026-10-03-pherc0139-review-queue/summary.json /tmp/pherc0139-review/summary.json
diff -u artifacts/2026-10-03-pherc0139-review-queue/review-points.json /tmp/pherc0139-review/review-points.json
```

The GitHub workflow `.github/workflows/pherc0139-review-queue.yml` runs the same check. The surface, the relationship to the cross-tool dossier and the claim boundary are as described in the 2026-10-02 README. These are ranked review coordinates, not confirmed defects.
