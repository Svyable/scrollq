# PHercParis4 winding attachment and cross-collection consistency (pre-registered) — 2026-10-03

This is the run of the test frozen in
[`docs/winding-attachment-protocol.md`](../../docs/winding-attachment-protocol.md)
(October goal O2, step 3).

- The pre-registration was committed as `32bf2c0` before any patch surface was read.
- The analysis ran in workflow `winding-attach.yml` on PR #75 at `dea843b`, generated 2026-10-03 04:48 UTC.
- The results were committed by the workflow.

```bash
python bin/winding_attach.py INPUT verified_patches.html \
  https://dl.ash2txt.org/datasets/spiral_datasets/PHercParis4/verified_patches OUT
```

Input hashes (`result.json` → `inputs.sha256`):

- `abs_winding.json` `4e566731…`
- `relative_windings.json` `a3243511…`
- `umbilicus.json` `c5f30b0d…`

## Verdict: INCONSISTENT, with 6 of 16,074 constraints flagged

The control works and the annotations are almost entirely consistent through the patches. **Six** attachments
disagree by two or more windings, and they are listed in `review-queue.csv` with VC3D coordinates.

| | |
|---|---|
| annotation points (absolute / relative) | 59 / 2,173 |
| patches whose bbox reaches a point (12-voxel margin) | 20,765, all read, 0 errors |
| excluded patch pieces (axis-encircling / step > π/4) | 0 / 0 |
| points attached within 8 voxels | **2,111 of 2,232 (94.6%)** |
| constraints · patch pieces · frames | 16,074 · 8,852 · 255 |
| relative collections tied to the absolute frame through patches | **206 of 254** |
| graph components · independent cycles · redundant constraints | 28 · 6,165 · 6,995 |
| residual 0 / \|r\| = 1 / \|r\| ≥ 2 | 15,550 (96.7%) / 518 / **6** |
| **injection control** (+2, 200 trials of 10,235 eligible) | **detected 194 (97%)**, localized 160 (80%) |

Reading the rule:

- The control cleared its 90% bar, so `decide()` does not return UNVERIFIED.
- Six constraints have |r| ≥ 2, so it returns INCONSISTENT.
- The six are review cues, not proven annotation errors: a patch traced onto a neighbouring winding produces the same signal.

Deviations: none.

## What the sense and cut table says

- **The spiral sense is decided by the data.** The best sense +1 pair leaves 524 nonzero residuals. The best sense −1 pair (cut 310°) leaves 2,120, with 1,618 of them at |r| ≥ 2.
- **The branch-cut angle is not well identified.** The pre-registered tie-break picked 320°, with 524 nonzero residuals. The upstream convention of 0° leaves 528, and the |r| ≥ 2 count is 6 at both. Across all sense +1 cuts the |r| ≥ 2 count runs from 5 to 39.

## Distance arms (descriptive, no gate)

| attach distance | constraints | \|r\| = 1 | \|r\| ≥ 2 | edges with disagreeing points |
|---:|---:|---:|---:|---:|
| 4 voxels | 14,618 | 73 | 3 | 1 |
| **8 voxels (primary)** | 16,074 | 518 | 6 | 381 |
| 12 voxels | 20,171 | 4,231 | 337 | 3,364 |

At 12 voxels attachments start to reach the next winding, and disagreements jump tenfold. At 4 voxels the
|r| = 1 count falls from 518 to 73, so most of the primary arm's |r| = 1 residuals are attachments near the
distance limit rather than branch-cut effects. The 8-voxel threshold sits below the point where adjacent
windings are reached. A threshold between 4 and 8 voxels would be cleaner. Any future run must pre-register it
as a new arm, not swap it in here.

## Post-hoc reading of the review queue (descriptive, not part of the decision)

`review-context.json` comes from `bin/winding_attach_review.py`, run by the workflow on the same input hashes. It lists every attachment of each of the 5 flagged points; the 6 flagged constraints include two patches for one point.

| point | attachments | agreeing (r = 0) | flagged | reading |
|---|---:|---:|---:|---|
| relative:166/2024 | 11 | 9 | 2 | closer patches agree: the two flagged patches (7.8–7.9 voxels away) are likely on a neighbouring winding |
| relative:227/2445 | 5 | 4 | 1 | patch-level conflict: one patch at similar distance disagrees by 5 windings |
| relative:242/2549 | 2 | 1 | 1 | patch-level conflict: two patches about 1 voxel away disagree with each other |
| relative:198/2233 | 9 | 0 | 1 | no attachment agrees exactly (the others are at \|r\| = 1): review the annotation |
| relative:280/2860 | 1 | 0 | 1 | single attachment: review the annotation and the patch |

So 3 of the 5 points look like patch-side issues: a neighbouring-winding attachment or two disagreeing patches. Only 2 point at the annotation itself. These readings come from a rule written after the result, and only a person in VC3D can confirm them.

## Files

- `result.json`: decision, summary, control, sense and cut table, distance arms, review queue, input counts and hashes, and constants.
- `attachments.json`: every attachment within 12 voxels (point, patch piece, distance, unwrapped angle), enough to recompute any arm offline.
- `review-queue.csv`: the six flagged attachments with VC3D XYZ.
- `vc3d-review-points.json`: five deduplicated native VC3D PointCollections markers for those six flagged constraints, hash-bound to `result.json`.
- `run.log`: the workflow output.
- `review-context.json` (post-hoc, descriptive, `bin/winding_attach_review.py`): for each flagged point, all its attachments and their residuals. It was added by the workflow after this run and is not part of the decision.

## Scope

This result says annotation windings agree through verified patches. It does not say:

- that the patches follow the papyrus in the CT;
- that a spiral fit is accurate;
- anything about readability.

48 relative collections are not tied to the absolute frame through any patch, so their offsets cannot be checked here.
