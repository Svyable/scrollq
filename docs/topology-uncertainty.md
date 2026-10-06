# Topology-conditioned uncertainty audit

`scroliq-topology-uncertainty` is a **post-hoc** test on already-frozen surface
predictions. Nothing is retrained, no learned confidence head is added, and every
report carries `promotional: false`. **There is no real-checkpoint result yet**:
the only committed numbers are the synthetic controls in
[`artifacts/2026-10-07-topology-uncertainty-synthetic/`](../artifacts/2026-10-07-topology-uncertainty-synthetic/README.md).

## Question (frozen before any real prediction is read)

A surface predictor can be confident voxel by voxel and still be topologically
wrong (a surface jumping between adjacent windings). On a frozen ensemble
(seeds, checkpoints, or controlled inference perturbations), does epistemic
disagreement rank independently known structural failures better than the
ordinary confidence the same ensemble already reports?

Failure fixtures, one stratum each (the spec names them): cross-roll impostors,
drifted surfaces, phantom predictions in unscanned CT, planted winding errors.
Verified-good surfaces are the reference stratum. Fixture strata come from sealed
fixture construction; a fixture derived from any member's output invalidates the
ranking.

## Method and provenance

The idea comes from the MIDL 2026 TUNE++ paper (uncertainty coupled to
topological complexity). **No TUNE++ code is used, vendored or adapted**: its
public repository states no license, and its released topology module is a
distance-transform approximation rather than the persistent-homology machinery
the paper describes. Everything here is an independent implementation on top of
`scroliq-ensemble-independence` (ancestry, held-out checks, mutual information)
and `scroliq-topology` (persistence engine). The paper's medical-imaging
results are not evidence for papyrus.

## Inputs

```bash
scroliq-topology-uncertainty evaluate --spec spec.json --out out/report.json
scroliq-topology-uncertainty self-test
```

```json
{
  "schema": "scroliq-topology-uq-spec-v1",
  "predictions": "predictions.npz",
  "ancestry": "ancestry.json",
  "failure_strata": ["cross_roll_impostor", "drifted_surface",
                     "phantom_unscanned_ct", "planted_winding_error"],
  "reference_stratum": "verified_good",
  "alpha": 0.05, "persistence_floor": 0.2, "min_class_count": 10,
  "bootstrap": {"seed": 0, "replicates": 2000},
  "units": [{"unit_id": "p-001", "group_id": "block-A", "scroll_id": "PHercEval",
             "stratum": "drifted_surface"}]
}
```

`ancestry.json` is an ensemble-independence manifest (members need not be
independent; the report states the detected regime and certified witness count,
and disagreement among dependent members is a ranking signal only). The run
refuses (exit 2) if any unit, group or scroll appears in any member's training
or calibration ancestry. `predictions.npz` (no pickle) holds `members` (IDs) and,
per unit, `p/<unit_id>` of shape `(members, H, W)` with probabilities in
[0, 1] on the TIFXYZ grid, plus optional `valid/<unit_id>` and `mask/<unit_id>`
(the fixture's failure-location cells). Members align by ID.

## Scores

- `mi`: mean mutual information across members over valid cells (the epistemic score).
- `confidence`: mean predictive entropy of the ensemble mean (the baseline).
- `topology_member_spread` (exploratory, never in the verdict): spread across
  members of significant H0/H1 persistence-feature counts (floor
  `persistence_floor`).
- Consensus component and hole counts per stratum are reported descriptively.
- `local_enrichment` (secondary, not in the verdict): within-unit cell AUROC of MI
  vs. entropy against the fixture mask.

## Decision rule (constants in code)

Intervals are block bootstraps over `group_id`. `PROMOTE` requires: pooled MI
AUROC lower bound above 0.5; pooled paired gain over confidence with a lower
bound above 0; at least half the failure strata individually beat confidence
(MI AUROC lower bound above 0.5 *and* gain lower bound above 0); no stratum
worse than confidence. Otherwise `DISMISS`, with `underpowered: true` if the gain
interval still reaches 0.1. A built-in control that does not fire, or any
stratum with fewer than `min_class_count` units in a class, gives `UNVERIFIED`.
`PROMOTE` would justify a simple topology-conditioned audit in ScrollQ, not a
trained head; `DISMISS` means the approach is dropped.

## Controls

Before any verdict a planted panel must show that disagreement ranks fields where
members split (and beats confidence, which the plant inverts), that confidently
wrong fields with zero disagreement are not credited (AUROC exactly 0.5), that
the mask localization is detected, and that permuted labels false-promote at a
rate of at most 0.2 over 12 trials. Seed and replicate count are code
constants, not spec fields.

## Limits

- Fixtures that differ from verified-good surfaces in acquisition or region can
  be ranked by that difference rather than by topology.
- Patches are not independent specimens; intervals reflect the number of groups.
- Synthetic controls only; detection limits on real papyrus are unmeasured.

```bash
python -m pytest tests/test_topology_uncertainty.py -q
```
