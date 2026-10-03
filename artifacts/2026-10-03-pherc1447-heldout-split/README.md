# PHerc1447 geometry-only held-out split — 2026-10-03

This closes the held-out-geometry-path evidence gap from the first target-freeze baseline for exact Grand Prize volume `PHerc1447 / 20250521151220`.

The role assignment uses all 15 exact-volume segment reports and reads only segment identity plus each report's observed XYZ bounding box. It does not read Mesh IQ findings or tiers, scan-health scores, render appearance, or ink.

## Deterministic rule

Each segment gets a central 256-slice z core. A candidate is isolated when that core has at least 128 slices of axial gap from every other candidate core. Six candidates satisfy that condition. Sorted by z center, three even-quantile ranks `floor((i+0.5)*N/3)` are held out; every other candidate is fit-role.

Result: **12 fit / 3 held out**, with a **193-slice minimum held-out-to-fit axial core gap**.

Held-out segments:
- `20250703034159-auto_grown_20250703034159599` (z≈5443.7)
- `20250702235910-auto_grown_20250702235910292` (z≈12702.2)
- `20250502182142-auto_grown_20250502161324419` (z≈22165.9)

## Reproduce

```bash
python artifacts/2026-10-03-pherc1447-heldout-split/derive.py
git diff --exit-code artifacts/2026-10-03-pherc1447-heldout-split/split.json
```

The derivation verifies the Git blob SHA-1 of the frozen corpus summary and all 15 source reports before reading geometry.

## Claim boundary

This proves a geometry-only held-out **path exists**; it is not held-out performance. A future fit must declare its largest spatial influence radius before evaluation. If that radius exceeds 193 slices, this split fails closed and a new dated split is required.
