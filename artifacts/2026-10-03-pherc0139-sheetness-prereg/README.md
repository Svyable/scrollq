# PHerc0139 w035 sheetness preregistration — 2026-10-03

**Status:** protocol frozen; no sheetness response has been computed by this campaign.

This artifact is the first irreversible step for issue #105. It freezes where the
reference probes will be placed on the official PHerc0139 w035 TIFXYZ before any
Hessian sheetness response is inspected.

## Official reference

- segment: `PHerc0139/segments/20260317000000-w035_2026031718`
- TIFXYZ: `mesh/20260317000000-on-20250728140407-9.362um.tifxyz/`
- exact native CT: `PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr`
- external binding: https://scrollprize.org/tutorial5
- voxel size fence: 9.362 µm

The Challenge tutorial explicitly downloads this TIFXYZ and renders it against
that exact native 9.362 µm CT volume.

## Frozen constants

These values are copied unchanged from the already-published example invocation
in `docs/sheetness-plan.md`, so they are not selected after observing a response:

- surface probes: **32**
- signed normal offsets: **-8, -4, +4, +8 voxels**
- CT halo: **8 voxels**
- sample selection: `lexicographic-even-quantiles-v1`
- randomness: **none**
- CT intensity consulted during planning: **no**
- sheetness response consulted during planning: **no**

At 9.362 µm/voxel the two absolute offset distances are approximately 37.4 µm
and 74.9 µm. That conversion is descriptive only; no threshold is derived from it.

## Workflow

`.github/workflows/pherc0139-sheetness-prereg.yml` performs exactly these steps:

1. fetch the four required TIFXYZ files (plus `mask.tif` if present) from the
   public Challenge bucket;
2. run `zpa-gate` on the exact CT root with the 9.362 µm physical-size fence;
3. extract the embedded full ZPA report to `zpa.json`;
4. run `scroliq-sheetness-plan` with the frozen constants above;
5. verify that all wrong-wrap controls remain
   `pending-independent-geometry`;
6. record source hashes, environment information and the run log;
7. commit the create-only outputs to the campaign branch.

The workflow refuses to overwrite `reference-plan.json`. A rerun after the
plan exists is therefore verification-only unless a new dated campaign is made.

## Expected outputs

- `campaign.json` — human-readable machine contract for this preregistration.
- `zpa.json` — exact-source audit report used by the planner.
- `reference-plan.json` — geometry-only frozen probes and normal offsets.
- `source-sha256.txt` — downloaded TIFXYZ byte hashes.
- `environment.txt` — Python/package environment.
- `run.log` — commands and checks emitted by the workflow.

## What happens next

This artifact deliberately does **not** nominate competing-sheet coordinates.
Each group remains blocked on a wrong-wrap control derived from geometry
independent of the sheetness response. Only after those coordinates are bound
will the CT cutouts and version-3 benchmark specs be frozen. Only after that
will `scroliq-sheetness` be run.

## Claim boundary

A successful preregistration proves only that the reference mesh, exact CT,
probe locations, normals and offset distances were frozen before response
inspection. It is not evidence that sheetness works, that the mesh is globally
the correct winding, or that any ink is present or readable.
