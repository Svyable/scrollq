# First Letters surface-prediction CT support — 2026-09-30

How much of each released surface prediction lies on real CT material, on
the **exact** eligible First Letters scan. A *positive* is a prediction voxel
above 127; a *phantom* is a positive whose aligned masked-CT voxel is exactly
0; support = 1 − phantoms / positives (the definition used by
axiosdevs/herculaneum-scroll-tools `ct_support`).

This is a geometry-prior sanity metric. It is not ink, readability or
First Letters success evidence.

## Reproduce

```bash
# native, first-party measurement (up to ~0.5 GB of public open data per scroll)
scroliq-support --prize first-letters --samples 256 --workers 16 \
  --out support_native.json

# external surveys, pinned to commit 63a09d4fd8a4 of the source repo
python bin/import_ct_support.py first-letters support_external.json

# agreement between the two on scrolls where both are exact-scan evidence
python bin/compare_support.py support_native.json support_external.json agreement.json

# qualifier with native support as a third, sensitivity-only axis
scrollq-grand-prize --prize first-letters \
  --volumes artifacts/2026-09-30-scrollq-n24-dense/volumes.json \
  --surface-support support_native.json --out targets_with_native_support.json
scrollq-grand-prize --prize first-letters \
  --volumes artifacts/2026-09-30-resampling-stability/stability-n24-dense-prov.json \
  --run run1 --surface-support support_native.json \
  --out targets_run1_with_native_support.json
```

## Native method (`scroliq-support`, method `scrollq-chunk-sample-v1`)

- Prediction: `<scroll>/representations/predictions/surfaces/<scan>-surface-20260413222639-surface-m7-L0-th0.2.zarr`
  level 0; CT: `<scroll>/volumes/<scan>-…-masked.zarr` level 0, both from
  the public `vesuvius-challenge-open-data` bucket.
- Prediction and CT must have the same L0 shape or the measurement fails
  closed. A CT name that is not the eligible scan is rejected before any
  download.
- Each sample is one 128³ CT chunk nested wholly inside one 192³ prediction
  chunk. Candidates are spread per dimension (12 per axis) and visited in a
  fixed-seed (0) order until 256 chunks with positives are found. Unstored
  prediction chunks hold no positives; unstored CT chunks are masked
  background and count fully as phantom.
- Support is pooled over positives; the 95% interval is a 2000-draw
  bootstrap over sampled chunks.

All 22 scans completed with 256 sampled chunks each.

## Agreement with the external survey (`agreement.json`)

The external surveys read every 12th chunk slab in full, a different and
much larger sample. On the 18 scrolls where both sources are exact-scan
evidence:

- external value inside the native 95% interval: **15 / 18**
- mean |difference| **0.043**, max **0.111**, Spearman ρ **0.78**
- outside the interval: PHerc0490B (native 0.599 vs 0.710), PHerc0306B
  (0.632 vs 0.544), PHerc0846B (0.417 vs 0.495)

So the native estimator reproduces the external numbers to within a few
hundredths on most scrolls, but individual values can differ by ~0.1.
Treat support differences under ~0.1 as ties.

## What the native run adds

Four of the 22 scans had no usable exact-scan support number before:

| Scroll | Native support (95% CI) | Why there was no exact-scan number |
|---|---|---|
| PHerc0846A | 0.455 (0.380–0.538) | external survey used the 2.403 µm scan (0.418) |
| PHerc1203 | 0.454 (0.383–0.539) | external survey used the 2.403 µm scan (0.698) |
| PHerc1218 | 0.646 (0.570–0.724) | external record does not keep its CT URL |
| PHerc0125 | 0.496 (0.422–0.576) | external record does not keep its CT URL |

PHerc1203 is the clearest case for the exact-scan guard: the
higher-resolution scan's survey (0.698) would have overstated support on the
eligible scan by about 0.24.

## Three-axis sensitivity frontier

Quality × segments × native support, all 22 scans comparable:

| run | frontier |
|---|---|
| run0 (published) | PHerc0175B, PHerc0306B, PHerc0490A, PHerc0800, PHerc0813 |
| run1 (disjoint resample) | PHerc0175B, PHerc0211, PHerc0306B, PHerc0490A, PHerc0800, PHerc1545 |
| both | **PHerc0175B, PHerc0306B, PHerc0490A, PHerc0800** |

PHerc0490A has the highest native support (0.743); the next is PHerc1218
(0.646), and their intervals overlap. PHerc0800 is the only scroll on every frontier computed here.
The support axis does not change the primary two-axis frontier.
