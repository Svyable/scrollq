# Papyrus microtexture seam authentication

**Status:** EXPERIMENT FURTHER. `scroliq-seam-fingerprint` is implemented and its
software controls pass on **synthetic** sheets. **No real-CT measurement exists.**
Nothing here is evidence that carbonized papyrus at scan resolution carries a
recoverable fingerprint, and nothing here may influence reconstruction yet.

## The question

| Evidence layer | Question it asks |
|---|---|
| CT sheetness | Is this papyrus-like? |
| Fiber audit / fiber frame | Is its structure coherent? |
| Winding, ray-order, braid | Is its topology plausible? |
| **Seam authentication** | **Is this literally the same physical piece of papyrus?** |

When an unroller joins patch A to patch B, the join claims their overlap is the
same material. Another winding can be locally smooth, sheet-like, similarly
oriented and similarly thick, and so survive every control above. It should not
reproduce the same microscopic arrangement of fiber crossings, voids and cracks.
Ink is never read.

Two uses, in order of value:

1. **Seam proof.** Mark each join `AUTHENTICATED`, `CONTRADICTED` or `UNKNOWN`.
2. **Seam refinement.** Once a join is authenticated, the correlation peak is a
   residual tangent displacement that could correct small registration error
   before flattening. Only reported as usable when the peak is strong
   (`refinement.usable`, below).

## Method: `tangent-microtexture-phasecorr-v1`

Input: two slabs `(depth, y, x)` already rectified into local tangent
coordinates on one pixel grid for the claimed overlap, plus optional validity
masks and the displacement the claimed registration implies (default zero).
The upstream sampling step stays explicit and is bound by a frozen manifest
hash, as for [`scroliq-fiber-frame`](fiber-frame.md).

1. **Reject what cannot correlate.** Invalid pixels, and amplitude outliers of
   the locally high-passed raw slice (cracks, folds, large voids), are replaced
   by a smooth normalized-convolution fill *before* band-passing and excluded
   after. A through-going crack shared by two different windings is exactly an
   outlier; removing it where it is a sharp line avoids the wide halo a
   band-pass would spread around it. The evidence must come from background
   microtexture.
2. **Band-pass** (difference of Gaussians, σ 1 and 4 px), then a Tukey window.
3. **Band-weighted phase correlation** per slice pair, pooled over depth lags
   `|dz| <= 2` (each lag needs at least half the slab). Convention: content at
   `r` in A appears at `r + d` in B.
4. **Peak statistic.** Robust z of the correlation plane (median/MAD) inside a
   search disk of radius 12 px around the expected shift. Report the sub-pixel
   shift (parabolic), depth lag, second-peak uniqueness ratio, and the fraction
   of slice pairs whose own best cell agrees with the pooled peak.
5. **Calibrate against surrogates of the same slab.** Sixteen 3-D
   phase-randomized copies of patch B (same power spectrum, destroyed identity),
   seeded from a digest of the inputs and config, give a per-case null. The
   falsification test is therefore inside every decision, not only in the tests.
6. **Decide**, in this order (first match wins):

| Verdict | Reason | Condition |
|---|---|---|
| UNKNOWN | `insufficient-valid-fraction` | a patch has < 70 % valid pixels |
| UNKNOWN | `identical-pixel-arrays` | the two arrays are bit-identical on the valid area |
| UNKNOWN | `insufficient-band-information` | in-band power < 1.5 × the top-frequency noise floor in either patch |
| UNKNOWN | `insufficient-unmasked-microtexture` | > 35 % of a patch was rejected as outlier/invalid |
| CONTRADICTED | `normal-orientation-flipped` | reversing B's depth axis gives z >= 9 and >= 1.5 × the unflipped z |
| CONTRADICTED | `no-correspondence-within-search` | z < 6 (informative texture on both sides, no compatible peak) |
| UNKNOWN | `peak-below-authentication-floor` | 6 <= z < 9 |
| UNKNOWN | `ambiguous-peak` | peak / second peak < 1.5 |
| UNKNOWN | `not-separated-from-phase-randomized-surrogates` | z < 1.25 × the largest of 16 surrogate z |
| UNKNOWN | `depth-lag-at-search-boundary` | best lag is at the edge of the lag search, so the lag is not established |
| CONTRADICTED | `registration-offset-exceeds-tolerance` | unique strong peak more than 3 px from the claimed registration |
| AUTHENTICATED | none | all of the above clear |

