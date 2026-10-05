# Prediction-volume physical-support preflight

`scroliq-prediction-support` checks one rule before a tracer uses a surface
prediction. A prediction voxel may seed geometry only if the masked CT voxel
under it was physically measured (CT != 0).

`scroliq-support` *estimates* the phantom fraction of a released prediction by
sampling chunks, and its numbers feed the Grand Prize frontier. This tool is the
per-voxel *gate*. For a region of one exact voxel grid, it reports what a tracer
would use and whether seeding from that data is safe.

## What it reports

| Field | Meaning |
|---|---|
| `counts.pred_positive` | prediction > 127 (strict, as `scroliq-support`) |
| `counts.pred_positive_ct_supported` | positives on masked CT != 0 |
| `counts.pred_positive_ct_zero` | positives on masked CT == 0 (phantoms) |
| `phantom_distance_to_ct_support` | Euclidean voxel distance from each phantom to the nearest CT support: min / median / p95 / max and a log-binned histogram. For a sub-region this is an upper bound, because support outside the box may be closer |
| `chunk_classes` | for each prediction chunk that holds positives: `supported` if the chunk itself holds CT support; `halo` if only a 26-neighbour chunk does; `beyond` if no chunk within one chunk does; `unresolved` if the chunk or part of its neighbourhood lies outside the audited region |
| `blend_boundary` | phantoms within `--blend-margin` voxels of a prediction-chunk face, compared with the fraction a uniform spread would put there (`enrichment`) |
| `seed_gate` | with `--seeds`: each seed is `accepted` (CT != 0), `rejected_ct_zero`, or `unverified` (outside the region) |

The tool keeps the chunk and blend-margin layout instead of filtering it away.
If phantoms concentrate in the one-chunk halo next to supported CT, that points
to an inference blending margin as the cause, not to a second physical signal.
The diagnosis is preserved for review. It never changes the verdict.

## Verdict

- `seed_safe`: the region has positives, and every one sits on measured CT.
- `requires_support_filter`: some positives sit on CT == 0. Only
  `pred_positive ∩ ct_supported` may seed. `--write-filtered` writes that
  filtered volume (`supported_prediction`) together with its hash.
- `unverified`: no positives were inspected, or the built-in positive control
  failed. This status is never reported as clean (AGENTS.md lesson 9).

Every report re-runs a synthetic positive control: a 32³ volume with 8³ chunks
and known counts of supported, halo and beyond chunks and known distances. A
shape mismatch between prediction and CT fails closed, because a prediction
made on another scan of the same scroll is not on this grid. An unstored CT
chunk reads as zero. It is masked background, so positives over it count as
phantom.

## Usage

```bash
scroliq-prediction-support --self-test
# local region, same grid; origin/volume shape place it on the global chunk grid
scroliq-prediction-support --pred pred.npy --ct ct.npy --origin 0,0,0 \
  --volume-shape Z,Y,X --chunk 192,192,192 --seeds seeds.json \
  --write-filtered out/pred-supported.npy --out out/prediction-support.json
# remote zarr v2 L0 levels (open bucket), one box
scroliq-prediction-support \
  --pred-url .../PHercXXXX/representations/predictions/surfaces/<vol>-surface-...-m7-L0-th0.2.zarr/0 \
  --ct-url .../PHercXXXX/volumes/<vol>-....zarr/0 \
  --box z0:z1,y0:y1,x0:x1 --out out/prediction-support.json
```

The exit code is 2 for `unverified`. With `--strict` it is also 2 for
`requires_support_filter`, so a tracer wrapper can refuse to start.

## Scope

This is input-validity evidence about the prediction volume only. A supported
positive can still lie on the wrong sheet. The tool says nothing about surface
correctness, winding, readability or ink. No real-volume result has been
committed yet; the first run belongs in a new dated `artifacts/` directory.
