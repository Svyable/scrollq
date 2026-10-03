# PHerc0800 sheetness preregistration — 2026-10-03

This directory freezes the first real-data experiment for the new
`scroliq-sheetness` baseline **before any CT cutout is extracted or real
sheetness value is measured**.

The experiment asks one narrow question:

> On one exact 2027 Grand Prize CT volume, does the frozen Hessian plate
> response preferentially support points on a published surface over fixed
> normal-offset controls and a geometrically distinct nearby-surface control?

It does not ask whether the mesh is the correct winding, whether recto coverage
is complete, or whether ink is readable.

## Frozen target

The target is **PHerc0800**, exact eligible volume
`20250521135224` (8.64 µm). The target and eligible volume ID come from the
committed Grand Prize manifest.

The primary mesh is **not hand-picked after looking at CT response**.
`derive.py` selects the lexicographically first PHerc0800 mesh among the six
exact-volume TIFXYZ rows that were already `pass` / `clean` / no-findings in
the frozen corpus Mesh IQ audit:

`20251028213516-auto_grown_20251028213516907`

The other five clean exact-volume PHerc0800 meshes form a candidate pool only.
They are **not automatically called wrong wraps**. All six audit bounding boxes
overlap, so a different segment ID alone is insufficient evidence that two
meshes represent different physical sheets.

## Wrong-wrap gate

At runtime, the coordinate files must first match the SHA-256 values frozen in
`protocol.json`.

For each candidate mesh, the preparation step must compare interior TIFXYZ
vertices to the primary surface and retain only nearest-point pairs whose:

- 3-D separation is **12–96 level-0 voxels**, inclusive;
- surface normals have **absolute cosine >= 0.8**;
- both vertices have valid +/-1 row and +/-1 column neighbours.

A candidate needs at least **four** such pairs. The candidate with the largest
eligible-pair count wins; ties go to the lexicographically smaller segment ID.

If no candidate satisfies that rule, **the experiment stops as inconclusive**.
A duplicate surface, distant background point, normal offset, or another scan
must not be relabeled as a wrong-wrap control just to make the benchmark run.

## Volume-context gate

There is a deliberate provenance blocker in the public evidence.

The frozen mesh audit records the registration root as
`community-uploads/forrest/volcomp/PHerc0800/volumes/20250521135224-...`,
while the Grand Prize CT is the top-level exact eligible S3 root
`PHerc0800/volumes/20250521135224-...`.

This protocol does **not** treat a shared volume ID as proof that those two
paths carry the same coordinate frame. Before CT extraction, one of these must
exist:

1. the downloaded TIFXYZ `meta.json` itself identifies the exact eligible
   volume in `target_volume`; or
2. a separately hash-pinned volume-context artifact proves the registered
   source and eligible CT share the required level-0 coordinate frame.

Otherwise the campaign stops and publishes `unbound` rather than sampling the
wrong CT.

## Frozen parameters

The sheetness engine is fixed at:

- sigmas: `0.8, 1.2, 1.8`
- beta: `0.5`
- gamma: `0.1`
- bright object: yes
- scale objectness: no
- normalization: 1st–99th percentile
- normal output: yes
- stochasticity: none

Four local probe groups are required. Normal-offset controls are fixed at
**-8 and +8 voxels** along the mesh normal. The local cutout gets 12 voxels of
padding and may not exceed 2,500,000 voxels; an oversize box is a stop
condition, not an invitation to choose another region.

The preregistered `scroliq-sheetness-eval` decision rule is:

- score completeness >= **1.00**
- surface beats all controls in >= **0.75** of all groups
- median surface-minus-best-control >= **0.00**
- normal completeness >= **1.00**
- median absolute cosine to the reference mesh normal >= **0.70**

A FAIL is published as FAIL. These values are not changed after seeing the
real result.

## Geometry stress control

The protocol also pins PHerc1447
`20251105093211-z_dbg_gen_00320`, the already-known multi-defect geometry
control. Its frozen Mesh IQ findings include 153 connected components, 1,335
local jump edges, 386 severe normal reversals, and p95 local stretch 5.07.

This is **not** assumed to have low sheetness. It may contain real papyrus.
Its role is to enforce a claim boundary: even a strong physical sheetness
response must never erase independent evidence that the mesh topology/geometry
is broken.

## Reproduce the preregistration

No network access is needed:

```bash
python artifacts/2026-10-03-sheetness-preregistration/derive.py --check
```

The corresponding pytest runs the same check in CI. `derive.py` rebuilds
`protocol.json` only from the committed September/October evidence snapshot
named in the protocol. Any later artifact drift fails instead of silently
changing the experiment.

## What comes next

The measured campaign must be a separate commit/PR. It must preserve this
protocol and add, without editing it:

1. a fresh ZPA PASS report for the exact eligible PHerc0800 CT;
2. volume-context evidence;
3. hash-verified TIFXYZ downloads and the mechanically selected control mesh;
4. a frozen generated probe spec;
5. a `scroliq-ct-cutout` manifest;
6. `scroliq-sheetness` outputs;
7. `scroliq-sheetness-eval` output, whether PASS or FAIL.

Only after a valid measured sheetness campaign exists may the preregistered
horizon-path work proceed.
