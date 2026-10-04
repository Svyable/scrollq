# Coverage-witness Stage C preregistration

**Status: frozen before any Stage-C witness response is read.**

Stage B failed for a useful reason: discrete harmonic XYZ continuation becomes
too flat/bias-prone over large curved holes. The independent prediction still
detects omissions when the correct sheet is localized, so Stage C changes the
geometry prior rather than weakening the identity gates.

## Fresh holdout

Stage C does not reuse the six Stage-B centers for its scientific decision.

Starting from the original 32 geometry-only probes, it excludes those six,
requires a complete 51×51 evaluation window, and deterministically takes six
even-quantile ranks from the 19 remaining eligible probes:

- surface-0003
- surface-0009
- surface-0014
- surface-0019
- surface-0024
- surface-0030

Their wrong-wrap controls were frozen before this experiment.

## Improvement under test

Fit two curvature-aware visible-only material-coordinate surfaces to the intact
51×51 annulus around each artificial hole:

- tensor polynomial degree 2;
- tensor polynomial degree 3.

The degree-3 surface proposes the expected corridor. A hidden location is used
only when the two models agree within 8 voxels **and** their analytic normals
have absolute cosine at least 0.9. Otherwise the method abstains.

This is intentionally precision-first. A completeness falsifier does not need
a dense hallucinated fill; it needs enough trustworthy independent witnesses to
localize a missing region without jumping windings.

## Visible-only reliability check

A two-cell inner collar is withheld from the polynomial fit and predicted from
the remaining visible annulus. This gives a per-variant reliability measure
without revealing hidden geometry.

The visible validation thresholds, candidate ray bands, wrong-wrap gates, and
precision/recall requirements are all frozen in spec.json.

A negative result is retained unchanged. No target-scroll data or ink is used.
