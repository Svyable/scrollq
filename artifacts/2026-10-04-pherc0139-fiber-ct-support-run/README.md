# PHerc0139 fiber CT support — result (replication of O9)

Run of [`../2026-10-04-pherc0139-fiber-ct-support-prereg/`](../2026-10-04-pherc0139-fiber-ct-support-prereg/)
(spec SHA-256 `254de784…a537c`, pushed in `ad31a3a` before its run workflow).
The workflow committed `result.json` here create-only. Deviations: none.

## Verdict: SUPPORTED. It replicates PHercParis4, and the wrong-frame control passed.

Volume `PHerc0139/volumes/20260102150214-2.399um-0.2m-78keV-masked.zarr`, level 1;
411 fibers, 32,880 single-voxel reads (1,167 from absent chunks, 12 out of bounds:
the near-miss fibers).

| vs same-region background | PHerc0139 (this run) | PHercParis4 (O9) |
|---|---|---|
| fiber points, AUC (95 % CI) | **0.760** (0.750 – 0.770) | 0.775 (0.760 – 0.789) |
| displaced ±272 µm | 0.546 | 0.555 |
| specificity F − S, 95 % CI | **0.204 – 0.224** | 0.207 – 0.233 |
| axis-swapped control | 0.468 (CI 0.455 – 0.481) | 0.429 |
| fibers flagged (own AUC ≤ 0.5) | **4 / 411** | 0 / 136 |
| displaced fibers flagged | 151 / 411 (36.7 %) | 38 / 136 |

**Review cues:** the 4 flagged fibers are `kb_20260828T170342976_000047` (0.455),
`kb_20260928T033335844_000218` (0.350), `lt_20260908T075121105_000082` (0.451)
and `lt_20260926T060937932_000191` (0.404). Each may be off-material, or in a
low-contrast region.

The volume choice was a disclosed 7-voxel near miss, not a strict range match.
SUPPORTED here is evidence that the PHerc0139 fibers were traced in this volume's
frame (or one sharing it); it is not a declared binding.
