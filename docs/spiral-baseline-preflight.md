# Spiral baseline preflight

`scroliq-spiral-preflight` is the hard gate immediately before the frozen
PHerc0826 baseline GPU fit.

The campaign intentionally reuses the official `ScrollPrize/villa` fitter and
the public `eligible-spiral-dataset` assembler. ScrolIQ's job here is not to
reimplement Spiral: it prevents an expensive run from starting when the local
dataset no longer matches the preregistered PHerc0826 recipe.

## Gate

```bash
scroliq-spiral-preflight \
  --dataset ds0826 \
  --recipe artifacts/2026-10-03-spiral-baseline-target/pherc0826_baseline_recipe.json \
  --out out/pherc0826.preflight.json
```

A PASS requires all of the following:

- `spiral-scroll.json` names PHerc0826 and matches the frozen 9.362 µm,
  outward-sense, normal-group, and Lasagna-scale values;
- the published umbilicus exists locally;
- `paths.tracks_dbm` resolves inside the dataset and names a regular file;
- exactly one crossings archive and one track-extraction provenance sidecar
  are present;
- the extraction provenance contains the exact eligible volume ID
  `20250821151701`;
- the crossings archive's own `db_signature` matches the local tracks DBM
  **size and nanosecond mtime**, catching the failure mode that causes villa to
  discard the published cache and rebuild it;
- the PHerc0826 Lasagna nx, ny, and gradient-magnitude stores contain the
  frozen group and agree on shape;
- the resident-pool sidecars required by the current villa path are present;
- the bounded z range, 30,000 steps, seed 1, and `input_use_tracks=true`
  remain exactly as preregistered;
- patches remain disabled for the reproduction baseline.

The report hashes the control files and the large track/crossings inputs so the
run log can bind what was actually consumed. It also emits canonical
`FIT_SPIRAL_CONFIG_OVERRIDES` JSON for the launcher.

This gate does **not** decide whether `CW` is scientifically correct. The
campaign explicitly treats it as the published-example setting for initial
reproduction and requires an independent VC3D/catalog cross-check before the
geometry is promoted beyond reproduction evidence.

## Why this is a separate tool

A 30,000-step fit that succeeds on the wrong local dataset is worse than a
preflight failure: it produces plausible geometry and consumes GPU time while
weakening the evidence chain. The preflight therefore treats cache drift,
source-volume ambiguity, missing Lasagna inputs, and config drift as blocking
errors rather than warnings.
