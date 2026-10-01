# Resampling stability — 2026-09-30

Reproducible measurement of how much ScrolIQ scan-health scores move when
the sampled shards change. Replaces the earlier published numbers
(ρ = 0.876, mean |Δ| = 3.07, top-10 8/10), which had no artifact behind
them and do not reproduce — they are retired, not defended.

## Method

`bin/stability.py` scores all 64 volumes twice via `score_volume(...,
samples=N, rotate=R)`. `rotate` cyclically shifts the 27-candidate shard
list before the first N are taken.

### At 4 samples/volume (`stability.json`)

- **rotate=0 vs 1** (weak resample): candidates [0,1,2,3] vs [1,2,3,4] —
  3 of 4 shards shared. ρ = 0.9929, mean |Δ| = 0.60, top-10 10/10.
  This measures the resample overlap, not score stability. Do not cite it
  as stability evidence.
- **rotate=0 vs 13** (strong resample): candidates [0,1,2,3] vs
  [13,14,15,16] — fully disjoint shard sets. ρ = 0.7575, mean |Δ| = 7.39,
  top-10 overlap 6/10. This is the honest measurement: ≈ ±5 points of
  sampling noise, below our ρ ≥ 0.85 gate.

### At 12 samples/volume (`stability-n12.json`) — current

- **rotate=0 vs 13**: candidates [0..11] vs [13..24] — fully disjoint
  shard sets (verified: zero shared candidates). ρ = **0.9948**,
  mean |Δ| = **0.56**, top-10 overlap **10/10** — clears the ρ ≥ 0.85 gate.
- Only 12 of 64 volumes moved at all between runs (largest move 5.8
  points); 52 were byte-identical. The score function has ceiling effects
  (components saturate via `min(1.0, …)`), so part of the stability is
  coarse resolution — the honest reading is ~±1 point of sampling noise,
  not infinite precision.
- Sparse volumes decode fewer than the requested 12 (spread candidates hit
  absent shards; 49/64 decoded < 12). The check is apples-to-apples: both
  rotations face the same sparsity.

`stability-n12.json` holds the n=12 result plus both full score tables
(`run0`, `run13`); `stability-n12.log` is the run log.

## Reading

- At 12 samples/volume the leaderboard is a real ranking with ~±1 point
  of sampling noise — the n=4 triage-band caveat is retired.
- Robust across both campaigns: PHerc0813 is #1 (77.4) everywhere;
  the Grand Prize Pareto frontier (PHerc0813 + PHerc1447) is unchanged.
- The n=4 campaign's sample-sensitive findings (PHerc1447's 67.3 → 53.2
  swing) were noise, not signal — which is exactly why we re-measured.

## Diagnostic: dense-grid heterogeneity check (not the published score)

`stability-dense12.json`: same 12 samples but from a 5×5×5=125 candidate
grid instead of 3×3×3=27. Result: ρ = 0.67, mean |Δ| = 7.7 — does NOT
clear the gate. Individual volumes swung up to 44 points between runs
(PHerc0211: 32.8 → 77.0).

This revealed two things:

1. **The 3×3×3 ρ=0.99 is inflated by shard re-reading.** The sampling
   loop scans all 27 candidates until 12 chunks are decoded. On sparse
   volumes (e.g., PHerc0813: 26/27 candidates absent), both rotations
   end up decoding the SAME 1–2 present shards — 0813 scored 77.4 in
   both runs because it read the same shard twice, not because the
   volume is uniform. The "disjoint candidate order" does not guarantee
   disjoint shards read.
2. **Volumes are genuinely heterogeneous.** When the dense grid forces
   different shards to be read, scores move a lot. A 12-chunk mean is
   a noisy estimate of a heterogeneous volume's quality.

The published 3×3×3 campaign stands as the stable, reproducible ranking,
but its thin-volume scores (fewer than ~6 chunks decoded) should be read
as "this shard looks good" rather than "this volume is uniformly good."
Per-volume `sampling.decoded` records the real chunk count. A future
campaign should sample enough shards to cover heterogeneous volumes —
the dense-grid diagnostic suggests 24–48 chunks may be needed, at
significant runtime cost.

## Reproduce

```bash
# n=12 disjoint resample (the current measurement; ~3 min)
.venv/bin/python bin/stability.py artifacts/2026-09-30-resampling-stability/stability-n12.json 12
# n=4 (the retired campaign's noise measurement; ~4 min)
.venv/bin/python bin/stability.py artifacts/2026-09-30-resampling-stability/stability.json
```

## Provenance: "disjoint" resamples are not disjoint (2026-09-30)

`stability-n24-dense-prov.json` adds per-chunk provenance (`sample_provenance`
with stable `shard_key#inner_flat` identities) and per-volume decoded-identity
overlap between the two runs. Results:

- **2/64** volumes had zero chunk overlap (truly disjoint samples).
- Mean Jaccard = 0.63 — on average, 63% of chunks were re-read.
- 5 volumes had Jaccard = 1.0 (identical chunk sets despite rotated candidate order).

The sampling loop scans all candidates until N chunks decode; on sparse
volumes both rotations re-read the same present shards. **Disjoint candidate
order does not imply disjoint chunks read.** The published ρ = 0.79 is
therefore inflated by re-reading — true disjoint-sample stability is lower,
and we do not claim otherwise. This is why `score_volume()` records provenance
and `bin/stability.py` reports identity overlap: so no future claim of
disjointness rests on candidate order alone.

## Reproduce

```bash
# n=24 provenance stability check (~12 min)
.venv/bin/python bin/stability.py artifacts/2026-09-30-resampling-stability/stability-n24-dense-prov.json 24 13 5
```
