# Surface-prediction value census — 2026-10-04

**Question:** are the published `PHerc0139` surface-prediction arrays graded or
binary? Probability-threshold and confidence-guided uncertainty constructions need
a graded source.

**Answer (sampled, not exhaustive): binary.** In every inspected chunk the only
nonzero stored value is 255.

| Array | Level | Chunks inspected | Nonzero voxels | Distinct nonzero values | Verdict |
|---|---:|---:|---:|---:|---|
| `surface-m7-L0-th0.2.zarr` | 0 | 16 | 21,389,105 | 1 | binary |
| `surface-recto-090.zarr` | 0 | 8 | 3,338,317 | 1 | binary |
| `surface-recto-090.zarr` | 1 | 8 | 4,840,804 | 1 | binary |
| `surface-recto-090.zarr` | 2 | 8 | 7,158,364 | 1 | binary |
| `surface-recto-090.zarr` | 3 | 8 | 8,003,760 | 1 | binary |
| `surface-recto-090.zarr` | 4 | 8 | 2,514,070 | 1 | binary |
| `surface-recto-090.zarr` | 5 | 8 | 1,701,296 | 1 | binary |

Full chunk identities, skipped-chunk counts and the nonzero histograms are in
`result-m7-L0.json` and `result-recto-090.json`.

## Reproduce

Read-only; needs network to the open-data bucket. Output is create-only.

```bash
B=https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0139/representations/predictions/surfaces

python scripts/surface_prediction_value_census.py --seed 20261004 --per-dim 5 --max-chunks 16 \
  --out out/result-m7-L0.json \
  --url "$B/20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr/0"

python scripts/surface_prediction_value_census.py --seed 20261004 --per-dim 5 --max-chunks 8 \
  --out out/result-recto-090.json \
  $(for l in 0 1 2 3 4 5; do printf -- "--url %s " \
    "$B/20250728140407-surface-20250701154204-surface-recto-090.zarr/$l"; done)
```

The committed files were produced by exactly these commands (with `--out`
pointing at this directory) and the nonzero-voxel counts above reproduce
deterministically for the fixed seed.

## Limits

- Sample-based. Chunks come from the repo's per-dimension spread
  (`scrollq.support._candidates`) with seed 20261004. Unstored and all-zero
  candidates are skipped and counted, because they say nothing about the encoding.
- It shows the stored values, not why they are binary. The `th0.2` in the
  `surface-m7` filename suggests thresholding at export; that is an inference.
- The `lasagna/` and `fibers/` product families under
  `PHerc0139/representations/predictions/` were not examined.
- No CT, TIFXYZ, ROI or ink was read.
