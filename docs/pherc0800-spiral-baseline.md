# PHerc0800 official Spiral baseline campaign

Status: execution contract. This document deliberately does not introduce a new
reconstruction algorithm.

Tracking issue: #123

## Objective

Run the official `ScrollPrize/villa` Spiral fitter on the exact Grand Prize
PHerc0800 volume, evaluate recovery against the already-frozen ink-blind
geometry split, and let measured failures choose the first reconstruction
intervention.

The endpoint is whole-recto reconstruction and legible text. Geometry metrics
are controls, not the prize objective.

## Frozen identities

| Item | Frozen value |
| --- | --- |
| Scroll | PHerc0800 |
| Prize volume | `20250521135224` |
| Villa revision | `5a4388f08cc547e6a1a037f949173e731a3e7aa2` |
| Candidate pool | `artifacts/2026-09-30-grand-prize-qualifier/geometry_candidate_pool.json` |
| Split | `artifacts/2026-09-30-grand-prize-qualifier/pherc0800_geometry_split.json` |
| Held-out windows | `7472`, `10464`, `15872` |
| Held-out use | evaluation only; never fitter supervision or parameter selection |

The villa SHA is a reproducibility pin, not a claim that this revision is
better than later revisions.

## Non-negotiable separation

Do not inspect ink output to choose the baseline configuration, checkpoint,
held-out windows, or reconstruction intervention. Do not feed held-out w020 or
w100 geometry to the fitter. Failed/missing predictions remain in the
denominator.

The first pass uses only fit-role geometry and other supervision whose
provenance is recorded and which does not leak the held-out cores.

## Dataset preflight

Create a villa-compatible dataset root outside this repository. Record SHA-256
for every file used as fitter supervision.

The current official fitter requires `spiral-scroll.json` and
`umbilicus.json`. Its scroll specification must be built from PHerc0800's
own catalog/store metadata.

In particular, **do not copy `normal_zarr_group` or `lasagna_scale` from
another scroll**. Read the PHerc0800 Lasagna store's own OME-Zarr multiscales
metadata and record the evidence used to derive both values. The villa
documentation warns that a mismatch can silently load normals at the wrong
resolution.

Before fitting, build the resident-pool sidecars for the selected Lasagna
normal/gradient group using the pinned villa revision. Preserve the packer
command and logs.

Preflight must fail closed if any of these are unresolved:

- exact eligible CT volume identity;
- scroll handedness / z-direction metadata needed by `spiral-scroll.json`;
- umbilicus coordinate frame and scale;
- Lasagna normal group and actual downsample factor;
- supervision source hashes;
- fit/held-out exclusion manifest.

## Phase A: bounded smoke fit

Use one fit-role axial region first. The smoke fit exists to prove that input
coordinates, stores, configuration, GPU execution, checkpointing, preview
export, and flattening agree before paying for a larger run.

Run the pinned villa `spiral-fitting/fit_spiral.py` with configuration
overrides captured verbatim. Capture:

- command/environment variables;
- resolved fit config;
- seed/RNG declarations;
- stdout/stderr;
- host/GPU/software inventory;
- wall time and peak memory where available;
- checkpoint SHA-256;
- model-state SHA-256 from villa artifacts;
- raw preview/export hashes.

A successful optimization run without a usable exported surface is not a
successful smoke fit.

## Phase B: export through the official path

Do not write a ScrolIQ-specific flatten/export bridge.

The pinned villa revision provides `flatten_spiral_checkpoint.py`, which
reconstructs the fitted surface from a checkpoint, invokes Lasagna, and writes
TIFXYZ. Use that path and record its command/config/output hashes.

The resulting surface must be traceable to the same checkpoint and exact CT
identity used by the fit.

## Phase C: sealed held-out recovery

Run the baseline without held-out geometry supervision and evaluate all frozen
held-out cores:

- z 7472
- z 10464
- z 15872

Report at minimum:

- attempted targets;
- recovered targets;
- missing targets;
- geometric residuals for recovered targets;
- completeness;
- explicit failures.

Use existing ScrolIQ evaluation commands where possible. Add an adapter only if
the villa export cannot be represented by an existing input contract.

## Failure-frontier classification

Each failed or materially bad held-out region receives evidence for one or more
of these labels:

1. coverage hole / no recovered surface;
2. wrong neighboring winding or sheet switch;
3. geometric displacement on the intended sheet;
4. discontinuity / tear handling;
5. insufficient or contradictory winding constraints;
6. patch-connectivity failure;
7. acceptable 3-D surface but flattening failure;
8. coordinate/source/provenance mismatch;
9. unknown.

Do not manufacture a composite score. Preserve raw measurements and spatial
locations.

## Intervention gate

No reconstruction intervention starts until the baseline identifies a concrete
failure mechanism.

Then change one mechanism at a time. The preregistration for that intervention
must state:

- the observed failure it targets;
- the exact code/config change;
- the frozen evaluation set;
- the primary metric expected to move;
- regression checks;
- stop/revert condition.

Negative results are retained.

## Campaign artifact

Write results to a new dated artifact directory; never mutate the frozen
September artifacts. It should contain a README plus machine-readable manifests
for source identities, inputs, resolved configuration, outputs, evaluation, and
the decision on the next intervention.

Human annotation/input time is logged from the first manual action so the
Grand Prize eight-hour allowance is auditable.

## Stop conditions

Stop and fix the baseline rather than expanding the run if:

- exact-volume identity is uncertain;
- a coordinate transform is inferred rather than evidenced;
- Lasagna scale/group is unresolved;
- held-out geometry leaked into supervision;
- export cannot be traced to its checkpoint;
- the surface cannot be evaluated in the frozen coordinate frame.

Only after a reconstruction candidate is frozen do we flatten/render for ink
and legibility assessment. Prediction-region ink never retroactively selects
the reconstruction.
