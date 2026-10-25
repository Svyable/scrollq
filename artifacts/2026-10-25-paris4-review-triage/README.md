# PHercParis4: two decisive first-pass reviews before October Progress Prize

**Prepared:** 2026-10-25 · **Status:** public reviewer-preparation artifact; **no independent review, correction, or prize submission**.

**Source:** [frozen 3 October attachment experiment](../2026-10-03-paris4-winding-attachment/README.md), [post-hoc review context](../2026-10-03-paris4-winding-attachment/review-context.json), [native coordinates](../2026-10-03-paris4-winding-attachment/review-queue.csv), [primary result](../2026-10-03-paris4-winding-attachment/result.json). The machine-readable [priority.json](priority.json) is derived from these exact committed files. The original run was at source commit `dea843b15f13db068abdb95f8137a2b45353371c`. Original annotation input SHA-256s are retained in the JSON.

## Why narrow to two points?

The 3 October experiment flagged **six constraints among 16,074** and mapped them to **five native VC3D points**. A retrospective scan of all five points' committed patch-attachment rows shows **two points with a flagged patch within 2 voxels AND at least one independent-looking residual-zero patch attachment**. These are the most useful *questions* for a reviewer, not confirmed errors or independent ground truth.

| Review order | Native point (x,y,z) | Flagged patch | Counter-evidence | Decision sought |
|---|---|---|---|---|
| **1. relative:227/2445** | **5255.7, 3610.2, 12125.7** | `same_wrap002432_growpatch/#90`: **0.886 voxels**, residual **−5** | Four residual-zero attachments, closest **3.835 voxels** | Does the near patch trace a different physical sheet/winding, have a winding-label defect, or indicate a coordinate/frame mismatch? |
| **2. relative:242/2549** | **5007.2, 3022.6, 11494.7** | `auto_grown_20260526143735233_sel_20260526_154138_283/#0`: **1.043 voxels**, residual **+2** | One residual-zero patch at **1.050 voxels** | Which of the two almost equidistant patches actually follows the physical sheet at this point? |

**Why point 227 first:** It has a larger residual magnitude (five windings), the flagged patch is the *closest* attached patch, and four other patches disagree with it. This makes it a high-information patch-identity check, **not** a high-probability annotation-error claim. The farther patches may themselves be off-sheet or mislabeled. The apparent consensus is not independent ground truth.

## Minimum 15-minute inspection protocol

1. Open **PHercParis4** in VC3D with the coordinate frame used by the frozen attachment experiment. Load [native PointCollections](../2026-10-03-paris4-winding-attachment/vc3d-review-points.json) without changing original source data.
2. At `relative:227/2445`, compare the closest `same_wrap002432_growpatch/#90` surface with the four residual-zero attachments against local CT cross-sections. Follow the physical papyrus sheet, not the numerical residual. Record which patch, if any, crosses sheets or carries a mistaken winding. If none can be established, mark `uncertain`.
3. Repeat at `relative:242/2549` with both almost-equidistant patches. A distance tie is **not** proof that one patch is wrong.
4. Save a reviewed native PointCollections file and complete the [five-marker adjudication sheet](../../docs/october-2026-review-adjudication-sheet.csv). Preserve reviewer identity, timezone-aware timestamp, actual minutes, CT evidence references, source/reviewed hashes and notes. Other three markers remain pending unless genuinely reviewed.
5. Only if an error is independently confirmed, create a **separate** proposed patch/annotation correction and compare the same frozen residual metric before/after. Do not silently edit `wind_a`, change the 8-voxel rule, or overwrite the pre-registered run.

## What this changes—and does not

**Changed:** A five-point unsorted review queue is now a transparent, reproducible, ranked two-point first-pass target with exact coordinates, source hashes, competing patches and explicit falsification questions. This can reduce *reviewer search effort*; no time saving has been measured.

**Not changed:** No CT image was inspected here. No annotation or patch was corrected. No reviewer was contacted. No external adoption, unwrapping improvement, or false-positive rate is established. The ordering is a **post-hoc heuristic** based on patch distances and residuals; it is not the pre-registered detection method. `priority.json` contains `review_status: pending` for every point.

## October prize economics and go/no-go

Official [Vesuvius Progress Prizes](https://scrollprize.org/prizes#progress-prizes) close **2026-10-31 at 23:59 Pacific**. Best submission is **$20,000** monthly; smaller discretionary awards have historically included **$250 and $500**. Reviewers value actual community use, actionable real-data findings, before/after evidence and integration with standard formats. Prior September 2026 winding-check work won $500, so *checking winding consistency* itself is not novel ([winners](https://scrollprize.org/winners)).

**Proceed with a prize entry only after applicant authorization.** A technically honest entry may describe the existing diagnostic and reviewer workflow, but should **not** claim a confirmed fix, adoption or quantitative downstream improvement without receipts. The first dollar-relevant next step is **independent VC3D adjudication of point 227**, then point 242. External outreach, upstream issues and submissions require explicit approval.

**If no reviewer is available by October 31:** retain the released artifact for a later monthly prize rather than invent evidence or imply a completed improvement.
