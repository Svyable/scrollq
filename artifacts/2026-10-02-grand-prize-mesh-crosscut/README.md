# Exact-volume Grand Prize mesh cross-cut — 2026-10-02

This artifact asks one narrow question:

> Of the **13 exact CT volumes eligible for the 2027 Grand Prize**, which ones
> already have published segment meshes in the committed corpus mesh audit, and
> what do the local Mesh IQ checks report on those exact registrations?

No network reads are performed. The result is derived from two frozen inputs:

- `../2026-10-01-prize-targets/grand-prize-manifest.json` — the 13 eligible
  volume IDs derived from pinned official sources.
- `../2026-10-01-corpus-mesh-audit/summary.json` — the 2026-10-01 public
  TIFXYZ corpus audit.

The matching rule is deliberately fail-closed: **scroll ID is not enough**.
A mesh counts only when its registered `volume_id` exactly equals the
prize-listed volume ID. Meshes from another scan of the same scroll are excluded.

## Result

Only **2 / 13** eligible target volumes currently have published exact-volume
segment meshes in the audited corpus:

| target | exact volume | official public segments | exact meshes audited | Mesh IQ tiers |
|---|---|---:|---:|---|
| **PHerc0800** | `20250521135224` | 6 | 6 | **6 clean** |
| **PHerc1447** | `20250521151220` | 15 | 15 | **14 review, 1 multi-defect** |
| other 11 targets | exact prize-listed volumes | 0 | 0 | evidence gap |

That is **21 / 21** published segments accounted for on the two eligible
volumes that currently expose segments.

### PHerc0800

All **6 / 6** exact-volume meshes have no local Mesh IQ finding in the frozen
corpus audit.

This is useful evidence, but it does **not** prove that the meshes follow the
correct papyrus sheet, cover the recto, or flatten with Grand-Prize-quality
isometry.

### PHerc1447

All **15 / 15** exact-volume meshes have at least one enclosed-hole finding:

- **14** are review tier.
- **1** is multi-defect:
  `20251105093211-z_dbg_gen_00320`, with connectivity, edge-jump, hole,
  isometry-distortion and normal-reversal findings.

That multi-defect segment was already used as the corpus audit's positive
control after being found broken by hand in the earlier audit. The other hole
findings remain **review candidates**, not confirmed defects; an enclosed
invalid region can have a legitimate explanation and needs VC3D/CT inspection.

## Why this matters

The Grand Prize fixes each scroll to a specific eligible scan. Surface evidence
from another scan cannot silently stand in for the prize-listed volume. This
cross-cut makes the current geometry evidence gap explicit:

- PHerc0800 and PHerc1447 have exact-volume public meshes to inspect now.
- The other 11 targets have no published exact-volume segment mesh in this
  committed corpus, so mesh quality is **unknown**, not clean or bad.

This is a prioritization/evidence result only. It is not a recommendation of
one target over another.

## Reproduce

From the repository root:

```bash
python artifacts/2026-10-02-grand-prize-mesh-crosscut/derive.py
git diff --exit-code artifacts/2026-10-02-grand-prize-mesh-crosscut/summary.json
```

The derivation uses only the two committed JSON inputs above.

## Claim boundary

- Local Mesh IQ checks do not prove physical sheet identity.
- A clean mesh does not prove full recto coverage or readable ink.
- A flagged mesh is a review candidate unless independently confirmed.
- Zero exact-volume meshes means **no current published mesh evidence**, not a
  defect in the scroll or scan.
