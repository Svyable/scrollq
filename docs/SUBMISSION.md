# ScrolIQ — reviewer map

This page is the shortest path through ScrolIQ for a Vesuvius Challenge reviewer.

**One-line claim:** ScrolIQ is an open, reproducible evidence layer for virtual unwrapping. It binds diagnostics to the exact CT / mesh / model / evaluation region they measured, fails closed on missing or mismatched provenance, and turns winding, mesh, fiber, scan-health and ink-validation outputs into reviewable artifacts rather than a single opaque score.

Prize criteria and deadlines can change; check the current official page before judging:
https://scrollprize.org/prizes

## Five-minute review path

1. **Start with the live Grand Prize evidence board:** https://svyable.github.io/scrollq/progress.html
2. **Read the exact current bottleneck and next experiment:** [November N2 — one exact-volume surface result, scored blind](november-2026.html#n2).
3. **Verify the strongest current real-data controls:** [two-scroll Fiber IQ evidence](fiber-audit.md) (547 / 547 public fibers plus replicated CT support/direction), [PHercParis4 winding attachment](../artifacts/2026-10-03-paris4-winding-attachment/), and [same-byte TIFXYZ cross-check](../artifacts/2026-10-02-doctor-same-byte/).
4. **Check the blind evaluation contract:** [held-out segmentation validation](segmentation-validation.md) and the [model-evaluation protocol](model-evaluation.md).
5. **Reproduce and inspect:** [pinned reviewer container](grand-prize-container.md) · [VC3D-native review queues](review-queues.md) · [source](https://github.com/Svyable/scrollq).

## What is already demonstrated on real Challenge data

| claim | committed evidence |
|---|---|
| Winding annotations can be checked against the scroll axis before spiral fitting | [2026-10-01 Paris4 winding ray-order artifacts](../artifacts/2026-10-01-paris4-winding-ray-order/) |
| The PHercParis4 ray-order audit covered 2,166 / 2,232 annotated points with comparable neighbours and found only two sub-0.1-voxel inversions among 13,700 comparable pairs | README, “Winding annotation audit” |
| The same detector catches deliberately corrupted labels on the real geometry: 179 / 200 testable ±3 shifts and 171 / 200 ±5 shifts | [ray_order_control.py](../bin/ray_order_control.py) and README control table |
| Cross-collection winding consistency can be tested through verified patches | [2026-10-03 Paris4 winding attachment artifacts](../artifacts/2026-10-03-paris4-winding-attachment/) |
| On that run, 2,111 / 2,232 points attached; 6 / 16,074 constraints were flagged; the +2 injection control detected 194 / 200 injected errors | README, “Cross-collection consistency through verified patches” |
| Every publicly listed PHercParis4 VC3D fiber can be audited reproducibly with an eight-file hash-pinned positive control | [2026-10-04 full fiber census](../artifacts/2026-10-04-fiber-corpus-census/) — 136 / 136 fibers, 388 gaps, 519 sharp turns, 0 control-line offsets/order inversions |
| The same census machinery scales to an independent scroll and retains its detector control | [PHerc0139 fiber census](../artifacts/2026-10-04-pherc0139-fiber-census/) — 411 / 411 fibers and 411 / 411 planted breaks detected; strict volume-range binding remains NONE COMPATIBLE by a 7-voxel near miss |
| Fiber placement has replicated physical CT support on two scrolls under frozen designs | [PHercParis4 CT support](../artifacts/2026-10-04-paris4-fiber-ct-support-run/) AUC 0.775 and [PHerc0139 replication](../artifacts/2026-10-04-pherc0139-fiber-ct-support-run/) AUC 0.760; both are evidence for the proposed frame, not declared dataset bindings |
| Fiber tangents independently run within the local CT sheet plane on both scrolls | [PHercParis4 direction](../artifacts/2026-10-04-paris4-fiber-ct-direction-run/) median 3.3° out of plane and [PHerc0139 replication](../artifacts/2026-10-04-pherc0139-fiber-ct-direction-run/) median 3.5°; wrong-frame controls pass |
| A plausible fiber-gap correction can fail an independent adoption gate and remain rejected | [PHercParis4 gap-rule test](../artifacts/2026-10-04-fiber-gap-rule-run/) was INSUFFICIENT; [PHerc0139 v2](../artifacts/2026-10-04-fiber-gap-rule-v2-pherc0139-run/) returned KEEP, so the current rule remains |
| Findings can be handed back to reviewers in native VC3D coordinates instead of as dashboard-only counts | [review-queues.md](review-queues.md) and [2026-10-04 review queue artifacts](../artifacts/2026-10-04-review-queues/) |
| Blind held-out TIFXYZ surface recovery has a salted private-truth commitment, exact-volume binding, bidirectional coverage and fail-closed region accounting | [segmentation-validation.md](segmentation-validation.md) |
| Held-out geometry evaluation has an explicit fit-input exclusion contract and keeps missing predictions in the denominator | [heldout-geometry-evaluation.md](heldout-geometry-evaluation.md) |
| CT integrity evidence is delegated to zarr-pyramid-audit and consumed fail-closed rather than re-invented here | [zarr-pyramid-audit](https://github.com/Svyable/zarr-pyramid-audit) and README “Diagnostic passport” |
| Submission packaging, image traceability, provenance and legibility evidence have explicit interfaces | [grand-prize-package.md](grand-prize-package.md), [grand-prize-images.md](grand-prize-images.md), [grand-prize-provenance.md](grand-prize-provenance.md), [grand-prize-legibility.md](grand-prize-legibility.md) |

## Why this is different from another quality score

The legacy 0–100 ScrolIQ score remains a **scan-health triage signal only**. It is not used as a Grand Prize readiness score.

The project’s stronger contribution is the **evidence contract across stages**:

- every artifact is bound to exact source identities;
- stale, cross-volume or incomplete evidence is rejected or kept unknown;
- negative controls and failed experiments stay published;
- held-out regions are separated from fit/training inputs;
- review queues preserve native VC3D coordinates so a flagged point can be inspected where it came from;
- established specialist tools remain specialist tools; ScrolIQ composes their evidence instead of claiming to replace them.

That makes the output useful even when a diagnostic produces a negative result: it tells the next stage what is known, what is not known, and what must not be trusted.

## Current Grand Prize frontier

The highest-priority experiment is **November N2: one exact-volume surface result, scored blind**:
[November 2026 goals — N2](november-2026.html#n2).

The measurement infrastructure is ready; the campaign result is not. N2 freezes one exact prize-eligible volume, public metric spec, probe regions, engine identity and a salted commitment over private TIFXYZ truth **before** predictions exist. It then scores every preregistered region with bidirectional surface coverage, topology gates and explicit failures. A negative result counts as evidence and does not authorize changing the rule after the fact.

[Issue #105](https://github.com/Svyable/scrollq/issues/105) remains the frozen PHerc0139 physical-sheetness reference/transfer experiment that informs the surface campaign; it is no longer a good summary of the whole project frontier by itself. Other active but subordinate dependencies are the blinded Mesh IQ review (N1), first external community-model evaluation (N3), the raised Fiber IQ question of sheet identity plus a CT-based gap model (N4), and held-out spiral score (N5). The earlier CT-conditioned Fiber IQ milestone was pulled into October and now has replicated two-scroll evidence. The v2 Grand Prize frontier rerun was also pulled into October and done on 2026-10-04: PHerc0813 left the frontier and PHerc1447 is its only robust member ([`prize-frontier-v2/`](../artifacts/2026-10-04-prize-frontier-v2/)).

## Reproducibility / integration surfaces

The repository is MIT licensed and exposes normal command-line and JSON interfaces. The central integration object is the **diagnostic passport**, which can bind scan, winding, mesh, fiber and ink evidence for one exact volume.

Example:

    scroliq-passport \
      --volumes artifacts/2026-09-30-scrollq/volumes.json \
      --coverage artifacts/2026-09-30-scrollq/coverage.json \
      --winding-audit out/PHerc0813.winding-audit.json \
      --mesh-audit out/PHerc0813.mesh-audit.json \
      --fiber-audit out/PHerc0813.fiber-audit.json \
      --ink-audit out/PHerc0813.ink-audit.json \
      --root PHerc0813 \
      --out out/PHerc0813.passport.json

Container/reproduction notes for the Grand Prize workflow live in [grand-prize-container.md](grand-prize-container.md). Standard community surfaces and meshes are kept traceable through the package/provenance documents linked above.

## Claims we are not making

ScrolIQ does **not** currently claim to:

- fully unroll a prize scroll;
- establish letter-by-letter legibility;
- prove biological ink identity from scan-health or sheetness metrics;
- replace VC3D, spiral fitting, TIFXYZ Doctor, windcheck, tifxyz-repair, or other specialist tools;
- turn an unmeasured pipeline stage into a positive readiness score;
- treat a neighbouring winding as a negative example merely because it is not the target winding.

Native spiral-fit export and the first frozen physical sheetness transfer remain active work. Those gaps are stated because the evidence contract is only useful if “unknown” stays unknown.

## What to verify before promoting any claim

For any prize-facing claim copied into a submission or public evidence page, require all four:

1. a dated committed artifact;
2. the exact command or protocol that produced it;
3. source hashes / provenance sufficient to identify the measured CT, mesh or labels;
4. a stated limitation or falsification control showing what the result does **not** prove.

If one of those is missing, do not promote the claim into the submission.
