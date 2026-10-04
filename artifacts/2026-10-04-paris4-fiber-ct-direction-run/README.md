# PHercParis4 fiber CT direction — result (November N4c, pulled into October)

Run of the test frozen in [`../2026-10-04-paris4-fiber-ct-direction-prereg/`](../2026-10-04-paris4-fiber-ct-direction-prereg/)
(spec SHA-256 `3690f5cc…59da`, pushed in `28d6514` before its run workflow
existed). The workflow committed `result.json` here create-only. Deviations: none.
Two workflow attempts before this run failed at YAML parsing, before any step ran.

## Verdict: SUPPORTED (wrong-frame control passed)

| | mean \|t·n\| | paired gap D = mean\|r·n\| − mean\|t·n\| (95 % CI) |
|---|---:|---|
| fiber tangents (1,074 points, 136 fibers) | **0.078** (median 0.058) | **0.418** (0.397 – 0.436) |
| random directions at the same points | 0.495 | — |
| axis-swapped control (855 points) | 0.471 | 0.042 (0.012 – 0.071), below the 0.1 bar |

The fibers run **within** the local CT sheet plane. The median tangent is about
3.3° out of plane (mean 4.5°), while a random direction averages 30°. Median
structure-tensor coherence at fiber points is 0.77. 14 fiber points were skipped
(cube outside the volume, mostly empty, or coherence < 0.1), and no fiber
averages above 0.25. The most out-of-plane fiber is
`kb_20260728T224853384_000201.json` (0.244), a review cue. The swapped control
shows a small residual (0.04). That is consistent with dominant layering
existing everywhere, and it stays well under the frozen 0.1 bar.

## What it means

Together with the [CT support result](../2026-10-04-paris4-fiber-ct-support-run/),
the public PHercParis4 fibers, placed in `20260411134726`, both sit on dense
material and run along the sheet that material forms. That is strong physical
evidence that the fibers are traced in this volume's frame. The binding is still
not declared by the dataset. This test does not say which sheet a fiber is on,
nor verify horizontal or vertical fiber identity.
