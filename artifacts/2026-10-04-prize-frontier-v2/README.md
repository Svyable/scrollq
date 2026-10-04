# Prize frontiers under the v2 sampling design — 2026-10-04 (October stretch goal O8)

The 2026-09-30 Grand Prize and First Letters frontiers rest on the September
grid-order sample. The pre-registered [stability v2](../2026-10-stability-v2/) run
showed that design carries an x-slab bias, which the balanced v2 design removes.
This directory recomputes both frontiers from the **committed v2 scores**
(balanced order, spread 7, two disjoint 48-chunk runs, pooled 96 chunks,
measured 2026-10-01 at `93ef7d5`). Nothing was rescored, and the September
artifacts are untouched.

```bash
python bin/prize_frontier_v2.py artifacts/2026-10-04-prize-frontier-v2
```

The frontier rule is the unchanged `scrollq.grand_prize.qualify`: a two-axis Pareto
frontier over scan-health score and public segment count, with exact-volume
matching and no blended score. The target manifests are the built-in ones
(eligibility as of 2026-09-30). The scores come from 2026-10-01. A member is
**robust** only if it is on the pooled, run A and run B frontiers.

**Disclosure:** the robustness rule was chosen after the three frontiers had been
looked at. It mirrors the leaderboard's rank bands (A, B, pooled). All three
frontiers are reported so readers can apply any other rule.

## Result

| prize | September frontier | v2 pooled | run A | run B | **robust** |
|---|---|---|---|---|---|
| 2027 Grand Prize | PHerc0813, PHerc1447 | PHerc0358, PHerc0800, PHerc1447 | PHerc0125, PHerc1203, PHerc1447 | PHerc0358, PHerc0800, PHerc1447 | **PHerc1447** |
| First Letters | PHerc0800, PHerc0813 | PHerc0358, PHerc0800 | PHerc0800, PHerc0846B | PHerc0358, PHerc0800 | **PHerc0800** |

- **PHerc0813 is off both frontiers in every v2 view.** Its v2 pooled score is 70.2.
  The stability v2 post-hoc already showed it 6.0 points below its September
  score.
- **The segment-bearing members are stable**: PHerc1447 (15 segments) for the
  Grand Prize and PHerc0800 (6) for First Letters.
- **The "best segment-free volume" slot is not identifiable.** Eleven of the 13
  Grand Prize targets have zero public segments. Their pooled scores span
  64.1–74.8, and the top five lie within 2.6 points (PHerc0358 74.8, PHerc0257 73.2,
  PHerc1203 72.5, PHerc0191 72.4, PHerc0125 72.2). That is inside the v2 noise
  (SD of run differences 4.10), so which of them sits on the frontier depends on
  the sample. Read that slot as a band, not a pick.
- **PHerc1545 has no v2 score.** Both runs were incomplete (47 and 44 of 48
  chunks), so it stays `needs-quality-score` and off every frontier. Its partial
  scores (71.5, 73.4) are not used.

Grand Prize scores (pooled / A / B): PHerc0358 74.8/73.1/76.6 · PHerc0257
73.2/72.9/73.3 · PHerc1203 72.5/74.1/70.9 · PHerc0191 72.4/70.6/73.7 · PHerc0125
72.2/74.1/69.6 · PHerc0826 70.3/71.8/68.7 · PHerc0813 70.2/72.2/68.1 · PHerc0800
68.7/65.5/71.4 · PHerc1447 68.6/69.9/67.3 · PHerc0211 68.5/68.9/68.2 · PHerc0268
64.1/65.4/62.9 · PHerc1218 56.6/60.2/52.9 · PHerc1545 —.

## Files

- `grand-prize.json`, `first-letters.json`: per-target scores in each view, frontier membership, and the full `qualify()` output.
- `summary.json`: source SHA-256, design constants and the frontiers.

## Limits

This is scan-health triage plus segment availability. It says nothing about
readability, surface quality or ink. The frontier is deliberately weight-free:
a scroll off it is not "worse", only dominated on these two axes.
