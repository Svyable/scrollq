# Truly-disjoint resampling stability — 2026-10-01

The first ScrolIQ stability measurement where the two runs are disjoint
**by construction**, not by candidate-order assumption.

## Method

`bin/stability.py ... disjoint` uses a two-phase protocol:

1. **Phase 1**: score all 64 volumes normally (`rotate=0`), recording
   per-chunk provenance (`sample_provenance` with stable
   `shard_key#inner_flat` identities).
2. **Phase 2**: re-score all 64 volumes with `score_volume(..., exclude=...)`,
   skipping every chunk identity decoded in phase 1. Excluded chunks are
   skipped before download, so they cost no network or decode time.

This replaces the rotate-based "disjointness" that the 2026-09-30 provenance
work proved was never disjoint (only 2/64 volumes had zero chunk overlap,
mean Jaccard 0.63). The exclusion mechanism guarantees zero identity
intersection; the `provenance` section of the JSON verifies it per volume.

`score_volume()` also reports `sampling.excluded_chunks` (chunks skipped
due to exclusion) so sparse volumes that cannot supply fresh chunks are
visible rather than silently re-read.

## Results (2026-10-01)

- **64/64 volumes truly disjoint** — zero chunk-identity intersection on every
  volume (mean Jaccard = 0.0). The exclusion mechanism works by construction.
- **Spearman ρ = 0.6283** — the honest disjoint-sample stability, down from
  the re-read-inflated ρ = 0.79.
- **Mean |Δ| = 7.95** points (was 4.195 with re-reading).
- **Top-10 overlap = 4/10** (was 7/10).
- **Gate ρ ≥ 0.85: FAILED.** The ranking does not clear the gate under
  truly independent samples.

Largest movers between the two disjoint runs:

| Volume | Phase 1 | Phase 2 | Δ |
|---|---|---|---|
| PHerc0841 | 31.4 | 75.1 | 43.7 |
| PHercMANB | 13.5 | 41.8 | 28.3 |
| PHerc0139 | 75.8 | 52.2 | 23.6 |
| PHercMANBp | 42.3 | 64.8 | 22.5 |
| PHerc0211 | 52.7 | 75.0 | 22.3 |

Sparse-volume capacity: 13 volumes could not supply a full 24 fresh chunks
in phase 2 (e.g., PHercParis4 45.532um: 21 → 3; PHercMANBp: 8 → 4). The
`excluded_chunks` counter makes this visible. These volumes have fewer
than 48 decodable chunks total — their scores are inherently noisier.

## Reading

The ρ = 0.63 is the number we should have published all along. It says:
24-chunk means from heterogeneous volumes are noisy estimates, and the
leaderboard is a triage band, not a precise ranking. The per-chunk
heterogeneity display (mean within-volume std 18.5) already told this story;
the truly-disjoint measurement confirms it with independent samples.

This does not invalidate the campaign — it bounds it. The Grand Prize
Pareto frontier (PHerc0813 + PHerc1447) and the label-next flags are
robust to this noise. What it invalidates is reading the leaderboard as
a precise 1-to-64 ordering.

## Reading

The ρ = 0.63 is the number we should have published all along. It says:
24-chunk means from heterogeneous volumes are noisy estimates, and the
leaderboard is a triage band, not a precise ranking. The per-chunk
heterogeneity display (mean within-volume std 18.5) already told this story;
the truly-disjoint measurement confirms it with independent samples.

This does not invalidate the campaign — it bounds it. The Grand Prize
Pareto frontier (PHerc0813 + PHerc1447) and the label-next flags are
robust to this noise. What it invalidates is reading the leaderboard as
a precise 1-to-64 ordering.

## Reproduce

```bash
# Truly-disjoint stability check, 24 samples from 5x5x5 grid (~25 min, two phases)
.venv/bin/python bin/stability.py artifacts/2026-10-01-truly-disjoint/stability-truly-disjoint.json 24 13 5 disjoint
```

`stability-truly-disjoint.json` holds the result plus both full score tables
(`run0`, `run1`) and the per-volume provenance verification;
`stability-truly-disjoint.log` is the run log.
