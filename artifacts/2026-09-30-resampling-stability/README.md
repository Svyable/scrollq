# Resampling stability — 2026-09-30

Reproducible measurement of how much ScrolIQ scan-health scores move when
the sampled shards change. Replaces the earlier published numbers
(ρ = 0.876, mean |Δ| = 3.07, top-10 8/10), which had no artifact behind
them and do not reproduce — they are retired, not defended.

## Method

`bin/stability.py` scores all 64 volumes twice via `score_volume(...,
samples=4, rotate=R)`. `rotate` cyclically shifts the 27-candidate shard
list before the first 4 are taken:

- **rotate=0 vs 1** (weak resample): candidates [0,1,2,3] vs [1,2,3,4] —
  3 of 4 shards shared. ρ = 0.9929, mean |Δ| = 0.60, top-10 10/10.
  This measures the resample overlap, not score stability. Do not cite it
  as stability evidence.
- **rotate=0 vs 13** (strong resample): candidates [0,1,2,3] vs
  [13,14,15,16] — fully disjoint shard sets. ρ = 0.7575, mean |Δ| = 7.39,
  top-10 overlap 6/10. This is the honest measurement.

`stability.json` holds the strong-resample result plus both full score
tables (`run0`, `run13`).

## Reading

- Scores carry ≈ ±5 points of sampling noise (single-estimate SE ≈
  7.4/√2). Ranks within ~10 points are interchangeable — read the
  leaderboard as a triage **band**, not a precise order.
- The measurement is **below** our own ρ ≥ 0.85 quality gate. The gate
  stays; the score does not clear it at 4 samples/volume.
- Robust findings: PHerc0813 is #1 in both runs (77.4, 77.4).
  PHerc0139 is top-5 in both (74.7→75.1). The Grand Prize Pareto frontier
  (PHerc0813 + PHerc1447) survives even at PHerc1447's low draw (53.2),
  because its 15 existing segments dominate the segment axis.
- Sample-sensitive: PHerc1447 swings 67.3 → 53.2 (rank 13 → 46).
  The 🎯 label-next flags: 16 on the published run, 10 stable across
  the resample.

## Reproduce

```bash
.venv/bin/python bin/stability.py artifacts/2026-09-30-resampling-stability/stability.json
```

(~4 minutes, 8 workers, live dl.ash2txt.org reads.)
