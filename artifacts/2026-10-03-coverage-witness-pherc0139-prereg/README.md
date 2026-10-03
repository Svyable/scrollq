# PHerc0139 coverage-witness deletion preregistration

**Status: frozen before witness response is read.**

This is the first real-papyrus calibration step for
[issue #151](https://github.com/Svyable/scrollq/issues/151). It does not add a
production diagnostic.

The experiment asks one deliberately narrow question:

> If a known patch of the public PHerc0139 w035 surface is removed from the
> submitted/reference point cloud, does the independently published
> `surface-m7` prediction still provide enough local evidence to identify the
> omission?

The reference surface, exact 9.362 µm CT, independent prediction source,
material-grid deletion centers, patch sizes, normal-search offsets, distance
thresholds, synthetic parallel-sheet substitution, and pass/fail criteria are
all frozen in [spec.json](spec.json) before any witness response is inspected.

## Why this comes before a global coverage-witness tool

The current `scroliq-recto-coverage` audit is correct but inventory-relative:
it cannot discover papyrus absent from its declared reference inventory. A
global independent witness test could close part of that gap, but first the
candidate witness source must demonstrate that it can detect **deliberate
omissions on real papyrus**.

This stage therefore conditions witness association on the known w035 surface.
That makes it a calibration/deletion-control experiment, not an unknown-surface
discovery claim.

A positive result may unlock Stage B, where witness points are extracted
without conditioning on the submitted surface and intact-surface false
unexplained clusters are measured. Stage B must be separately frozen before it
runs.

## Frozen source identity

Reference:

- `PHerc0139/segments/20260317000000-w035_2026031718`
- `mesh/20260317000000-on-20250728140407-9.362um.tifxyz`
- exact CT:
  `PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr`

Independent witness source:

- published `surface-m7`, model `20260413222639`
- exact level-0 prediction on the same CT grid
- stored threshold `>127`
- masked-CT support `>0`

These are reused from the already-frozen wrong-wrap campaign rather than
selected for this experiment after seeing a response.

## Frozen deletions

Six centers come directly from the already-frozen 32 geometry-only sheetness
probes. Each receives 21x21, 31x31, and 41x41 material-grid deletions.

No center may be replaced because prediction support is inconvenient.

For each independently supported material point, the witness is the nearest
supported `surface-m7` sample among signed normal offsets
`[-2,-1,0,+1,+2]` voxels. A deletion succeeds when those witness points become
farther than the frozen 8-voxel primary tolerance from the counterfactual
submitted surface while witnesses outside the deletion remain explained.

A second falsifier replaces the omitted surface by a +20-voxel normal-shifted
parallel copy. This is intentionally synthetic; it tests whether nearby
parallel geometry can incorrectly satisfy the coverage metric.

## Claim boundary

Even a clean pass will **not** prove that `surface-m7` can discover every
unknown omitted recto region. It will prove only that the independently
generated source can preserve omission evidence for known real w035 material
under the frozen deletion controls.

That distinction is the reason this is a research artifact instead of a new
ScrollQ CLI.
