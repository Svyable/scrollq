# VC3D-native review bundles

ScrolIQ diagnostics should end in a place where a surface reviewer can act on
them. `scroliq-vc3d-review` converts a diagnostic review queue into VC3D's
native PointCollections v1 JSON instead of introducing another review format.

The first supported source is the pre-registered winding-attachment result.
It turns each unique flagged annotation point into one VC3D collection. If
several patch constraints flag the same physical point, the marker is
deduplicated and every patch, residual and attachment distance is retained in
the collection's `findings_json` tag.

## Export

```bash
scroliq-vc3d-review \
  --input artifacts/2026-10-03-paris4-winding-attachment/result.json \
  --scroll PHercParis4 \
  --out /tmp/paris4-winding-review.points.json
```

The command is deterministic: it writes no timestamps, hashes the exact source
JSON, rejects non-finite coordinates and malformed findings, and refuses to
overwrite an existing output.

## Load in VC3D

VC3D's agent bridge exposes the native loader directly. Start VC3D with
`--agent-bridge`, open the matching scroll volume/package, then call:

```text
vc3d_load_points_json(path="/tmp/paris4-winding-review.points.json")
```

The same JSON is ordinary VC3D PointCollections v1 and can be handled by the
normal point-collection workflow. Coordinates are full-resolution
volume-space XYZ voxels.

For the frozen PHercParis4 result, a ready-made file lives beside the evidence:

```text
artifacts/2026-10-03-paris4-winding-attachment/vc3d-review-points.json
```

It contains five physical review points representing six flagged constraints.
The duplicate constraints at `relative:166/2024` remain available in the
collection tag instead of drawing two coincident markers.

## Review contract

These points are cues, not verdicts. A disagreement can come from the winding
annotation, a patch traced onto a neighbouring winding, or local surface
geometry. Inspect the point against CT and the relevant patch before changing
training data or annotations.

The exported file preserves:

- the source JSON SHA-256 and source verdict;
- scroll id and coordinate-space declaration;
- original frame, source point id and winding number;
- finding count and maximum absolute residual;
- every flagged patch piece, residual and attachment distance.

The committed Paris4 bundle is regression-tested against a fresh deterministic
export from the frozen `result.json`. This makes the review artifact itself
part of the reproducible evidence chain.

## Record the review in VC3D

A reviewer records exactly one status and one note on every review collection.
VC3D already exposes collection tags through its agent bridge, so no custom
review format or UI is required.

Allowed `scroliq_review_status` values are:

- `annotation_corrected`: the annotation winding is wrong and the marker's
  `wind_a` has been changed to the reviewed winding;
- `patch_issue`: the annotation should remain unchanged and the conflicting
  patch/attachment is the suspected problem;
- `no_issue`: inspection does not support changing the annotation or blaming
  the flagged patch;
- `uncertain`: the evidence is insufficient for a correction.

Every collection also requires a non-empty `scroliq_review_note`. For example:

```text
vc3d_set_point_collection_tag(
  collection_id=3,
  key="scroliq_review_status",
  value="patch_issue"
)
vc3d_set_point_collection_tag(
  collection_id=3,
  key="scroliq_review_note",
  value="Annotation follows the local sheet; flagged patch is on a different winding."
)
```

For `annotation_corrected`, edit only the winding value on the existing marker:

```text
vc3d_update_point(point_id=3, collection_id=3, winding=2)
```

Do not move review markers, rename their collections, remove provenance tags, or
add unrelated tags. Save the reviewed collection set through VC3D:

```text
vc3d_save_points_json(path="/tmp/paris4-winding-reviewed.points.json")
```

## Ingest reviewed decisions

`scroliq-vc3d-review-ingest` verifies the returned VC3D file against both the
original review bundle and the exact diagnostic `result.json`. It then emits a
deterministic review ledger:

```bash
scroliq-vc3d-review-ingest \
  --original artifacts/2026-10-03-paris4-winding-attachment/vc3d-review-points.json \
  --reviewed /tmp/paris4-winding-reviewed.points.json \
  --diagnostic-result artifacts/2026-10-03-paris4-winding-attachment/result.json \
  --reviewer REVIEWER_ID \
  --reviewed-at 2026-10-03T18:00:00-05:00 \
  --review-minutes 25 \
  --out /tmp/paris4-winding-review-ledger.json
```

The ingest fails closed if provenance tags change, collections or point ids
change, a marker moves beyond the lossless VC3D float32 round trip, a winding
changes without `annotation_corrected`, an annotation correction leaves the
winding unchanged, any decision/note is missing, or the original bundle cannot
be regenerated from the supplied diagnostic source.

The ledger binds:

- the exact diagnostic, original bundle and reviewed bundle SHA-256 hashes;
- the original winding-input hashes carried by the diagnostic;
- every review decision and note;
- before/after winding values;
- reviewer identity, timezone-aware completion time and documented human-review
  minutes.

That closes the provenance half of the review loop without pretending that a
human classification is itself proof of CT support or downstream improvement.
The next step is deterministic application of confirmed annotation corrections
to the hash-matched source PointCollections file, followed by a fresh diagnostic
and before/after comparison.
