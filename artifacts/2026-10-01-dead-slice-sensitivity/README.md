# Dead-slice penalty sensitivity

This is a deterministic, synthetic analysis of the existing
`scan-health-v1` score policy. It is not corpus evidence and does not change
the score, the detector, any frozen artifact, or the published leaderboard.

The v1 score averages continuous chunk metrics but sums detected dead slices
before applying 15 points per slice, capped at 30. Two controlled cases make
the resulting sampling behavior explicit:

- At a fixed prevalence of one detected slice per six decoded chunks, the
  penalty rises from 15 points at a six-chunk budget to the 30-point cap at 12
  chunks and stays capped thereafter.
- One observed slice remains a 15-point penalty as clean chunks increase from
  a one-chunk to a 48-chunk budget; v1 does not normalize the observation by
  decoded coverage.

Reproduce without network access:

```bash
python -m scrollq.dead_slice_sensitivity \
  --out artifacts/2026-10-01-dead-slice-sensitivity/analysis.json
```

Acceptance check:

```bash
tmp=$(mktemp)
python -m scrollq.dead_slice_sensitivity --out "$tmp"
diff -u artifacts/2026-10-01-dead-slice-sensitivity/analysis.json "$tmp"
```

Result: the current penalty is budget-sensitive. No replacement policy is
selected here. A later scoring change must pre-register its aggregation rule,
repeat the disjoint stability analysis, and create new dated evidence rather
than rewriting existing rankings.
