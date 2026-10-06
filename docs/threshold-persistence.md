# Threshold-persistence audit of ink predictions

**Status:** EXPERIMENT FURTHER. Executable harness with synthetic controls;
**no real prediction map has been measured**, so whether real ink and real false
positives differ in threshold persistence is unknown. Set 2026-10-05. Tool:
`scroliq-persistence`.

This is a falsification control, not an ink detector. It generates no ink, reads
no text, compares nothing with a character template and never chooses a
threshold. It consumes the probability maps of a frozen detector.

## Hypothesis, and what would kill it

A detector's probability map is a scalar field. Judging it at one threshold hides
how its evidence is arranged. Sweep the threshold and track how components,
holes, merges and stroke skeletons persist. The hypothesis is deliberately
narrow:

> Real surface-bound ink may have a different threshold-persistence signature
> from brittle model artifacts, even when both look letter-like at one threshold.

A false stroke that exists only in a tiny threshold interval is epistemically
different from a component whose location and topology hold across a broad
confidence range. Conversely, if verified ink is as unstable as false positives,
the hypothesis fails cleanly. The frozen rule below decides that on domains held
out whole, against stated baselines, with controls.

What it cannot do: reject a false positive whose confidence filtration is as
stable as ink's. A persistent artifact passes this audit.

## The filtration (frozen)

Implemented exactly in `src/scrollq/persistence.py`; every convention below is
part of the protocol.

- **Superlevel sets** `{f >= t}` of the field over the region's valid pixels.
- **Foreground 8-connected, background 4-connected**, so `beta0 - beta1` equals
  the Euler characteristic of the union of closed foreground pixel squares at
  every threshold (the control suite checks this against an independent count).
- **Exact diagrams, no grid.** H0 (components, elder rule) by union-find over the
  8-connected edge graph; H1 (holes) from the dual 4-connected background
  filtration. Component and hole births and deaths are exact, not sampled.
- **The parameter is rank, not probability.** A level's coordinate is its
  mid-rank *kept fraction* `s(u)`: the share of valid pixels at or above it,
  counting half of its own ties. Persistence is measured in kept-fraction units.
- **Masked pixels are outside.** A region enclosed only by masked pixels is never
  a hole.
- **Ties are broken by flat pixel index.** The off-diagonal diagram does not
  depend on that choice; spatial attributes of exactly tied peaks follow it.

### Why rank, and the monotone-remap control

Every persistence quantity is a function of the integer level image and the
nominal level only, never of raw probabilities. It is therefore **bitwise
invariant to any strictly monotone recalibration** (temperature scaling, a
different sigmoid, a gamma curve), so the audit is not hostage to checkpoint
calibration. The control suite checks this on every run, and checks that a
value-parameterised persistence (`diagram_persistence(..., "value")`) is **not**
invariant, so the control can fail.

The boundary of that claim: it holds for remaps that are *injective on the
represented scores*. Saturation (a float32 sigmoid that rounds to 1.0),
quantisation to uint8, or a float offset that swallows small differences
(`5*v + 2` merged two distinct near-zero scores in development) merges ranks.
That is information loss, not a violation of invariance, and it is not a pass:
`measure` runs two frozen remaps per region, reports `not_injective` for any that
collapse scores, and fails the region unless at least one conclusive remap leaves
the levels unchanged and none changes them. A uint8 map has at most 256 levels and
many ties; the diagram is still exact, but fine structure is gone.

## Units, features and labels (frozen)

A **candidate** is an 8-connected component of `{valid and score >= nominal
threshold}` with at least 12 pixels. The nominal threshold is the detector's own
operating threshold, declared per region in the manifest. More than 400
candidates in a region fails that region rather than truncating it, because
noisy, fragile regions are exactly the ones a silent cap would drop.

**Baseline features** (what a reviewer already has; computed at the nominal
threshold):

| Feature | Meaning |
|---|---|
| `peak_prob`, `mean_prob` | raw maximum and mean score in the candidate (calibration-dependent) |
| `log_area` | log10 pixels |
| `peak_margin_log` | log10(nominal kept fraction / peak kept fraction), the peak's rank margin |
| `elongation` | sqrt of the covariance eigenvalue ratio (a 1/12 px² regulariser) |
| `bbox_fill` | pixels / bounding-box area |

`B_rank` drops the two raw-probability features, so it is calibration-free like
the persistence features.

**Persistence features** (the sweep covers +/-0.5 decade of kept fraction around
the nominal level, 9 levels; a candidate's lineage ends where a stronger peak
absorbs it):

