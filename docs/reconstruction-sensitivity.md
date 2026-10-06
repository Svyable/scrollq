# Reconstruction-sensitivity audit

`scroliq-reconstruction-sensitivity` asks which ink and geometry claims survive
when **only the reconstruction mathematics, or a physically plausible
calibration parameter, changes**. The measured projections, the acquisition
geometry (except a declared perturbation), the preprocessing and the downstream
geometry/render/ink pipeline are held fixed; only each variant's frozen outputs
are read. It never runs a reconstruction and imports no tomography package.

It is evidence machinery. A component that exists under only one reconstruction
assumption becomes `reconstruction_sensitive` evidence, not prize-grade ink. One
that survives is `reconstruction_stable`, which is **not** an ink verdict,
readable text or a claim about the ancient papyrus: it means only that it
persisted across the preregistered family that was actually run. Every report
carries `promotional: false`.

**State of evidence.** Synthetic controls only
([artifact](../artifacts/2026-10-06-reconstruction-sensitivity-synthetic/README.md)).
No reconstruction has been run, and it has not been established here that raw
projections and acquisition geometry are released for any Vesuvius scan (see the
[research note](research/2026-10-06-reconstruction-sensitivity-and-cil.md)). The
audit is the part that can be built and falsified now; the experiment is blocked
on one pinned ROI with projections, geometry and a reproducible official
reconstruction.

## The experiment it serves

For one ROI with raw projections, reconstruct exactly that ROI four ways, chosen
before any ink inference:

| variant | role |
|---|---|
| official reconstruction | reference |
| LSQR | `lsqr` |
| LSQR + weak Tikhonov | `lsqr_tikhonov` |
| LSQR + stronger Tikhonov | `lsqr_tikhonov` |

Select convergence and regularisation from projection residual and ordinary
physical reconstruction criteria. Do not look at ink while selecting. Freeze
every volume, then run the identical ScrolIQ geometry, render and ink pipeline
over each. An optional **calibration arm** perturbs a known acquisition
parameter (for example centre of rotation) by small, physically plausible,
preregistered amounts around one baseline reconstruction.

This audit reads the results. The outputs it records are deliberately not PSNR or
visual sharpness: surface displacement along the reference normal, neighbouring
sheet separation, fibre-orientation change, connected ink-component persistence,
ink-response position along the normal, and detections inside known-negative
regions.

## What is held fixed, and enforced

`validate_spec` refuses a spec in which any of these is violated:

- **Selection is ink-blind and early.** Every non-reference variant records
  `selection.criteria`, `ink_used_in_selection: false`,
  `selected_before_ink_inference: true`, a recorded `projection_residual` and the
  hash of the evidence behind it. A true or missing flag is a refusal. These are
  declarations; the tool cannot prove their timing, so commit the spec before
  any ink inference.
- **One measured dataset.** Every variant's fingerprint must equal the family's
  `projections_sha256`, `preprocessing_sha256`, `pipeline_sha256` and
  `coordinate_convention`. Geometry must also match, unless the variant is a
  declared calibration perturbation.
- **The perturbation is the only change.** A `calibration_perturbation` variant
  must repeat its baseline's software and algorithm exactly, carry a geometry
  hash different from the baseline's, declare a nonzero parameter value, and stay
  within a `calibration_bounds` entry (`max_abs` plus the evidence for it). Without
  a preregistered bound a parameter cannot be perturbed, which is what prevents
  perturbing until a letter appears or disappears. All calibration variants share
  one baseline.
- **Distinct, declared variants.** Exactly one `official` reference that
  succeeded; unique ids; no two variants with the same declaration;
  `lsqr_tikhonov` needs a positive `regularisation_strength` (the adapter-neutral
  name used here, not necessarily a library argument).
- **Dependencies are recorded exactly** (next section).