Low-information texture can only produce `UNKNOWN`. A strong peak at the wrong
displacement is `CONTRADICTED` (the claim is wrong even though the material is
shared) and the report still carries the recovered offset.

`CONTRADICTED` means "informative texture on both sides and no compatible
correspondence under a translation-plus-depth-lag model". Non-rigid deformation
over the tile can also cause it. The real-CT benchmark must measure that
false-contradiction rate; it is not assumed small.

`refinement.usable` is true only for `AUTHENTICATED` with z >= 25. In the
held-out synthetic suite, authenticated runs with weak peaks carried displacement
errors up to 0.93 px while strong ones stayed under 0.4 px (numbers below), so
`AUTHENTICATED` alone must never be read as "safe to shift the seam".

### Frozen constants

The constants live in `SeamConfig`; `config_sha256` and `source_sha256` are bound
into every report. **They are provisional**: set on synthetic data only, to be
re-derived on a real-CT development split and frozen unchanged before any
held-out evaluation. Shape defaults used by the synthetic suite: 64 × 64 px
tiles, 5 depth slices (tiles must be at least 4 × the search radius).

| Constant | Value | Role |
|---|---|---|
| `sigma_low_px`, `sigma_high_px` | 1.0, 4.0 | band-pass; removes pixel noise and gross structure |
| `window_alpha` | 0.5 | Tukey taper |
| `search_radius_px`, `exclusion_radius_px` | 12, 3 | peak search / second-peak exclusion |
| `depth_search` | 2 | depth lags tried |
| `geometry_tolerance_px` | 3 | residual allowed for AUTHENTICATED |
| `z_authenticate`, `z_contradict` | 9, 6 | peak z floors |
| `min_unique_ratio` | 1.5 | peak / second peak |
| `surrogates`, `surrogate_margin` | 16, 1.25 | phase-randomized null |
| `min_band_snr`, `min_valid_fraction` | 1.5, 0.7 | information gates |
| `feature_clip_sigma`, `feature_dilate_px`, `max_masked_fraction` | 4, 2, 0.35 | outlier-feature rejection |
| `flip_margin` | 1.5 | normal-flip detection |
| `z_refine` | 25 | refinement usable |

`z_authenticate = 9` and `z_contradict = 6` were chosen from a small initial
synthetic null (a few dozen wrong-sheet pairs, not committed) before the larger
suites ran. The committed suites later produced null and destroyed-identity
peaks above `z_contradict` (see the gate summary below), so the margin to
`z_authenticate` is **thin**. A real-CT calibration must set these from an
empirical null with a quantified false-authentication rate, not carry them over.

## What a peak can mean: two arms

Two slabs sampled from the **same CT volume** share its voxel noise. A peak there
certifies that both patches read the same voxel neighborhood at the recovered
transform. That is a high-sensitivity registration check, **not** proof of an
independent physical fingerprint, and it is close to what the XYZ coordinates
already imply. The control `blank_shared_voxel_noise` shows the hazard is real:
with the information gate off, featureless papyrus whose two patches read one
noise realization is `AUTHENTICATED`.

Only **independent registered rescans** of the same scroll (different noise,
different acquisition, related by a `transform.json`-style registration; see
`scroliq-pairs --list`) can test physical microstructure. The CLI records which
arm a report belongs to (`noise_arm`: `shared-voxels` when both volume roots
are equal, `independent-scans` otherwise) and writes the matching caveat into
`interpretation`. Independence between two different roots is declared, not
verified here.

## Synthetic software controls

