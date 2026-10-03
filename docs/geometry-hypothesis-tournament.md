# Geometry hypothesis tournament

`scroliq-geometry-tournament` is the first step from passive geometry QA to a
closed-loop hypothesis system.

It compares two or more `scroliq-geometry-validate` reports produced against
the **same frozen held-out specification**. The command deliberately does not
invent a blended score. It computes a Pareto frontier over four already-audited
quantities:

- held-out targets within tolerance, with every target in the denominator;
- number of targets for which a prediction exists;
- median error among predicted targets;
- maximum error among predicted targets.

A candidate dominates another only when it is no worse on every axis and
strictly better on at least one. A winner is emitted only when **all** candidate
reports are complete and exactly one candidate remains on the frontier.
Otherwise the verdict is `indeterminate`.

This is intentional. If one fit has better typical error while another has
better held-out hit rate or worst-case error, ScrolIQ records the tradeoff rather
than hiding it behind arbitrary weights.

## Usage

First evaluate each fit against the same frozen held-out geometry spec:

```bash
scroliq-geometry-validate \
  --spec evidence/heldout.json \
  --predictions evidence/baseline.predictions.json \
  --out evidence/baseline.geometry.json

scroliq-geometry-validate \
  --spec evidence/heldout.json \
  --predictions evidence/candidate.predictions.json \
  --out evidence/candidate.geometry.json
```

Then run the tournament:

```bash
scroliq-geometry-tournament \
  --candidate official-spiral=evidence/baseline.geometry.json \
  --candidate alternative-fit=evidence/candidate.geometry.json \
  --out evidence/geometry-tournament.json
```

Exit code 0 means there is one decisive complete winner. Exit code 1 means the
evidence is valid but still indeterminate. Malformed, incomparable, stale, or
tampered evidence fails as a CLI error.

## Fail-closed comparison contract

Every report must agree on:

- exact `volume_root`;
- `spec_sha256`;
- held-out tolerance;
- held-out denominator;
- exact target IDs and reference coordinates.

The tournament also recomputes report counts, hit rate, median error and maximum
error from each target row before comparing candidates. Duplicate prediction
hashes are rejected so the same evidence cannot be presented as two competing
methods.

The output SHA-pins every input report and retains each prediction/checkpoint
hash.

## What this enables next

For the current PHerc0826 Spiral path, the official Villa fit becomes the
baseline arm rather than an unquestioned answer. Alternative seeds, constraint
sets, fit implementations, or future surface methods can enter the same
held-out tournament without changing the decision rule.

The next extension should add **independent axes as separately bound evidence**,
not weights: CT support / wrong-wrap controls, mesh topology, flattening
distortion, then ink counterfactuals. Geometry should only be promoted when it
survives evidence that was not used to create it.

## Limits

A geometry-tournament winner is not proof of sheet identity, topology, CT
support, flattening quality, ink presence, legibility, or Grand Prize
readiness. It only means one complete candidate dominates the other submitted
candidates on the frozen held-out point-evaluation axes.
