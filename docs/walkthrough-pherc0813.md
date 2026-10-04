# Walkthrough: what ScrolIQ says about PHerc0813

This page follows one Grand Prize target, PHerc0813, through every ScrolIQ
artifact committed for it. It shows what the tools measured, what they
deliberately leave `unknown`, and which next step the evidence points to.
Every number below comes from a file in this repository; the file is named
next to it.

ScrolIQ does not predict readability. Nothing here says PHerc0813 will or
will not read.

## 1. Which data counts

The 2027 Grand Prize names one eligible CT volume per scroll. For PHerc0813
that is `20250821151723` (9.362 µm, 113 keV). The qualifier pins that exact
volume and never substitutes a different scan of the same scroll.

- Source: `artifacts/2026-09-30-grand-prize-qualifier-n24-dense/targets.json`

## 2. Is the data intact?

`scrollq-health` ran the companion
[zarr-pyramid-audit](https://github.com/Svyable/zarr-pyramid-audit) on the
volume: integrity **PASS** across 6 pyramid levels, with 1 informational
finding and no high- or medium-severity findings. Verdict: **TRAIN**.

- Source: `artifacts/2026-09-30-health-verdicts/train-pherc0813.json`
- Caveat: the quality half of that verdict (77.4) came from the retired
  4-sample campaign. The integrity result does not depend on it.

## 3. What does the scan look like?

The published campaign decoded 24 full-resolution 128³ chunks from a 5×5×5
candidate grid (45 candidate shards were unstored masked background, which
is expected and not a defect).

| | value |
|---|---|
| scan-health score | **76.2** (rank 4 of 64 volumes) |
| components | signal 40.0/40, texture 21.4/30, dynamic range 15.0/20, saturation −0.2 |
| per-chunk scores | 30.3 – 87.7, std 14.3 |
| dead slices | 0 |

- Source: `artifacts/2026-09-30-scrollq-n24-dense/volumes.json`

The per-chunk spread matters more than the mean. A 57-point range across 24
chunks says the volume is heterogeneous, and the 76.2 is an average over
very different regions.

## 4. How stable is that number?

Not measured yet for this volume. In the published resample, both runs
decoded the **same 24 chunks** (Jaccard 1.0), so the identical 76.2 in both
runs is a re-read, not a confirmation. This is the failure mode the
forced-disjoint resample in `bin/stability.py ... disjoint` was built to
remove.

- Source: `artifacts/2026-09-30-resampling-stability/stability-n24-dense-prov.json`

## 5. Where in the scroll were the observations?

`scroliq-scan-map` keeps the level-0 voxel box of each observation. On a
6×6×6 shard grid (216 candidates): 48 decoded, 9 sparse mask, 159 unstored.
Gradient energy across decoded observations runs from 0.014 to 11.85
(median 7.11).

Compared with PHerc1667, the first scroll completely unwrapped and read, the
central-80% ranges overlap heavily (interval Jaccard 0.61 for gradient
energy, 0.90 for dynamic range). That overlap is a guard, not a score: it
means none of these values alone justifies calling a PHerc0813 region bad.

- Sources: `artifacts/2026-09-30-spatial-scan-campaign/PHerc0813.scan-map.json`,
  `artifacts/2026-09-30-pherc1667-scan-control/README.md`

## 6. The passport: what is known and what is not

`scroliq-passport` collects the evidence above by Open Problems stage:

| stage | status | why |
|---|---|---|
| data | measured | 24/24 requested chunks decoded, read provenance kept |
| scan | measured | sections 3 and 5 |
| labels | partial | 0 published ink labels, 0 segments; flagged `label_next` |
| winding | unknown | no PointCollections audit supplied |
| surface | unknown | no surface prediction or support diagnostic supplied |
| mesh | unknown | no TIFXYZ audit supplied |
| fibers | unknown | no fiber evidence supplied |
| spiral | unknown | no spiral fit evaluated |
| ink | unknown | no held-out ink evidence supplied |

- Source: `artifacts/2026-09-30-spatial-scan-campaign/PHerc0813.passport.json`

Seven of nine stages are `unknown`, and the passport says so instead of
letting a 76.2 stand in for them.

## 7. What it points to next

> **Update 2026-10-04.** Under the v2 sampling design PHerc0813 is no longer on
> the Grand Prize frontier (pooled v2 score 70.2; see
> [`prize-frontier-v2/`](../artifacts/2026-10-04-prize-frontier-v2/)). The
> paragraph below describes the frozen September result.

PHerc0813 sat on the Grand Prize Pareto frontier because it had the best
scan health of the 13 targets, but it has **no public segments**. PHerc1447,
the other frontier member, has 15 segments but a lower score (61.7). The
trade-off is explicit rather than hidden in a weight.

The evidence therefore points to two concrete next steps for PHerc0813:

1. **Surface and mesh first.** With zero segments, the binding constraint is
   geometry, not scan quality. Run `scroliq-mesh` (with the VC3D selfcross
   and Villa surface-preflight reports) on the first segments as they
   appear, so mesh defects are caught before any flattening or ink work.
2. **Measure the score's stability properly.** Run the forced-disjoint
   resample so the 76.2 carries a real uncertainty band.

Reproduce the passport:

```bash
scroliq-passport \
  --volumes artifacts/2026-09-30-scrollq-n24-dense/volumes.json \
  --coverage artifacts/2026-09-30-scrollq-n24-dense/coverage.json \
  --scan-map artifacts/2026-09-30-spatial-scan-campaign/PHerc0813.scan-map.json \
  --root 20250821151723 \
  --out PHerc0813.passport.json
```
