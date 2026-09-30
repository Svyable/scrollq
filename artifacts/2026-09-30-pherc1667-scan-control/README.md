# PHerc1667 spatial-scan control — 2026-09-30

PHerc1667 is the Challenge's first completely virtually unwrapped and
read Herculaneum scroll. This campaign uses ScrolIQ's public 2.399 µm
PHerc1667 volume as a **scroll-level known-success control** for the raw
spatial CT metrics used on PHerc0813 and PHerc1447.

Official outcome source: https://scrollprize.org/firstscroll

## Reproduce

```bash
scroliq-scan-map --root community-uploads/forrest/volcomp/PHerc1667/volumes/20251217075048-2.399um-0.2m-78keV-masked.zarr --grid 6 --chunks-per-shard 1 --out PHerc1667.scan-map.json
```

Source commit: `7323b7108b5ff91351fc299ef80b535500600f9e`.

## Descriptive central-80% overlap

| Target | Metric | PHerc1667 p10–p90 | Target p10–p90 | interval Jaccard |
|---|---|---:|---:|---:|
| PHerc0813 | nonzero_frac | 0.012546–1.0 | 0.009461–0.999997 | 0.996883 |
| PHerc0813 | grad_energy | 0.069284–6.752949 | 0.030983–11.011927 | 0.60866 |
| PHerc0813 | dyn_range | 0.8–174.0 | 0.0–157.3 | 0.899425 |
| PHerc0813 | sat_frac | 0.0–0.001026 | 0.0–0.000359 | 0.349903 |
| PHerc1447 | nonzero_frac | 0.012546–1.0 | 0.012022–0.999994 | 0.999464 |
| PHerc1447 | grad_energy | 0.069284–6.752949 | 0.118442–9.084437 | 0.735928 |
| PHerc1447 | dyn_range | 0.8–174.0 | 1.6–150.4 | 0.859122 |
| PHerc1447 | sat_frac | 0.0–0.001026 | 0.0–0.000182 | 0.177388 |

Interval overlap is not a quality score. It is a guard against inventing
universal thresholds from visually appealing statistics: substantial
overlap with a successfully read scroll means that metric alone cannot
justify calling the same value a failure on a target scroll.

## Critical limitation

This control is **scroll-level, not local ground truth**. The sampled
level-0 voxel boxes have not yet been intersected with the published
PHerc1667 surface/mesh coordinates. The next validation must perform
that coordinate alignment and compare ScrolIQ diagnostics against
locally verified successful and difficult unwrapping regions.
