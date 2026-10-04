# Review queues: how to act on ScrolIQ findings

ScrolIQ produces four review queues. Each item is a **cue to look**, not a
verdict. This page says where each queue lives, how to open it, and what to
record. (October goal O6.)

| queue | items | where | open in |
|---|---|---|---|
| Mesh IQ flags | 54-segment blinded sample (30 flagged, 4 debug controls, 20 clean) | `artifacts/2026-10-01-mesh-review-sample/` | VC3D, per CSV row |
| Winding attachment | 5 points / 6 constraints, PHercParis4 | `artifacts/2026-10-03-paris4-winding-attachment/vc3d-review-points.json` | VC3D PointCollections |
| Winding ray order | 4 points, PHercParis4 | `artifacts/2026-10-04-review-queues/PHercParis4.ray-order.points.json` | VC3D PointCollections |
| Fiber gaps | 388 gap candidates (2 in native trace spans) | `artifacts/2026-10-04-fiber-span-test-run/fiber-gaps.points.json` | VC3D PointCollections |
| Fiber sharp turns | 519 in 100 of 136 fibers | `artifacts/2026-10-04-fiber-corpus-census/summary.json` | VC3D fiber files |

## 1 · Mesh IQ flags

Purpose: measure how often a mesh flag is a real defect (goal O1).

1. Build the key-free packet: `python bin/mesh_review_packet.py --out out/mesh-review.zip` (see
   [mesh-review-handoff.md](mesh-review-handoff.md)).
2. Open each row's `mesh_url` and `volume_root` in VC3D. Do not substitute
   another scan of the same scroll.
3. Label each segment `defect`, `not a defect` or `unclear`, **without** reading
   ScrolIQ's finding kinds first. Return the CSV unchanged apart from labels.

Protocol and statistics: [mesh-review-protocol.md](mesh-review-protocol.md).

## 2 · Winding attachment and 3 · ray order

Both are VC3D PointCollections v1 in full-resolution level-0 voxel XYZ.

1. Start VC3D with `--agent-bridge` and open the PHercParis4 volume.
2. Load the file: `vc3d_load_points_json(path="…points.json")`, or use the
   normal point-collection import.
3. For every collection, set `scroliq_review_status` and a note, exactly as in
   [vc3d-review-bundles.md](vc3d-review-bundles.md#record-the-review-in-vc3d);
   ingest the result with `scroliq-vc3d-review-ingest`.

Each collection's tags carry the source SHA-256, frame, point id and winding,
plus `findings_json` (attachment) or `inversion_pairs`/`comparable_pairs`
(ray order). Ray-order points are blue, attachment points orange.

Regenerate either file deterministically:

```bash
scroliq-vc3d-review --input artifacts/2026-10-03-paris4-winding-attachment/result.json \
  --scroll PHercParis4 --out out/attach.points.json
scroliq-vc3d-review --kind winding-ray-order \
  --input artifacts/2026-10-01-paris4-winding-ray-order/PHercParis4.winding-audit.json \
  --scroll PHercParis4 --out out/ray.points.json
```

## 4 · Fiber gaps and sharp turns

**Gaps load directly in VC3D:** `artifacts/2026-10-04-fiber-span-test-run/fiber-gaps.points.json`
has one point per gap candidate, at the midpoint of the long step. Each point
is tagged with `source_file`, `line_step`, `span`, `span_mode` and `step_ratio`.
The pre-registered span test showed 386 of the 388 sit in fallback-interpolated
spans that are rendered sparsely. Review `span_mode = trace` (2 points) and
`step_ratio > 8` (17 points) first. No CT volume is declared for these
coordinates (see goal O9).

For sharp turns, or to re-derive positions for one fiber:

Every row of the census summary names a public fiber (`source_url`, `sha256`)
and its gap / sharp-turn counts. To get exact positions for one fiber:

```bash
curl -fsSL -o fiber.json "<source_url>?download=true"
sha256sum fiber.json                       # must equal the row's sha256
scroliq-fiber fiber.json --out fiber.audit.json
```

`findings` in the report give the `line_points` index of each gap (`segment`)
and sharp turn (`vertex`); open the fiber in VC3D and step to that index.
Record whether each candidate is a real trace break, a sheet switch, or a
rendering artefact of a fallback-interpolated span.

## Upstream reports (drafts, unfiled)

Confirmed data problems in public Vesuvius data, written up for the maintainer
to reproduce and file. **Nothing is filed without explicit maintainer
approval.**

| defect | draft | live recheck |
|---|---|---|
| PHerc0814 surface volume: 6 level headers, 0 chunks (reads return all zeros) | [UPSTREAM-DRAFT-PHerc0814.md](../artifacts/2026-10-04-review-queues/UPSTREAM-DRAFT-PHerc0814.md) | 2026-10-04, still present |
| PHerc1447 `20251105093211-z_dbg_gen_00320`: broken debug mesh among real segments | [UPSTREAM-DRAFT-PHerc1447.md](../artifacts/2026-10-04-review-queues/UPSTREAM-DRAFT-PHerc1447.md) | 2026-10-04, same bytes, same findings |
| PHerc0343P 8.64 µm level 0: 555 chunk objects 8× / 64× declared size | [UPSTREAM-ISSUE-DRAFT.md](../artifacts/2026-10-01-bucket-chunk-audit/UPSTREAM-ISSUE-DRAFT.md) | 2026-10-01 |

Any issue, comment or reply that results is linked from
[progress.html](progress.html).