A failed reconstruction is listed (`outcome: failed` plus a reason), never
dropped. A variant whose `volume_sha256` equals its baseline's, or whose ink array
is bitwise identical to it, is **not varied**: the declared intervention had no
effect, and a family containing one cannot yield `reconstruction_stable`.

## Licences

CIL itself is Apache-2.0; the ASTRA Toolbox is GPLv3, and the CIL ASTRA plugin is
documented as GPLv3 (read here only through search snippets of the CIL and ASTRA
pages). The framework's top-level licence is therefore not inferred for an
execution path. Each non-reference variant declares
`dependencies.manifest_sha256`, `complete_transitive` and the exact
`packages` with SPDX-style licences; the report classifies each as
`permissive`, `weak_copyleft`, `copyleft` or `unknown` (`A AND B` is as
restrictive as its worst part, `A OR B` its best, parentheses or unrecognised
text are `unknown`) and summarises `permissive_only`, `weak_copyleft_present`,
`copyleft_present`, `unknown_present` or `incomplete_manifest`. Run the
reconstructions in an isolated external environment with that lock file; ScrolIQ
itself depends on neither package, and the frozen volumes are data inputs. If a
variant were ever part of a submitted pipeline, the declared licences are what
the prize's permissive-licence requirement would be checked against.

## Inputs

```bash
scroliq-reconstruction-sensitivity evaluate --spec spec.json --out out/sensitivity.json
```

Paths are relative to the spec's directory. The spec holds the ROI
(`level0-voxel-index-zyx`), the shared UV `grid.shape`, the `rules`, the
`calibration_bounds`, the `family` fingerprint and the variant records:

```json
{
  "schema": "scroliq-reconstruction-sensitivity-spec-v1",
  "roi": {"volume_id": "...", "start": [0, 0, 0], "stop": [64, 512, 512],
          "coordinate_space": "level0-voxel-index-zyx"},
  "grid": {"shape": [512, 512]},
  "masks": "masks.npz",
  "rules": {"ink_threshold": 0.5, "min_component_cells": 40, "match_iou": 0.5,
            "negative_component_tolerance": 0, "min_reconstruction_variants": 3,
            "min_calibration_variants": 2, "require_calibration_arm": true,
            "required_channels": ["surface_xyz", "neighbor_xyz", "fiber_angle", "ink_depth_offset"],
            "tolerances": {"normal_displacement_voxels": 1.0, "neighbor_separation_voxels": 1.0,
                           "fiber_angle_degrees": 10.0, "ink_depth_offset_voxels": 1.0}},
  "calibration_bounds": {"center_of_rotation_pixels": {"max_abs": 1.0, "evidence": "<calibration report>"}},
  "family": {"projections_sha256": "...", "geometry_sha256": "...", "preprocessing_sha256": "...",
             "pipeline_sha256": "...", "coordinate_convention": "..."},
  "variants": [{
    "id": "lsqr", "role": "variant", "kind": "lsqr", "outcome": "ok", "data": "lsqr.npz",
    "baseline": "official",
    "fingerprint": {"projections_sha256": "...", "geometry_sha256": "...", "preprocessing_sha256": "...",
                    "pipeline_sha256": "...", "volume_sha256": "...", "coordinate_convention": "..."},
    "software": {"name": "...", "version": "..."},
    "algorithm": {"name": "...", "parameters": {"iterations": 20}},
    "selection": {"criteria": ["projection_residual", "physical_plausibility"],
                  "ink_used_in_selection": false, "selected_before_ink_inference": true,
                  "projection_residual": 0.01, "evidence_sha256": "..."},
    "dependencies": {"manifest_sha256": "...", "complete_transitive": true,
                     "packages": [{"name": "...", "version": "...", "license": "..."}]}
  }]
}
```

