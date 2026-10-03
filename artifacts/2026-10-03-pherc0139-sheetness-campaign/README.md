# PHerc0139 Phase-A sheetness campaign freeze — 2026-10-03

**Status before this campaign runs:** geometry-only reference probes are frozen;
independent wrong-wrap controls are frozen and measured; no Hessian sheetness
response has been computed for this campaign.

This artifact is the final preregistration gate before Phase-A
`scroliq-sheetness` inference in issue #105.

## Exact upstream evidence

Reference geometry:
`artifacts/2026-10-03-pherc0139-sheetness-prereg/reference-plan.json`

Independent wrong-wrap rule:
`artifacts/2026-10-03-pherc0139-wrong-wrap-prereg/wrong-wrap-spec.json`

Observed independent-geometry controls:
`artifacts/2026-10-03-pherc0139-wrong-wrap-run/wrong-wrap-result.json`

The wrong-wrap observation completed 32 / 32 groups with zero missing
prediction or CT chunks and explicitly records
`sheetness_response_consulted: false`.

## Engine frozen before response

The Phase-A reference engine is the existing deterministic ScrolIQ Hessian
baseline, without tuning:

- sigmas: **0.8, 1.2, 1.8 voxels**;
- beta: **0.5**;
- gamma: **0.1**;
- polarity: **bright object**;
- scale-objectness: **off**;
- robust normalization: **1st / 99th percentile**;
- Hessian normal output: **required**;
- per-cutout memory guard: **2,500,000 voxels**;
- random state: **none**;
- code revision:
  `65bb493b87795011e1bed1ed0b2e0272e0f5a733`.

The frozen plan also records the exact SHA-256 bytes of
`sheetness.py`, `sheetness_benchmark.py`, and `sheetness_campaign.py`.

## Campaign decision rule frozen before response

A positive Phase-A result requires all of:

1. score completeness = **100%**;
2. the surface beats **every** ±4 / ±8 voxel normal-offset control in at least
   **75% of the 32 groups** (at least 24 / 32);
3. median surface-minus-best-normal-offset response margin ≥ **0**;
4. predicted-normal completeness = **100%**;
5. median absolute cosine between the predicted Hessian normal and the frozen
   TIFXYZ normal ≥ **0.70**;
6. no group/spec/result is missing or invalid.

The 75% gate is an operational localization criterion, not a p-value. The
0.70 cosine gate corresponds to median angular disagreement no worse than about
45.6 degrees.

Wrong-wrap response is **mandatory descriptive evidence but not a pass/fail
criterion**. A real neighboring papyrus winding is itself sheet-like, so using
it as a negative would ask a Hessian plate detector to solve global sheet
identity.

A valid negative Phase-A result is publishable and must not be retuned into a
positive result.

## Bounded cutouts, not one giant volume

The 32 probes are spatially dispersed across the reference surface. The
campaign therefore freezes one smallest source-bounded ZYX cutout per group
that contains:

- the surface probe;
- all four signed normal offsets;
- the measured wrong-wrap control;
- the already-frozen 8-voxel halo.

The campaign planner additionally requires that the halo cover the maximum
Gaussian support plus Hessian-gradient context and that every cutout stay below
the frozen memory cap.

## Freeze command

The workflow runs exactly:

```bash
scroliq-sheetness-campaign freeze \
  --reference-plan artifacts/2026-10-03-pherc0139-sheetness-prereg/reference-plan.json \
  --wrong-wrap-spec artifacts/2026-10-03-pherc0139-wrong-wrap-prereg/wrong-wrap-spec.json \
  --wrong-wrap-result artifacts/2026-10-03-pherc0139-wrong-wrap-run/wrong-wrap-result.json \
  --code-revision 65bb493b87795011e1bed1ed0b2e0272e0f5a733 \
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
  --min-median-abs-cosine 0.70 \
  --out artifacts/2026-10-03-pherc0139-sheetness-campaign/campaign-plan.json
```

The output is create-only. A rerun after the plan exists must stop at the guard.

## Frozen plan produced

The create-only workflow produced a plan with:

- **32 / 32** groups ready;
- **0** blocked groups;
- **823,643** voxels across all planned cutouts;
- largest individual cutout: **46,464 voxels**;
- frozen 8-voxel halo satisfying the planner's support/context check;
- sheetness engine SHA-256:
  `d04c84aaadad5d3b42f372b9702c3980ae4dad8cc895fa0b02c9264d44473a51`;
- v3 benchmark SHA-256:
  `0c0b3b5c4eeedfc8a5002b356439c874849301588c5a1c2ee53e9cf43eb88e79`;
- campaign planner SHA-256:
  `6ba6a78cb5ab45c8ddb462df59f99034ce0697617d3e3502e61b5f57b411a243`.

These are descriptive properties of the already-frozen plan. No sheetness
response, response summary, or Hessian normal field was generated or inspected
during this freeze.

## What may happen after this freeze

Only after `campaign-plan.json` is committed may the execution campaign:

1. extract each exact frozen bbox with `scroliq-ct-cutout` using the already
   committed PASS ZPA report;
2. run `scroliq-sheetness` with the exact engine configuration above;
3. use `scroliq-sheetness-campaign seal-group` to bind each deterministic
   cutout/report to one measurement-only v3 spec;
4. run `scroliq-sheetness-eval` for every group;
5. aggregate all 32 frozen groups with the campaign decision rule.

No probe, offset, bbox, sigma, polarity, normalization choice or threshold may
change after the first sheetness response is observed. A change creates a new
campaign/version.

## Claim boundary

This preregistration does not claim that sheetness works. It only fixes the
test that will decide whether this baseline locally distinguishes the known
reference surface from nearby off-surface probes and aligns with its local
normal.

Even a pass would not establish global winding, physical sheet identity,
topology, ink or readability.
