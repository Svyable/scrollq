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

This closes a practical loop: ScrolIQ can detect a high-value inconsistency,
hand the exact location to the standard VC3D review environment, and keep the
diagnostic evidence attached to the marker a reviewer sees.
