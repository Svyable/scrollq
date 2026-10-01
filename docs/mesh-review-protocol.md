# Pre-registration: how often are Mesh IQ flags real defects? (October goal O1)

**Status:** frozen before any segment in the sample is reviewed. The sample is
drawn by [`bin/mesh_review_sample.py`](../bin/mesh_review_sample.py) and scored
by [`bin/mesh_review_score.py`](../bin/mesh_review_score.py); the verdict is
computed by that code, not by hand. The commit that adds this file is the
timestamp. The sample lives in
[`artifacts/2026-10-01-mesh-review-sample/`](../artifacts/2026-10-01-mesh-review-sample/).

## Why

The 2026-10-01 corpus audit
([`artifacts/2026-10-01-corpus-mesh-audit/`](../artifacts/2026-10-01-corpus-mesh-audit/))
flags 77 of 307 published segments as multi-defect (three or more finding kinds
on every audited registration). A flag list is only actionable if reviewers can
trust it, and the progress-prize criteria ask analytic tools to show they find
real failure cases. Nobody has yet opened these segments to check. This
measures the flag's precision against a person looking at the mesh on its CT.

## Unit, strata and sample (fixed)

The unit is the **segment**. A segment is *flagged* if every audited
registration is multi-defect, *clean* if no registration has any finding, and
*mixed* otherwise. Mixed segments are not sampled: the claim under test is the
flag.

| stratum | population | sampled | role |
|---|---:|---:|---|
| F: flagged, name without `z_dbg` | 51 | 30 | precision of the flag |
| D: flagged, name with `z_dbg` | 26 | 4 | reviewer calibration (known broken) |
| C: clean | 54 | 20 | negative control: how often clean segments are defects |

- F is allocated across scrolls by largest remainder with at least one per
  scroll: PHercParis4 15, PHerc0814 7, PHerc0172 7, PHerc1667 1.
- D always contains PHerc1447 `20251105093211-z_dbg_gen_00320`, the segment
  found broken by hand in `2026-10-01-real-mesh-audit`; the other three are
  drawn at random.
- C is drawn uniformly.
- Seed `20261001`. The review order is shuffled across strata.
- One registration per segment is shown: a registration bound to a volcomp CT
  root when one exists, then the lowest volume id.

## Blinding (procedural)

The reviewer sheet (`review-sheet.csv`) carries only an id, the scroll, the
segment, the mesh URL and the CT root. It has no stratum, tier or finding kind.
The key (`key.json`) can be regenerated from public inputs, so blinding is
procedural, not cryptographic: the reviewer must not open `key.json`, the
audit reports, the corpus `flagged.tsv` or this sample's generator output before
labelling. The debug controls are recognisable by their `z_dbg` names; they
calibrate the reviewer, they do not enter the precision estimate.

## What the reviewer does

Open the mesh in VC3D on the listed CT volume and look over the whole surface.
Record one label per segment:

- `defect`: a geometric error visible on the mesh or against the CT that would
  have to be corrected before the segment could be trusted for unrolling. For
  example a tear or hole not explained by the papyrus edge, a jump or switch to
  a neighbouring sheet, a fold or self-overlap, a disconnected fragment, or
  severe stretching.
- `not_defect`: the surface looks usable; any irregularities are explained by
  the papyrus itself (its edge, real damage or a real gap).
- `unclear`: cannot be decided, for example the mesh will not load or the CT
  does not resolve it.

`defect_type` (free text) and `notes` are optional and are not scored. The
reviewer records who they are and the date in the PR that adds the labels.

## Decision rule (implemented in `bin/mesh_review_score.py`)

1. **Calibration.** At least 3 of the 4 D controls must be labelled `defect`.
   Otherwise the review is `uncalibrated` and no precision is published as a
   finding; the labels are still committed.
2. **Precision of the flag** = `defect / (defect + not_defect)` over F, with a
   Wilson 95% interval. `unclear` is excluded from the point estimate and
   reported as bounds (all unclear as defect, all as not defect).
3. **Clean defect rate**, computed the same way over C.
4. The flag may be described as **enriched for real defects** only if the
   Wilson lower bound for F exceeds the Wilson upper bound for C.
5. Per-finding-kind precision is descriptive only; no claim is made from it.

## What this does not show

- Precision of the *multi-defect* flag on these scrolls, as judged by one
  reviewer. It does not measure recall over all broken segments, and it says
  nothing about mixed segments.
- One reviewer means no inter-rater agreement. A second reviewer on the same
  sheet is welcome and would be reported separately, not averaged in.
- A `not_defect` label is a judgement about usability, not proof that the
  surface follows the right sheet everywhere.

## Deviation policy

Any change after this file is committed (a segment that cannot be opened and is
replaced, a changed label definition, a second reviewer) is logged in the
artifact README with its date and reason. The original sample and rules stay as
committed.

## Reproduce

```bash
python bin/mesh_review_sample.py artifacts/2026-10-01-mesh-review-sample
# after labelling review-sheet.csv:
python bin/mesh_review_score.py artifacts/2026-10-01-mesh-review-sample --out result.json
```