| Feature | Meaning |
|---|---|
| `down_slack_log` | log10(kept fraction at which the candidate is absorbed / nominal kept fraction); how far the threshold can loosen before it merges into something stronger |
| `area_growth_log` | log10(area at the loosest level where it is still its own component / nominal area) |
| `area_retention_tight` | area at the tightest level / nominal area; 0 if its peak is gone |
| `centroid_drift_norm` | largest centroid displacement along its lineage / sqrt(nominal area) |
| `skeleton_log_change` | log10(skeleton pixels at the loosest own level / at nominal), Zhang-Suen pixel counts (a proxy, not physical length) |
| `hole_life_log` | log10(1 + N * longest-lived hole enclosed at nominal), in rank units |
| `n_significant_peaks` | H0 branches with persistence >= 5e-4 absorbed inside the candidate |

**Labels** (`measure` only; no feature reads them): in a `verified_ink` region a
candidate is **positive** if at least half of its pixels are verified ink, an
**in-region false positive** if no pixel lies within 3 px of ink, and otherwise
**ambiguous** (excluded and counted). Every candidate in a `blank_papyrus`,
`crack`, `fiber`, `fold`, `known_false_positive` or `injected_perturbation`
region is a negative of that kind, and such regions must contain no ink labels.

## Manifest and the selection contract

`measure` reads a JSON manifest (schema 1, protocol `threshold-persistence-v1`):

```json
{
  "schema_version": 1,
  "protocol": "threshold-persistence-v1",
  "selection_contract": {
    "nominal_thresholds_declared_before_measurement": true,
    "topology_used_to_choose_threshold": false,
    "ocr_or_text_used_to_choose_regions_or_thresholds": false,
    "detector_trained_on_evaluation_domains": false
  },
  "detector": {
    "name": "...", "checkpoint_sha256": "<64 hex>", "inference_config_sha256": "<64 hex>",
    "training_domains": ["scroll-A"]
  },
  "regions": [
    {"id": "frag3-r07", "domain": "fragment-3", "kind": "verified_ink",
     "prediction": "pred/frag3-r07.npy", "prediction_sha256": "<64 hex>",
     "labels": "labels/frag3-r07.npy", "labels_sha256": "<64 hex>",
     "valid_mask": "masks/frag3-r07.npy", "valid_mask_sha256": "<64 hex>",
     "nominal_threshold": 0.5}
  ]
}
```

The four contract values must be exactly as shown; they are attestations, not
verifications, and a false attestation is the author's. What the tool does check:
every region's `domain` must not appear in `detector.training_domains`, every
input file's SHA-256 must match, `nominal_threshold` must lie in (0, 1), and
paths cannot leave the manifest directory. Prediction scale follows
`scroliq-ink-validate` (`prediction_scale`, default `auto`). Outputs are
create-only.

A **domain** is a whole fragment or scroll. Statistics are derived on the
remaining domains only.

## Evaluation: leave one domain out (frozen)

`evaluate` applies the rule in `artifacts/2026-10-05-threshold-persistence-prereg/spec.json`
(SHA-256 `31e22a9153463dd514dbffecfaa458a990ea331a7717a49d66326ef1e3699b26`,
pinned as a literal in the code and checked by a test). Any other spec yields
`EXPLORATORY` at best.

For each held-out domain a ridge-logistic model (L2 = 1, deterministic Newton
solve, standardised features) is fit on the *other* domains and scores the held
domain. Arms:

- baselines `B_full`, `B_rank` (linear) and `Bq_full`, `Bq_rank` (quadratic:
  features, squares, pairwise products);
- challengers `BP_full = B_full + persistence` and `BP_rank = B_rank + persistence`
  (linear);
- `P_only`, descriptive.

The baselines get the quadratic form so a "gain" cannot come merely from
re-encoding baseline information nonlinearly. For each held-out domain,
**false-positive rate at 90 % verified-ink recall** is read from out-of-fold
scores (ties count against the model). The **gain** is the smaller, over the full
and rank pairs, of `min(FPR_B, FPR_Bq) - FPR_BP`. Taking the better baseline and
the worse pair makes the hypothesis harder to confirm, never easier.

Gates, each required:

1. mean gain over domains >= 0.05 FPR;
2. 95 % domain-bootstrap interval (2000 resamples, seeded) has a lower bound > 0;
3. gain > 0 in at least 66 % of domains;
4. permutation test (200 within-domain label permutations of the *whole*
   pipeline, seeded) gives p <= 0.05.

