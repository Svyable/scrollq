# Horizon path baseline

`scroliq-horizon-path` tracks one left-to-right path through a 2-D likelihood
field from sparse hard anchors. It is a deliberately small experiment inspired
by seismic-horizon interpretation, where a geologic layer must be followed
through noisy, folded, and locally interrupted volumetric data.

This command is **not** a 3-D surface grower. It is the smallest testable
question first: given a 2-D score field that should peak on a papyrus layer,
can a globally constrained path recover a held-out layer better than local
peak-picking?

## Adjacent-field references

The scientific analogy comes from public seismic work:

- Aina Juell Bugge et al.'s
  [HorizonTracker](https://github.com/ajbugge/HorizonTracker) describes
  data-driven horizon tracking using non-local dynamic time warping and
  unwrapped instantaneous phase. We use the repository and paper as method
  inspiration only; this implementation does not copy its code.
- [seismiqb](https://github.com/GeoscienceML/seismiqb) provides a broader
  open seismic-interpretation toolkit, including horizon operations, under
  Apache-2.0.

ScrolIQ's first baseline is intentionally simpler than either system: a
first-order dynamic program over rows with an explicit maximum step, a
total-variation smoothness penalty, and hard sparse anchors.

## Objective

For one row coordinate `y_x` at every image column `x`, the tracker
maximizes

```text
sum_x score[y_x, x] - smoothness * sum_x |y_x - y_(x-1)|
```

subject to

```text
|y_x - y_(x-1)| <= max_step
```

and every declared anchor `(x, y)` being satisfied exactly.

This is solved by deterministic dynamic programming. There is no random state.
Ties resolve by the first NumPy argmax, so repeated runs on the same numerical
stack produce the same path.

## Run it

```bash
scroliq-horizon-path sheetness-slice.npy \
  --out-prefix out/slice-042 \
  --max-step 2 \
  --smoothness 0.20 \
  --anchor 0:137 \
  --anchor 220:141 \
  --anchor 511:128
```

Anchors may also be supplied with `--anchors-json` as

```json
[
  {"x": 0, "y": 137},
  {"x": 220, "y": 141},
  {"x": 511, "y": 128}
]
```

Accepted score maps are 2-D NPY, NPZ, TIFF, or TIF. By default the score map is
robustly normalized from its 1st to 99th percentile so the smoothness parameter
has a reproducible scale. `--no-normalize` preserves the supplied scores.

Outputs:

- `*.horizon.csv`: one `x,y` point per column plus normalized and source
  score values;
- `*.horizon.json`: exact input and CSV SHA-256 values, normalization,
  parameters, hard anchors, full path, objective decomposition, and path
  smoothness statistics.

The default 2-million-pixel guard keeps this reference implementation bounded.

## Fail-closed behavior

The command rejects:

- non-2-D inputs;
- invalid or conflicting anchors;
- anchor coordinates outside the score map;
- anchor pairs that cannot be connected under `max_step`;
- negative/non-finite smoothness;
- invalid normalization ranges;
- oversized inputs unless the guard is explicitly raised.

A large local score cannot buy a jump beyond `max_step`.

## Claim boundary

A successful path establishes only that **one 2-D trajectory is favored by the
declared score field and path constraints**. It does not establish:

- that the trajectory is papyrus;
- that it belongs to the same physical sheet across the whole slice;
- winding identity;
- 3-D surface connectivity;
- recto versus verso;
- ink or readability.

It therefore stays outside the diagnostic passport until real-data held-out
validation exists.

## Synthetic falsification controls

`tests/test_horizon_path.py` pins the first contract before any Vesuvius
result is claimed:

1. recover a known curved horizon through a deliberately removed evidence gap;
2. satisfy every sparse hard anchor exactly;
3. reject anchor pairs impossible under the declared step bound;
4. prove a high-score distractor cannot violate the step constraint;
5. reproduce the exact same path across repeated runs;
6. hash-pin the emitted path artifact;
7. reject malformed anchor JSON and oversized inputs.

## Predeclared real-data experiment

The next campaign should join this path baseline to `scroliq-sheetness`
without tuning on the held-out curve:

1. select a hash-pinned, publicly available high-confidence segment;
2. choose CT cross-sections that intersect the segment in one traceable curve;
3. derive the score map from a frozen sheetness configuration;
4. keep only sparse anchor points from the known curve as fit input;
5. hide all remaining segment coordinates during tracking;
6. measure row error against the held-out curve, keeping missing/unrecoverable
   columns in the denominator;
7. run fixed normal-offset and wrong-surface controls;
8. publish the result even if the tracker fails.

Only after that experiment should we consider a second-order model, non-local
trace matching, 3-D propagation, or passport integration.
