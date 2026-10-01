# Stability v2 results (pre-registered) — 2026-10-01

Run of the test frozen in [`docs/stability-v2-protocol.md`](../../docs/stability-v2-protocol.md)
(merged in #60 before any data was read). Workflow `stability-v2.yml`, dispatched on
`main` at the pre-registration merge commit `93ef7d5`; generated 2026-10-01 07:37 UTC.

```bash
python bin/stability_v2.py artifacts/2026-10-stability-v2
python bin/stability_v2_posthoc.py artifacts/2026-10-stability-v2/stability-v2.json artifacts/2026-10-stability-v2/posthoc.json
```

## Verdict: FAIL

| arm | eligible volumes | Spearman ρ | mean \|Δ\| | mean shift B − A | SD of differences | top-10 overlap |
|---|---:|---:|---:|---:|---:|---:|
| **48 chunks per run (primary)** | **48 / 64** | **0.750** | 2.94 | +0.25 | 4.10 | 7 / 10 |
| 24 chunks per run (secondary) | 55 / 64 | 0.745 | 3.64 | −0.62 | 4.89 | 4 / 10 |

ρ = 0.750 < 0.85 on exactly the required 48 eligible volumes, so `decide()`
returns **FAIL** (not INSUFFICIENT). The pre-registered consequence is applied:
the leaderboard's rank column now shows each volume's **rank band**, the best and
worst rank it takes across run A, run B and their pooled 96-chunk score. The 16
volumes too sparse for two disjoint 48-chunk samples show "—" and are listed with
their decoded counts in `summary.json`. No two runs shared a chunk.

Deviations: none.

## Post-hoc (descriptive; not part of the decision) — `posthoc.json`

- **The sampling bias the design targeted is gone.** The B − A shift fell from
  +5.46 (2026-10-01 truly-disjoint, grid order) to +0.25. The spread of
  differences is now what independent sampling predicts: 4.10 against 3.84. Before
  it was 10.1 against 5.82. Each run covers a median of 6 of 7 x planes.
- **Scores are reliable, ranks are not.** Pearson r between the runs is 0.911 at 48
  chunks (0.855 at 24). Spearman stays at 0.750 because most volumes sit within a
  few points of each other: the pooled scores have a between-volume SD of 9.45,
  so neighbours swap ranks on noise of about 4 points. More chunks helps only
  slowly: on the same 48 volumes ρ goes from 0.702 at 24 chunks to 0.750 at 48.
- **The September scores carry the slab bias.** Against the v2 pooled score, the
  published 2026-09-30 scores agree at Spearman 0.637 (Pearson 0.763), mean |Δ| 6.92
  points. PHerc0826 rises 33.1 and PHerc0841 rises 31.7; PHerc0813 drops 6.0. v2 also
  differs in spread (7 vs 5) and chunk count (96 vs 24), so this compares the two
  designs, not candidate order alone.

## Consequences outside this test (not yet acted on)

The September per-volume scores and the frontiers derived from them (Grand
Prize: PHerc0813 + PHerc1447; First Letters) rest on the grid-order sample. They
are frozen, dated data and are not edited here. Re-deriving them needs a new
dated campaign with the v2 design.
