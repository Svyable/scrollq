# Held-out surface / segmentation validation

`scroliq-segmentation-validate` is the trusted surface-scoring adapter for the
ScrolIQ model-evaluation harness. It compares predicted TIFXYZ papyrus surfaces
with private held-out TIFXYZ truth while keeping the truth outside the
model-author inference environment.

It is deliberately a **surface-recovery measurement**, not a readability or
Grand Prize verdict.

## Primary metric

The preregistered primary metric is:

```text
truth_coverage = fraction of truth vertices within tolerance of prediction
prediction_coverage = fraction of prediction vertices within tolerance of truth

bidirectional_coverage = min(truth_coverage, prediction_coverage)
```

Distances are Euclidean in base-resolution CT voxel XYZ coordinates.

Using the minimum matters:

- truth → prediction penalizes **missing papyrus surface**;
- prediction → truth penalizes **extra surface / wrong-sheet growth**;
- one direction cannot compensate for failure in the other.

The adapter also reports directional p50/p95/max distances, vertex counts,
4-connected TIFXYZ grid component counts, largest-component fractions, and
`symmetric_p95_voxels = max(directional p95)`.

These diagnostics never replace the primary score.

## No silent subsampling

Every valid TIFXYZ vertex is evaluated, up to the public spec's
`max_vertices_per_surface` hard cap.

If either surface exceeds that cap, the region fails. The evaluator does **not**
take a convenient sample after seeing a large result. Split a benchmark into
smaller preregistered regions instead.

TIFXYZ validity follows the Challenge convention used elsewhere in ScrolIQ:
`z <= 0` is invalid; an integer-multiple `mask.tif`, when present, further
restricts valid vertices.

## The blind workflow

There are two trust domains.

### 1. Held-out provider freezes private truth

Create a standard `models/dataset.schema.json` manifest with:

- `task: "segmentation"`;
- `primary_metric.name: "bidirectional_coverage"`;
- `higher_is_better: true`;
- `failure_value: 0`;
- stable held-out region IDs.

The private truth manifest follows
`models/segmentation-truth.schema.json`. It contains the exact volume,
private TIFXYZ paths, and a private random 32-byte salt.

Example:

```json
{
  "schema_version": 1,
  "dataset": "gp-surface-blind-v1",
  "volume_root": "PHercXXXX/volumes/EXACT-VOLUME.zarr",
  "coordinate_system": "base_voxel_xyz",
  "commitment_salt": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "regions": [
    {"id": "region-01", "tifxyz": "truth/region-01.tifxyz"}
  ]
}
```

Compute the commitment **before any submitted prediction is scored**:

```bash
scroliq-segmentation-validate \
  --dataset public-dataset.json \
  --truth /secure/truth.json \
  --truth-root /secure \
  --print-truth-commitment
```

Only the resulting commitment goes into the public evaluation spec. Keep the
salt and truth surfaces private while the benchmark is blind.

### 2. Freeze the public metric spec

The public spec follows `models/segmentation-spec.schema.json` and contains:

- canonical SHA-256 of the public dataset manifest;
- the salted private-truth commitment;
- exact CT volume root;
- coordinate system;
- voxel tolerance;
- hard maximum vertices per surface;
- the exact region set;
- optional preregistered topology gates per region.

Example:

```json
{
  "schema_version": 1,
  "dataset": "gp-surface-blind-v1",
  "dataset_manifest_sha256": "<sha256>",
  "truth_commitment_sha256": "<sha256>",
  "volume_root": "PHercXXXX/volumes/EXACT-VOLUME.zarr",
  "coordinate_system": "base_voxel_xyz",
  "tolerance_voxels": 5.0,
  "max_vertices_per_surface": 2000000,
  "regions": [
    {
      "id": "region-01",
      "max_prediction_components": 1,
      "min_largest_component_fraction": 0.98
    }
  ]
}
```

The topology gates are optional because a legitimate benchmark region may
contain a known break or detached patch. If used, they must be frozen before
predictions are inspected.

Publish the spec hash:

```bash
scroliq-segmentation-validate \
  --dataset public-dataset.json \
  --spec segmentation-spec.json \
  --print-spec-hash
```

This command is public-only and neither accepts nor needs hidden truth.

### 3. Run untrusted inference without truth

Model-author code runs in the untrusted inference environment. It sees the
blind input CT and the public dataset/spec, but **not** the truth manifest,
salt, or truth TIFXYZ.

