# PHerc0139 wrong-wrap geometry preregistration — 2026-10-03

**Status:** protocol source and constants declared; the campaign workflow may
only freeze the spec. It must not read prediction voxels.

This campaign is the next dependency in issue #105 after the committed w035
surface-probe plan. The goal is to bind each pending wrong-wrap control to a
deterministic **independent geometry proposal rule** before inspecting the
published surface prediction at any of the 32 frozen probes.

## Frozen upstream input

Reference plan:

`artifacts/2026-10-03-pherc0139-sheetness-prereg/reference-plan.json`

That plan already freezes:

- exact native CT:
  `PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr`;
- the official source-bound w035 TIFXYZ bytes;
- 32 deterministic surface probes and TIFXYZ-derived normals;
- normal-offset controls at -8, -4, +4 and +8 voxels;
- no CT-intensity or sheetness-response selection;
- all wrong-wrap controls as `pending-independent-geometry`.

The new spec must hash-bind those exact reference-plan bytes.

## Independent geometry source

The preregistered proposal source is the Challenge-published m7 surface
prediction on the **same base CT volume and level-0 grid**:

`20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr`

The data-browser page is recorded only as the public identity/binding reference.
The prediction is a proposal source, not physical truth.

## Frozen rule

`normal-ray-supported-surface-v1`:

- trace both signs of the already-frozen TIFXYZ normal;
- one-voxel ray step;
- search begins at 12 voxels, outside every existing ±8-voxel offset control;
- stop at 64 voxels;
- require 3 consecutive **in-bounds prediction-absent** voxels immediately
  before a candidate run;
- candidate run requires at least 2 consecutive prediction values >127;
- every candidate-run voxel must also have nonzero masked CT;
- choose the nearest qualifying run midpoint by absolute signed distance;
- negative-normal direction wins exact ties;
- no randomness and no seed;
- no sheetness response.

The CT mask may reject a run. It cannot manufacture the separation gap.

## Observation boundary

`.github/workflows/pherc0139-wrong-wrap-prereg.yml` runs **only**
`scroliq-wrong-wrap-plan freeze`. The freeze path validates strings,
reference-plan provenance and constants; it does not instantiate a remote Zarr
reader.

The workflow then checks the frozen JSON and commits:

- `wrong-wrap-spec.json`;
- `freeze.log`;
- `environment.txt`.

It refuses to overwrite the spec. Once the spec exists, reruns stop at the
guard and cannot regenerate it.

No `scroliq-wrong-wrap-plan run`, `scroliq-sheetness`, CT cutout extraction,
or response evaluation belongs in this campaign.

## Next irreversible step

Only after this spec is committed and merged may a separate campaign run it
against the published prediction/CT. Missing wrong-wrap candidates must remain
missing. The measured proposal result will then be eligible for a separately
preregistered validation arm against PHerc0139's independent physical-geometry
labels.

The higher-resolution-derived PHerc0139 labels are for generic calibration of
this control-selection rule only. They must never be transferred to, or used as
reconstruction/training evidence for, a 2027 Grand Prize scroll.

## Claim boundary

This artifact will prove only that the geometry-source identity and nomination
rule were frozen before their values at the selected probes were observed. It
does not prove that the proposed coordinates are neighboring windings, that m7
is correct, or that sheetness works.
