# Threshold-persistence audit: synthetic controls (2026-10-05)

Evidence for [`scroliq-persistence`](../../docs/threshold-persistence.md).
**Everything here is synthetic.** It shows the implementation honors its stated
rules, including the controls that can fail. It says nothing about whether real
ink and real false positives differ in threshold persistence: no real prediction
map has been measured. Status: EXPERIMENT FURTHER.

All reports are bound to spec digest
`31e22a9153463dd514dbffecfaa458a990ea331a7717a49d66326ef1e3699b26`
([`../2026-10-05-threshold-persistence-prereg/`](../2026-10-05-threshold-persistence-prereg/README.md))
and to these source digests (SHA-256):

| File | SHA-256 |
|---|---|
| `src/scrollq/persistence.py` | `432387721c70bbaa6748509650d856e371521c5a5025ad0e96ff09195fdc24fa` |
| `src/scrollq/persistence_audit.py` | `d48bab56c65cc42730526a510577dfe51720905e7c48512c59961c4057abf35b` |
| `src/scrollq/persistence_controls.py` | `d2bd4162f9fec0897331155ad2d064fe363fa6e61cdafff85790abe4355c7a2e` |

Generated with NumPy 2.4.6 on Python 3.11.15. NumPy does not promise identical
`Generator` streams across versions, so a rerun elsewhere should reproduce the gate
outcomes and the qualitative table but may move individual numbers.

## Files

| File | Command | Gate |
|---|---|---|
| `controls-heldout.json` | `scroliq-persistence controls --out controls-heldout.json --seed-base 700000 --n 24` | PASS |
| `controls-development.json` | `scroliq-persistence controls --out controls-development.json --seed-base 100000 --n 12` | PASS |

Output files are create-only, so rerun into a fresh path.

- **Held-out** (`700000`) was run once, after the code and the spec were final (the
  source digests above were taken first and re-checked afterwards).
- **Development** (`100000`) was looked at while the generators and rules were being
  built, so it is *not* held-out. Its outcomes agreed qualitatively with the held-out
  run (planted effect found in 11 of 12 seeds; the other three scenarios 0 of 12); it
  is kept so the earlier run stays next to the later one.

## Held-out results (24 seeds per scenario)

Each seed builds four domains, each with its own monotone calibration (one of four
maps) and its own noise level, and runs the frozen leave-one-domain-out rule from
`scroliq-persistence evaluate`, with its 200-permutation test, on every seed.

| Scenario | Construction | `PERSISTENCE_ADDS_SIGNAL` | Cross-region scope alone passes | Within-region scope alone passes | Median gain, all / within (range, all) |
|---|---|---|---|---|---|
| `planted_sweep_effect` | false positives carry a sub-nominal skirt, invisible at the nominal threshold | **24 / 24** | 24 | 24 | +0.49 / +0.60 (+0.33 to +0.66) |
| `null_no_effect` | both classes from one generator | 0 / 24 | 0 | 0 | -0.07 / -0.07 (-0.17 to +0.04) |
| `baseline_explained` | classes differ in peak amplitude only | 0 / 24 | 0 | 0 | -0.08 / -0.09 (-0.15 to -0.01) |
| `region_confound_only` | blank regions carry the skirt, in-region false positives look like ink | 0 / 24 | **21** | **0** | +0.17 / -0.07 (+0.04 to +0.30) |

"Gain" is the reduction in false-positive rate at 90 % verified-ink recall over the
better baseline (see the protocol). The median permutation p-value in
`planted_sweep_effect` is 0.005, the smallest value 200 permutations allow.

Engine and invariance controls (all passed):

- persistence-derived Betti numbers matched an independent connected-component count
  at all 20,845 levels checked (0 mismatches), and `beta0 - beta1` matched an
  independent `V - E + F` Euler count at all 14,513 unmasked levels (0 mismatches);
- diagrams were identical under all eight grid symmetries on 6 of 6 fields;
- the oracle is not vacuous: given the wrong foreground connectivity it disagreed
  with the engine at 2,543 of 4,198 levels;
- every rank feature was bitwise identical under four injective monotone remaps
  (cube, `expm1(3v)`, square root, scaling), while value-parameterised persistence
  changed under all four, so the invariance control can fail.

## What this shows

- The pipeline **finds a difference that exists only in the threshold sweep** and is
  invisible at the nominal threshold by construction, on domains whose calibration
  differs.
- It **does not credit** a class difference the baselines already explain, nor
  identical generators. With 0 of 24 on each, the false-alarm rate is bounded below
  about 12 % (one-sided 95 %); that is a bound, not a calibration.
- It **does not pass a region-level confound**: where the cross-region scope alone
  passed in 21 of 24 seeds, the within-region scope blocked it in every one. In the
  development run the cross-region scope alone passed 12 of 12 times, so the
  confound is not a rare accident of the generator.

## What this does not show

- That real ink and real false positives differ in persistence. **Unmeasured.**
- Statistical power on real data. The planted effect's size is my choice, so
  24 / 24 is a sensitivity check of the instrument, not a power estimate.
- Anything about stable false positives: the audit cannot reject them by design.
- That the synthetic domains resemble real fragments. They are 64 x 64 stroke fields
  with a smooth noise background; they exercise the logic, not the physics.

## Known limits of these controls

- The invariance control analysed only 5 components in its single test region
  (4 injective remaps); the unit tests and the per-region check in `measure` extend
  it, but this artifact's number is small.
- The `region_confound_only` scenario is one construction of a region-level
  confound. Real confounds (scanner, fragment, texture) need not look like it.
- A first confound scenario that varied only background noise never produced a
  cross-region gain and was replaced; see the development log in the protocol.
