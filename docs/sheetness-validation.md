# Frozen sheetness validation

`scroliq-sheetness-validate` evaluates **local papyrus-sheet evidence** produced
by an external engine. It deliberately does not compute Hessians, fit a surface,
choose correspondences, or claim that a locally sheet-like response belongs to
the globally correct winding.

The first intended engine is the deterministic `scroliq-sheetness` multiscale
Hessian plate-objectness baseline already in this repository. The same contract
can later evaluate ITK, learned membrane segmentation, or another local
sheet-evidence field without changing the benchmark.

## Why freeze the benchmark first

A visually convincing response field is not enough. The useful question is
whether an engine assigns stronger evidence to a known/high-confidence papyrus
surface than to deliberately difficult controls:

- points displaced along the surface normal;
- a competing or wrong-wrap point.

The specification is hashed before the engine is run. Engine observations must
repeat that hash and the exact CT `volume_root`. Missing and failed probes stay
visible and prevent the benchmark from passing.

## Specification

Coordinates are base-resolution CT voxels in XYZ order.

```json
{
  "schema_version": 1,
  "volume_root": "exact-scan.zarr",
  "coordinate_system": "base_voxel_xyz",
  "criteria": {
    "min_surface_control_margin": 0.1,
    "min_surface_normal_abs_cosine": 0.9
  },
  "probes": [
    {
      "id": "g1-surface",
      "group_id": "g1",
      "role": "surface",
      "xyz": [10, 20, 30],
      "reference_normal_xyz": [0, 0, 1]
    },
    {
      "id": "g1-offset-plus",
      "group_id": "g1",
      "role": "normal_offset",
      "xyz": [10, 20, 33],
      "reference_surface_id": "g1-surface",
      "offset_voxels": 3
    },
    {
      "id": "g1-wrong-wrap",
      "group_id": "g1",
      "role": "wrong_wrap",
      "xyz": [14, 25, 40],
      "reference_surface_id": "g1-surface"
    }
  ]
}
```

Each group must have exactly one `surface` probe and at least one control.
`normal_offset` controls record a non-zero signed displacement. Controls must
name the surface probe they challenge.

The normal criterion uses the **absolute cosine** because a Hessian-derived
normal has an arbitrary sign: `n` and `-n` describe the same local plane.

Freeze the spec and record its hash before generating observations:

```bash
scroliq-sheetness-validate --spec spec.json --print-spec-hash
```

## Engine observations

```json
{
  "schema_version": 1,
  "volume_root": "exact-scan.zarr",
  "coordinate_system": "base_voxel_xyz",
  "spec_sha256": "<hash printed above>",
  "engine": {
    "name": "scroliq-sheetness",
    "version": "0.1",
    "source_revision": "<pinned revision>",
    "config_sha256": "<sha256 of canonical engine configuration>",
    "deterministic": true
  },
  "observations": [
    {
      "id": "g1-surface",
      "status": "ok",
      "sheetness": 0.8,
      "normal_xyz": [0, 0, -1],
      "scale_voxels": 2
    },
    {
      "id": "g1-offset-plus",
      "status": "ok",
      "sheetness": 0.5
    },
    {
      "id": "g1-wrong-wrap",
      "status": "ok",
      "sheetness": 0.4
    }
  ]
}
```

A stochastic engine must declare an integer `engine.seed`. A deterministic
engine may omit it.

Evaluate without overwriting an existing report:

```bash
scroliq-sheetness-validate \
  --spec spec.json \
  --observations observations.json \
  --out sheetness-validation.json
```

Exit 0 means every frozen probe was observed and every group met the two frozen
criteria. Exit 1 means valid evidence did not meet the frozen criteria or was
incomplete. Invalid or binding-mismatched input exits 2.

## Measurements

For every group the report retains:

- the surface score and strongest control score;
- their signed score margin;
- whether the margin clears the frozen threshold;
- absolute cosine agreement between the predicted and reference surface normal;
- whether the normal clears the frozen threshold;
- whether the group met both frozen criteria.

The report also preserves every individual probe and explicit `missing` /
`failed` states. It summarizes the median margin and median normal agreement,
but does not collapse the benchmark into a synthetic quality score.

## First public experiment

The first real experiment should use frozen public, high-confidence surfaces
and contain at least:

1. the native surface coordinate;
2. symmetric positive/negative normal offsets at predeclared distances;
3. an independently selected nearby competing/wrong-wrap coordinate.

Run the predeclared `scroliq-sheetness` scale set and polarity over exactly
those frozen coordinates. Commit the spec, engine configuration, observations,
validation report, exact commands, source revision, and CT provenance.

Do not tune scales or thresholds on the held-out probe groups after observing
the benchmark result. If tuning is needed, create a separate development set
and freeze a new held-out spec before rerunning.

## What a pass does not mean

A passing group says only that this local engine preferred the frozen surface
coordinate over its controls and produced an aligned local normal. It does not
prove:

- global winding identity;
- topology or connectivity;
- full recto coverage;
- low-distortion flattening;
- ink presence;
- text legibility;
- Grand Prize readiness.

Those require separate evidence layers.
