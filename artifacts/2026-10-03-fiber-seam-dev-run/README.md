# Cross-ply seam development run

This is the create-only measured counterpart to
[`../2026-10-03-fiber-seam-prereg/spec.json`](../2026-10-03-fiber-seam-prereg/spec.json).

The run intentionally reuses only the ten development regions. The ten holdout
regions remain unread.

For each development center the runner samples the frozen 9×64×64 tangent-frame
CT slabs for the known w035 surface and the already-frozen adjacent winding. It
then analyzes three fixed variants with the pre-existing `scroliq-fiber-frame`
implementation:

- intact target;
- target left half + wrong-wrap right half;
- wrong-wrap left half + target right half.

Only the four 16×16 tile-neighbor comparisons crossing the x=32 seam count.
Detection and coverage denominators remain all ten frozen groups and all forty
possible seam comparisons per variant.

A PASS only permits a separate, unchanged holdout preregistration. A FAIL
dismisses `cross-ply-seam-v1`. No response-dependent tuning is allowed.

No ink or surface-prediction values are read.
