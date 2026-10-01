# Real-segment mesh audit — 2026-10-01

First run of `scroliq-mesh` on published community segments, not synthetic
fixtures. It covers every TIFXYZ mesh in the open S3 bucket for the two 2027
Grand Prize targets that have public segments: **PHerc1447 (15)** and
**PHerc0800 (6)**. Each mesh is audited against the exact eligible CT volume
named in its directory (`-on-<volume id>`): PHerc1447 `20250521151220`,
PHerc0800 `20250521135224`.

## Reproduce

```bash
PATH=.venv/bin:$PATH artifacts/2026-10-01-real-mesh-audit/run.sh
```

`run.sh` lists the bucket, writes `keys.txt` (84 objects: `meta.json`,
`x.tif`, `y.tif`, `z.tif` per mesh), downloads to `out/s3/` (untracked), runs
`scroliq-mesh` per mesh into `reports/`, and builds `summary.json` with
`summarize.py`. Every report records the SHA-256 of all four mesh files.

## Results

| | PHerc0800 (6) | PHerc1447 (15) |
|---|---|---|
| status `pass` | 6 | 0 |
| status `partial` | 0 | 15 |
| enclosed holes in the valid grid | 0 in every mesh | 8–28 per mesh |
| disconnected valid components | 1 in every mesh | 1 in 13, 2 in one, **153 in one** |
| edge jumps > 4× median spacing | 0 | 0, except **1,335 in one** |
| severe normal reversals (>120°) | 0 | 0, except **386 in one** |
| isometry stretch p95 | 1.016–1.026 | 1.011–1.023, except **5.07 in one** |

**One published PHerc1447 segment is geometrically broken.**
`20251105093211-z_dbg_gen_00320` fails every local check: 153 disconnected
pieces, 1,335 edge jumps, 386 severe normal reversals, and a p95 local stretch
of 5.07 (max 81). Its name suggests a debug output. It sits in the public
`segments/` prefix next to the 14 coherent PHerc1447 meshes, so a segment
count of 15 for PHerc1447 includes it. Anyone training or rendering from
"all PHerc1447 segments" would ingest it. This is an observed property of the
published files; the cause is unknown and nothing has been filed upstream.

The other 20 meshes are locally near-isometric (p95 stretch ≤ 1.026), with no
edge jumps or normal reversals. The PHerc1447 holes are enclosed invalid
regions inside otherwise connected grids; they are flagged for review, not as
failures.

## Scope

These are local TIFXYZ checks. They do **not** establish CT support (no
`vesuvius.surface_preflight` report was supplied), freedom from nonlocal
self-intersection (no `vc_tifxyz_selfcross` report), correct winding identity,
or ink. Every report says so in its `limitation` field.
