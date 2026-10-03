# PHerc0139 Mesh IQ → VC3D review queue — 2026-10-02

This artifact turns Mesh IQ's local geometry findings into **native VC3D
PointCollections** on a real public TIFXYZ surface.

Surface:

- scroll: **PHerc0139**
- segment: `20260306000001-w051_2026030600`
- exact volume: `20250728140407` (9.362 µm)
- TIFXYZ source: public Vesuvius Challenge open-data S3

Every downloaded input file is pinned by byte count and SHA-256 before the
audit runs.

## Result

The full local audit finds:

- **15 edge-jump candidates**;
- **173 severe neighbouring-normal-reversal pairs**.

With the default review limit of 20 sites per finding kind, the emitted
`review-points.json` contains:

- **15 / 15** edge-jump review sites;
- the **top 20 / 173** normal-reversal review sites, ranked by angle;
- **35 total points** in two VC3D collections;
- `vc_pointcollections_json_version: "1"`.

Frozen PointCollections SHA-256:

`c0c8a86dd36d5f80449d39fc5dc45b394415f442c198a857f68caf8e68571282`

The first ranked edge-jump site is:

```text
XYZ = [4151.66796875, 2948.667236328125, 2125.196044921875]
```

The first ranked normal-reversal site is:

```text
XYZ = [2319.84912109375, 4407.392578125, 2783.482666015625]
```

Load `review-points.json` in VC3D as a PointCollections JSON to jump directly
to the highest-priority local review sites.

## Relationship to the cross-tool dossier

The same surface is independently coordinate-bound to Windcheck in
`../2026-10-02-cross-tool-mesh-dossier/`. That dossier reports **3,333
transverse contacts** on the same published original coordinate geometry.

The two evidence layers are intentionally separate:

- this queue localizes Mesh IQ's **local** edge/normal cues for inspection;
- Windcheck supplies the independently bound **nonlocal** intersection census;
- the official VC3D self-cross validator remains the preferred final validator.

## Reproduce

```bash
python -m pip install .
python scripts/pherc0139_mesh_review_queue.py \
  --out-dir /tmp/pherc0139-review

diff -u \
  artifacts/2026-10-02-pherc0139-review-queue/summary.json \
  /tmp/pherc0139-review/summary.json

diff -u \
  artifacts/2026-10-02-pherc0139-review-queue/review-points.json \
  /tmp/pherc0139-review/review-points.json
```

GitHub workflow:
`.github/workflows/pherc0139-review-queue.yml`.

## Claim boundary

These are ranked **review coordinates**, not confirmed defects. A local edge
jump or normal reversal can have a legitimate geometric cause. The queue does
not establish sheet identity, whole-scroll recto coverage, or readable ink.