`rules` has no defaults: every threshold, tolerance, minimum and required channel
is a preregistered field. `masks.npz` holds boolean `valid` and `negative`
arrays (every negative cell must be valid). Each variant's `.npz` holds float
arrays on the **reference's UV grid** (resample a re-inferred surface onto it
upstream): `ink` in [0, 1] (required) and the optional `surface_xyz` and
`neighbor_xyz` (`rows x cols x 3`, level-0 `[z, y, x]`), `fiber_angle`
(radians) and `ink_depth_offset` (voxels along the normal). Unknown array
names, non-float dtypes, NaN, wrong shapes and pickles are refused. A channel
listed in `required_channels` that a variant lacks makes its components
`unverified`, never stable.

## Reading the report

For each reference ink component (8-connected cells of `ink >= ink_threshold`
inside `valid`, at least `min_component_cells` cells):

- **Presence.** In each variant of an arm it is matched if its best IoU with a
  variant component is `>= match_iou` (IoU exactly at the threshold counts).
- **Geometry under its footprint**, change relative to the arm's baseline: p95 of
  the absolute surface displacement along the *baseline* normal, neighbouring-sheet
  separation, fibre orientation (modulo pi, degrees) and ink-response position.
  Each is compared with its preregistered tolerance (strictly greater is an
  exceedance).
- **`evidence_class`**: `reconstruction_sensitive` if the component is absent, or
  a geometry channel exceeds tolerance, in any effective variant of either arm;
  `reconstruction_stable` only if the family is complete (no failed or not-varied
  variant, at least the minimum effective variants, every required channel
  measured) and nothing exceeded; otherwise `unverified`. Measured sensitivity
  outranks an incomplete family, but an incomplete family can never certify
  stability. A calibration arm whose baseline is not the official reference is
  reached through the matched baseline component, not through its label.
- **Variant-only components** and **known-negative regions**: components a
  variant produces with no match in its baseline (flagged if they touch the
  negative region), and the change in the number of components and ink fraction
  inside the known-negative cells (`manufactures_negative_components` if the
  excess is above `negative_component_tolerance`; `not_measured` if there are no
  negative cells).
- `global_change` per variant summarises each channel over all valid cells. It
  can hide a localized change (a 1% displaced patch does not move a 95th
  percentile); the per-component values are the ones to read.

## Controls

Before any verdict, `evaluate` runs a built-in control: planted components that
must be recovered with their reasons, a manufactured component in a negative
region that must be flagged, a null family that must stay all-stable, and a
no-op family (bitwise copies of the reference) that must not pass. If it does not
fire the report is `unverified` with no component results. `self-test` also
checks that an ink-selected variant, an implausible perturbation and a
copyleft backend are refused or flagged, and exits 1 on any failure.

## Limits

- Declarations are not verified: fingerprints, the ink-blind selection, the
  projection residual and the dependency manifest are recorded and
  cross-checked for consistency, not recomputed. The tool does **not** compute a
  projection-consistency residual; that belongs to the reconstruction
  environment.
- The family is small. `reconstruction_stable` means stable across the variants
  that were run, not across every defensible inverse solution, and not stable
  under settings that were not preregistered.
- Every reconstruction variant is compared with the official reference, which
  differs from a CIL reconstruction in preprocessing and algorithm at once. A
  component absent in `lsqr` and in both Tikhonov variants points at that
  difference, not at regularisation; only contrasts between variants that change
  one declared parameter (for example the two Tikhonov strengths against `lsqr`)
  are controlled, and this version reports them only through the common reference.
- Components are matched on the UV grid; split and merged components lower IoU and
  read as absent.
- No uncertainty interval is attached: classification is a deterministic function
  of frozen rules, so the choice of tolerances matters and is the preregistered
  judgement.
- Patches are not independent specimens; one ROI supports a statement about that
  ROI.

Next evidence needed: one ROI with released projections, acquisition geometry and
a reproducible official reconstruction; the frozen spec committed before ink
inference; and the licence manifest of the isolated environment.

```bash
python -m pytest tests/test_reconstruction_sensitivity.py -q
```
