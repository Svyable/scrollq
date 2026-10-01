# 2027 Grand Prize target qualifier — 2026-09-30

Frozen output from the first ScrolIQ Grand Prize qualification pass.

Primary reproduction:

```bash
scrollq-grand-prize \
  --volumes artifacts/2026-09-30-scrollq/volumes.json \
  --out /tmp/grand-prize-targets.json
```

Primary method: a weight-free Pareto frontier over the existing ScrolIQ
scan-quality score and current public segment count. Surface and lasagna
predictions are required bootstrap assets. This is campaign triage, not a
readability or ink prediction.

Primary frontier across all 13 current Grand Prize volumes:
**PHerc0813**, **PHerc1447**.

Optional external surface-support sensitivity pass:

```bash
scrollq-grand-prize \
  --volumes artifacts/2026-09-30-scrollq/volumes.json \
  --surface-support artifacts/2026-09-30-grand-prize-qualifier/surface_support_external.json \
  --out /tmp/grand-prize-targets-with-support.json
```

The external evidence is imported from
`axiosdevs/herculaneum-scroll-tools/ct_support/`, with every survey file SHA
recorded in `surface_support_external.json`. A support number is accepted only
when its evidence points to the exact prize-eligible volume. This excludes
PHerc1203's published support survey because it uses volume
`20260319130212` at 2.403 µm rather than eligible volume
`20250820131727` at 9.362 µm. PHerc0125 and PHerc1218 remain unverified
because their salvaged records do not preserve the CT URL.

Exact-volume surface-support evidence is therefore comparable for 10/13
targets. Its three-axis Pareto frontier is:
**PHerc0191, PHerc0211, PHerc0268, PHerc0800, PHerc0813, PHerc1447**.

The wider sensitivity frontier is not a ranking failure; it shows that scan
quality, existing segmentation bootstrap, and surface-prediction CT support
trade off. The next discriminator is held-out geometry performance.

Source metadata is dated 2026-09-30 and each target row contains its official
Scroll Prize data-browser URL. Same-scroll higher-resolution data is never
silently substituted into the prize comparison.