These are **software controls on synthetic sheets** (crossed fiber plies with
cross-ply depth structure, plus voids; slab standard deviation about 1.1). They
show the implementation honors its stated rules, including the falsification and
low-information controls. They say nothing about real carbonized papyrus.

Held-out run: `controls-heldout.json`, seed base 700000 (never looked at before
the constants were final), 40 seeds per control, `scroliq-seam-fingerprint controls --seed-base 700000 --n 40 --sweep-n 12`.
Gate: **PASS**. Peak z is the robust z of the best cell in the search disk.

| control | kind | AUTH / CONTRA / UNKNOWN | peak z (min / median / max) | shift error px, authenticated runs (median / max) |
|---|---|---|---|---|
| `genuine_small_offset` | genuine | 40 / 0 / 0 | 101.2 / 186.4 / 497.0 | 0.14 / 0.25 |
| `genuine_independent_noise` | genuine | 40 / 0 / 0 | 26.4 / 30.7 / 33.8 | 0.09 / 0.19 |
| `genuine_rerendered` | genuine | 40 / 0 / 0 | 38.1 / 44.0 / 52.5 | 0.08 / 0.15 |
| `genuine_depth_offset` | genuine | 40 / 0 / 0 | 85.4 / 168.1 / 456.5 | 0.14 / 0.28 |
| `genuine_fused_sheet` | genuine | 40 / 0 / 0 | 21.2 / 30.7 / 40.7 | 0.13 / 0.37 |
| `genuine_shared_crack` | genuine | 40 / 0 / 0 | 94.7 / 148.4 / 540.3 | 0.18 / 0.36 |
| `genuine_degraded` | genuine | 20 / 0 / 20 | 7.9 / 10.2 / 12.3 | 0.64 / 0.93 |
| `genuine_depth_misregistered` | genuine | 0 / 0 / 40 | 28.0 / 51.4 / 62.2 | - |
| `genuine_registration_offset` | misregistered | 0 / 40 / 0 | 30.2 / 44.4 / 63.7 | - |
| `wrong_sheet_independent` | impostor | 0 / 40 / 0 | 3.1 / 3.8 / 5.8 | - |
| `adjacent_shared_coarse` | impostor | 0 / 39 / 1 | 2.8 / 4.0 / 6.0 | - |
| `shared_crack_impostor` | impostor | 0 / 37 / 3 | 3.6 / 4.8 / 7.5 | - |
| `shared_fold_impostor` | impostor | 0 / 39 / 1 | 3.1 / 4.1 / 6.1 | - |
| `offset_beyond_search` | misregistered | 0 / 39 / 1 | 2.8 / 3.9 / 7.5 | - |
| `flipped_normal` | misregistered | 0 / 40 / 0 | 39.5 / 52.0 / 67.7 | - |
| `phase_randomized` | falsification | 0 / 40 / 0 | 3.0 / 4.0 / 4.7 | - |
| `block_shuffled` | falsification | 0 / 40 / 0 | 2.9 / 3.8 / 5.5 | - |
| `blank_smooth` | unknown-required | 0 / 0 / 40 | 3.4 / 4.0 / 5.6 | - |
| `blank_shared_voxel_noise` | unknown-required | 0 / 0 / 40 | 254.9 / 337.9 / 1883 | - |
| `pure_noise` | unknown-required | 0 / 0 / 40 | 3.1 / 4.0 / 5.7 | - |
| `identical_pixels` | unknown-required | 0 / 0 / 40 | 11842 / 20634 / 56246 | - |

What the table says, with the caveats attached:

- **No false authentications**: 0 of 160 impostor runs (wrong sheet, shared coarse
  structure, shared crack, shared fold), 0 of 120 misregistered runs (flipped
  normal, 8 px and 20 px offsets), 0 of 80 destroyed-identity runs, and 0 of 160
  low-information runs.
