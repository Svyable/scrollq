# Projected component correspondence

**Status: preregistered after prediction-connectivity-recovery-v1 failed and before
any projected-relaxation response is read. Measured 2026-10-04: FAIL — see
[Result](#result).**

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

## Result

**FAIL. The frozen gate was not met and `surface-constrained-material-laplacian-v1`
is dismissed.** The measured, create-only result is
[`artifacts/2026-10-03-projected-relaxation-run/result.json`](../../artifacts/2026-10-03-projected-relaxation-run/result.json);
the input hashes, run log and Python environment sit beside it.

Identity locks held. All four centers reproduced the exact v1 candidate SHA-256 and
selected component label, and all four wrong-wrap controls were still rejected.

| center | within 8 voxels (v1 → relaxed) | median error (v1 → relaxed) | p95 error (v1 → relaxed) |
| --- | --- | --- | --- |
| surface-0008 | 0.993 → 1.000 | 2.47 → 2.17 | 6.1 → 5.0 |
| surface-0012 | 0.422 → 0.444 | 10.44 → 10.31 | 37.1 → 37.1 |
| surface-0016 | 0.685 → 0.660 | 3.95 → 3.46 | 20.4 → 20.4 |
| surface-0023 | 0.454 → 0.476 | 9.67 → 8.93 | 28.3 → 27.8 |

Gate checks, from `decision.checks`:

- **Failed:** median within-8 fraction 0.568 (needs ≥ 0.75); median p95 24.1 voxels
  (needs ≤ 16); every center ≥ 50% within 8 voxels (surface-0012 at 0.444 and
  surface-0023 at 0.476 fall short); every center median error ≤ 8 voxels
  (surface-0012 at 10.31 and surface-0023 at 8.93 exceed it).
- **Passed:** cohort complete; v1 identity exact; no center regressed more than
  5 points (largest regression 0.025); all wrong-wrap controls rejected; median unique
  recovered voxel fraction 1.0.

This is not a rejection-gate artifact. Between 437 and 441 of the 441 hidden cells
accepted their proposal in every iteration, and the median accepted movement fell from
1.0 voxel at iteration 1 to 0.0 at iteration 84. The relaxation ran as specified and
settled; it simply did not repair the tail. surface-0008 and surface-0016 meet the
per-center bars, but surface-0012 and surface-0023 do not, and p95 error was left
essentially unchanged on the three patches v1 had not already recovered (37.1 → 37.1,
20.4 → 20.4, 28.3 → 27.8), which is what sinks the cohort-level median p95.

What this does and does not establish:

- It dismisses this one correspondence mechanism on this four-patch development
  cohort. It does not show that component identity is wrong, and it does not reopen or
  weaken the v1 component-selection result.
- Per the preregistration, thresholds are not retuned after observation and the
  holdout stays unopened. Any next mechanism needs its own preregistration.
- Development cohort only; no readability, ink, or Grand Prize claim.
