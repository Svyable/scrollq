# Stability v2 pre-registration inputs — 2026-10-01

Numbers the pre-registration ([`docs/stability-v2-protocol.md`](../../docs/stability-v2-protocol.md))
cites as motivation, computed **only** from already-published artifacts
(`2026-09-30-scrollq-n24-dense/volumes.json`, `2026-10-01-truly-disjoint/`).
No new scan data was read.

```bash
python bin/stability_v2_prereg.py artifacts/2026-10-01-stability-v2-prereg/analysis.json
```

| quantity | value |
|---|---|
| iid-predicted resample reliability at 24 chunks | 0.888 |
| observed truly-disjoint correlation (Pearson / Spearman) | 0.609 / 0.628 |
| mean score shift, run 1 − run 0 | +5.46 |
| SD of per-volume differences (observed / iid expected) | 10.1 / 5.82 |
| x planes spanned by the first 12 candidates, 5×5×5 lattice (grid / balanced order) | 1 / 4 |

The results of the test itself will be in a separate dated directory written by
`bin/stability_v2.py` (workflow `stability-v2.yml`, run only after the
pre-registration is on `main`).
