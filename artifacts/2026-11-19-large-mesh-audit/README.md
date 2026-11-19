# 2026-11-19 large-mesh audit

The [2026-10-01 corpus mesh audit](../2026-10-01-corpus-mesh-audit/README.md)
audited 843 of the 903 primary TIFXYZ meshes in the open bucket. The other 60
ran out of memory (59 PHercParis4, 1 PHerc1667; its `failed.tsv`). This
artifact audits those 60 with `scroliq-mesh`, which now evaluates edge, quad
and review-queue metrics in row blocks, and folds them into the corpus view.
The October artifact is frozen and unchanged.

Status: **complete**. All 60 listed meshes have a report, none failed, and the
equivalence check passed.

## Results

- **Coverage.** 60 of 60 audited, so the TIFXYZ corpus is now 903 of 903.
  The meshes have 19.1M to 116.1M vertices (median 35.7M).
- **Memory and time.** They ran one at a time on a 16 GB machine. The peak
  RSS was 11.9 GB on the largest mesh (median 3.7 GB), and the median run took
  54 s (82 minutes in total). Per-mesh numbers are in `runs.tsv` and in each
  row's `run` field of `summary.json`.
- **Tiers.** 2 clean, 29 review and 29 multi-defect. Finding counts:
  normal reversal 55, hole 37, edge jump 32, connectivity 30 and isometry
  distortion 2. `flagged.tsv` lists the 29 multi-defect meshes.
- **Corpus view.** Across both artifacts, 75 of 307 segments are multi-defect
  on every TIFXYZ registration (October: 77). By scroll: PHercParis4 25,
  PHerc0500P2 25, PHerc0814 12, PHerc0172 11, PHerc1447 1 and PHerc1667 1.
  - No segment is newly flagged. All 54 segments the 60 meshes belong to
    already had an audited registration in October.
  - Two PHercParis4 segments drop out of the flag: `20260701183130-w064-068`
    and `20260701183131-w069-072`. Their October registrations were
    multi-defect (connectivity, hole, normal reversal). Their 2.4 µm
    registrations audited here show connectivity and normal reversal but no
    hole, so the segment is no longer multi-defect on every registration.

## Equivalence with the unblocked code

The unblocked code cannot run the 60 large meshes, so equivalence was checked
on a deterministic sample of 30 smaller real meshes (`select_sample.py`,
`equivalence_sample.txt`). Per scroll, the sample takes the smallest
multi-defect mesh, the smallest mesh in another tier, and the largest mesh
whose `z.tif` is at most 80 MB, plus the positive control
`z_dbg_gen_00320`. The largest sampled mesh has 19.9M vertices, so it spans
about ten default row blocks.

`verify_equivalence.py` downloads each mesh with its SHA-256 pinned to the
October report. It audits the mesh with the baseline module from `9807b0c`
(loaded from git), with the current code at its default block size, and with
the current code at `block_rows=1`.

- **30 of 30 are byte-identical across all three** (`equivalence.json`,
  ignoring `tifxyz_path`).
- **29 of 30 report the same finding kinds as the October reports.** The
  exception is PHerc0814 `20260225160055` on volume 20250804134230 at
  9.362 µm. October reported `isometry-distortion` and the current code
  reports no findings. This comes from a later change, before the baseline,
  that normalizes isometry stretch by the observed median spacing instead of
  `meta.scale`. Row blocks do not cause it.
- **Caveat for the corpus view.** Its 843 October rows come from the October
  code and its 60 new rows from the current code. The sample suggests this
  mixes in about 1 isometry difference per 30 meshes.
- **Positive control.** `z_dbg_gen_00320` is still multi-defect with all five
  kinds.

`tests/test_tifxyz_blockwise.py` checks the same property on fixtures: every
block size from 1 row to more than the grid gives the same JSON. Removing
either block-boundary carry makes those tests fail.

## Files

- `run.sh` runs the whole pipeline. It builds `meshes.txt` from the October
  `failed.tsv`, runs `audit_one.sh` on each mesh serially, then runs
  `select_sample.py`, `verify_equivalence.py` and `summarize.py`.
- `audit_one.sh` downloads one mesh into the untracked `out/large-s3/`,
  audits it through `peak.py`, appends the exit code, peak RSS (MB) and
  seconds to `runs.tsv`, logs any failure to `failed.tsv` (empty here), and
  deletes the download.
- `reports/` holds one `scroliq-mesh` JSON per mesh.
- `summary.json` and `flagged.tsv` are written by `summarize.py`.

No readability claim is made. A flag is a triage signal to look at a
segment, and its precision is still unmeasured
([N1](../../docs/november-2026.html#n1)).
