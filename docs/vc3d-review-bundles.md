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

## Apply confirmed annotation corrections

`scroliq-winding-apply-review` consumes the review ledger and the exact
`relative_windings.json` whose SHA-256 was carried through the diagnostic.
It applies only decisions marked `annotation_corrected`, never edits the source
in place, and writes both a new native PointCollections file and a deterministic
application manifest.

```bash
scroliq-winding-apply-review \
  --source INPUT/relative_windings.json \
  --ledger /tmp/paris4-winding-review-ledger.json \
  --out /tmp/relative_windings.corrected.json \
  --manifest-out /tmp/relative_windings.application.json
```

The application fails closed if the source hash differs from the reviewed
diagnostic input, the ledger summary disagrees with its decisions, a correction
targets a missing collection or point, the source winding or XYZ no longer
matches the reviewed point, two corrections target the same source point, or a
supposed correction does not actually change `wind_a`. Non-correction decisions
never change source data.

The application manifest binds the source, review ledger, reviewed VC3D bundle,
diagnostic, reviewer/time record, corrected output hash, and every before/after
winding edit. The tool currently applies relative-winding corrections only.
That is intentional: a `relative:<collection-id>` frame maps unambiguously back
to the native source collection, while the shared `absolute` frame does not
carry enough source-collection identity to edit safely.

A corrected file is still only a reviewed hypothesis. The next evidence step is
to construct a rerun dataset with the corrected relative file, leave every other
input byte-identical, and run the pre-registered winding-attachment diagnostic
again.

## Compare the controlled rerun

`scroliq-winding-review-compare` turns that rerun into a fail-closed before/after
artifact:

```bash
scroliq-winding-review-compare \
  --before-result artifacts/2026-10-03-paris4-winding-attachment/result.json \
  --before-attachments artifacts/2026-10-03-paris4-winding-attachment/attachments.json \
  --after-result /tmp/rerun/result.json \
  --after-attachments /tmp/rerun/attachments.json \
  --application /tmp/relative_windings.application.json \
  --out /tmp/winding-review-comparison.json
```

The comparison refuses to run unless the baseline result is the exact diagnostic
bound by the review application; the before/after relative-winding hashes match
the application's source and corrected hashes; every other declared input hash
is unchanged; the diagnostic input accounting and preregistered constants are
unchanged; and the full parsed `attachments.json` list is identical before and
after.

That last requirement closes an important provenance gap: a network rerun cannot
quietly change patch geometry and still be presented as the effect of the winding
edit. The comparison reports residual and review-queue deltas, resolved,
persisted and introduced physical review points, each corrected point's
post-rerun disposition, and before/after positive-control performance. It does
not label a correction physically correct merely because a residual disappeared.
