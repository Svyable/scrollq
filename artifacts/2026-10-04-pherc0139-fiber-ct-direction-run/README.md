# PHerc0139 fiber CT direction — result (replication of N4c)

Run of [`../2026-10-04-pherc0139-fiber-ct-direction-prereg/`](../2026-10-04-pherc0139-fiber-ct-direction-prereg/)
(spec SHA-256 `548c9109…c29c8c5`, pushed in `ad31a3a`). The workflow committed
`result.json` here create-only. Deviations: none.

## Verdict: SUPPORTED. It replicates PHercParis4, and the wrong-frame control passed.

| | PHerc0139 (this run) | PHercParis4 |
|---|---|---|
| fiber points used | 3,189 (99 skipped) in 411 fibers | 1,074 in 136 |
| mean \|t·n\| fiber / random | **0.083** / 0.496 | 0.078 / 0.495 |
| median out-of-plane angle | **3.5°** (mean 4.7°) | 3.3° (mean 4.5°) |
| D (95 % CI) | **0.414** (0.403 – 0.424) | 0.418 (0.397 – 0.436) |
| axis-swapped D (95 % CI) | 0.053 (0.037 – 0.068), below 0.1 | 0.042 |
| median coherence at fiber points | 0.72 | 0.77 |

No fiber averages above 0.25. The most out-of-plane fibers are
`kb_20260908T012312096_000113` (0.210), `lt_20260901T081258097_000040` (0.198) and
`lt_20260925T092921311_000187` (0.189).

The public PHerc0139 fibers run within the CT sheet plane of `20260102150214`,
just as the PHercParis4 fibers do in theirs. Two scrolls, two volumes, and the
same answer from the same frozen design.
