# Span-aware fiber gap rule — result (November N4a, pulled into October)

Run of the test frozen in [`../2026-10-04-fiber-gap-rule-prereg/`](../2026-10-04-fiber-gap-rule-prereg/)
(spec SHA-256 `09ea046e…da56`, pushed in `214fe0a`). The workflow committed
`result.json` here. Deviations: none.

## Verdict: INSUFFICIENT, so the rule is not adopted

Every decision check passed, but only **24** fibers have a fallback span with
at least 8 non-zero steps to plant a break in. The frozen minimum is 30 per
class, so the verdict is INSUFFICIENT as written, not ADOPT.

| | old rule | span rule |
|---|---:|---:|
| real candidates in fallback spans | 386 | **189** (ratio 0.49, limit 0.5) |
| real candidates in native spans | 2 | 2 |
| planted span-relative breaks found, native (n = 136) | 100 % | 100 % |
| planted span-relative breaks found, fallback (n = 24) | 100 % | 100 % |
| planted *fiber-relative* breaks found, fallback (n = 24, descriptive) | 100 % | **0 %** |

The descriptive row shows the expected trade-off. A break of 6× the fiber's
usual step inside a sparsely rendered span looks like ordinary rendering to a
span-aware rule. Halving the fallback flags costs that sensitivity.

## Next

Pre-registered as v2: the same rule and thresholds, unchanged, on the
independent PHerc0139 census, which has 2,900 fallback spans. That also removes
this test's disclosure that the thresholds were chosen after seeing the
PHercParis4 span test.
