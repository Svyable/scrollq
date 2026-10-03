# Pre-registration: patch attachment and cross-collection winding consistency (October goal O2, step 3)

**Status:** frozen before any patch surface (`x/y/z.tif`) is read. The
constants and the decision rule are implemented in
[`bin/winding_attach.py`](../bin/winding_attach.py)
(`preregistered_constants()`, `analyse()`, `decide()`), and that code
computes the outcome, not a person. The commit that adds this file is the
timestamp. Steps 1 and 2 (`bin/winding_recon.py`,
`bin/winding_patch_index.py`) read the annotations, the umbilicus and the
patch `meta.json` bounding boxes, but no surface geometry.

## Question

PHercParis4's spiral-fitting inputs hold one absolute winding frame and many
relative collections, each with its own unknown offset. Do the winding
numbers agree with each other once they are tied together through the
verified patch surfaces they sit on?

## Why patches

- Step 1: annotations from different collections almost never sit close
  enough to link directly. Only 3 point pairs lie within 4 voxels, and the
  absolute frame is never linked.
- Step 2: all 89,237 verified patches carry a bbox, but a bbox is far too
  coarse. A point sits in a median of 179 bboxes. Only the surfaces can link
  annotations.
- Scope: the 20,438 patches whose bbox (expanded by 12 voxels) contains an
  absolute or relative point. Step 2 estimated about 4.1 GB. Same-winding
  collections are out of scope for this step.

## Method (constants in parentheses)

1. **Attach.** A point attaches to a patch when its distance to the patch's
   triangulated grid is at most 8 voxels (`ATTACH_DISTANCE`). A vertex is
   valid when x, y and z are all finite and non-negative, since VC3D marks
   holes with −1. The distance is exact to the triangles around the 4
   nearest usable vertices.
2. **Unwrap.** Each connected piece of a patch grid gets a continuous angle
   `phi` around the umbilicus. The umbilicus is interpolated linearly in z,
   as upstream does. A piece is excluded, and counted, if:
   - any grid edge turns more than π/4 around the axis (`MAX_STEP_RADIANS`); or
   - its unwrap is path-dependent, meaning it encircles the axis.
3. **Constrain.** Spiral sense `s` and branch-cut angle `c` give the patch's
   integer winding at an attached point as `o_P + floor(s·(phi − c)/2π)`. The
   annotation says this equals `wind_a + f_F`, where `f_F` is 0 for the
   absolute frame and unknown for each relative collection. Each attachment
   is one integer constraint `o_P − f_F = d`.
4. **Choose sense and cut.** All 72 pairs are evaluated: s = ±1 and
   c = 0°, 10°, …, 350°. The primary pair is the one with the fewest nonzero
   residuals; ties go to s = +1 and then to the smallest c. The full table is
   published. Choosing one discrete pair out of 72 is the only fitted choice.
5. **Solve.** Offsets are fitted per connected component of the
   patch-piece/frame graph. The method is:
   - build a maximum-support spanning tree;
   - refine with a weighted mode, at most 50 rounds and in a deterministic
     order;
   - fix the absolute frame at 0, and anchor any other component at its
     smallest name.

   The residual of each constraint is `o_P − f_F − d`.
6. **Inconsistency.** A residual with |r| ≥ 2 is an inconsistency
   (`INCONSISTENT_ABS_RESIDUAL`). A residual with |r| = 1 is reported
   separately, because a branch cut placed differently from the
   annotator's can produce it. Ray order (`winding_geometry.py`) uses the
   same gap of two.

## Positive control (lesson 9)

The control draws up to 200 constraints (`CONTROL_TRIALS`, seed 20261003)
from those that are:

- *checkable*: removing the constraint leaves its patch piece and frame
  connected; and
- currently at residual 0.

For each drawn constraint:

1. Shift its `d` by +2 (`CONTROL_SHIFT`).
2. Re-solve its component.
3. Count it **detected** if the component gains a constraint with |r| ≥ 2,
   and **localized** if the shifted constraint itself is flagged.

## Decision rule

- **UNVERIFIED** if there is no redundant constraint (constraints ≤ nodes −
  components) or if the control detects fewer than 90%
  (`CONTROL_MIN_DETECTION`) of the injected errors. A clean result that
  checked nothing is not a result.
- **CONSISTENT** if no constraint has |r| ≥ 2.
- **INCONSISTENT** otherwise. The review queue (`review-queue.csv`, at most
  200 rows) lists each flagged attachment with:
  - its VC3D coordinates;
  - its frame, point id and `wind_a`;
  - its patch piece and attachment distance.

Reported either way:

- attachment counts;
- excluded pieces and the reason for each;
- how many relative collections are tied to the absolute frame;
- independent cycles and redundant constraints;
- the |r| = 1 count;
- the sense/cut table;
- the 4- and 12-voxel distance arms (descriptive, no gate);
- the control's detection and localization rates.

## Known limitations

- A flagged constraint is a review cue, not a verdict. A verified patch can
  itself be traced onto a neighbouring winding, so an inconsistency may sit
  in the patch rather than the annotation. Two patches that disagree look
  the same as one annotation that disagrees.
- The weighted-mode solve is a local optimum. When a cycle has no majority,
  the residual can land on the wrong edge, which is why localization is
  reported apart from detection.
- The result says nothing about CT support, mesh quality, or how accurate a
  spiral fit is, and nothing about readability.

## Deviation policy

Any change after this commit is logged with its date and reason in the
results artifact, and never applied by editing this file or the constants.
This covers:

- an unreadable patch;
- a runner fix;
- a rerun.

A post-hoc analysis is allowed only as a separately labelled arm.

## Reproduce

```bash
python bin/winding_attach.py INPUT_DIR verified_patches.html \
  https://dl.ash2txt.org/datasets/spiral_datasets/PHercParis4/verified_patches OUT_DIR
```

The workflow `.github/workflows/winding-attach.yml` (manual, or on the PR
that adds it) runs this
against the live data and commits the results to a dated artifact
directory.
