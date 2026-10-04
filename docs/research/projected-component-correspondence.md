# Projected component correspondence

**Status: preregistered after prediction-connectivity-recovery-v1 failed and before
any projected-relaxation response is read.**

The first connected-component recovery experiment changed the problem. It found one
surface-prediction component on four of six development patches and rejected every
frozen adjacent-winding control. One patch recovered almost perfectly. The remaining
error on selected components was mostly correspondence: the one-shot nearest point to
the harmonic XYZ prior could land far along the correct physical sheet.

This experiment leaves component identity untouched. It asks whether the hidden
material grid can relax **on the already-selected component**.

For the four v1-selected development patches, the runner must first regenerate the
exact v1 candidate hash and selected component label. It then performs 84 synchronous
material-grid relaxation iterations. Each hidden point is pulled toward the mean of
its four material neighbors, with visible TIFXYZ neighbors just outside the deletion
held fixed, and is projected back onto a raw CT-supported surface-m7 voxel on the same
v1 component. Projection residual and per-iteration movement are both capped at 16
voxels; failed proposals keep the previous coordinate.

The full frozen contract and no-regression gate live in
[`artifacts/2026-10-03-projected-relaxation-prereg/spec.json`](../../artifacts/2026-10-03-projected-relaxation-prereg/spec.json).

This is deliberately development-only because the four-patch cohort was selected from
v1 outcomes. A PASS can justify freezing an integrated method before opening the
untouched holdout; it is not itself held-out evidence.
