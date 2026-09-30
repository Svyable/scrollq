# scrollq n=12 campaign + resampling stability (2026-09-30)

## Why a second campaign

The first campaign (`artifacts/2026-09-30-scrollq/`, 4 samples per volume)
carried roughly ±5 points of sampling noise: an independent disjoint-shard
resample gave Spearman ρ = 0.76, mean |Δscore| = 7.4, top-10 overlap 6/10 —
below our own ρ ≥ 0.85 stability gate. That result is kept in
`artifacts/2026-09-30-resampling-stability/`; this directory supersedes the
campaign it was measured on.

This campaign triples the sampling to **12 per volume** (same per-dimension
spread candidates, same strict dead-slice detector, same published weights).
The resample check was re-run under the new sampling:

- `stability-n12.json`: rotate=0 vs rotate=13 (verified disjoint shard sets:
  candidates [0..11] vs [13..24] of the 27-spread)
- **Spearman ρ = 0.99, mean |Δscore| = 0.56, top-10 overlap 10/10** —
  clears the ρ ≥ 0.85 gate
- `stability-n12.log`: full run log (64 volumes, ~3 min both rotations)

## Campaign

- `volumes.json` — all 64 dl volumes scored at n=12
  (`scrollq-score --samples 12 --workers 8`); provenance per volume in the
  `sampling` block (`decoded` is the real chunk count — sparse volumes decode
  fewer than the requested 12 because spread candidates hit absent shards;
  49/64 volumes decoded < 12).
- `coverage.json` — ink-label join against the S3 audit roots;
  14 top-quartile (q75 = 67.2) zero-label volumes flagged `label_next`.
- `campaign.log` — full campaign output.

## What changed vs n=4

- Range: 27.3–77.4 (was 27.4–77.4). PHerc0813 still #1 at 77.4.
- Grand Prize Pareto frontier (re-run in
  `artifacts/2026-09-30-grand-prize-qualifier-n12/`): unchanged —
  PHerc0813 + PHerc1447.
- Scores are now stable under disjoint resampling, so the leaderboard can be
  read as a ranking with ~±1 point of sampling noise rather than ±5.
- Honest caveat: effective sample size varies by volume (sparse shard grids
  decode fewer chunks); per-volume `sampling.decoded` records the real count.

## Reproduce

```bash
.venv/bin/scrollq-score --base https://dl.ash2txt.org --volumes volumes.txt \
  --samples 12 --workers 8 --out-dir artifacts/2026-09-30-scrollq-n12
```
