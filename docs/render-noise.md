# Flatten/render measurement-noise floor

`scroliq-render-noise` blocks one specific mistake: claiming that a small
geometry change moved recovered ink (or any rendered quantity) when the
flatten/render stage alone moves an *unchanged* surface by as much.

## Input

The input is one experiment's measurement record:

- `determinism.mode`: `deterministic` or `nondeterministic`, with the
  settings used (for example deterministic PyTorch algorithms on or off).
  A missing or `unknown` mode makes the block `unverified`.
- `repeats`: at least `min_repeats` (default 3) flatten+render runs of the
  same unchanged surface. Each repeat has the measured `value` and,
  optionally, `outputs_sha256` for its x/y/z.tif.
- `claims`: `{claim_id, baseline, candidate}` for each claimed effect.

## Output

The output is a `measurement_noise` block for the experiment passport. It
records:

- the declared mode;
- whether the repeat outputs were bit-identical;
- the relative noise floor (repeat range ÷ repeat mean);
- a verdict per claim. A claim is `EXCEEDS_NOISE_FLOOR` only if
  `|relative change| > k × max(floor, floor_min)` (default k = 3);
  otherwise it is `WITHIN_NOISE`.

A record declared deterministic whose outputs differ carries a warning.

```bash
scroliq-render-noise --self-test
scroliq-render-noise --record measurement.json --out out/measurement-noise.json
```

## Scope

The floor covers re-rendering one fixed surface. It is the right control for
within-surface perturbations, such as displacing one fitted surface by a few
voxels. It is **not** evidence about variation between independently fitted
surfaces, where fit randomness can dominate.

## Source

The external motivation is `vesuvius-autoresearch`. It reports that Lasagna
flattening on byte-identical inputs moved the layout and changed
`total_fg_pixels` by about 3%, and became bit-identical with deterministic
PyTorch algorithms at roughly 9.5× the cost. Those are the project's own
reports and are not reproduced here.