Both **scopes** must pass every gate:

- `all`: every labelled candidate;
- `within_region`: candidates in `verified_ink` regions only, where true ink and
  false positives share a region.

The second scope exists because negatives from other regions can differ from ink
regions in texture or noise alone. A gain that disappears within a region is not
evidence about ink. If a real run lacks the in-region false positives to test it
(10 positives and 10 negatives per domain, at least 3 domains), the verdict is
`INCONCLUSIVE`, never a pass.

Minimum counts: at least 3 usable domains, each with at least 20 positives and
20 negatives (`all`). A domain below the floor is excluded and listed. A region
that fails measurement makes the run `INCONCLUSIVE`; failed regions are reported,
never dropped.

### Verdicts

| Verdict | Meaning | `evaluate` exit |
|---|---|---|
| `PERSISTENCE_ADDS_SIGNAL` | every gate on both scopes, preregistered spec | 0 |
| `NO_ADDED_SIGNAL` | adequate data, gates not met: the hypothesis fails cleanly | 3 |
| `INCONCLUSIVE` | too few domains/counts, failed regions, or within-region scope infeasible | 1 |
| `EXPLORATORY` | spec is not the preregistered one | 1 |
| `INVALID_DESIGN` | spec mismatch or selection contract not satisfied | 2 |

`NO_ADDED_SIGNAL` is a result, not an error. The report also states whether the
interval excludes the minimal effect (`refuted_minimal_effect`), per-domain FPRs,
per-negative-kind flag counts at the matched recall, and per-domain AUROC of each
persistence feature (signed: above 0.5 means higher for ink).

A positive verdict means these features added held-out false-positive rejection
beyond the stated baselines on the evaluated domains. It does not show that a mark
is ink, that text is legible, or that a scan is readable.

## Controls

`scroliq-persistence controls` runs, deterministically and with no network:

1. **Engine oracles.** Persistence-derived Betti numbers equal an independent
   scipy connected-component count at every level; `beta0 - beta1` equals an
   independent `V - E + F` Euler count; diagrams are identical under the eight
   grid symmetries; and the oracle disagrees when given the wrong connectivity
   (so a clean result is not vacuous).
2. **Invariance.** Rank features are bitwise identical under four monotone remaps;
   value-parameterised persistence is not.
3. **Decision-rule scenarios** on synthetic regions with per-domain calibration
   shift (one of four monotone remaps per domain, per-domain noise):

| Scenario | Construction | Required outcome |
|---|---|---|
| `planted_sweep_effect` | false positives carry a sub-nominal skirt, invisible at the nominal threshold by construction | found |
| `null_no_effect` | both classes from one generator | not credited |
| `baseline_explained` | classes differ in peak amplitude only | not credited to persistence |
| `region_confound_only` | blank regions carry the skirt; false positives inside ink regions look like ink | cross-region scope alone passes, within-region fails, verdict not a pass |

The planted effect is constructed, not discovered: it shows the pipeline can see
a difference that lives only in the sweep and does not credit one the baseline
explains. It says nothing about papyrus. Results and commands:
[`artifacts/2026-10-05-threshold-persistence-synthetic/`](../artifacts/2026-10-05-threshold-persistence-synthetic/README.md).

## What a real run needs

- at least three domains (fragments or scrolls) held out whole from the detector,
  declared in `detector.training_domains`;
- per domain at least 20 verified-ink and 20 negative candidates, with negatives
  of the named kinds (blank papyrus, cracks, fibers, folds, known false
  positives, injected perturbations) matched to the ink regions as well as can be
  independently argued, and, for the within-region scope, at least 10 verified-ink
  and 10 in-region false-positive candidates per domain;
- nominal thresholds declared before measuring, in the manifest;
- a frozen detector: this audit consumes predictions and trains no detector.

Detached fragments are the cleanest source of verified ink because exposed ink
can be photographed directly; nothing in the tool is specific to them.

## Known limits

- **Persistent false positives are invisible.** The audit can only reject
  artifacts that are fragile across the filtration.
- **Matching cannot be verified.** Matched negatives are the user's claim. The
  within-region scope reduces, but does not remove, region-level confounding:
  neighbouring strokes still share context.
- **Ranks are per region.** The kept fraction depends on how much of a region is
  confident, so ink-dense and blank regions have different rank scales. The
  region-composition effect is part of what the within-region scope tests.
- **The baselines are regularised logistic models.** A stronger learner on the
  baseline features (boosted trees, a network) could absorb a gain that this
  comparison credits. Promotion beyond `EXPERIMENT FURTHER` should repeat the
  comparison against one.