- **Falsification pair collapses**: the median peak z of the phase-randomized and
  block-shuffled controls is 2.1 % and 2.0 % of the matched genuine control's, and
  neither is ever authenticated. This is the test that separates correspondence
  from generic papyrus appearance.
- **The margin is thin.** The largest impostor-or-destroyed peak was z 7.49 against
  `z_authenticate` 9.0 (1.2×); the development-seed run gave 7.45. The gap to
  well-posed genuine pairs (smallest z 21.2) is wide, but the gap to the threshold
  is not, and real-CT calibration has to widen it or accept the false-authentication
  rate it measures.
- **Displacement**: the largest error among authenticated runs in the well-posed
  genuine controls was 0.37 px (median 0.08–0.18); depth lag was recovered in all
  runs of `genuine_small_offset` and `genuine_depth_offset`. The degraded control
  authenticates 20 of 40 runs (the rest abstain, none are contradicted), but the
  authenticated ones carry error up to 0.93 px (median 0.64) at peak z 7.9–12.3.
  That is why `AUTHENTICATED` does not imply `refinement.usable`: every run with
  error above 0.5 px has z below 12.4, and `z_refine = 25` was set from a
  development scatter of error against z (not committed) and not tuned on this run.
- **Shared voxel noise is a real hazard.** `blank_shared_voxel_noise` peaks at
  z 255–1883, far above any threshold; only the information gate keeps it
  `UNKNOWN`.
- A flipped normal is `CONTRADICTED` with reason `normal-orientation-flipped`, and
  a sampling-depth error beyond the lag search is `UNKNOWN`
  (`depth-lag-at-search-boundary`), not a wrong lag asserted with confidence. The
  flip is only detectable because the synthetic sheet has cross-ply depth
  structure; on a depth-invariant sheet it would not be.

Detectability envelope (informational, not gated; 12 seeds per level,
independent noise in each patch as in an independent-scan arm):

| noise σ per patch | AUTH / CONTRA / UNKNOWN (n=12) | median peak z |
|---|---|---|
| 0.5 | 12 / 0 / 0 | 44.2 |
| 1 | 12 / 0 / 0 | 30.1 |
| 2 | 12 / 0 / 0 | 17.5 |
| 3 | 12 / 0 / 0 | 11.9 |
| 4 | 0 / 0 / 12 | 8.9 |
| 6 | 0 / 0 / 12 | 5.5 |
| 8 | 0 / 0 / 12 | 4.7 |

Authentication holds up to per-patch noise about 2.7× the sheet's own standard
deviation and abstains from about 3.6×. That is a property of this synthetic
texture and this band, not a forecast for real CT.

| in-plane rotation of B (deg) | AUTH / CONTRA / UNKNOWN (n=12) | median peak z |
|---|---|---|
| 0 | 12 / 0 / 0 | 44.2 |
| 0.5 | 12 / 0 / 0 | 42.9 |
| 1 | 12 / 0 / 0 | 40.2 |
| 2 | 12 / 0 / 0 | 32.9 |
| 4 | 12 / 0 / 0 | 20.0 |

A translation-only model survives 4° of in-plane rotation of B on a 64 px tile
with the peak z roughly halved; the tool does not estimate rotation.

### Ablations: why each gate exists

Same seeds, one gate disabled, committed so the hazards stay visible (both are
expected to FAIL and do):

- `controls-ablation-feature-gate.json` (`--ablate feature-gate`):
  `shared_crack_impostor` is **`AUTHENTICATED` in 33 of 40 runs** (peak z up to
  14.7). A crack that crosses two different windings is exactly what a naive
  correlation recognizes.
- `controls-ablation-information-gate.json` (`--ablate information-gate`):
  `blank_shared_voxel_noise` is **`AUTHENTICATED` in 40 of 40 runs**, and the
  independent-noise `blank_smooth` and `pure_noise` controls flip from `UNKNOWN`
  to `CONTRADICTED` in every run: without the gate, noise is read as evidence of a
  wrong sheet instead of as no evidence.

