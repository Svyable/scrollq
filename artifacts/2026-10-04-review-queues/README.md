# Review queues in reviewers' hands — 2026-10-04 (October goal O6)

Companion artifact to [`docs/review-queues.md`](../../docs/review-queues.md).

| file | what it is |
|---|---|
| `PHercParis4.ray-order.points.json` | VC3D PointCollections v1 export of the 4-point ray-order review queue in `../2026-10-01-paris4-winding-ray-order/PHercParis4.winding-audit.json` (source SHA-256 `58d33646…3a8505`) |
| `PHerc1447.z_dbg_gen_00320.recheck-2026-10-04.json` | `scroliq-mesh` re-run on the live S3 bytes of the broken PHerc1447 segment; hashes identical to the 2026-10-01 audit, findings reproduced (153 components, 1,335 edge jumps, 386 reversals) |
| `UPSTREAM-DRAFT-PHerc0814.md` | **unfiled** draft: surface volume with six `.zarray` headers and zero chunks (live recheck 2026-10-04) |
| `UPSTREAM-DRAFT-PHerc1447.md` | **unfiled** draft: debug segment published among real PHerc1447 segments |

The third O6 draft (PHerc0343P chunk-size mismatch) is
`../2026-10-01-bucket-chunk-audit/UPSTREAM-ISSUE-DRAFT.md`. The
winding-attachment VC3D bundle is `../2026-10-03-paris4-winding-attachment/vc3d-review-points.json`.

Reproduce the ray-order export (refuses to overwrite):

```bash
scroliq-vc3d-review --kind winding-ray-order \
  --input artifacts/2026-10-01-paris4-winding-ray-order/PHercParis4.winding-audit.json \
  --scroll PHercParis4 --out out/ray.points.json
cmp out/ray.points.json artifacts/2026-10-04-review-queues/PHercParis4.ray-order.points.json
```

Nothing here has been filed upstream. Filing needs the maintainer's explicit
approval and a human reproduction.
