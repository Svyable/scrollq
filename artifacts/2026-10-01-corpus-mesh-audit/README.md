# Corpus-wide mesh audit, 2026-10-01

Every published segment mesh in the open bucket
(`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`), audited
with `scroliq-mesh` (TIFXYZ) and `scroliq-obj` (OBJ). This extends
`artifacts/2026-10-01-real-mesh-audit/` (21 Grand Prize meshes) to the whole
corpus. Reproduce with `run.sh`.

These are local geometry checks. They do not say whether a surface follows the
papyrus sheet in the CT, and a flagged mesh is a review candidate, not a
verdict. Nothing here has been confirmed by a person in VC3D or filed upstream.

## Coverage

| | listed | audited | failed |
|---|---|---|---|
| TIFXYZ meshes (`<segment>/mesh/*.tifxyz/`) | 903 | 843 | 60 |
| OBJ meshes (`<segment>/mesh/intermediate/*_original.obj`) | 200 | 200 | 0 |

- The 903 TIFXYZ meshes are 307 segments across 11 scrolls. Most segments are
  registered on several scans, one mesh per scan.
- Every one of the 307 segments has at least one audited mesh.
- **Failures.** All 60 failures ran out of memory (exit 137). They are the
  largest meshes: 59 PHercParis4 registrations on its 1.129 µm and 2.4 µm
  scans and 1 PHerc1667 mesh. The largest z.tif is 464 MB.
  - Three jobs ran in parallel on a 16 GB machine.
  - Each failure is listed with its reason in `failed.tsv`. The first pass's
    log is kept in `failed-pass1.tsv`.
  - Retried alone, 10 of the original 70 completed and 1 ran out of memory
    again. The remaining retries were stopped for time.
- `status` in `summary.json` is therefore `partial`, not `complete`.
- Volume binding: 695 of the 843 TIFXYZ audits were bound to the exact CT
  volume root via `volumes.txt`. The rest name a scan that is not in
  `volumes.txt` and ran unbound.

## Positive controls (AGENTS.md rule 9)

- PHerc1447 `20251105093211-z_dbg_gen_00320`, found broken by hand in the
  earlier audit, lands in the top tier in both formats.
- All 26 segments whose names contain `z_dbg` are in the top tier on every
  registration. That these are debug or generated segments is inferred from
  the name only.

## Results

Tiers count distinct finding kinds. They are not a quality score.

| tier | TIFXYZ meshes | OBJ meshes |
|---|---|---|
| clean (no findings) | 189 | 47 |
| review (1–2 kinds) | 462 | 88 |
| multi-defect (3+ kinds) | 192 | 65 |

Finding counts are numbers of meshes with each finding:

| finding | TIFXYZ meshes | OBJ meshes |
|---|---|---|
| normal reversal (> 120° between neighbours) | 591 | 127 |
| hole (enclosed invalid region / interior boundary loop) | 267 | 75 |
| edge jump (> 4× median spacing) | 216 | 82 |
| connectivity (> 1 component) | 152 | 38 |
| isometry distortion (p95 stretch > 2) | 47 | 30 |
| degenerate faces | n/a | 2 |

The OBJ audit found no non-manifold edges, inconsistent winding or flipped UV
triangles.

- **Flagged segments.** 77 of 307 segments are multi-defect on every
  registration: PHercParis4 27, PHerc0500P2 25, PHerc0814 12, PHerc0172 11,
  PHerc1447 1 and PHerc1667 1. `flagged.tsv` lists every multi-defect mesh.
- **Normal reversals alone are common.** The median TIFXYZ mesh has 52
  reversal pairs, so a single reversal finding is not by itself a reason to
  distrust a segment. That is why the flag is three or more kinds.
- **Agreement across scans.** 190 of 262 multi-registration segments report
  identical finding kinds on every scan.
- **Agreement across formats.** 185 segments have both an audited TIFXYZ and
  a published `_original.obj`. They agree on whether any shared finding kind
  is present in 175 of them: 131 flagged by both and 44 by neither.
  - 9 are flagged only in the OBJ and 1 only in the TIFXYZ.
  - The OBJ is a decimated triangulation of the same surface, so exact counts
    differ.

## Files

- `run.sh` runs the full pipeline.
- `list_meshes.py` lists the TIFXYZ mesh directories using S3 delimiter
  listings.
- `audit_one.sh` and `audit_obj_one.sh` download one mesh, audit it, and
  delete it.
- `obj_keys.py` lists the `_original.obj` keys from the pinned
  `../2026-10-01-bucket-index/metadata.min.json.gz`.
- `mesh_dirs.txt` and `obj_keys.txt` are the exact inputs.
- `reports/` and `obj-reports/` hold one JSON per mesh, with input file
  SHA-256s.
- `summary.json` has the counts and per-mesh rows.
- `flagged.tsv` lists the multi-defect TIFXYZ meshes.
- `failed.tsv` and `failed-pass1.tsv` list the meshes that could not be
  audited, with reasons.
