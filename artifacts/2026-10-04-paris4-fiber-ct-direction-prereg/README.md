# PHercParis4 fiber CT direction — pre-registration (November N4c, pulled into October)

**Status: frozen before any CT is read for this test.**

The CT support test showed that the public fibers sit on dense material in
`20260411134726`. This test asks the next physical question: do they run **within**
the papyrus sheet? At 8 points per fiber, a structure tensor over a 25³
level-1 neighbourhood gives the local sheet normal *n*. A fiber lying in the sheet
has a small |t·n|. A random direction has |t·n| uniform on [0, 1] (mean 0.5).

**Decision:** SUPPORTED iff the paired gap D = mean|r·n| − mean|t·n| has a
fiber-cluster 95 % CI lower bound above 0.1. **Wrong-frame control:** if the same
test also passes with x and y swapped, the verdict is `CONTROL FAILURE`.

Runner: `scripts/paris4_fiber_ct_direction.py` (pins this spec's SHA-256).
Tests: `tests/test_paris4_fiber_ct_direction.py`.