Other artifacts: `controls-development.json` (seed base 100000; gate PASS; used
while developing, so not held-out), `controls-heldout-run1-superseded.json` (first
held-out run, 19 cases, earlier source), and `descriptor-comparison.json`
(`scripts/seam_descriptor_comparison.py`).

## Real-CT benchmark (pre-registration; not run)

Everything above is a prerequisite. The real experiment is:

**Pairs.** Genuine pairs come from independently generated overlapping patches
(separate extraction calls, different tangent-frame origins), so the test cannot
rediscover shared preprocessing. Negatives, in increasing difficulty:

1. distant papyrus;
2. a nearby non-adjacent winding;
3. the immediately adjacent winding at nearly identical orientation and depth.

Each negative is also run with the shared-structure confounders the synthetic
suite models: a crack or fold crossing both windings, a shared coarse thickness
profile, a fused sheet.

**Independence requirements.** Hash every rendered tile array; any shared tile
hash between a genuine pair is an invalid pair (the module detects only exact
array identity). Run both arms: same volume (registration check) and registered
independent rescans (physical identity).

**Metrics.**

- ROC and precision-recall for same-sheet versus adjacent-winding impostor, per
  arm, stratified by CT quality (resolution/energy, local SNR, band information).
- Displacement error on overlaps with a known transform (applied offsets on
  independently rendered patches), reported at `AUTHENTICATED` and at
  `refinement.usable`.
- `UNKNOWN` rate by stratum. The lowest-information stratum must abstain, not
  authenticate.
- False-contradiction rate on genuine overlaps with real deformation.

**Mandatory controls** (already implemented synthetically, to be repeated on
real patches): blank/smooth papyrus, severe compression, cracks, folds, fused
sheets, flipped normals, altered sampling depth, synthetic coordinate offsets,
independently rerendered TIFXYZ patches, plus the **falsification pair**:
phase-randomize and block-shuffle one CT texture while keeping its local
statistics. Authentication must collapse. If it does not, the method recognizes
generic papyrus appearance, not physical identity, and is rejected.

**Gross-structure nuisance baseline.** Re-score the same negatives with a
descriptor limited to gross fiber direction, depth and thickness. The seam
statistic must beat it on the adjacent-winding negatives by a margin fixed in
advance; otherwise the result is attributed to those nuisances.

**Freeze before held-out.** Frequency bands, slab depth, normalization, search
radius, acceptance rule and the seam-level aggregation rule are committed (with
`config_sha256` and `source_sha256`) before any held-out pair is scored.
Seam-level aggregation across tiles is **not implemented**: the tool authenticates
one tile pair. A proposed rule, to be frozen first: authenticate a seam only when
enough informative tiles authenticate with mutually consistent residuals, and
raise any informative contradicted tile for review.

### Decision rule (proposed; numbers to be confirmed before the real run)

- **INCLUDE** only if, on held-out real overlaps: zero false authentications in at
  least 300 independent adjacent-winding impostor tiles (rule of three: 95 %
  upper bound about 1 %) drawn from more than one region and scan; the
  independent-scan arm separates genuine from adjacent impostors; displacement
  error at `refinement.usable` has p95 <= 0.5 px; the lowest-information stratum
  abstains; the falsification pair collapses; and the gross-structure baseline is
  beaten.
- **DISMISS** if separation comes mainly from gross fiber direction, depth, or
  shared rendering artifacts, or the falsification pair does not collapse. Do not
  rescue it with a learned matcher.
- Otherwise **EXPERIMENT FURTHER**. A Siamese or other learned matcher is
  DISMISSED for now ([why](research/dismissed-and-deferred.md)); it could exploit
  scanner, depth, geometry or preprocessing shortcuts, and its score could not be
  tied to a physical cause.

## Development log and deviations

Kept next to the results so that every change made after seeing data is visible.

1. **First probe: naive correlation accepted shared cracks.** With band-passed
   phase correlation and no feature rejection, a crack shared by two different
   sheets was `AUTHENTICATED`, including a crack-dominated case. Added outlier
   rejection. The committed `--ablate feature-gate` artifact keeps this failure
   reproducible.
