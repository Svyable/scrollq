# Fiber span test — result (October stretch goal O7)

Run of the test frozen in [`../2026-10-04-fiber-span-test-prereg/`](../2026-10-04-fiber-span-test-prereg/)
(pushed as `02500d9` before the run workflow existed). GitHub Actions run
[37169552146](https://github.com/Svyable/scrollq/actions/runs/37169552146) on
`8faefec`. `result.json` and `fiber-gaps.points.json` are copied verbatim from the
job log. Spec SHA-256 `670f8091…a57edf` matched; all 136 fibers re-downloaded and
hash-matched the census. Deviations: none.

## Verdict: SUPPORTED (controls passed)

| | fallback spans | native spans |
|---|---:|---:|
| spans | 502 | 5,001 |
| spans with a gap candidate | **101 (20.1 %)** | **2 (0.04 %)** |

- Risk difference **0.201**, fiber-cluster bootstrap 95 % CI **[0.145, 0.299]**
  (10,000 reps); Mantel–Haenszel odds ratio 1,496 over 79 informative fibers.
- Positive control (gaps planted only in fallback spans): SUPPORTED.
  Null control (gaps independent of mode): SUPPORTED in 3 / 200 replicates
  (1.5 %, limit 10 %).
- No non-monotone fibers; no gap steps outside spans.

## What it means (descriptive, not part of the decision)

The pre-registered mechanism arm points to rendering density, not trace
breaks. Fallback spans are drawn with a median step of **3.26×** the fiber's
median step (p90 4.06), against 1.00× for native spans. The gap rule fires
at 4×, so it mostly measures how sparsely a fallback span was rendered:

- 386 of 388 gap candidates are in fallback spans (356 `lasagna`, 30 `cspline`);
  their median step ratio is 4.25, just over the threshold.
- Only **2** are in native trace spans: consecutive steps 2410–2411 of
  `kb_20260721T175535642_000571.json` (8.6× and 8.4×). These, together with the
  15 fallback gaps above 8×, are the candidates worth a reviewer's time.

**Consequence for Fiber IQ.** The current whole-fiber gap rule conflates
fallback rendering density with discontinuities. A span-aware rule would fix
that, for example normalizing by the span's own median step, or reporting
fallback spans separately. That rule needs its own pre-registered evaluation;
it is not changed here. Until then, read Fiber IQ gap counts on VC3D fibers
together with their fallback share.

## Review in VC3D (goal O10)

`fiber-gaps.points.json` is VC3D PointCollections v1. It holds all 388 gap
candidates at the midpoint of the long step, tagged with source file, SHA-256,
line step, span, span mode and step ratio. To start with the strongest cues,
filter on `span_mode = trace` or `step_ratio > 8`. Coordinates are the fibers'
published xyz; no CT volume binding is asserted (see O9).

## Limits

The result is an association at span level. Nothing here reads CT, so it
cannot say whether any gap is a physical break or sheet switch.
