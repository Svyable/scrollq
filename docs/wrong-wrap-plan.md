# Independent wrong-wrap planning

`scroliq-wrong-wrap-plan` freezes and then applies a geometry-only rule for
nominating competing-sheet controls in the sheetness benchmark.

The purpose is narrow: issue #105 requires each frozen reference-surface probe
to carry a competing papyrus-sheet coordinate derived from evidence that is
independent of the sheetness response. A neighboring winding is itself a
sheet-like object, so these controls are **descriptive ambiguity evidence**.
They are mandatory in the benchmark but are not a target that sheetness is
expected to suppress.

## Why use the published surface prediction?

For PHerc0139 the Challenge publishes a level-0 `surface-m7` prediction made
on the same base CT volume as the official w035 TIFXYZ reference. That gives us
an independent geometry proposal source on the exact voxel grid. It is not
ground truth: the model can miss sheets, merge nearby sheets, or place the
surface on the wrong side. The planner therefore:

- hash-binds the already-frozen geometry-only reference plan;
- requires the prediction URL and masked-CT URL to name the exact reference
  volume;
- requires the live prediction and CT arrays to match the frozen level-0 shape;
- uses the TIFXYZ-derived reference normal, never a sheetness-derived normal;
- requires prediction support **and** a non-zero masked-CT voxel for the candidate run;
- requires an explicit **prediction** gap after the reference sheet before a candidate run; CT masking cannot manufacture that gap;
- leaves any group with no qualifying run missing rather than hand-picking a
  substitute.

Masked-CT support removes predictions that land entirely in masked background.
It does not prove physical papyrus or winding identity.

## Frozen default rule

The version-1 rule is intentionally small and deterministic:

| Parameter | Value |
| --- | ---: |
| ray step | 1 voxel |
| minimum competing-sheet distance | 12 voxels |
| maximum search distance | 64 voxels |
| required preceding gap | 3 voxels |
| minimum prediction run | 2 voxels |
| stored prediction threshold | >127 |
| tie break | negative normal direction |
| stochastic | no |

The minimum distance is beyond the sheetness campaign's existing ±8-voxel
normal-offset controls. The rule searches both signs of the frozen TIFXYZ
normal and selects the nearest qualifying run midpoint. Exact-distance ties
choose the negative-normal direction so the result is deterministic.

These constants must be frozen **before** reading prediction values at the
campaign's 32 selected probes. If the rule later proves scientifically weak,
publish that result and create a new protocol version; do not rewrite this one.

## Freeze before reading the geometry source

```bash
scroliq-wrong-wrap-plan freeze \
  --reference-plan artifacts/2026-10-03-pherc0139-sheetness-prereg/reference-plan.json \
  --prediction-url https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0139/representations/predictions/surfaces/20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr \
  --ct-url https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr \
  --model-id 20260413222639 \
  --prediction-binding-url https://scrollprize.org/data_browser/PHerc0139 \
  --min-distance 12 \
  --max-distance 64 \
  --min-gap 3 \
  --min-run 2 \
  --threshold 127 \
  --out wrong-wrap-spec.json
```

`freeze` reads the reference plan only. It does **not** instantiate a Zarr
reader or inspect the prediction/CT voxels.

Commit the resulting spec before running the next command.

## Apply the frozen rule

```bash
scroliq-wrong-wrap-plan run \
  --spec wrong-wrap-spec.json \
  --reference-plan artifacts/2026-10-03-pherc0139-sheetness-prereg/reference-plan.json \
  --out wrong-wrap-result.json
```

The result reports every group, both search directions, the chosen signed
distance/run when one exists, completeness, and the number of remote chunks
that were absent and therefore treated as zero. A missing control remains
`no-independent-competing-sheet-found`.

The output also states `sheetness_response_consulted: false`. No downstream
sheetness inference should run until the accepted wrong-wrap coordinates,
provenance-bound CT cutouts, and version-3 benchmark specs are frozen.

## Validation path

PHerc0139 is a calibration scroll rather than a 2027 Grand Prize target. A
public independent physical-audit dataset derived from its separate
higher-resolution scan can therefore be used as a **generic validation check**
for this nomination rule before transferring the unchanged sheetness method to
a prize-eligible volume. That higher-resolution-derived geometry must not be
used as evidence for, training data for, or reconstruction input to a submitted
Grand Prize scroll.

The physical-validation arm should be preregistered separately. Failure should
invalidate or demote this proposal rule; it should not trigger manual
replacement of individual controls.

## Claim boundary

A `found` row says only that an independently produced, exact-grid published
surface prediction has a CT-supported separated run along the frozen reference
normal. It does not prove that the location belongs to the intended neighboring
winding, that the upstream prediction is correct, or that sheetness can
distinguish sheets. Those remain separate empirical questions.
