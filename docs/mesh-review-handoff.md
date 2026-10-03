# Mesh review: reviewer instructions

This packet contains candidate surfaces, not confirmed defects. It contains no
finding key. Review the listed surfaces independently before reading ScrolIQ
reports or discussing their labels with another reviewer. Some filenames may
reveal debugging surfaces; blinding is procedural, not guaranteed.

## Open and inspect

Use VC3D: https://scrollprize.org/tutorial_VC3D . Each CSV row gives the exact
`mesh_url` and `volume_root`. The latter is relative to https://dl.ash2txt.org/ .
Load the corresponding CT and tifxyz surface using your normal VC3D workflow.
Do not substitute a different scan of the same scroll. This packet does not
download CT data or automate VC3D.

Inspect the whole surface and its placement in CT cross-sections. Check for
sheet jumps, folds, unexplained tears/holes, disconnected fragments and severe
stretching. A real papyrus edge or damaged patch is not automatically a defect.
If CT or mesh cannot be loaded, record `unclear` and explain the access problem;
do not delete or replace the row.
If `volume_root` is blank, CT registration is not supplied by this packet.
Record that limitation and use `unclear` where it prevents a decision; do not
guess a compatible volume.

## Record and return

Keep `review_id`, `scroll`, `segment`, `mesh_url` and `volume_root` unchanged.
Fill `label` with exactly one of:

- `defect`: a visible geometric error requiring correction before unrolling.
- `not_defect`: the surface appears usable; irregularity is explained by papyrus.
- `unclear`: insufficient evidence to decide.

Use `defect_type` and `notes` for observations. Where possible, put CT XYZ
coordinates, screenshot filenames, and the action needed in notes. Do not
annotate characters or infer legibility from geometry. Preserve CSV quoting.

Return the completed CSV plus reviewer name/identifier, date, VC3D version,
and whether you had previously seen ScrolIQ findings. Keep screenshots linked
by review ID. Return all rows, including unclear cases. The coordinator will
score the labels; do not look up the hidden classes while reviewing.

Reviewing a packet does not authorize publication of your name or images.
Agree on attribution and screenshot sharing before the coordinator publishes.
