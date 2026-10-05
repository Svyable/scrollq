# Winding conservation — synthetic planted-defect calibration (2026-10-05)

**Synthetic only. No real stitched solution is measured here.** The substrate is
a deterministic deformed spiral built by `synthetic_solution()`. It is not
scroll data, and these numbers are not real-scroll detection limits.

- Source commit: `17653a1b2534c514d721006211fb0fa9bfa72455`
- Method: `scroliq-winding-conservation-v1`, with thresholds frozen in
  `src/scrollq/winding_conservation.py`. Thresholds were not changed after any
  calibration output was read. One reporting rule changed after a first run:
  "smallest reliable" now also requires every larger θ extent to be reliable.
  That first run's output was discarded and the calibration regenerated from
  the commit above.
- `calibration.json` SHA-256: `433f98e3e79d8c0732fb10443b963fb1f4f70748ec872181023334b894a96369`

## Reproduce

```bash
scroliq-winding-conservation calibrate --seed 0 --placements 16 --out calibration.json
```

This takes about 8 minutes on one CPU; see `run.log`. The tables below are read
from `calibration.json`. The first comes from `smallest_reliable_extent`, the
others from `rows[*].detection_rate`.

## Substrate (`substrate.parameters`)

| parameter | value |
|---|---|
| windings | 16 |
| pitch | 20 voxels × 8.64 µm = 172.8 µm |
| inner radius | 60 voxels |
| z range | 0–256 voxels |
| sampling | 1° × 4 voxels |
| pitch modulation | ±15%, smooth in θ and z |
| radial jitter | σ = 0.75 voxel |
| hard null | a compressed-but-correct sector: windings 6–9 squeezed to 0.65× pitch over ±60° and ±96 z, with a raised-cosine taper |
| tilted umbilicus | yes |

## Clean solution (the null)

- 1,152 of 1,152 cells evaluated, 0 flagged (`status: consistent`), including
  the compressed sector.
- Measured pitch: median 19.97 voxels = **172.5 µm**, IQR 163.0–181.7 µm.
- Null rate (same footprint on the unmodified solution) was 0.00 for every
  defect, extent and family.

A zero null on this substrate says only that the synthetic deformations stay
inside the frozen tolerances. Real folds and crush will not all do so.

## Smallest reliable angular extent

A defect sits on one winding k ∈ [3, 11], with 16 seeded placements per extent.
Each cell below is the smallest θ extent from which every larger θ extent fires
in ≥ 95% of placements. "—" means no extent qualifies. Cells are 5° × 16 voxels.

| defect | family | Δz 4 | Δz 8 | Δz 16 | Δz 32 | Δz 64 | Δz 128 |
|---|---|---:|---:|---:|---:|---:|---:|
| delete | layer_count | — | — | — | 10° | 10° | 10° |
| delete | pitch | — | — | — | 10° | 10° | 10° |
| delete | continuity | — | — | — | 10° | 10° | 10° |
| delete | support | — | — | — | — | — | — |
| delete | **any** | — | — | — | **10°** | **10°** | **10°** |
| duplicate | layer_count | 5° | — | — | 2.5° | 2.5° | 2.5° |
| duplicate | pitch | — | — | — | — | — | — |
| duplicate | continuity | 360° | 360° | 10° | 5° | 5° | 5° |
| duplicate | support | 5° | 5° | — | — | — | — |
| duplicate | **any** | **5°** | **5°** | **5°** | **2.5°** | **2.5°** | **2.5°** |
| merge | layer_count | — | — | — | — | — | — |
| merge | pitch | — | — | 10° | 20° | 10° | 5° |
| merge | continuity | — | — | 10° | 5° | 5° | 5° |
| merge | support | 10° | 10° | — | — | — | — |
| merge | **any** | **10°** | **10°** | **5°** | **2.5°** | **2.5°** | **2.5°** |
| switch | layer_count | — | — | — | 5° | 5° | 5° |
| switch | pitch | — | — | 10° | 5° | 5° | 5° |
| switch | continuity | — | — | 10° | 5° | 5° | 5° |
| switch | support | — | — | — | — | — | — |
| switch | **any** | — | — | **10°** | **5°** | **5°** | **5°** |

Any-family detection rate at Δz = 16 voxels (one cell height, randomly placed):

| defect | 2.5° | 5° | 10° | 20° | 45° | 90° | 180° | 360° |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| delete | 0.38 | 0.44 | 0.88 | 0.75 | 0.94 | 1.00 | 0.75 | 0.75 |
| duplicate | 0.94 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| merge | 0.88 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| switch | 0.00 | 0.62 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

## Reading

- **Layer count and pitch need about two cells of z.** A deletion or switch
  reliably moves both residuals once it spans Δz ≥ 32 voxels (2 cell heights)
  and 5–10° (1–2 cell widths). At Δz = 16, a randomly placed defect almost
  never covers a whole cell, so each cell's median radius barely moves. Even a
  full-turn 16-voxel deletion fires in only 75% of placements, through
  `support`. This is the cell bandwidth, not a tuning artefact: a finer grid
  trades resolution for noise and would need its own calibration.
- **Identity defects are the easiest.** Duplicates and merges relabel every
  outer winding, so `continuity` and `layer_count` (for duplicates) fire from
  2.5–5° at Δz ≥ 32. Below one cell height they are caught only by `support`.
- **A merge sits at the edge of the pitch band.** Its 1.5× gap is just outside
  the frozen 0.6–1.4 band, so merge `pitch` detection is uneven across z
  extents (5–20°). `continuity` carries merge detection.
- **A switch needs geometry, not support.** It reuses the neighbour's own
  vertices, so point density is unchanged and `support` never fires. Layer
  count, pitch and continuity all catch it from 5° × 32 voxels.
- **Deletions are the hardest.** They need 10° × 32 voxels before
  layer/pitch/continuity are reliable.

## What this does not establish

- No real stitched solution is measured, and no real false-alarm rate. On a
  real scroll, folds, tears, crush, the scroll's own edges and long outer-ring
  cells will raise the null rate.
- Cell sizes are in voxels and degrees, not physical length. Converting
  "10° × 32 voxels" to arc length depends on radius.
- Nothing here concerns ink, CT support or readability.

The next step is the promotion gate in
[the research note](../../docs/research/2026-10-05-winding-conservation-and-watch.md):
a frozen real solution, the same four planted defects on it, and VC3D
classification of every flag on the unmodified solution.