It emits `models/segmentation-predictions.schema.json`:

```json
{
  "schema_version": 1,
  "model": "community-surface-v3",
  "dataset": "gp-surface-blind-v1",
  "spec_sha256": "<public spec hash>",
  "volume_root": "PHercXXXX/volumes/EXACT-VOLUME.zarr",
  "coordinate_system": "base_voxel_xyz",
  "provenance": {
    "checkpoint_sha256": "<sha256>",
    "inference_script_sha256": "<sha256>",
    "inference_config_sha256": "<sha256>"
  },
  "regions": [
    {"id": "region-01", "status": "ok", "tifxyz": "region-01.tifxyz"}
  ]
}
```

Missing or failed regions are permitted in the prediction manifest so they can
be scored fail-closed instead of disappearing.

### 4. Score in the trusted environment

After inference exits, a separate trusted job mounts the hidden truth and
runs:

```bash
scroliq-segmentation-validate \
  --dataset public-dataset.json \
  --spec segmentation-spec.json \
  --truth /secure/truth.json \
  --truth-root /secure \
  --predictions out/predictions.json \
  --prediction-root out \
  --out out/segmentation.regions.json
```

Before any distance is measured, the evaluator:

1. verifies dataset/spec/prediction/volume identities;
2. hashes every private truth TIFXYZ tree;
3. recomputes the salted truth commitment;
4. refuses the run if the hidden truth changed;
5. hashes each prediction TIFXYZ tree;
6. evaluates every expected region.

The common result file carries the public dataset/spec/truth-commitment hashes
plus each prediction-surface hash. It intentionally does **not** publish raw
private-truth surface hashes, because those can leak benchmark membership when
candidate truth surfaces are enumerable.

### 5. Aggregate with `scroliq-eval`

The region output goes directly into the task-neutral evaluator:

```bash
scroliq-eval \
  --model models/community-surface-v3/model.json \
  --dataset public-dataset.json \
  --checkpoint /cache/community-surface-v3.ckpt \
  --results out/segmentation.regions.json \
  --root . \
  --out out/community-surface-v3.eval.json
```

Failed or missing regions receive the dataset's zero failure value, stay in
`n`, and block ranking. Successful regions preserve all directional
diagnostics and evidence hashes in the final report.

## Hidden-truth commitment

The commitment is versioned as
`scroliq-segmentation-truth-commitment-v1`.

Conceptually:

```text
SHA256(
  version || 0x00 ||
  32-byte private random salt || 0x00 ||
  canonical_json({
    dataset_manifest_sha256,
    volume_root,
    coordinate_system,
    sorted [{region id, TIFXYZ tree SHA-256}, ...]
  })
)
```

The random salt prevents a published commitment from acting as a simple lookup
hash over an enumerable set of candidate truth surfaces. The provider can
later reveal the salt and truth package if the benchmark is retired or
published.

## Fail-closed behavior

A region fails rather than disappearing when:

- the model reports inference failure;
- no prediction is emitted;
- a prediction path is missing or malformed;
- the TIFXYZ has no valid vertices;
- valid coordinates are non-finite;
- the hard vertex cap is exceeded;
- an optional preregistered topology gate fails.

Dataset/spec/truth/prediction identity mismatches and hidden-truth commitment
mismatches invalidate the evaluation itself.

A failed region may still retain numeric diagnostics in the common result.
Those numbers are for diagnosis only: `scroliq-eval` still uses the declared
failure value and blocks ranking.

## Claim boundary

This evaluator establishes geometric proximity between two vertex sets in one
declared base-voxel coordinate frame. It does **not** by itself establish:

- that either surface is physically supported by CT signal;
- that the prediction follows the correct global winding when two sheets fall
  within the tolerance;
- recto versus verso identity;
- absence of self-intersection;
- low-distortion flattening;
- ink identity or readability;
- 100% whole-scroll coverage.

Pair a qualifying surface result with exact-volume CT support/preflight,
winding/order evidence, mesh/self-cross checks, flattening evidence, recto
coverage accounting, and held-out ink/legibility evidence.

The current metric is vertex-weighted rather than area-weighted. Benchmarks
should use comparable TIFXYZ sampling density or preregister an independently
justified area-weighted extension in a new schema/version rather than changing
this metric after results are visible.
