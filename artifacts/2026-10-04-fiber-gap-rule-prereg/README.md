# Span-aware fiber gap rule — pre-registration (November N4a, pulled into October)

**Status: frozen before the comparison is run.**

The [span test](../2026-10-04-fiber-span-test-run/) showed that the current
whole-fiber gap rule mostly flags fallback spans, because they are rendered
sparsely. `spec.json` freezes a span-aware alternative and the test it must pass
to be adopted:

- **Planted breaks.** One planted break per fiber in a native span and one in a
  fallback span, each 6× its span's own median step. The span rule must find at
  least 95 % of them in both span classes.
- **Fewer artefacts.** It must at least halve the real fallback-span candidates.
- **No native loss.** It must not lose more than 2 points of native recall
  relative to the old rule.

Breaks sized relative to the fiber median are reported too, as a descriptive
look at the trade-off.

**Disclosure:** the thresholds were chosen after seeing the span test, which
makes the fallback reduction likely. The planted-break sensitivity is the part
that is actually at risk.

Runner: `scripts/fiber_gap_rule_eval.py` (pins this spec's SHA-256). Tests:
`tests/test_fiber_gap_rule_eval.py`.