- **Domain bootstrap is coarse with few domains.** With 3-4 domains the interval
  is close to the per-domain minimum; the 66 % rule and permutation gate matter
  more than the interval there.
- **Hole features see only holes alive at the nominal threshold.** A ring that
  closes only when the threshold loosens is not scored as a hole.
- **Skeleton length is a pixel-count proxy** (Zhang-Suen), not physical length.
- **Cost.** About 0.3 s for 256x256, 1.6 s for 512x512 and 10 s for 1024x1024
  (the cap of 1,048,576 pixels); the union-find is a Python loop.
- **NumPy versions.** Synthetic seeds are stable for a given NumPy; another
  version may move individual numbers while the qualitative outcome should hold.

## Development log and deviations

The synthetic generators and several rules were shaped during development on
seeds `100000+`; those seeds are **not** held-out. The reported run uses seeds
`700000+`, run after the code and spec were pinned. Nothing was tuned on real
data because none was read. Each change below followed an observation:

1. **Float collapse.** A smoke test of a `5*v + 2` remap changed ranks (1814 to
   1813 distinct scores). The cause was float rounding, not the engine. The
   invariance claim was narrowed to injective remaps and `measure` now checks
   injectivity.
2. **Straw-man baseline.** With linear baselines only, the baseline-explained
   scenario produced one persistence "gain" in 12 development seeds. Whether or
   not that was chance, persistence features can re-encode baseline information
   nonlinearly, and a linear baseline invites that objection, so quadratic
   baselines and the best-baseline / worst-pair gain were added before the spec
   was pinned. A later development run with the stronger baselines still showed
   one false alarm in 12 with negative median gain, which is consistent with the
   nominal 5 % permutation level rather than a systematic credit.
3. **Cross-region confound.** Negatives from other regions confound region-level
   texture with class. The `within_region` scope and the `region_confound_only`
   scenario were added.
4. **A control that did not test anything.** The first confound scenario varied
   only background noise and never produced a cross-region gain
   (`all` scope alone passed 0 of 12), so passing it proved nothing. It was
   redesigned so the confound is real, and the suite now fails unless the
   cross-region scope alone passes in at least half the seeds.
5. **Infeasible within-region scope.** The first within-region runs were
   `INCONCLUSIVE` (11 of 12) because the synthetic regions produced too few
   in-region false positives. The generator was rebalanced; the fail-closed
   behaviour itself was correct.

## What stays out

- **Choosing the threshold, checkpoint or component by how letter-like its
  topology is: DISMISS.** Semantic cherry-picking and a direct hallucination
  route. Thresholds come from the manifest; nothing searches over them.
- **Greek-character topology templates (expected holes, stroke counts, junction
  patterns) as a validator: DISMISS.** It rewards textual plausibility instead of
  physical evidence. No feature is compared with an expected count or shape.
  See [dismissed-and-deferred.md](research/dismissed-and-deferred.md).

## Provenance

Independently implemented from published definitions: elder-rule persistence of
cubical (pixel) complexes with a union-find sweep, the dual-filtration route to
H1 in the plane, and Zhang-Suen thinning (1984). No persistent-homology library
or third-party code is used or vendored; the only dependencies are NumPy and
SciPy, which the package already requires. Correctness does not rest on the
author's reading of the definitions: the engine is checked against two
independent oracles (a connected-component count and a V - E + F Euler count).

## Second stage (not started)

**Cross-checkpoint topological persistence** asks whether independently trained
checkpoints preserve the same physical component and its threshold-evolution
topology. It could be more informative than pixelwise agreement, but correlated
checkpoints remain correlated evidence. It is only worth building if stage 1
returns `PERSISTENCE_ADDS_SIGNAL` on real held-out domains, and it needs its own
preregistration.

## Reproduce

```bash
pip install -r requirements-ci.txt && pip install -e .
scroliq-persistence controls --out out/persistence-controls.json --seed-base 700000 --n 24
scroliq-persistence measure  --manifest manifest.json --out out/features.json [--overlay-dir out/overlays]
scroliq-persistence evaluate --features out/features.json --out out/report.json
python -m pytest tests/test_persistence.py tests/test_persistence_audit.py tests/test_persistence_controls.py -q
```

`--overlay-dir` writes, per region, a float32 `.npy` raster in which each
candidate's pixels carry its `down_slack_log` and everything else is NaN: a
persistence-margin evidence field. Loading it into VC3D is not implemented here.
