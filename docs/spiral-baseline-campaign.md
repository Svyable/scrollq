# Grand Prize Spiral baseline campaign

Status: execution contract. This document deliberately does not introduce a new
reconstruction algorithm.

Tracking:
- PHerc0826 baseline bring-up: create/track in the campaign issue
- PHerc0800 sealed transfer evaluation: #123

## Objective

Get a real official-villa Spiral baseline running as quickly as possible, then
test whether what we learned transfers to a second exact Grand-Prize volume
without using prediction-region ink to select geometry.

The endpoint is whole-recto reconstruction and legible text. ScrolIQ is the
experiment/evidence harness, not the reconstruction product.

## Two-scroll design

### PHerc0826 — execution bring-up

Exact Grand Prize volume: `20250821151701`.

Use PHerc0826 first because the currently published public input stack is
substantially more complete than PHerc0800's:

- tracks: published;
- crossings cache: published;
- umbilicus: published;
- Lasagna normals: published;
- surface prediction: published.

The public `eligible-spiral-dataset` project also documents a PHerc0826
whole-scroll crossings cache covering `z_range [4500, 16919]` and a real
30,000-iteration fit on z `[11000, 12000)`. This lowers execution uncertainty:
we can reproduce a known path before changing reconstruction code.

PHerc0826 is a bring-up choice, not a claim that it is intrinsically the easiest
scroll or guaranteed to be the final submission scroll.

### PHerc0800 — sealed transfer / geometry evaluation

Exact Grand Prize volume: `20250521135224`.

Keep the already-frozen, ink-blind ScrolIQ split as independent transfer
evidence:

- fit/held-out split:
  `artifacts/2026-09-30-grand-prize-qualifier/pherc0800_geometry_split.json`;
- held-out windows: `7472`, `10464`, `15872`;
- held-out geometry is evaluation-only.

PHerc0800 currently has published tracks, crossings, normals and surface
prediction, but no published umbilicus according to the public eligible-scroll
survey. Do not invent one. A PHerc0800 run begins only after an umbilicus is
created through the documented VC3D workflow and its human-input time is logged,
or an authoritative public one becomes available.

This separation prevents us from repeatedly debugging the fitter against the
same geometry later used as our transfer test.

## Frozen software baseline

Pin the first campaign to:

`ScrollPrize/villa@5a4388f08cc547e6a1a037f949173e731a3e7aa2`

The SHA is a reproducibility pin, not a claim that it is superior to later
revisions.

Do not fork or reimplement the fitter for baseline bring-up.

## Public dataset assembly

Prefer the MIT-licensed public
`ttendoscopie-creator/eligible-spiral-dataset` assembler for the initial
PHerc0826 dataset rather than recreating its discovery logic in ScrolIQ.

Important constraints from that project and villa:

1. It requires `--outward-sense`; do not guess the winding sense.
2. Preserve the published crossings cache fingerprint/mtime handling so villa
   does not silently discard and rebuild it.
3. `input_use_tracks` must be explicitly enabled for the current recipe.
4. Assemble/download Lasagna inputs separately; the public assembler surveys
   their existence but does not fetch them.
5. Verify `normal_zarr_group` and `lasagna_scale` against the exact store
   metadata/template before fitting. Never transplant values from another
   scroll.

Record source URL, size and SHA-256 for every supervision file actually used.

## Non-negotiable separation

No ink output may choose:

- baseline configuration;
- checkpoint;
- reconstruction intervention;
- PHerc0800 held-out windows;
- geometry promotion decisions.

Failed/missing held-out predictions stay in the denominator.

## Phase A — reproduce a known PHerc0826 bounded fit

Start with the documented z band `[11000, 12000)` so execution can be checked
against an already-reported real run.

Capture:

- exact eligible volume identity;
- villa commit;
- dataset assembler commit;
- generated `spiral-scroll.json`;
- published umbilicus SHA-256;
- track DBM / crossings / provenance hashes;
- Lasagna input identities and multiscale evidence;
- all config overrides, including `input_use_tracks=true`;
- seeds/RNG state;
- stdout/stderr;
- hardware/software environment;
- wall time and peak host/GPU memory;
- checkpoint/model-state hashes;
- raw preview/export hashes.

A fit that optimizes but cannot export/evaluate is not a successful baseline.

## Phase B — official export only

Use villa's `flatten_spiral_checkpoint.py` path for checkpoint -> Lasagna ->
TIFXYZ. Do not build a ScrolIQ-specific exporter.

Bind every exported surface to the checkpoint and exact CT identity that
produced it.

## Phase C — establish PHerc0826 failure frontier

After the bounded reproduction works, expand z coverage and classify failures
from evidence:

1. coverage hole / no recovered surface;
2. wrong neighboring winding or sheet switch;
3. geometric displacement on the intended sheet;
4. discontinuity / tear handling;
5. insufficient or contradictory winding constraints;
6. patch-connectivity failure;
7. acceptable 3-D surface but flattening failure;
8. coordinate/source/provenance mismatch;
9. unknown.

Preserve raw measurements and spatial locations. Do not collapse them into a
synthetic quality score.

## Phase D — one reconstruction intervention

Only after a concrete baseline failure is measured:

1. preregister the failure hypothesis;
2. change one reconstruction mechanism;
3. rerun the same frozen evaluation;
4. require improvement on the targeted failure without material regression;
5. retain negative results.

Candidate mechanisms are chosen by evidence, not in advance.

## Phase E — PHerc0800 transfer test

After the first PHerc0826 intervention is frozen, transfer the method to
PHerc0800.

Create/log the minimum required umbilicus annotation if no authoritative public
one exists. Do not expose the frozen held-out meshes to fitting or parameter
selection.

Evaluate all three frozen held-out windows with the existing ScrolIQ geometry
contract. This is where we test whether an intervention learned from PHerc0826
generalizes beyond the scroll used for bring-up.

## Phase F — whole-scroll and text

Promote only interventions that increase reliable recoverable recto surface,
not merely a local geometry metric.

Then:

- expand toward full recto coverage;
- identify detached flakes/patches;
- preserve column-scale geometry suitable for TIFXYZ/VC3D;
- log all human input against the Grand Prize eight-hour allowance;
- freeze geometry;
- flatten/render;
- run held-out-safe ink inference;
- assess preserved characters and legible lines separately.

Prediction-region ink never retroactively selects reconstruction parameters.

## Stop conditions

Stop and repair the baseline instead of expanding if:

- exact-volume identity is uncertain;
- winding sense is guessed rather than evidenced;
- an umbilicus is invented from a crude centroid/barycentre;
- Lasagna scale/group is unresolved;
- crossings are silently rebuilt because provenance/fingerprint handling failed;
- held-out geometry leaked into supervision;
- export cannot be traced to its checkpoint;
- the surface cannot be evaluated in the intended coordinate frame.

## Why this is faster

PHerc0826 minimizes bring-up uncertainty; PHerc0800 preserves independent
transfer evidence. This spends engineering time on the first measured
reconstruction failure instead of on rebuilding already-published dataset
assembly, exporter, or audit machinery.