2. **Band-domain masking leaked.** Masking in the band-passed image left the
   band-pass halo (σ 4) around the crack, and a shared-crack impostor still
   exceeded the acceptance floor. Moved detection and fill to the raw domain.
   This is the shipped design.
3. **Two controls were ill-posed, not the method.** The synthetic sheet was
   nearly depth-invariant, so a flipped normal changed nothing and "depth beyond
   search" was still correlated through the texture's depth correlation. The
   generator gained cross-ply depth structure; `depth_search` went 1 → 2, a
   `depth-lag-at-search-boundary` rule was added so an unestablished lag is not
   asserted, and the flip diagnostic now always runs. The genuine shared-crack
   control had left the crack fixed while the texture moved; fixed.
4. **A prediction failed.** I expected the existing `tangent-fiber-spectrum-v1`
   descriptor to be blind to phase randomization. Measured on synthetic shifted
   copies (`scripts/seam_descriptor_comparison.py`, 20 seeds,
   `descriptor-comparison.json`), its median distance to the original was 0.0006
   for the genuine copy, 0.0540 for a phase-randomized copy, 0.0665 for a
   block-shuffled copy and 0.0433 for an unrelated sheet. It separates them. The
   claim was dropped; the real difference is that it returns a similarity, not a
   displacement or a calibrated correspondence.
5. **Seed bookkeeping.** Seed base 100000 was looked at while developing and is
   labeled development. The held-out base 700000 was not run until the
   constants were final. `min_band_snr` was lowered from 3.0 to 1.5 after a
   development noise sweep showed 3.0 abstained on pairs whose peak was far above
   the null.
6. **A control was added after the first held-out run.** `blank_shared_voxel_noise`
   was missing: the earlier blank control used independent noise, so it passed
   whether or not the information gate existed. Adding it changed the source, so
   the held-out run was repeated on the same seeds. The first held-out artifact is
   kept as `controls-heldout-run1-superseded.json` (19 cases, earlier source).

## Known limits

- All numbers above are synthetic. Whether 7.91 µm or 3.24 µm carbonized papyrus
  keeps texture at the frozen band is the open question.
- Translation plus depth-lag model per tile. In-plane rotation was swept (see the
  results) but the tool does not estimate rotation or non-rigid warp; tile size
  trades overlap against how rigid the patch is.
- The crack/fold gate rejects anything that looks like an amplitude outlier, which
  also discards genuine voids and inclusions that might carry identity. The cost
  is measured by the `genuine_*` cases and by real-CT information loss.
- A residual crack halo remains the closest impostor approach to the threshold
  (see the margin above); the gate is validated on Gaussian-profile cracks only.
- Exact-array identity is detected; near-identical derived pixels are not.
- Not implemented: tiling and seam-level aggregation, CT-volume hashing (only a
  declared root plus the sampling-manifest digest are bound), VC3D
  green/red/gray display and correlation-surface review, any real-data sampler.

## Reproduce

```bash
scroliq-seam-fingerprint controls --out out/controls.json \
  --seed-base 700000 --n 40 --sweep-n 12            # exit 0 iff the gate passes
scroliq-seam-fingerprint controls --out out/abl.json --seed-base 700000 \
  --n 40 --sweep-n 12 --ablate feature-gate          # expected to FAIL
scroliq-seam-fingerprint pair --input out/pair.npz --volume-root <exact root> \
  --surface-a-sha256 <64-hex> --surface-b-sha256 <64-hex> \
  --sampling-manifest out/sampling.json --out out/seam.json
```

Exit codes for `pair`: 0 `AUTHENTICATED`, 1 `UNKNOWN`, 3 `CONTRADICTED`, 2 error.
Output files are create-only. Artifacts:
[`artifacts/2026-10-04-seam-fingerprint-synthetic/`](../artifacts/2026-10-04-seam-fingerprint-synthetic/).
