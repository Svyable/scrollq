# Spatial scan campaign — 2026-09-30

This artifact is the first real-data run of `scroliq-scan-map`.
It uses the exact prize-eligible volumes for PHerc0813 and PHerc1447
recorded in ScrolIQ's frozen Grand Prize manifest.

## Reproduce

```bash
scroliq-scan-map --root community-uploads/forrest/volcomp/PHerc0813/volumes/20250821151723-9.362um-1.2m-113keV-masked.zarr --grid 6 --chunks-per-shard 1 --out PHerc0813.scan-map.json
scroliq-scan-map --root community-uploads/forrest/volcomp/PHerc1447/volumes/20250521151220-8.640um-1.2m-116keV-masked.zarr --grid 6 --chunks-per-shard 1 --out PHerc1447.scan-map.json
```

Base URL: `https://dl.ash2txt.org`. Level: full-resolution L0.
Source commit: `fed5e31e412ee8d7ca158b6d5910fcf285e8d235`.

## Observed survey coverage

| Scroll | Candidate shards | Chunks decoded | Spatial states | Gradient-energy range | Dynamic-range range |
|---|---:|---:|---|---:|---:|
| PHerc0813 | 216 | 48 | decoded=48, sparse-mask=9, unstored-shard=159 | 0.013853–11.854323 | 0.0–188.0 |
| PHerc1447 | 216 | 83 | decoded=83, sparse-mask=19, unstored-shard=114 | 0.011722–11.700658 | 0.0–188.0 |

See `summary.json` for machine-readable campaign metadata and each
`*.scan-map.json` for level-0 voxel bounding boxes and local metrics.

## Scope

These outputs demonstrate local coordinate-preserving CT diagnostics.
They do **not** yet establish that a region is compressed, decohered,
correctly surfaced, ink-bearing, readable, or Grand Prize ready.
Physical interpretation is the next validation step.
