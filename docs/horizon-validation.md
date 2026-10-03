# Held-out horizon validation

`scroliq-horizon-validate` evaluates a `scroliq-horizon-path` result against a
frozen reference curve while excluding every declared anchor and a fixed
neighborhood around it from scoring.

This is the bridge between the new sheetness/path baselines and a defensible
real-data experiment. It is modeled on ScrolIQ's existing held-out geometry
discipline: freeze the protocol first, hash-bind every input, keep missing
predictions in the denominator, and publish a failed decision rule rather than
retuning it after seeing the result.

## Freeze the specification before tracking

A version-1 specification contains:

```json
{
  "schema_version": 1,
  "coordinate_system": "score_map_xy",
  "protocol_id": "phercXXXX-slice-042-v1",
  "shape_yx": [512, 768],
  "score_sha256": "<64 lowercase hex>",
  "truth_sha256": "<64 lowercase hex>",
  "tracker": {
    "max_step": 2,
    "smoothness": 0.2,
    "normalization": {
      "enabled": true,
      "lower_percentile": 1.0,
      "upper_percentile": 99.0
    }
  },
  "anchors": [
    {"x": 0, "y": 137},
    {"x": 220, "y": 141},
    {"x": 511, "y": 128}
  ],
  "anchor_exclusion_columns": 8,
  "tolerance_rows": 2.0,
  "minimum_within_tolerance_rate": 0.9
}
```

The truth CSV must contain `x,y` columns and its exact bytes must match
`truth_sha256`. The score map used by the tracker must match
`score_sha256`. Choose the tolerance, anchor-exclusion radius, tracker
parameters, and success-rate threshold before generating the prediction.

Calculate the canonical protocol hash:

```bash
scroliq-horizon-validate \
  --spec protocol.json \
  --print-spec-hash
```

Commit the specification before the measured run.

## Run the frozen tracker configuration

Generate the prediction with exactly the score map, anchors and parameters
declared in the spec:

```bash
scroliq-horizon-path sheetness-slice.npy \
  --out-prefix out/slice-042 \
  --max-step 2 \
  --smoothness 0.2 \
  --anchor 0:137 \
  --anchor 220:141 \
  --anchor 511:128
```

The evaluator independently verifies:

- score-map SHA-256 and image shape;
- tracker method;
- `max_step` and `smoothness`;
- normalization mode and frozen percentiles;
- exact anchor list;
- prediction CSV SHA-256;
- equality between the prediction CSV `x,y` rows and the JSON path.

A stale or edited artifact fails before measurement.

## Evaluate withheld columns

```bash
scroliq-horizon-validate \
  --spec protocol.json \
  --prediction out/slice-042.horizon.json \
  --truth withheld-curve.csv \
  --out out/slice-042.validation.json
```

If the prediction JSON was moved away from its CSV, provide the exact
hash-matched file with `--prediction-csv`.

For an anchor at column `x=a` and exclusion radius `r`, every truth point
whose column satisfies `|x-a| <= r` is excluded. This includes the anchor
itself. If the exclusions remove all truth points, the evaluator fails rather
than reporting an empty success.

Every remaining truth point is in the denominator. A missing prediction counts
against `within_tolerance_rate`; it cannot improve the score. Error summaries
are explicitly predicted-only and are reported alongside completeness.

The preregistered verdict is:

```text
PASS iff within_tolerance_rate >= minimum_within_tolerance_rate
```

Equality passes. The CLI exits 0 for PASS, 1 for FAIL, and 2 for invalid
inputs through argparse.

## What the result proves

A PASS means that, under one frozen 2-D protocol, the declared path stayed
within the declared row tolerance on at least the preregistered fraction of
held-out truth columns outside anchor neighborhoods.

It does **not** establish:

- independent blindness of parameter tuning;
- that the score map was constructed without reference leakage;
- papyrus or winding identity;
- 3-D topology or full-surface continuity;
- recto/verso;
- ink or readability.

Those remain separate evidence obligations. In particular, the report says
explicitly that upstream score construction and parameter-tuning history are
not independently verified.

## First public campaign

For the first real-data campaign:

1. choose one hash-pinned public segment with high-confidence geometry;
2. define several cross-sections where the mesh intersects as one unambiguous
   curve;
3. freeze sheetness parameters, sparse anchors, `max_step`, smoothness,
   exclusion radius, row tolerance and success threshold;
4. commit every protocol before running any corresponding prediction;
5. evaluate all frozen slices, including failures;
6. add fixed normal-offset and deliberately wrong-surface controls;
7. publish aggregate and per-slice results without changing the frozen decision
   rules.

A negative result is useful: it tells us not to spend the eight-hour Grand
Prize human-input allowance on a propagation signal that does not recover
known geometry.
