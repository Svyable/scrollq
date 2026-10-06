# Dinovol positional debiasing and public-data limits

**Status:** research decision, 2026-10-06. Adds `scroliq-crop-invariance`
([doc](../crop-invariance.md)). No scoring behaviour, frozen artifact or Grand
Prize execution order changes. Findings below are as relayed; none of the
external figures is reproduced in this repository.

## Decisions

| Idea | Decision | Implemented as | Next evidence |
|---|---|---|---|
| INSID3 (Apache-2.0, CVPR 2026): DINOv3 dense features carry a positional bias; a training-free correction is reported to raise semantic-correspondence PCK@0.10 from 46.8 to 52.6 and PCK@0.20 from 61.2 to 68.7 | **INTEGRATE EXPERIMENT** (the debiasing idea only, not the 2-D segmentation system) | `scroliq-crop-invariance`: same voxels under shifted crops, held-out position R², same-voxel cosine, NN-identity stability, sheet/neighbour and ink/negative separation, raw vs debiased | A frozen Dinovol fixture with verified-ink and physical-negative labels. If `NO_POSITIONAL_DEPENDENCE_DETECTED`, dismiss INSID3 for this use |
| INSID3 code / DINOv3 weights | **DO NOT IMPORT** | none | DINOv3 weight terms are separate from the Apache-2.0 code and unaudited here; the gate runs on the already-approved Dinovol stack |
| AMF-U-Net (multimodal residual 3-D U-Net, brain-tumour MRI) | **DISMISS** | none | No papyrus or thin-laminar evidence; MRI channels have no Vesuvius analogue; adds a supervised model without a demonstrated ScrollQ failure |
| Indexed Kaggle Surface Detection notebook/checkpoint repository | **DISMISS** as an incorporation candidate | none | No new capability and no clear reusable license; historical ideas only if provenance and license are resolved |
| Projection-domain reconstruction gates (FaCT-GS / CIL style) | **BLOCKED on public data** | status `unavailable_input` | The open-data documentation says raw projections are not shared; public volumes are reconstructed, masked/windowed 8-bit OME-Zarr. Perturbing reconstructed volumes is allowed but must not be called projection consistency |

## Rules carried forward

- A proof gate distinguishes **failed** from **cannot currently be evaluated
  from public evidence** (`unavailable_input`). Substituting reconstructed CT
  and calling it projection consistency is a vacuous gate (lesson 9).
  `scroliq-crop-invariance` is the first tool to emit the status; no other
  tool was changed.
- Promotion requires crop-coordinate invariance **without loss of physical
  discrimination**; smoother similarity maps are not a criterion.
- Expected impact is unknown; transfer from 2-D DINOv3 to volumetric CT is
  unmeasured. Synthetic controls pass, which shows only that the machinery
  detects a planted bias.
