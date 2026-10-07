# PHerc1447 v8-in pinned ROI reproduction (2026-10-07)

This is a bounded execution gate for issue #172, not the full zero-shot campaign.

The experiment reruns the immutable base `v8-in` checkpoint and released inference code on a deterministic w058 ROI from the eligible PHerc1447 volume context. The ROI was selected **before ink labels or released predictions were downloaded**. Selection used only the pinned certainty mask and layer dimensions.

## Result

**REPRODUCED.**

On the 1,849-pixel frozen interior:

| comparison to released base prediction | MAE | RMSE | Pearson r | max abs |
| --- | ---: | ---: | ---: | ---: |
| correct PHerc1447 layer order (`--reverse`) | 0.001787 | 0.002106 | 0.999675 | 0.003887 |
| wrong layer order adverse control | 0.035508 | 0.049121 | 0.551710 | 0.178462 |

The preregistered reproduction gate was MAE <= 0.03 and Pearson r >= 0.95, so the correct-order rerun passed comfortably. The wrong-order run is retained as an adverse input control and is substantially less consistent with the released prediction.

## What this establishes

- the frozen base checkpoint bytes can be executed with the pinned released inference code and environment;
- the released w058 prediction is reproducible on this independently selected ROI;
- PHerc1447 layer order materially changes the output on the same bytes/ROI.

## What this does **not** establish

The frozen ROI contains only positive label pixels inside the scored interior (1,849 positive, 0 negative), so ROC AUC is undefined here. This artifact therefore **does not** establish zero-shot held-out ink discrimination, readability, full-surface reproducibility, physical specificity, or Grand Prize readiness. The full #172 campaign still needs a both-class evaluation region plus the frozen falsification controls.

## Custody

- PR: #242
- successful Actions run: `37625902869`
- Actions artifact id: `11484501707`
- Actions artifact digest: `sha256:ef8f3835df167ed3c571aa923e3a1968a2e485b144a8baad4a2433f8bf15fe87`
- eligible volume id: `20250521151220`
- surfaces revision: `7e4d918712a8d8642a6fdeee45b80217c1e98317`
- ROI manifest SHA-256: `59739f4840d83609831bdd6d8a89243913b38abf36b8c47605f0f3b01aebdece`
- correct prediction SHA-256: `182626cc8f22cd395cdca89fc08de066331f471ba4b4d65c4b05500b5ce87780`
- wrong-order prediction SHA-256: `50d0df29f8959a85386856ab21be7030c9aa0a065ca83918ee71d2ee60f2cdd8`

The complete ~791 kB workflow artifact retains cropped layers, predictions, environment, and SHA256SUMS. The committed files here preserve the frozen selection contract and measured receipt permanently.
