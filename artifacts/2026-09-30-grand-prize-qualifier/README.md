# 2027 Grand Prize target qualifier — 2026-09-30

Frozen output from the first ScrolIQ Grand Prize qualification pass.

> **Current result.** The September write-up cites the dense 24-sample
> qualifier, not this first pass. It reproduces byte-for-byte from the
> n24-dense campaign:
>
> ```bash
> scrollq-grand-prize \
>   --volumes artifacts/2026-09-30-scrollq-n24-dense/volumes.json \
>   --out /tmp/targets.json
> diff <(python -m json.tool /tmp/targets.json) \
>      <(python -m json.tool artifacts/2026-09-30-grand-prize-qualifier-n24-dense/targets.json)
> ```
>
> Primary frontier: **PHerc0813**, **PHerc1447** (same as this first pass).
> Adding `--surface-support` to the n24-dense run gives the sensitivity
> frontier **PHerc0268, PHerc0800, PHerc0813, PHerc1447**. That output is not
> committed. The six-scroll sensitivity frontier below comes from the retired
> 4-sample campaign and is kept for history.
>
> The rest of this README documents that first pass, which used the retired
> 4-sample campaign (`artifacts/2026-09-30-scrollq/volumes.json`).

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
