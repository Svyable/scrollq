# Geometry-stratified, label-coverage-conditioned evaluation

**Status:** EXPERIMENT (machinery implemented and unit-tested on synthetic
fixtures; **no real-data result exists in this repository**).

`scroliq-geometry-strata` asks one question the aggregate held-out score cannot
answer: *is the candidate's improvement present where the scroll is hard and
where the labels are thin, or only where evaluation is easy?*

## Why

A public surface-geometry diagnostic reports that available surface labels
cover well under half of a predicted surface (about 45%, as reported; **not
reproduced here**) and that the unlabeled part is geometrically structured, not
random. If labeled examples over-represent gentle curvature or wide sheet
spacing, an ordinary held-out comparison can be optimistic even when it is
clean. The hardest compressed geometry is also where a wrong-sheet render can
produce the most convincing false texture.

This is an evaluation experiment, not a model. It is registered under the
"geometry-stratified generalization" proof gate.

## Method

1. **Freeze a spec before any performance is read** (`spec-hash` pins it):
   covariates, bin edges, which bins are *hard*, and for each covariate
   `min_rois_per_bin` (≥ 3), `min_target_fraction`, `low_coverage_ratio`,
   `max_unmeasured_fraction`, `margin`; plus the bootstrap samples and seed.
2. **Measure covariates on geometry only**, identically for the committed ROIs
   and for the *inventory*: the actual target scroll cut into units with an
   area weight. Both files carry the same `measurement {method, reference}`
   and the tool refuses any mismatch. The reference surface must not depend on
   the models being compared.
3. **Evaluate** baseline and candidate per-region results (the common
   `models/results.schema.json` shape from the task adapters; for
   segmentation that is `scroliq-segmentation-validate`). A failed or missing
   region keeps the preregistered `failure_value` in the denominator.

For each covariate and bin the report gives the share of the target scroll, the
labeled fraction of that bin, its **representation ratio** (labeled fraction
relative to the overall labeled fraction; < 1 means the labels are thin there),
baseline and candidate means, and the paired improvement with a deterministic
percentile-bootstrap 95% CI (the same bootstrap `scroliq-eval` uses). The
target-weighted improvement re-weights the per-bin improvements to the actual
scroll with a stratified bootstrap; the labeled-set mean is shown for contrast
only.

Bins are half-open `[e_i, e_{i+1})` with open outer bins, so every measured
value lands in exactly one bin; a missing value is reported as unmeasured, never
dropped.

## Decision rule

A covariate `GENERALIZES` only if none of these reasons fire (listed in
precedence order); the run passes (`STRATA_PASS`) only if every covariate does.

| Reason | Fires when |
| --- | --- |
| `UNMEASURED_TARGET` | more of the target lacks the covariate than `max_unmeasured_fraction` |
| `UNMEASURED_ROI` | a committed ROI has no value, so it cannot be assigned a stratum |
| `INVENTORY_DOES_NOT_CONTAIN_ROIS` | a bin's labeled weight exceeds its target weight |
| `UNDER_EVALUATED_STRATUM` | a bin holding ≥ `min_target_fraction` of the target has < `min_rois_per_bin` ROIs |
| `REGRESSION_IN_STRATUM` | an evaluable bin's improvement CI lies entirely below 0 |
| `TARGET_WEIGHTED_NOT_IMPROVED` | the CI lower bound of the target-weighted improvement does not exceed `margin` |
| `HARD_STRATUM_NOT_IMPROVED` | a designated hard bin's CI lower bound does not exceed `margin` |
| `UNDER_REPRESENTED_STRATUM_NOT_IMPROVED` | a bin with representation ratio ≤ `low_coverage_ratio` has CI lower bound ≤ `margin` |

Well-covered, non-hard strata only need to show no significant regression, so a
saturated baseline on easy geometry does not block a candidate that helps where
it matters. Pooling was deliberately rejected for the under-represented
strata: a pooled test let one strong stratum mask a thin, flat one.

The rule is a conjunction over strata, which is conservative against false
promotion and, with few regions per bin, will often return "not enough
evidence". That is the intended failure direction.

## Workflow

```bash
# 1. freeze (commit the spec), then pin it
scroliq-geometry-strata spec-hash --spec heldout/strata-spec.json

# 2. measure the same covariates on the committed ROIs and on the target
scroliq-geometry-strata measure --as regions --dataset DATASET_ID \
  --reference REFERENCE_SURFACE_ID --surface ROI-1=roi1.tifxyz --surface ROI-2=roi2.tifxyz \
  --out out/regions.json
scroliq-geometry-strata measure --as inventory --target PHercXXXX --tile 64 \
  --reference REFERENCE_SURFACE_ID --surface TARGET=reference.tifxyz \
  --out out/inventory.json

# 3. apply the gate (exit 0 pass, 1 blocked, 2 invalid input)
scroliq-geometry-strata evaluate --spec heldout/strata-spec.json \
  --expect-spec-sha256 <hash from step 1> \
  --inventory out/inventory.json --regions out/regions.json \
  --baseline out/baseline.regions.json --candidate out/candidate.regions.json \
  --out out/strata.json
```

`measure` currently derives two covariates from a TIFXYZ surface:

- `mean_abs_curvature` (voxel⁻¹): the normal's rotation rate between adjacent
  quads, averaged over the two grid directions. Controls in the tests: a plane
  reads 0, a cylinder of radius R reads 1/(2R), a sphere 1/R. It is a
  mean-curvature-magnitude proxy tied to the grid, not a principal curvature.
- `axis_tilt_deg`: the angle between the sheet and the z axis.

Estimated **inter-sheet spacing/compression, CT support and winding depth** are
not measured here; supply them as additional covariates in the same files from
their own audited tools. Do not add a covariate whose measurement used model
output.

## Claim boundary

A pass means that, on these committed ROIs, every required stratum of every
preregistered covariate was adequately evaluated and the improvement held where
the geometry is hard and the labels are thin. It does **not** establish sheet
identity, topology, CT support or readability. Strata are marginal (one
covariate at a time), so a joint hard corner — high curvature *and* compressed
spacing — can still be unevaluated; add the joint cell as its own derived
covariate in the frozen spec if it matters.

The official data keeps its separate Vesuvius data terms; the MIT software
licence does not change them.
