# PHerc0490A first-letter hunt — frozen axial target

This artifact freezes the first spatial reduction for a First Letters search on **PHerc0490A**, exact eligible volume `20250521151210` (8.640 µm, 116 keV).

It is intentionally not an ink claim. The only question answered here is: *which measured interior 64-slice z-window of the released surface-prediction volume has the strongest pooled support from non-zero masked CT?*

## Source

Upstream: `axiosdevs/herculaneum-scroll-tools`, `ct_support/survey_PHerc0490A.json`, Git blob `26d66ccac89a880a73a4bc8a9727097679d014fb`.

The upstream survey measures the exact eligible CT and matching released m7 surface prediction. Across all sampled planes it reports support `0.7407448073112333`.

## Frozen rule

- ignore the first and last 1,000 CT slices;
- consider only contiguous 64-slice windows wholly represented in one measured slab;
- maximize pooled support `1 - sum(phantom) / sum(positives)`;
- tie-break by larger mean positive-voxel count, then lower `z0`.

Result: **z `[9274, 9338)`**.

- 848,531,539 prediction-positive voxels
- 213,573,919 phantom voxels
- pooled support `0.7483017316578494`
- mean 13,258,305.296875 prediction-positive voxels per plane

The machine-readable receipt is `axial-target.json`.

## What happens next

This is axial triage only. It does not establish a seated sheet, recto identity, ink, or a letter. Local surfaces inside the frozen band must be CT-seated and then rendered. Unknown-ground-truth ink outputs are ranked with `scroliq-first-letter-hunt`; a window cannot enter its review queue without two distinct checkpoint hashes and `-3/+3` normal-offset, adjacent-winding, and geometry-perturbation controls.
