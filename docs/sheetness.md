# Sheetness baseline

`scroliq-sheetness` measures whether a local 3-D CT cutout contains a
plate-like second-order intensity structure. It is intended as an independent
physical diagnostic for papyrus-surface hypotheses, not as an unrolling or
sheet-identity verdict.

## Why this exists

Papyrus layers are locally sheet-like objects embedded in a 3-D CT volume.
Medical-imaging software has a mature family of Hessian-eigenvalue
"objectness" measures that distinguish blob-, tube-, and plate-like structures.
ScrolIQ uses the **M=2 object in N=3 dimensions** specialization of that idea as
a deterministic reference baseline.

The implementation is dependency-light NumPy rather than an ITK dependency in
the core package, but follows the same mathematical contract documented by
ITK's `HessianToObjectnessMeasureImageFilter`:

- smooth the volume at one or more Gaussian scales;
- compute the scale-normalized Hessian;
- sort its eigenvalues by absolute magnitude;
- prefer two small tangential curvatures and one large normal curvature;
- enforce an explicit bright- or dark-sheet polarity;
- combine the plate ratio with second-order structureness;
- retain the best response across the declared scales.

Upstream reference:
<https://docs.itk.org/projects/doxygen/en/latest/classitk_1_1HessianToObjectnessMeasureImageFilter.html>
(ITK is Apache-2.0 licensed).

## Run it

The first version deliberately operates on bounded local cutouts rather than
pretending it can stream an entire Grand Prize scan:

```bash
scroliq-sheetness cutout.npy \
  --out-prefix out/pherc-cutout \
  --sigmas 0.8,1.2,1.8 \
  --write-normal
```

Accepted inputs are 3-D `.npy`, `.npz`, `.tif`, or `.tiff` arrays in ZYX
order. The default memory guard is 2.5 million voxels; raising it is explicit.

Outputs are deterministic `.npy` arrays plus a JSON report:

- `*.sheetness.npy`: maximum plate response across scales;
- `*.scale.npy`: sigma that won at each voxel;
- `*.normal-zyx.npy`: optional local normal from the strongest Hessian
  eigenvector (its sign is arbitrary);
- `*.sheetness.json`: exact input/output SHA-256 values, parameters,
  normalization values, scale summaries, and response quantiles.

No random state is used.

## Claim boundary

A high response means only that the local CT intensity field is consistent with
a thin plate at one of the tested scales. It **does not** establish:

- that the plate is papyrus rather than another sheet-like structure;
- that a candidate surface follows the correct winding;
- that two nearby responses belong to the same physical sheet;
- recto versus verso;
- fiber identity;
- ink;
- readability.

Those distinctions are exactly why this signal is useful: it can be tested as
an independent observation inside a larger evidence graph without laundering it
into a stronger conclusion.

## Falsification tests shipped with the code

`tests/test_sheetness.py` pins several behaviors before any Vesuvius result is
claimed:

1. a synthetic Gaussian plate must score higher than a tube and a blob;
2. the recovered normal on that plate must point along the known thin axis;
3. bright/dark polarity must reject the wrong sign;
4. repeated multiscale runs must be bitwise deterministic;
5. the CLI must hash-pin the source and every emitted array;
6. the memory guard must fail before the expensive Hessian calculation.

## Next evidence campaign

The first real-data experiment should be frozen before tuning thresholds:

1. choose a known-good public surface and several Grand Prize surfaces;
2. sample identical-width CT cutouts centered on the submitted surface and at
   fixed normal offsets;
3. run a predeclared sigma set and polarity;
4. compare on-surface sheetness with offset controls;
5. repeat on an intentionally wrong or broken surface;
6. only after those results are frozen decide whether sheetness belongs in the
   passport or surface-growth objective.

A useful result is either positive or negative. If correct surfaces do not
separate from offset controls, this signal should remain an exploratory
diagnostic rather than becoming another score.


## Frozen control evaluation

`scroliq-sheetness-eval` turns the exploratory response field into a
pre-registered falsification experiment. The benchmark spec must bind:

- the exact eligible `volume_root`;
- the ZPA `zpa-metadata-semantics-v1` digest for that source;
- the exact CT cutout SHA-256;
- the exact `scroliq-ct-cutout` manifest SHA-256, which binds that local
  array to one global level-0 ZYX box;
- the exact `scroliq-sheetness` report SHA-256;
- one known/high-confidence surface probe per group;
- a reference surface normal;
- at least one deliberate `normal-offset` control and one `wrong-wrap`
  control per group;
- all pass/fail thresholds before evaluation.

The version-2 evaluator verifies the provenance-bound cutout manifest before
reading any probe score. It checks exact volume identity, ZPA metadata
attestation (including audited ZYX axes), retained PASS ZPA-report hash,
cutout SHA, global half-open bbox, local-to-global transform, source-chunk
completeness, and cutout shape. Every emitted probe then carries
both its local array coordinate and its derived global level-0 CT coordinate.

It also verifies the response and normal-array hashes recorded by the
sheetness report and measures four things without dropping failures: score
completeness, the fraction of all groups where the surface beats every control,
the median surface-minus-best-control margin, and absolute-cosine normal
alignment. Missing, out-of-bounds, or non-finite probes remain in the group
denominator rather than disappearing from the result.

```bash
scroliq-sheetness-eval \
  --spec campaign/sheetness-spec.json \
  --cutout-manifest out/cutout.json \
  --report out/cutout.sheetness.json \
  --response out/cutout.sheetness.npy \
  --normal out/cutout.normal-zyx.npy \
  --out campaign/sheetness-result.json \
  --require-pass
```

A valid negative experiment is still a reproducible result: without
`--require-pass` the CLI exits zero for both `pass` and `fail`, while an
invalid/tampered bundle exits 2. The output records both the raw spec-file hash
and a canonical semantic spec hash, the engine parameters, every probe result,
and each frozen decision-rule check.

The evaluator now requires the `scroliq-ct-cutout` lineage artifact, so the
local bytes and every frozen probe are traceable to one exact audited level-0
CT box. That strengthens source/coordinate provenance; it still does not prove
that the chosen surface belongs to the correct physical winding, that topology
is globally correct, or that ink is present or readable.
