# PHercParis4 winding ray-order audit

Source commit: `c9f1d38e9a9f7d931b243c5cc35b199f81d73452`
Inputs: https://dl.ash2txt.org/datasets/spiral_datasets/PHercParis4/
(SHA-256 of every input is recorded in both JSON reports.)

## Reproduce

```bash
scroliq-winding --dataset <PHercParis4 spiral-input root> --out PHercParis4.winding-audit.json
python bin/ray_order_control.py <PHercParis4 spiral-input root> injection-control.json --injections 200 --shifts 2,3,5 --seed 0
```

## Audit (first lines of summary.txt)

```
Winding annotation audit: PARTIAL
collections=460 points=7645 annotated=2232
axial collection-center gap=943.7 slices between 15976.5 and 16920.2
umbilicus ray order: review inversions=2/13700 comparable pairs
  review relative collection=178 point=2106 wind_a=8 xyz=[3244.9, 3302.7, 8879.0] inversions=1/7
  review relative collection=178 point=2108 wind_a=10 xyz=[3242.8, 3362.3, 8879.0] inversions=1/8
  review relative collection=250 point=2607 wind_a=6 xyz=[3258.2, 3097.7, 11432.2] inversions=1/6
  review relative collection=250 point=2609 wind_a=8 xyz=[3237.8, 3160.0, 11432.2] inversions=1/6
- absolute: warn collections=6 points=59 sha256=4e566731f7cb...
```

## Injection control

One real annotated point at a time is mis-numbered by ±shift and the
check is rerun on otherwise unmodified data.

```
shift ±2: detected 0/191 testable (9 untestable of 200); rank-1 share None; median rank None
shift ±3: detected 179/200 testable (0 untestable of 200); rank-1 share 0.18994413407821228; median rank 4
shift ±5: detected 171/200 testable (0 untestable of 200); rank-1 share 0.8830409356725146; median rank 1
```

A ±2 error is undetectable by construction (the minimum compared
winding gap is 2). Inversions are review candidates, not errors:
folding can legitimately break ray order.
