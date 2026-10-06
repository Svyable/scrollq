# Threshold-persistence preregistration (2026-10-05)

The frozen specification for [`scroliq-persistence`](../../docs/threshold-persistence.md).

| File | What it is |
|---|---|
| `spec.json` | The complete spec: filtration conventions, sweep constants, region limits, labelling rule, feature lists, model, and every decision constant |

**Frozen hash.** The canonical SHA-256 of `spec.json` (sorted keys, compact
separators) is

```
31e22a9153463dd514dbffecfaa458a990ea331a7717a49d66326ef1e3699b26
```

It is pinned as a literal (`FROZEN_SPEC_SHA256` in
`src/scrollq/persistence_audit.py`), not derived from the spec, and
`tests/test_persistence_audit.py` asserts that the literal, the in-code `SPEC` and
this file all agree. Verify with:

```bash
python -c "from scrollq import persistence_audit as pa; print(pa.canonical_sha256(pa.SPEC))"
```

**What "preregistered" means here.** `spec.json` records
`real_prediction_maps_read: 0`: no real prediction map had been read when it was
frozen, and none has been since. `measure` and `evaluate` carry the hash of the spec
they ran under; a run under any other spec is reported `preregistered: false` and
can only return the verdict `EXPLORATORY`, never `PERSISTENCE_ADDS_SIGNAL`.

The feature and model definitions and the within-region count floors took their
final form during synthetic development, each change prompted by a recorded
observation (see the development log in the protocol). The gate constants
(90 % recall, 0.05 minimum gain, 66 % positive domains, alpha 0.05) were set before
any synthetic result was inspected and have not changed. None was tuned to a real
result, because none exists.

**Deviations.** Changing any value in `spec.json` changes the hash. Run the changed
spec as an exploratory run, log what changed and why next to its results, and keep
the earlier run: do not edit this directory in place.
