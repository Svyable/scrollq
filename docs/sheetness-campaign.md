# Dispersed sheetness campaign

`scroliq-sheetness-campaign` turns the single-cutout sheetness tools into a
preregistered multi-probe experiment without creating one enormous CT cutout.

The intended order is strict:

```text
independent geometry frozen
        ↓
campaign freeze
        ↓
bounded CT cutouts
        ↓
deterministic sheetness inference
        ↓
seal one v3 measurement spec per group
        ↓
scroliq-sheetness-eval per group
        ↓
campaign aggregate
```

The **campaign freeze happens before any sheetness response exists**.

## Why one cutout per group

A reference surface can span thousands of voxels along the scroll axis. A
single bounding box around all probes would make a local Hessian experiment
unnecessarily large and would weaken the existing memory guard.

Instead, each frozen group gets the smallest half-open global ZYX box that
contains:

- the known reference-surface probe;
- all frozen signed normal-offset controls;
- the independently nominated wrong-wrap control, when available;
- the already-preregistered halo on every axis.

Every cutout remains independently traceable through `scroliq-ct-cutout`.

## Freeze

All parameters are explicit. The CLI intentionally has no silent scientific
defaults for the campaign.

Example:

```bash
scroliq-sheetness-campaign freeze \
  --reference-plan artifacts/.../reference-plan.json \
  --wrong-wrap-spec artifacts/.../wrong-wrap-spec.json \
  --wrong-wrap-result artifacts/.../wrong-wrap-result.json \
  --code-revision <40-hex-git-sha> \
  --sigmas 0.8,1.2,1.8 \
  --beta 0.5 \
  --gamma 0.1 \
  --bright-object \
  --no-scale-objectness \
  --normalize \
  --normalize-low 1 \
  --normalize-high 99 \
  --max-voxels 2500000 \
  --min-score-completeness 1 \
  --min-normal-offset-win-fraction 0.75 \
  --min-median-normal-offset-margin 0 \
  --min-normal-completeness 1 \
  --min-median-abs-cosine 0.7 \
  --out campaign-plan.json
```

The freeze verifies that:

- reference-plan bytes match the hash bound by the wrong-wrap preregistration;
- wrong-wrap result bytes bind the exact frozen wrong-wrap spec;
- no sheetness response was consulted by the geometry-source step;
- no prediction or CT chunks were missing during wrong-wrap nomination;
- the group set is unchanged;
- every expanded bbox stays inside the exact audited source;
- every group stays below the declared sheetness memory cap;
- the preregistered halo is large enough for the maximum Gaussian support plus
  Hessian-gradient context;
- engine source files and the Git revision are recorded.

If a wrong-wrap control is missing, the group is retained as
`blocked-missing-wrong-wrap`; it is not silently replaced.

## Phase-A engine configuration

For the first PHerc0139 reference campaign, the proposed frozen engine is the
unmodified reference configuration already documented and regression-tested in
ScrolIQ:

- sigma = 0.8, 1.2, 1.8 voxels;
- beta = 0.5;
- gamma = 0.1;
- bright-object polarity;
- scale-objectness disabled;
- robust normalization at the 1st/99th percentiles;
- Hessian normal output required;
- deterministic; no random state;
- 2.5 million voxel hard cutout guard.

This is deliberately a **reference baseline**, not a tuned optimum.

The campaign-level decision rule is frozen separately:

- score completeness = 100%;
- surface beats every ±4/±8 normal-offset control in at least 75% of groups;
- median surface-minus-best-normal-offset margin ≥ 0;
- normal completeness = 100%;
- median absolute cosine between Hessian normal and frozen surface normal ≥
  0.70.

The 75% localization gate means at least 24 of 32 frozen probes must win. The
0.70 normal gate corresponds to a median angular disagreement no worse than
about 45.6°. These are operational falsification gates, not p-values.

Wrong-wrap response is **descriptive only**. A real neighboring papyrus layer
is itself sheet-like, so requiring the reference sheet to beat it would turn a
sheetness detector into an unjustified sheet-identity classifier.

A negative result is a valid result and should remain published.

## Extract the cutouts

For each ready group, use the exact bbox from the frozen plan:

```bash
scroliq-ct-cutout \
  --ct-url <exact-public-CT-url> \
  --volume-root <exact-volume-root> \
  --zpa-report <frozen-zpa-report.json> \
  --start Z,Y,X \
  --stop Z,Y,X \
  --out cutouts/<group>.npy \
  --manifest cutouts/<group>.json
```

Do not recompute a "nicer" box after seeing CT intensity.

## Run deterministic sheetness

For every cutout, use the frozen engine exactly:

```bash
scroliq-sheetness cutouts/<group>.npy \
  --out-prefix fields/<group> \
  --sigmas 0.8,1.2,1.8 \
  --beta 0.5 \
  --gamma 0.1 \
  --bright-object \
  --normalize-low 1 \
  --normalize-high 99 \
  --write-normal \
  --max-voxels 2500000
```

The campaign sealer rejects changed sigmas, beta/gamma, polarity,
scale-objectness, normalization, missing normal output, changed cutout bytes,
changed bbox, or changed source attestation.

## Seal a group

The v3 evaluator requires the actual deterministic report hash, which cannot
exist before inference. `seal-group` solves that without moving the
scientific goalposts: geometry, engine choices, and the campaign decision rule
already live in the pre-response campaign plan; sealing only binds the actual
cutout/report bytes.

```bash
scroliq-sheetness-campaign seal-group \
  --plan campaign-plan.json \
  --group-id surface-0001 \
  --cutout-manifest cutouts/surface-0001.json \
  --sheetness-report fields/surface-0001.sheetness.json \
  --out specs/surface-0001.json
```

Each per-group v3 spec uses a **measurement-only rule**: complete score and
normal fields are required, but no single group decides the scientific
campaign. This prevents a global 75%-of-groups hypothesis from being
misinterpreted as a 75% threshold on every one-group evaluation.

Then evaluate:

```bash
scroliq-sheetness-eval \
  --spec specs/surface-0001.json \
  --cutout-manifest cutouts/surface-0001.json \
  --report fields/surface-0001.sheetness.json \
  --response fields/surface-0001.sheetness.npy \
  --normal fields/surface-0001.normal-zyx.npy \
  --out results/surface-0001.json
```

## Aggregate

After every frozen group has a result:

```bash
scroliq-sheetness-campaign aggregate \
  --plan campaign-plan.json \
  --specs-dir specs \
  --results-dir results \
  --out campaign-result.json
```

The aggregate is where the preregistered scientific rule is applied. Missing,
invalid, or blocked groups stay in the 32-group denominator and cause the
no-missing-evidence check to fail.

Use `--require-pass` only when the campaign is being used as a CI gate. A
valid scientific negative result otherwise exits zero and remains publishable.

## Claim boundary

A positive Phase-A result would establish that this fixed Hessian baseline
locally concentrates on the known PHerc0139 reference surface relative to
nearby normal offsets and that its local normal is directionally consistent.

It would **not** establish:

- correct global winding;
- physical sheet identity of the wrong-wrap probes;
- topology or unrolling quality;
- recto/verso identity;
- ink;
- readability.

The Grand Prize transfer must reuse the frozen engine configuration and
evaluation procedure on an exact eligible volume. Changing the engine after
seeing Phase-A results creates a new campaign/version.
