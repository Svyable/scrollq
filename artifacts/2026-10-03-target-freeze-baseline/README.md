# Grand Prize target-freeze baseline — 2026-10-03

This is the first **execution artifact** for `scroliq-target-gate`. It applies the
gate to the historical first-wave hypotheses using only already-frozen,
exact-volume geometry evidence. It does not select a winner.

| candidate | exact-volume identity | surface foothold | held-out geometry path | input integrity | ink validation | VC3D handoff | gate |
|---|---|---|---|---|---|---|---|
| PHerc0800 | pass | pass | pass | unknown | unknown | unknown | provisional |
| PHerc0813 | pass | pass | pass | unknown | unknown | unknown | provisional |
| PHerc1447 | pass | pass | unknown | unknown | unknown | unknown | provisional |

## What changed by running the gate

The old first-wave prose mixed different reasons for considering the three
scrolls. The gate converts that into prerequisite evidence:

- **PHerc0800** has 24 frozen exact-volume atlas candidates with complete bounds,
  a geometry-only 18-fit / 6-held-out split, and 6 exact-volume public meshes in
  the later Mesh IQ cross-cut.
- **PHerc0813** has 24 frozen exact-volume atlas candidates with complete bounds
  and a geometry-only 18-fit / 6-held-out split. It has no official public
  segment mesh in the later cross-cut; the surface foothold here is the frozen
  atlas candidate pool.
- **PHerc1447** has 15 exact-volume public segment meshes in the cross-cut, but
  its comparable centroid/bounds extraction was still pending in the frozen
  candidate pool, so the held-out-geometry prerequisite remains unknown.

The artifact intentionally does **not** infer input integrity, ink validity, or
target-specific VC3D handoff from those geometry facts.

## First shared blocker

`input_integrity` is unknown for all three candidates in the frozen baseline.
That is the next stage to close because the blind-probe protocol explicitly
requires provenance/integrity to pass before geometry or ink results are treated
as interpretable.

The required next artifact is one exact-volume ZPA report with `integrity: PASS`
and source attestation for each candidate CT (and for geometry inputs actually
consumed). A same-scroll alternate scan does not count.

## Reproduce

From the repository root on this branch:

```bash
python artifacts/2026-10-03-target-freeze-baseline/derive.py
git diff --exit-code artifacts/2026-10-03-target-freeze-baseline/
```

`derive.py` first verifies the Git blob SHA-1 of every frozen source file before
regenerating the evidence, gate inputs, gate reports, and cohort summary.

## Claim boundary

- `provisional` is not failure and not a quality ranking.
- A surface foothold does not prove correct sheet identity or full recto coverage.
- A held-out split is a path to evaluation, not a successful held-out result.
- Mesh IQ review findings remain review cues unless independently confirmed.
- Nothing here establishes ink, legibility, or Grand Prize readiness.
