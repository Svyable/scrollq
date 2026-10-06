# Crop-coordinate invariance of dense embeddings

`scroliq-crop-invariance` asks one question before a dense embedding
similarity (for example Dinovol features) is allowed to carry independent
evidence about sheets or ink: **does the embedding of a physical voxel depend
on where that voxel sits inside the crop it was extracted from?**

If it does, a cosine-similarity field can look spatially coherent because two
voxels occupy analogous crop positions, not because they depict analogous
structure.

## Fixture

The same physical voxels, embedded under several deliberately shifted crop
frames (at least 3, origins that actually differ). Arrays in one `.npz`,
declared by a manifest with `arrays_sha256`:

| array | shape | meaning |
|---|---|---|
| `embeddings` | C × N × D | embedding of point *i* in crop frame *c* |
| `crop_origin` | C × 3 | crop origin in volume voxel coordinates |
| `points_xyz` | N × 3 | physical voxel coordinates (must lie inside every crop) |
| `labels` | N | `sheet`, `neighbor_sheet`, `fiber`, `void`, `ink`, `negative` |
| `split` | N | `calibration` (fits the transform only) or `evaluation` |

Manifest: `{"schema_version": 1, "experiment_id", "crop_shape": [z,y,x],
"embedding_source": {...}, "arrays": "f.npz", "arrays_sha256"}`. Each class
needs at least 10 points in both splits, otherwise the result is
`unverified`. `ink` and `negative` must come from verified-ink and
physical-negative labels; the tool cannot check that.

## Measures (evaluation points only, raw and debiased)

- `position_r2`: held-out share of the *within-point* across-crop variance
  explained by crop-relative coordinates (degree-3 polynomial, ridge).
- `same_voxel_cosine`: one voxel's embedding across crop pairs.
- `nn_stability`: nearest-neighbour *identity* unchanged between crop pairs.
- `sheet_vs_neighbor_auroc`, `ink_vs_negative_auroc`: within-crop AUROC of
  same-class vs cross-class cosine (physical discrimination).

The debiasing transform subtracts the calibration-fitted position component
from every embedding. It is a representation-agnostic stand-in, not
INSID3's transform and not an adaptation to Dinovol's own positional
encoding; a Dinovol-specific transform would be a further arm judged by the
same rule.

## Frozen rule

Constants are in `crop_invariance.RULE`. Outcomes:

- `NO_POSITIONAL_DEPENDENCE_DETECTED`: raw `position_r2` < 0.10 and frame
  variance < 0.10. The concern is falsified *within the polynomial family* and
  debiasing is dismissed for this fixture.
- `FRAME_DEPENDENCE_UNEXPLAINED`: embeddings vary across frames but not as a
  polynomial of position. Neither bias nor invariance is established.
- `POSITIONAL_DEPENDENCE_DEBIAS_PROMOTED`: dependence present and every check
  holds: residual `position_r2` ≤ min(0.05, 0.25 × raw); same-voxel cosine and
  NN stability not lower; both separations drop by ≤ 0.02.
- `POSITIONAL_DEPENDENCE_DEBIAS_REJECTED`: dependence present, a check failed
  (listed in `failed_checks`).
- `unverified`: too few frames/points, identical frames, or raw separation
  below 0.60 (no discrimination to preserve).
- `unavailable_input`: no embeddings supplied. This means the gate cannot
  currently be evaluated; it is not a failure and not a pass.

Smoother similarity maps never count: a transform that deletes the signal
raises same-voxel cosine and is rejected by the separation checks (built-in
control).

```bash
scroliq-crop-invariance --self-test
scroliq-crop-invariance --manifest fixture/manifest.json --out out/crop-invariance.json
```

## Scope

Synthetic controls only; **no real Dinovol result exists yet**. A PROMOTE is
evidence about one fixture, not about Dinovol in general, and is neither
surface nor ink evidence. Point estimates only (no bootstrap CIs). Only
polynomial position dependence is probed. The INSID3 gains cited in the
research note are the authors' 2-D DINOv3 figures and are not reproduced
here. Neither INSID3 code nor DINOv3 weights are imported.
