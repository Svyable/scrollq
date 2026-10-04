# CT fiber-fingerprint development run

This directory is the create-only measured counterpart to
[`../2026-10-03-fiber-fingerprint-dev-prereg/spec.json`](../2026-10-03-fiber-fingerprint-dev-prereg/spec.json).

The experiment is intentionally development-only. It samples CT descriptors for
the ten frozen development regions and **must not read descriptors for the ten
holdout regions**.

The runner:

1. verifies the frozen TIFXYZ hashes, reference-plan centers, adjacent-winding
   coordinates, exact CT identity, and development/holdout split;
2. samples five 25x25 tangent-frame CT slices per descriptor using the frozen
   nearest-voxel convention;
3. computes the preregistered 260-value `tangent-fiber-spectrum-v1`;
4. pools center-to-neighbor same-sheet distances;
5. derives the threshold exactly as the development 95th percentile;
6. scores adjacent-winding rejection and the frozen distance-ratio gates;
7. writes the result once.

A development **PASS** only permits a separate holdout preregistration that
freezes the exact derived threshold before any holdout CT texture is read. A
development **FAIL** dismisses descriptor v1; thresholds are not tuned after
observation.

No ink or surface-prediction values are read by this experiment.
