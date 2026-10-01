# Score refactor equivalence — 2026-10-01

Evidence that the scoring refactor in this change (single home for the
weights; chunk-level failure counters; guarded reshape) did **not** change any
score or any sample selection. It backs the numbers quoted in the commit
messages.

## Reproduce

From the repository root, with the package installed:

```bash
python artifacts/2026-10-01-score-equivalence/verify.py            # baseline 3352966
python artifacts/2026-10-01-score-equivalence/verify.py <git-ref>  # any other baseline
```

The script reads `src/scrollq/score.py` at the baseline ref straight from git
(default `3352966`, the last commit before this change), so no hand-copied
reference is involved. It is fully seeded and deterministic: rerunning it
reproduces `verify.log` byte for byte. It exits non-zero on any difference.
It needs the baseline commit in local history (`git fetch --unshallow` on a
shallow clone).

## What it checks

1. **Formula.** `score_from_metrics` and the rounded `components` breakdown,
   baseline vs. current, on 200,000 seeded random metric sets, compared with
   exact equality.
2. **Sampling.** `score_volume`, baseline vs. current, on 300 seeded
   randomized fake volumes with injected faults: absent shards (404), shard
   read errors (503), structurally invalid shard indexes, missing inner
   chunks, chunk range-read errors, and decoder rejections. Every field must
   match except the three new `sampling` counters (`shard_index_invalid`,
   `chunk_read_failures`, `chunk_decode_failures`). The error string was
   intentionally extended, so the check requires the old text to remain a
   prefix of the new one.

## Result (`verify.log`)

| Check | Cases | Mismatches |
|---|---|---|
| Formula (score + components) | 200,000 | **0** |
| Sampling / selection | 300 volumes (230 scored OK) | **0** |

Across those 300 volumes the new counters recorded **982** failure events that
the baseline silently discarded. That is the point of the change: the baseline
produced the same scores while hiding the failures.

## The verifier can fail

Two negative controls were run against this script (not committed; one-line
monkeypatches):

- Nudging the score formula by `+0.001` → 200,000/200,000 formula mismatches,
  exit 1.
- Replacing the shard-selection `_spread` with a different spread → 198/300
  sampling mismatches, exit 1, with the formula check correctly still at 0.

The sampling check is far less sensitive to a tiny formula nudge than the
formula check (the nudge flipped only 18/300 volumes, because published scores
round to one decimal). The two checks are complementary; the formula check is
the one that guards the weights.

## Limits

- **Synthetic volumes only.** This shows the logic is unchanged. It does not
  re-measure any live `dl.ash2txt.org` volume, and no published ranking,
  leaderboard, or earlier artifact was regenerated. Those artifacts predate
  the three counters and simply lack the keys; their scores are unaffected by
  construction, as shown above.
- The 982 count is a property of this fault-injection model, not a rate
  observed on real data. Do not cite it as one.
