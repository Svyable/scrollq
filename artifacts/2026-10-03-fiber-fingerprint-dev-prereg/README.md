# CT fiber-fingerprint development preregistration

**Status: frozen before CT texture is read.**

Coverage-witness Stages B and C both reached the same conclusion: once the
correct sheet location is known, the independent surface predictor detects a
deliberate omission cleanly, but smooth visible-surface continuation is not a
reliable way to infer physical sheet identity across large gaps.

This experiment changes the information source. It asks whether **local CT
texture in a material-aligned tangent frame** can distinguish nearby material
on the known w035 sheet from the already-frozen adjacent-winding control.

## Development / holdout firewall

The 20 original geometry-only probes not used as Stage-B or Stage-C decision
regions are split before any CT texture is read:

- 10 development regions: alternating even positions in original order;
- 10 holdout regions: alternating odd positions.

The development workflow is forbidden from sampling holdout descriptors.

The same-sheet threshold is not hand-picked. It is the frozen 95th percentile
of pooled development center-to-neighbor distances. Only if the development
gate passes may that exact threshold be frozen in a separate holdout
preregistration.

## Descriptor

At each point, w035 centered tangents define an orthonormal material frame.
The CT is sampled in five 25x25 tangent slices at normal depths
`[-4,-2,0,+2,+4]` voxels.

Each slice contributes:

- an unsigned 12-bin gradient-orientation histogram;
- four gradient-magnitude quantiles;
- three radial Fourier-power bands × 12 unsigned angular bins.

The five 52-value slice descriptors are concatenated and L2 normalized.

Same-sheet controls are exactly three material-grid cells from the center in
the four cardinal directions. The wrong-wrap descriptor uses the same frozen
center frame at the already-frozen wrong-wrap coordinate.

This is intentionally a simple, auditable physical descriptor rather than a
learned embedding.

## Decision

A development pass is not evidence on the holdout and is not an INCLUDE
decision. It only permits freezing the derived threshold and running the
untouched holdout.

A development failure dismisses this descriptor version without tuning it on
the holdout.
