# Prediction-connectivity gap recovery

**Status: preregistered before connected-component structure is read.**

The current surface-recovery evidence points to a specific failure: the independent
published surface prediction continues to witness deliberately omitted papyrus, but
methods that try to infer missing sheet identity from smooth geometry or local CT
appearance have failed.

This experiment therefore stops asking an extrapolator to invent the missing sheet.
It treats the independent surface-m7 prediction as candidate geometry and asks which
local 3-D prediction component is physically anchored to the visible submitted sheet.

For each of six already-development-exposed PHerc0139 w035 regions:

1. hide a 21x21 material-grid patch before candidate generation;
2. compute the existing harmonic fill only as a coarse search/correspondence prior;
3. associate prediction-supported visible anchors on all four sides of the hole;
4. read the local CT-supported surface-m7 mask inside the frozen 64-voxel search
   envelope;
5. form 26-connected components after one voxel of connectivity-only dilation;
6. accept a component only when it is anchored from all four sides and receives the
   frozen seed majority;
7. snap each hidden material cell's coarse coordinate to a raw prediction voxel on
   that selected component; and
8. only after the complete candidate is frozen, read the hidden TIFXYZ truth and
   score the recovered XYZ.

The dilation is never output as geometry. It only makes the component-labeling
question robust to one-voxel holes. Recovered coordinates must be real
surface-prediction voxels with masked-CT support.

The full immutable algorithm, centers, thresholds, denominators and promotion rule
are in
[`artifacts/2026-10-03-prediction-connectivity-recovery-prereg/spec.json`](../artifacts/2026-10-03-prediction-connectivity-recovery-prereg/spec.json).

## Why 64 voxels

This number is frozen from evidence already observed before this experiment. On the
same six development centers, the failed Stage-B harmonic method's maximum 21x21
hidden-XYZ error was about 43.3 voxels. The new method uses 64 voxels only as a
candidate search envelope and maximum snap radius. The acceptance tolerance remains
8 voxels.

## What counts as success

The development gate requires a unique multi-side component on at least five of six
centers, high candidate availability, substantial recovery within 8 voxels, bounded
median/p95 error, wrong-wrap rejection, and non-degenerate recovered geometry.

A PASS is not promotion to a Grand Prize claim. It only authorizes a separate,
unchanged holdout preregistration. A FAIL is preserved and the mechanism changes;
these thresholds are not tuned after observation.

No ink is used.
