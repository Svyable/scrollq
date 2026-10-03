# Sheetness preregistration

`scroliq-sheetness-preregister` separates scientific choices from
data-dependent artifact hashes for the Stage-1 sheetness experiment.

This exists because the final `scroliq-sheetness-eval` spec necessarily names
the cutout and sheetness-output hashes. Those files do not exist until after CT
voxels have been read. A Git commit containing only that final spec therefore
does not, by itself, prove that thresholds and probes were fixed before the
response field was visible.

The preregistration is the pre-result half of that proof.

## What must be frozen first

A `scroliq-sheetness-preregistration/1` JSON record fixes, before CT-derived
sheetness values exist:

- experiment ID and phase (`reference` or `transfer`);
- exact public CT URL and exact `volume_root`;
- exact ZPA-report SHA-256 and metadata-semantics attestation;
- one half-open global level-0 ZYX cutout box;
- the complete deterministic sheetness engine configuration;
- the complete current benchmark decision rule;
- a geometry-only probe-selection rule;
- stop/failure rules;
- every surface, normal-offset and wrong-wrap probe in **global continuous ZYX**;
- hash-pinned TIFXYZ coordinate sources for surface and wrong-wrap geometry.

The validator rejects result-derived top-level fields such as cutout,
sheetness-report, response, normal, metric, decision-check, or result hashes.

The selection rule must explicitly state:

```json
{
  "ct_intensity_used": false,
  "sheetness_outputs_used": false
}
```

That is a contract statement, not a substitute for review of the generating
script and commit history.

## Controls are not arbitrary points

For each probe group, the preregistration requires symmetric `-1` and `+1`
normal-offset controls at one frozen distance. Their global coordinates are
recomputed from the frozen surface coordinate and frozen reference normal; a
hand-edited mismatch is invalid.

Each group also requires at least one `wrong-wrap` ambiguity probe from a
different hash-pinned TIFXYZ coordinate geometry. Merely renaming the same
coordinate hashes does not count.

Wrong-wrap response remains descriptive in `scroliq-sheetness-eval`: a
neighboring papyrus winding is itself sheet-like. Its purpose is to expose the
local detector's sheet-identity limitation, not to manufacture a negative.

## Freeze before CT response

Validate the preregistration and write a create-only receipt:

```bash
scroliq-sheetness-preregister validate \
  --prereg campaign/preregistration.json \
  --out campaign/preregistration.receipt.json
```

The receipt records both the raw file SHA-256 and canonical semantic SHA-256,
plus the exact benchmark schema. Commit **both files before running**
`scroliq-ct-cutout` or `scroliq-sheetness`.

A valid receipt explicitly states that it contains no CT response values.

## Run without changing the scientific choices

After the preregistration commit:

1. create the exact provenance-bound CT cutout with `scroliq-ct-cutout`;
2. run `scroliq-sheetness` with exactly the frozen engine configuration and
   `--write-normal`;
3. do not edit the preregistration if the result is unattractive.

A failed reference experiment is a result. Any changed parameter, threshold,
probe rule or target requires a new preregistration artifact.

## Finalize the evaluation spec

The finalizer is deliberately allowed to add only information that could not
exist before the run:

```bash
scroliq-sheetness-preregister finalize \
  --prereg campaign/preregistration.json \
  --cutout-manifest out/cutout.json \
  --sheetness-report out/cutout.sheetness.json \
  --out out/sheetness-eval.spec.json
```

Before writing the create-only spec, it verifies:

- exact CT URL and volume root did not drift;
- exact preregistered cutout bbox did not drift;
- retained ZPA report hash and source attestation did not drift;
- the cutout has zero missing source chunks;
- the sheetness input hash equals the cutout hash;
- sheetness method, sigmas, beta, gamma, polarity, scale-objectness and
  normalization settings exactly match the preregistration;
- the normal output exists;
- every frozen global probe lies inside the cutout's trilinear interpolation
  domain.

It then converts the frozen global coordinates to local cutout coordinates and
adds only the measured cutout/report file hashes. Geometry provenance and
frozen global coordinates are retained as extra evidence in the final benchmark
spec.

The resulting spec can be passed directly to `scroliq-sheetness-eval`.

## Reference then transfer

For the first campaign, use a public known-good reference surface first. Only
after its disposition is frozen should the unchanged engine configuration and
decision thresholds be transferred to a Grand Prize-eligible volume.

A transfer may use new geometry-specific probes and a new exact cutout, but
those probes must be generated under the same committed geometry-only selection
rule and frozen in a new preregistration before target CT sheetness is inspected.

This gives the Stage-1 result a stronger anti-tuning story than direct tuning on
the prize target.
