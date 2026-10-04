# Span-aware gap rule v2 on PHerc0139 — result

Run of [`../2026-10-04-fiber-gap-rule-v2-pherc0139-prereg/`](../2026-10-04-fiber-gap-rule-v2-pherc0139-prereg/)
(spec SHA-256 `e70e851d…e42de`, pushed in `ad31a3a`). The rule, thresholds and
decision are identical to v1. The workflow committed `result.json` here.
Deviations: none.

## Verdict: KEEP. The span-aware rule is not adopted.

| | old rule | span rule |
|---|---:|---:|
| real candidates in fallback spans | 1,622 | **1,088** (ratio **0.67**, limit 0.5) |
| real candidates in native spans | 0 | 0 |
| planted span-relative breaks found, native (n = 409) | 100 % | 100 % |
| planted span-relative breaks found, fallback (n = 71) | 100 % | 100 % |
| planted fiber-relative breaks found, fallback (n = 71, descriptive) | 100 % | 0 % |

There were enough fallback spans this time (71 ≥ 30), and sensitivity held.
But on independent data the span-aware rule removes only a third of the
fallback candidates, not half. Together with v1 (INSUFFICIENT on PHercParis4),
the frozen question is answered: this simple renormalization is not enough.
The current rule stays. The guidance in `docs/fiber-audit.md` stands: read gap
counts together with the fallback share, and treat gaps in native `trace` spans
as the strong cues. On PHerc0139 there are none.
