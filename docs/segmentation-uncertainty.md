# Structural segmentation uncertainty

`scroliq-segmentation-uq` adds a fail-closed uncertainty layer on top of trusted
`scroliq-segmentation-validate` results. It does **not** change a segmentation,
fit a surface, or choose a prize region.

The audit separates two failure classes that should not be collapsed into one
"uncertainty" number:

1. **Boundary uncertainty** — `symmetric_p95_voxels`, the held-out p95 distance
   between prediction and truth.
2. **Structural/component uncertainty** — whether every disconnected truth
   component has at least one predicted vertex within the preregistered
   segmentation tolerance. The trusted scorer emits
   `truth_component_recall_any`; a value below 1 means at least one truth
   component received zero support.

The implementation is independent ScrollQ code. It does not copy the 2026
MICCAI tumor-segmentation repository whose license had not been independently
verified when this gate was designed. As of 2026-10-04 that repository declares
the MIT license; this implementation remains independent, and any future reuse
needs a pinned-revision entry in `THIRD_PARTY_NOTICES.md`. The set-level
follow-up is queued in
[`research/structure-aware-conformal-surface-uncertainty.md`](research/structure-aware-conformal-surface-uncertainty.md).

## Why vacuity is explicit

A coverage guarantee can be mathematically valid and still be useless. This
tool therefore reports a result as **vacuous** when either:

- the finite-sample corrected conformal rank is larger than the available
  calibration set, so no finite distribution-free upper bound is available;
- the calibrated boundary radius exceeds a preregistered useful limit; or
- the component bound is 1, meaning the calibrated set still permits a
  completely missed truth component.

A vacuous result never passes `SURFACE_STRUCTURAL_UQ_NONVACUOUS`.

For a one-sided split-conformal upper bound, the tool uses the standard finite
sample rank

`ceil((n_calibration + 1) * (1 - alpha))`.

For example, a nominal 95% bound cannot be finite from only ten calibration
regions. ScrollQ records that as insufficient calibration instead of silently
using the calibration maximum.

## Frozen spec

Freeze the split before looking at results:

```json
{
  "schema_version": 1,
  "method": "split_conformal",
  "alpha": 0.05,
  "boundary_metric": "symmetric_p95_voxels",
  "component_metric": "truth_component_recall_any",
  "max_nonvacuous_boundary_voxels": 5.0,
  "calibration": {
    "dataset": "blind-surface-cal-v1",
    "region_ids": ["c01", "c02", "c03"]
  },
  "test": {
    "dataset": "blind-surface-test-v1",
    "region_ids": ["t01", "t02"]
  }
}
```

The short example above intentionally has too few calibration regions for
`alpha=0.05`; it demonstrates the fail-closed behavior rather than a passing
campaign.

Hash the frozen contract before inference:

```bash
scroliq-segmentation-uq \
  --spec uq-spec.json \
  --print-spec-hash
```

Then evaluate immutable trusted segmentation result files:

```bash
scroliq-segmentation-uq \
  --spec uq-spec.json \
  --calibration calibration-results.json \
  --test test-results.json \
  --out structural-uq.json \
  --format github
```

Calibration and test results must contain exactly the preregistered region IDs
and must have identical model/checkpoint/script/config provenance. Failed or
missing regions are never dropped to make calibration look better.

## Interpretation

A passing artifact says that, for this frozen exchangeable calibration/test
experiment, the boundary and complete-component-omission channels both produced
nonvacuous conformal bounds and the untouched test set met the nominal coverage
level.

It does **not** prove sheet identity, topology, readability, or coverage under
distribution shift. It should complement, not replace, held-out bidirectional
surface coverage, winding/fiber checks, CT support, and ink falsification.
