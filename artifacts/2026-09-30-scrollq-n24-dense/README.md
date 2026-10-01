# ScrollQ campaign — 2026-09-30 (n=24, dense 5×5×5 grid)

The published September 2026 leaderboard. Supersedes
`artifacts/2026-09-30-scrollq-n12/` (12 samples, 3×3×3 grid) and
`artifacts/2026-09-30-scrollq/` (4 samples).

## What changed and why

The 3×3×3 n=12 campaign reported Spearman ρ = 0.99 against a disjoint
resample — but a dense-grid diagnostic proved that number was inflated:
on sparse volumes both resample runs re-read the *same* present shards
(the sampling loop scans all candidates until N chunks decode), so
disjoint candidate *order* did not mean disjoint shards *read*.
Thin-volume scores were reproducible but covered little of the volume
(PHerc0813: 2 chunks from 1 shard).

This campaign samples **24 chunks from a 5×5×5 = 125 candidate grid**
per volume (`--samples 24 --spread 5`):

- 64/64 volumes scored.
- Mean decoded chunks per volume: **22.9** (vs 6.9 at 3×3×3).
- 55/64 volumes decoded the full 24 chunks.
- Score range: 13.5 – 78.3.

## Stability (honest)

`artifacts/2026-09-30-resampling-stability/stability-n24-dense.json`
(disjoint rotate=0 vs 13):

- Spearman ρ = **0.79**
- mean |Δscore| = **4.2**
- top-10 overlap **7/10**

This does **not** clear our ρ ≥ 0.85 gate — because the volumes are
genuinely heterogeneous (individual volumes swung up to 44 points
between dense resamples). We publish this ranking because a
representative measurement with stated uncertainty is more useful for
triage than a stable measurement built on re-read shards.

## Headline results

- **PHerc0172 leads at 78.3** (n=1 volume). PHerc0813, the 3×3×3 leader,
  scores 76.2 here (rank 4) — its earlier 77.4 came from 2 chunks on a
  single shard.
- **Grand Prize Pareto frontier unchanged**: PHerc0813 + PHerc1447
  (`artifacts/2026-09-30-grand-prize-qualifier-n24-dense/targets.json`).
- **Label coverage still concentrated**: all 70 published ink-detection
  labels on PHercParis4 (now quality rank 2); **16** top-quartile
  zero-label volumes flagged 🎯 label-next (q75 = 67.7)
  (`coverage.json`).

## Files

- `volumes.json` — per-volume scores, components, sampling provenance
  (samples, spread, decoded count, candidate count).
- `coverage.json` — ink-label / segment counts per volume + label-next flags.
- `index.html` — the generated leaderboard (copied to `docs/index.html`).
- `campaign.log` — scorer stdout.
