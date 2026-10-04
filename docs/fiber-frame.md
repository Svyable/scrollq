# Cross-ply fiber-frame continuity

`scroliq-fiber-frame` is an experimental, ink-blind physical continuity
diagnostic for candidate papyrus surfaces. It is designed to catch a failure
that can evade smoothness and sheetness checks: a reconstruction can remain
locally smooth while silently switching onto an adjacent winding.

The tool does **not** infer text direction or declare that one absolute fiber
orientation is recto. It asks only whether a locally recovered two-axis material
frame changes abruptly across neighboring surface tiles.

## Input contract

The command accepts a compressed or uncompressed NumPy `.npz` containing:

- `slab`: required finite numeric array with shape `(depth, y, x)`. Depth is
  the signed surface-normal sampling axis; `y/x` are the local tangent raster.
- `xyz`: optional finite array with shape `(y, x, 3)` containing the level-0
  voxel-space surface coordinate represented by each tangent pixel.

The upstream extraction step remains explicit. A frozen sampling manifest must
record the exact CT source, candidate-surface geometry, normal orientation,
tangent-frame construction, depth offsets, interpolation method, and code
revision used to produce the slab. ScrolIQ hashes that manifest and the NPZ
instead of silently guessing those choices.

## Method

For every non-overlapping spatial tile, the v1 method:

1. optionally smooths only the tangent dimensions;
2. computes 2-D image gradients independently at each depth;
3. forms a depth-local structure tensor;
4. converts its principal gradient axis to an axial fiber direction;
5. retains sufficiently coherent depth slices;
6. deterministically clusters their axial angles into two unordered modes;
7. rejects tiles whose two modes are insufficiently separated or grossly
   unbalanced;
8. compares each valid two-axis frame to its right/down neighbor.

The frame distance is invariant to swapping the two recovered modes. A neighbor
pair becomes a review finding only when the worst optimally matched axial
difference exceeds the frozen `--switch-degrees` threshold.

This is intentionally a review statistic, not an automatic repair rule.

## Example

```bash
scroliq-fiber-frame \
  --input out/region.surface-slab.npz \
  --volume-root <exact-volume-root> \
  --surface-geometry-sha256 <64-hex> \
  --sampling-manifest out/region.surface-slab.manifest.json \
  --tile-size 32 \
  --sigma 1.0 \
  --min-coherence 0.35 \
  --min-separation-degrees 25 \
  --min-mode-share 0.15 \
  --switch-degrees 25 \
  --out out/region.fiber-frame.json
```

If the NPZ contains `xyz` and the report has findings, export them to native
VC3D PointCollections:

```bash
scroliq-vc3d-review \
  --input out/region.fiber-frame.json \
  --kind fiber-frame-discontinuity \
  --scroll PHercParis4 \
  --out out/region.fiber-frame.points.json
```

The exported markers are immutable review cues. They intentionally contain no
invented winding annotation.

## Synthetic positive control

The regression suite constructs an 8-depth, 64×64 synthetic cross-ply slab.
One arm keeps the same two fiber modes everywhere and must produce zero switch
findings. A second arm rotates both modes by 35 degrees on the right half,
aligned to a tile boundary. With 16×16 tiles and a 25-degree review threshold,
the expected result is exactly four flagged horizontal boundary comparisons.

That control establishes basic detector behavior and swap invariance. It does
not establish usefulness on real CT.

## Promotion gate

Keep the method at **EXPERIMENT FURTHER** until a frozen real-data campaign
demonstrates all of the following:

- recoverable two-mode frames on real carbonized papyrus across multiple
  regions or scrolls;
- materially better detection of adjacent/wrong-winding substitutions than
  false alarms on intact same-sheet material;
- explicit controls for folds, tears, cracks, kollesis/joins, low-SNR and
  low-texture regions, tangent-frame perturbations, and normal reversal;
- incremental value beyond existing sheetness/topology diagnostics;
- thresholds selected without target-scroll ink or attractive renders.

If those conditions fail, discard the metric rather than allowing it to become
another permanent confidence score.

## Claim boundary

A flagged discontinuity is not proof of a sheet switch, and a smooth frame is
not proof of sheet identity. The diagnostic is deliberately ink-blind and
independent of the primary dependency-order reconstruction pipeline.
