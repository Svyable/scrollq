# Pre-registration: scan-score stability, version 2 (October goal O5)

**Status:** frozen before any version-2 run reads scan data. The constants
below and the decision rule are implemented in
[`src/scrollq/stability_protocol.py`](../src/scrollq/stability_protocol.py)
(`preregistered_constants()`, `arm_summary()`, `decide()`); the verdict is
computed by that code, not by hand. The commit that adds this file is the
timestamp. Every motivating number below is reproduced from published
artifacts by [`bin/stability_v2_prereg.py`](../bin/stability_v2_prereg.py)
into [`artifacts/2026-10-01-stability-v2-prereg/analysis.json`](../artifacts/2026-10-01-stability-v2-prereg/analysis.json).

## Why

The published ranking failed its own stability gate. The 2026-10-01
truly-disjoint resample gave Spearman ρ = 0.628 against a gate of 0.85
(`artifacts/2026-10-01-truly-disjoint/`). Version 2 asks whether that failure
comes from the scores themselves or from how they were sampled. Published data
already says it is largely the sampling:

- **Noise alone does not explain it.** A variance-components model fitted to
  the 24-chunk campaign (between-volume variance 134.45, mean within-volume
  chunk variance 406.3) predicts a resample reliability of 0.888 at 24 chunks
  if chunks were independent draws. The observed disjoint correlation was 0.609
  (Pearson).
- **The runs differ systematically.** The second disjoint run scored 5.46
  points higher on average. The per-volume differences have a standard
  deviation of 10.1, against 5.82 expected from independent sampling.
- **The candidate order explains why.** Sampling consumes shard candidates in
  x-major order until N chunks decode. On a 5×5×5 lattice the first 12
  candidates, enough for 24 chunks at 2 per shard, share a single x plane. A
  24-chunk score can therefore describe one or two slabs of the scroll, and the
  disjoint second run read neighbouring positions of the same slabs.

## Hypothesis

H1 (primary): with candidates ordered so every prefix fills the volume, and
the two runs given interleaved, shard-disjoint halves of that order, the
resample correlation at 48 chunks per run reaches Spearman ρ ≥ 0.85.

H2 (secondary, descriptive): the same design at 24 chunks per run exceeds the
0.628 measured under the grid order. This separates the effect of the design
from the effect of more chunks. It has no gate.

## Pre-registered constants

- Volumes: the 64 roots in `volumes.txt`, read from `https://dl.ash2txt.org`.
- Candidate lattice: spread 7 (7×7×7 = 343 shard candidates).
- Order: `balanced`. Halton points (bases 2, 3, 5) are mapped in sequence to
  the nearest unused lattice point, so the interior fills first and boundary
  planes come late.
- Runs: run A = part `(2, 0)`, run B = part `(2, 1)`. Each consecutive pair of
  the balanced order is dealt one candidate per run, with the assignment
  permuted by a fixed hash of the pair. The runs are shard-disjoint, so their
  chunks are disjoint by construction, and neither run is confined to a half of
  the volume (`tests/test_candidate_order.py`).
- Primary arm: 48 chunks per run. Secondary arm: 24 chunks per run.
- Everything else in `score_volume` is unchanged: at most 2 chunks per shard,
  shards under 5% present are skipped, and the same metrics and weights apply.

## Decision rule (primary arm only)

1. A volume is **eligible** if both runs scored and each decoded exactly 48
   chunks. Ineligible volumes are listed with their decoded counts and errors,
   never dropped silently.
2. **INSUFFICIENT** if fewer than 48 of the 64 volumes are eligible, or ρ is
   undefined.
3. **PASS** if Spearman ρ ≥ 0.85 on the eligible volumes.
4. **FAIL** otherwise.

Consequences, committed in advance:

- **PASS:** the leaderboard publishes the version-2 ranking with the gate
  marked as passed. The volumes left out stay listed as unranked.
- **FAIL or INSUFFICIENT:** the leaderboard's rank column is replaced by a
  **rank band** per volume: the best and worst rank the volume takes across
  run A, run B, and their pooled 96-chunk score (`rank_bands()`).

Reported either way: mean |Δ|, the mean and spread of the run B − run A
shift, top-10 overlap, and the secondary arm's ρ.

## Known limitations

- The test measures stability of the *score*, not whether the score means
  anything for unwrapping. It cannot establish readability.
- Sparse volumes may not supply 96 fresh chunks. They show up as ineligible,
  which is why INSUFFICIENT exists.
- Within a shard, chunks are still chosen in a fixed inner order. Version 2
  fixes the shard order, not the inner order.

## Deviation policy

Any change after this commit (a volume that cannot be read, a code fix to the
runner, a rerun) is logged with its date and reason in the results artifact.
It is never applied by editing this file or the constants. A post-hoc analysis
is allowed only as a separately labelled arm.

## Reproduce

```bash
python bin/stability_v2_prereg.py artifacts/2026-10-01-stability-v2-prereg/analysis.json   # inputs above
python bin/stability_v2.py OUT_DIR                                                         # the test
```
