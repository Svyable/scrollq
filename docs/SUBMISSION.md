# October 2026 Progress Prize — reviewer map

This page is the shortest path through ScrolIQ for a Vesuvius Challenge reviewer.

**One-line claim:** ScrolIQ is an open, reproducible evidence layer for virtual unwrapping. It binds diagnostics to the exact CT / mesh / model / evaluation region they measured, fails closed on missing or mismatched provenance, and turns winding, mesh, fiber, scan-health and ink-validation outputs into reviewable artifacts rather than a single opaque score.

Prize criteria and deadlines can change; check the current official page before judging:
https://scrollprize.org/prizes

## Five-minute review path

1. **Start with the live overview:** https://svyable.github.io/scrollq/
2. **See the Grand Prize contract:** https://svyable.github.io/scrollq/grand-prize-readiness.html
3. **Read the October evidence update:** https://svyable.github.io/scrollq/october-2026-update.html
4. **Inspect the real PHercParis4 winding controls:** [README — Winding annotation audit](../README.md#winding-annotation-audit)
5. **Inspect the current real-data frontier:** [issue #105](https://github.com/Svyable/scrollq/issues/105), the frozen PHerc0139 sheetness campaign before transfer to an exact prize-eligible volume.

## What is already demonstrated on real Challenge data

| claim | committed evidence |
|---|---|
| Winding annotations can be checked against the scroll axis before spiral fitting | [2026-10-01 Paris4 winding ray-order artifacts](../artifacts/2026-10-01-paris4-winding-ray-order/) |
| The PHercParis4 ray-order audit covered 2,166 / 2,232 annotated points with comparable neighbours and found only two sub-0.1-voxel inversions among 13,700 comparable pairs | README, “Winding annotation audit” |
| The same detector catches deliberately corrupted labels on the real geometry: 179 / 200 testable ±3 shifts and 171 / 200 ±5 shifts | [ray_order_control.py](../bin/ray_order_control.py) and README control table |
| Cross-collection winding consistency can be tested through verified patches | [2026-10-03 Paris4 winding attachment artifacts](../artifacts/2026-10-03-paris4-winding-attachment/) |
| On that run, 2,111 / 2,232 points attached; 6 / 16,074 constraints were flagged; the +2 injection control detected 194 / 200 injected errors | README, “Cross-collection consistency through verified patches” |
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

## Current October frontier

The highest-priority scientific step is **issue #105**:
[Freeze first physical sheetness campaign on PHerc0139 w035 before Grand Prize transfer](https://github.com/Svyable/scrollq/issues/105).

The experiment is intentionally frozen before reading the result. PHerc0139 w035 is used as a geometry/source reference; the exact sheetness configuration and evaluation procedure are then transferred unchanged to an exact Grand Prize-eligible CT volume. A negative result is a valid result.

A separate flattening experiment, [issue #114](https://github.com/Svyable/scrollq/issues/114), is explicitly marked R&D-only and must not displace that main dependency frontier.

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

## What to verify in an October submission

For any claim copied into the October Progress Prize submission, require all four:

1. a dated committed artifact;
2. the exact command or protocol that produced it;
3. source hashes / provenance sufficient to identify the measured CT, mesh or labels;
4. a stated limitation or falsification control showing what the result does **not** prove.

If one of those is missing, do not promote the claim into the submission.
