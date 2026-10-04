# Span-aware gap rule v2 on PHerc0139 — pre-registration

**Status: frozen before the comparison is run on PHerc0139.**

[v1](../2026-10-04-fiber-gap-rule-run/) on PHercParis4 came back INSUFFICIENT:
every check passed, but there were only 24 fallback spans to plant breaks in,
below the minimum of 30. v2 applies the **identical rule, thresholds and decision**
to the independent PHerc0139 census (411 fibers, 2,900 fallback spans). Only the
inputs and the seed change. Because nothing was tuned on PHerc0139, this also
answers v1's disclosure that its thresholds were chosen after seeing the
PHercParis4 data.
