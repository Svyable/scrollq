# October 2026 Progress Prize — five-point VC3D reviewer handoff

**ScrolIQ / Svyable · prepared 2026-10-23 · public, non-confidential · NOT A SUBMISSION**

**Prize:** Vesuvius Challenge October Progress Prize, due **2026-10-31 23:59 Pacific**. Official criteria: https://scrollprize.org/prizes#progress-prizes . Judges favor actual community use, quantitative or qualitative improvements on real scroll data, actionable bug findings, and integration with community formats. Prize awards are discretionary apart from the $20,000 best-submission award; smaller past awards include $250, $500 and $1,000.

## The narrow contribution reviewers can use today

Five PHercParis4 points need human inspection **before** any annotation or patch is changed. ScrolIQ's pre-registered patch-attachment consistency test attached **2,111/2,232 points** and flagged **6/16,074 constraints**, representing **5 unique native VC3D markers**. The planted +2 winding-error control detected **194/200** injected errors. These are diagnostic observations, **not** proof of five annotation mistakes, better spiral fitting, or improved text reading.

**Input:** [native VC3D PointCollections v1 file](../artifacts/2026-10-03-paris4-winding-attachment/vc3d-review-points.json).
**Evidence:** [frozen result, methods, and known limitations](../artifacts/2026-10-03-paris4-winding-attachment/README.md).
**Pre-registration:** [frozen method and thresholds](winding-attachment-protocol.md).
**Complete round-trip protocol:** [VC3D-native review bundles](vc3d-review-bundles.md).

## Independent adjudication receipt (new, unfilled)

Use the [five-marker review worksheet](october-2026-review-adjudication-sheet.csv) to record each actual VC3D decision. All five rows intentionally begin as `pending`; **no review has been performed by publishing the worksheet**. Valid final `review_status` values are `patch_issue`, `annotation_corrected`, `no_issue`, or `uncertain`. Record an identifiable reviewer, timezone-aware timestamp, original and reviewed bundle hashes, CT/patch evidence links, review minutes, and a concrete note. Leave before/after metrics empty unless the same frozen evaluation has actually been rerun. Never treat `pending` or `uncertain` as a verified error.

**Promotion gate:** A claimed correction requires (1) a completed review record, (2) exact source and reviewed hashes, (3) an independent confirmation receipt, and (4) a controlled before/after measurement on the same scan and frozen evaluation rule. Without all four, describe the result only as an actionable diagnostic. The worksheet is a coordination aid, not a substitute for the canonical native VC3D PointCollections review ingest described below.

## Ten-minute first pass — no changes to source data

1. In VC3D open **PHercParis4**, using the matching coordinate frame; do not silently substitute another scan.
2. Load `artifacts/2026-10-03-paris4-winding-attachment/vc3d-review-points.json` as PointCollections v1. In agent-bridge mode: `vc3d_load_points_json(path="/absolute/path/vc3d-review-points.json")`.
3. Inspect each point and nearby traced patch against CT. Preserve its `findings_json` provenance tag.
4. Record one status for each point: `patch_issue`, `annotation_corrected`, `no_issue`, or `uncertain`; add a substantive `scroliq_review_note`. **Do not edit `wind_a` unless a correction is independently confirmed.**
5. Save the reviewed PointCollections file. For a full reproducible handoff, run `scroliq-vc3d-review-ingest` with the exact original bundle, diagnostic result, reviewer identity, timezone-aware timestamp and review minutes; see [exact command and safety gates](vc3d-review-bundles.md#ingest-reviewed-decisions).

## Review priority — five concrete points

| Marker | Observed evidence | What to check, without presuming a defect |
|---|---|---|
| `relative:166/2024` | 11 attachments; 9 agree, 2 disagree at 7.8–7.9 voxels | Are the two farther patches on the neighboring winding? |
| `relative:227/2445` | 5 attachments; 4 agree, 1 differs by 5 windings | Is the outlying patch mislabeled or attached across sheets? |
| `relative:242/2549` | 2 near-equidistant patches, contradictory winding assignments | Which patch follows the same physical sheet as the point? |
| `relative:198/2233` | 9 attachments, none exact; others at residual 1 | Is the annotation wrong, or does branch-cut ambiguity explain the residuals? |
| `relative:280/2860` | 1 flagged attachment and no redundant local confirmation | Is there enough evidence to decide anything? `uncertain` is a valid outcome. |

These interpretations were **post-hoc descriptive triage**, not the pre-registered decision rule. Source: [review-context.json and artifact notes](../artifacts/2026-10-03-paris4-winding-attachment/README.md).

## What would turn the diagnostic into prize-grade improvement?

A reviewer or independent contributor must produce **one actionable downstream receipt**, such as:
- a confirmed incorrect annotation with a hash-bound corrected PointCollections file, unchanged other inputs, and before/after residual comparison;
- a confirmed neighboring-winding patch issue with reproducible coordinates and an upstream bug report or fix;
- a documented finding that all five are false positives, with a reproducible rule refinement proposed for a *new* frozen experiment.

**Do not claim any of these has happened.** As of this handoff, the five markers are unresolved review cues. A claim of improved unwrapping requires before/after geometry or downstream fitting evidence, not a lower diagnostic count alone.

## Prior art and competitive positioning

The Vesuvius Challenge awarded **$500 in September 2026 for winding consistency checks** (Sergei Evland), and earlier awards recognized windcheck, TIFXYZ Doctor, and related specialist tools. This handoff **does not** claim winding checking is new. The proposed incremental contribution is the reproducible **diagnostic → native VC3D point → human adjudication → exact-hash correction → controlled rerun** evidence chain. That advantage must be demonstrated by actual reviewer use, not just described. See https://scrollprize.org/winners .

## Reviewer-safe status and next step

- **Measured:** real PHercParis4 inputs, 6/16,074 flagged constraints, 5 markers, 194/200 injected-error detection.
- **Not measured:** true-positive rate of the 5 markers, reviewer time saved, corrected upstream annotations, improved spiral fit, improved ink reading, or external adoption.
- **Known scope gap:** 48 relative collections were not tied to the absolute frame; 8-voxel attachments can hit neighboring windings; a +2 injection is not an empirical false-positive estimate.
- **Next step:** obtain an independent VC3D review and controlled rerun *with permission*. External outreach, upstream issue filing and prize submission require separate authorization.

## Short submission description — DRAFT ONLY

“ScrolIQ turns winding-consistency diagnostics on public PHercParis4 annotations and verified patches into five provenance-bound, native VC3D review markers. A pre-registered run attached 2,111 of 2,232 points, flagged six of 16,074 constraints, and detected 194 of 200 planted +2 winding errors. The output is a reviewer queue, not a declaration that annotations are wrong. Our contribution is a fail-closed review/correction/re-run path that preserves exact input identity. We disclose existing community winding-checking tools and do not claim improved unwrapping or community adoption without independent evidence.”

**Do not submit this draft as proof of a downstream improvement.** Attach independently reviewed results if available before the October deadline.
