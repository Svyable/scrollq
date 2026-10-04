# Fiber IQ: VC3D-native fiber audit

ScrolIQ audits the geometry and provenance of fiber traces without claiming that
a trace is the correct papyrus fiber or even the correct sheet.

The Vesuvius Challenge uses fibers as evidence and constraints for large-scale
unwrapping, and the current Villa/VC3D toolchain persists fibers as
`vc3d_fiber` JSON. ScrolIQ therefore reads that format directly rather than
requiring a lossy intermediate conversion. The validator is explicitly pinned
in each JSON report to Villa commit `56d7c3aeea4bbccf5f56b195ce2a44ea2cf601dd`
and `vesuvius/src/vc3d_fiber_format/__init__.py`, so later upstream schema drift
is visible instead of silently changing the meaning of an audit.

## Inputs

`scroliq-fiber` accepts:

- native VC3D `vc3d_fiber` JSON versions 1, 3, and 4;
- the existing ordered CSV interchange format
  `trace_id,x,y,z`.

Auto-detection treats `.json` as VC3D JSON and other paths as CSV. Override it
with `--format csv` or `--format vc3d-json`.

```bash
# Native VC3D fiber
scroliq-fiber fiber.json --volume-root <exact CT root> --out fiber.audit.json

# Existing CSV path
scroliq-fiber traces.csv --out traces.audit.json

# Make review findings block a CI/unwrapping pipeline.
scroliq-fiber fiber.json --volume-root <exact CT root> --fail-on-findings --out fiber.audit.json
```

## What the audit validates

For VC3D JSON the audit checks the current structural contract used by Villa:

- file versions 1, 3, and 4;
- finite XYZ `line_points` and control-point positions;
- version-3/4 control-point span ownership;
- current native tracer metadata/tracer versions;
- interpolation goal and actual interpolation mode;
- trace-to-base scale;
- native-trace meeting error and meeting-error ratio;
- the persisted tracer configuration and its numeric domains;
- version-4 span tags;
- SHA-256 and byte length of the exact input;\n- the exact Villa commit/path used as the format reference.

The line geometry is then audited for:

- **gaps**: a step longer than `--gap-factor` times that line's median
  non-zero step;
- **sharp turns**: a direction change larger than `--turn-degrees`;
- **control-line offsets**: persisted control points farther than
  `--control-line-factor` (default 4) times the rendered line's median non-zero
  step from their nearest `line_points` sample;
- **control-order inversions**: consecutive control points whose nearest rendered
  line indices move backward.

The control-line threshold is relative to each fiber's own rendered sampling
step, not an absolute voxel cutoff. These are review findings because close
self-approaches can make nearest-point assignment ambiguous.

The output separately summarizes native-trace spans, fallback spans,
interpolation modes/goals, meeting-error ratios, persisted failure codes, and
tagged spans.

## Why fallback spans are not findings

A VC3D span whose actual interpolation mode is Lasagna or cubic spline is not
automatically wrong. It may be an intentional policy choice or a valid fallback.
ScrolIQ records those spans but does not turn them into geometry findings.

That distinction matters for automation. `--fail-on-findings` blocks on
reviewable geometry discontinuities while preserving tracer/fallback provenance
as evidence rather than silently converting it into a failure verdict.

## Output and exit contract

Every report is versioned JSON and records the input digest. Supply `--volume-root` to bind the evidence to the exact CT volume; `scroliq-passport` rejects missing or mismatched bindings. Parse/schema errors
produce `status: "fail"` and exit 2. Geometry review findings produce
`status: "caution"` and normally exit 0. With `--fail-on-findings`, the same
caution report exits 2 so CI or an unwrapping pipeline can opt into a hard gate.

This mirrors the explicit advisory-versus-gating contract used by
`scroliq-mesh` and `scroliq-obj`.

## Relationship to Villa

Villa's current fiber tooling includes the VC3D format reader, native
`vc_fiber_tracer`, and `vc_fiber_trace_metric`. ScrolIQ does not replace
those algorithms. It provides a dependency-light audit boundary around their
persisted outputs so geometry discontinuities, fallback coverage, acceptance
errors, and exact-file provenance can travel through reproducible pipelines.

Upstream references:

- https://github.com/ScrollPrize/villa/tree/main/vesuvius/src/vesuvius/neural_tracing/fiber_trace
- https://github.com/ScrollPrize/villa/blob/main/vesuvius/src/vc3d_fiber_format/__init__.py
- https://github.com/ScrollPrize/villa/blob/main/volume-cartographer/apps/src/vc_fiber_trace_metric.cpp

## Current evidence boundary

The implementation has regression coverage for legacy v1 and current v3/v4
files, schema drift, native/fallback span accounting, geometry findings, input
hashing, and CLI gating.

A frozen real-data campaign now audits eight SHA-256-pinned public PHercParis4
VC3D fibers spanning four filename/annotator prefixes and June–August 2026
timestamps. Across 53,828 rendered line points and 369 control-point spans, the
campaign found 11 gap candidates and 26 sharp-turn candidates, while all 377
control points remained on the rendered lines in forward order. Fifteen spans
used fallback interpolation; the other 354 used native tracing. See
[`artifacts/2026-10-01-public-fiber-audit/`](../artifacts/2026-10-01-public-fiber-audit/).

All 11 gap candidates occur in one sampled fiber, which also has the highest
fallback share in this eight-file sample (7/28 spans). That co-occurrence is
reported for review and is not treated as evidence that fallback interpolation
caused the gaps.

The public PHercParis4 fiber directory is not asserted here to identify one
exact CT volume root, so the campaign is intentionally **not** passport
evidence. Volume-bound reports can be attached with
`scroliq-passport --fiber-audit fiber.audit.json`; the passport records them
as partial evidence and fails closed on missing or cross-volume bindings.

The next Fiber IQ evidence step is to establish a defensible exact CT-volume
mapping for public fibers and broaden the campaign toward cross-fiber
connectivity. A separate experimental CT-conditioned orientation layer now
exists as [`scroliq-fiber-frame`](fiber-frame.md): it measures depth-resolved
cross-ply frame continuity on already-rectified shallow CT slabs, but remains
outside the production path until real adjacent-winding controls pass.

GPU TEASAR/skeletonization backends are evaluated separately from this persisted
trace audit. Brook is tracked under the preregistered
[CUDA TEASAR accelerator equivalence gate](brook-teasar-gate.md), which requires
object/geometry parity and target-domain downstream evidence before an
accelerated backend is accepted for the same use. The current Brook
GPL-3.0-only license is also kept distinct from Grand Prize
submission-eligibility.
