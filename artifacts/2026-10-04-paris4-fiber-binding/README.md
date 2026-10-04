# Which CT volume are the public PHercParis4 fibers in? — 2026-10-04 (goal O9, step 1)

**Verdict: AMBIGUOUS. The dataset declares no volume, and range compatibility leaves one readable candidate.**

Produced by `scripts/paris4_fiber_binding.py` in GitHub Actions
(`.github/workflows/paris4-ct-binding-discovery.yml`, run
[37169673942](https://github.com/Svyable/scrollq/actions/runs/37169673942) on `ed00320`).
`result.json` is copied verbatim from the job log.

## What the dataset declares

Nothing. `dl.ash2txt.org/datasets/spiral_datasets/PHercParis4/` and the Hugging
Face bucket have no README or metadata file. The fiber JSON top-level keys are
`branches, control_points, filename, generation, hv_classification,
line_points, optimization_mode, sequence, started_at, tags, type, username,
version`, with no volume field. Span manifests name only local annotator paths
such as `/media/…/PHercParis4.volpkg/las008_s1_full/las_008.lasagna.json`.

## What can be derived

The bounding box of all line and control points of the 136 census fibers (VC3D
xyz) is x 6,583–27,261, y 7,247–27,352, **z 3,222–75,500**. Against each public
PHercParis4 level-0 shape (`[z, y, x]` from the open bucket):

| volume | level-0 shape | can contain every point? |
|---|---|---|
| 20260411134726 · 2.400 µm · 78 keV | 75,784 × 32,693 × 32,693 | **yes** |
| 20260608103018 · 1.129 µm | 59,969 × 36,006 × 32,354 | no (z) |
| 20260323153942 · 2.400 µm · 137 keV | 6,625 × 8,431 × 8,431 | no |
| 20260310170716 / 20260310173927 · 45.5 µm | ~4,070 × 2,264 × 2,264 | no |
| 20230205180739 / 20230206171837 · 7.91 µm | listed in the index, **no objects in the bucket** | unknown |

Range compatibility can only rule volumes out. One readable candidate is not a
binding: two volumes cannot be checked, and another scan could share the frame.
Step 2 tests the candidate against CT content
(`../2026-10-04-paris4-fiber-ct-support-prereg/`).
