# Public PHercParis4 Fiber IQ audit — 2026-10-01

This artifact freezes a real-data ScrolIQ Fiber IQ campaign over **eight public
VC3D fiber annotations** from the Vesuvius Challenge PHercParis4 spiral-input
dataset. The selection spans four filename/annotator prefixes (`dj`, `et`,
`kb`, `lt`) and June–August 2026 timestamps.

The campaign is intentionally a small, deterministic cross-section rather than
an exhaustive census. Every selected public object is pinned by SHA-256 in
`scripts/public_fiber_campaign.py`. A changed or missing upstream object fails
the campaign instead of silently changing the evidence.

## Result

The eight pinned inputs total **5,304,973 bytes**, **53,828 rendered line
points**, **377 control points**, and **369 control-point spans**.

- **8 / 8** downloaded and matched their pinned SHA-256.
- **8 / 8** parsed as native VC3D fiber **version 3**.
- **354 / 369** spans used native trace interpolation; **15 / 369** used a
  fallback interpolation mode.
- **1 / 8** audits had no review findings; **7 / 8** were `caution`.
- Across the sample ScrolIQ reported **11 gap candidates** and **26 sharp-turn
  candidates**.
- It reported **0 control-line offset candidates** and **0 control-order
  inversions**. In this sample every persisted control point coincided with a
  rendered `line_points` sample and progressed monotonically through the
  rendered line.
- All **11** gap candidates occur in
  `lt_20260702T055841011_000320.json`, which also has the sample's largest
  fallback share (**7 / 28 spans, 25%**). This is a co-occurrence in this
  selected sample, **not evidence that fallback interpolation caused the
  gaps**.

See `summary.json` for per-file hashes, sizes, counts and findings.

## Reproduce

From a checkout of this repository:

```bash
python -m pip install .
bash artifacts/2026-10-01-public-fiber-audit/run.sh
```

`run.sh` downloads the exact named public objects, enforces the pinned
SHA-256s, runs the current Fiber IQ implementation, and verifies stable evidence
fields against `summary.json`. Floating descriptive values such as median
rendered step are not used as byte-for-byte gates.

The GitHub Actions workflow
`.github/workflows/public-fiber-evidence.yml` runs the same campaign on hosted
infrastructure and uploads the fresh summary as an Actions artifact. The
hash-pinned run that established this frozen evidence completed successfully on
2026-10-01.

## Evidence boundary

This artifact establishes that ScrolIQ's native VC3D format/provenance and
geometry-review checks run on current public scroll fiber data and surface
actionable review candidates.

It does **not** establish:

- that the eight-file subset represents every PHercParis4 fiber;
- that a gap or sharp turn is a physical sheet switch or a wrong fiber;
- that the dataset directory maps to one exact CT volume root;
- CT-conditioned fiber orientation/support;
- cross-fiber connectivity or sheet identity.

Because no exact CT volume binding is asserted, these campaign outputs are
**not** attached as `scroliq-passport` evidence. Exact-volume binding remains a
separate fail-closed contract.
