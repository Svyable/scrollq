# Configured vs effective objective

**Rule.** A nonzero configured loss weight is not evidence that the term
contributed gradients. Every training or optimization passport distinguishes
`configured_objective` from `effective_objective`, and `scroliq-objective-audit`
fails closed when they disagree.

A reported Lasagna defect is the model case (maintainers' note; **not
reproduced here**): the dense normal/spacing losses can be silently zeroed when
no outer-shell mesh exists. Nothing errors; the run is just not the run its
config describes. `scroliq-spiral-run` already guards the analogous hole for
*supervision* by parsing the fit's stdout; this generalizes it to loss terms.

## Passport format

```json
{
  "schema_version": 1,
  "run_id": "optional",
  "arm": "optional",
  "configured_objective": {
    "terms": [
      {"name": "sheet_fit",    "weight": 1.0},
      {"name": "dense_normal", "weight": 2.0, "claim": "inter-sheet-ordering"},
      {"name": "dense_spacing","weight": 0.5, "expect": "inactive"}
    ]
  },
  "effective_objective": {
    "steps": 1000,
    "terms": [
      {"name": "dense_normal", "evaluations": 1000, "finite_evaluations": 1000,
       "nonzero_evaluations": 1000, "accumulated_contribution": 12.5,
       "gradient_norm": {"count": 1000, "sum": 310.0, "max": 0.9, "nonfinite": 0}}
    ]
  }
}
```

(Synthetic illustration.) `expect` is `active` or `inactive` and defaults to
`active` for a nonzero weight; `inactive` lets an **ablation arm** assert that a
term is really off. `claim` names the property the passport says the term
enforces (topology, ordering, safety…); a claimed term must carry gradient
evidence.

## Producing the effective block

`ObjectiveTracker` is dependency-free. Call `record` once per term evaluation
with the term's **weighted contribution to the total loss as computed** (after
any mask or early return — not the configured weight) and, if available, the
term's gradient norm:

```python
from scrollq.objective_audit import ObjectiveTracker

tracker = ObjectiveTracker(["sheet_fit", "dense_normal", "dense_spacing"])
for batch in loader:
    ...
    tracker.record("dense_normal", float(weighted_loss.detach()), grad_norm=float(g))
    tracker.end_step()
passport["effective_objective"] = tracker.effective_objective()
```

Terms the loop never calls still appear with zero evaluations, so
non-activation is explicit rather than a missing record.

## Failures

| Code | Meaning |
| --- | --- |
| `MISSING_FROM_EFFECTIVE` | a configured-active term has no effective record |
| `NEVER_EVALUATED` | evaluations = 0 |
| `ALWAYS_ZERO` | every evaluation contributed exactly zero (the silent-zero case) |
| `LOW_ACTIVATION` | nonzero in fewer evaluations than `--min-nonzero-fraction` |
| `NONFINITE` / `NONFINITE_GRADIENT` | NaN/inf loss or gradient norm was recorded |
| `ZERO_GRADIENT` | gradient evidence exists but never positive |
| `NO_GRADIENT_EVIDENCE` | a claimed term has none (`--allow-missing-gradient` relaxes this) |
| `INACTIVE_TERM_IS_ACTIVE` / `INACTIVE_TERM_HAS_GRADIENT` | an expected-inactive term acted: the arm was not ablated |
| `UNDECLARED_ACTIVE_TERM` | an active term the configuration never declared |

Malformed passports (duplicate names, impossible counts, a term expected active
with weight 0, zero steps) raise an error rather than pass.

```bash
scroliq-objective-audit --passport out/arm-b.passport.json --out out/arm-b.objective.json
```

Exit 0 is `OBJECTIVE_VERIFIED`, 2 is `OBJECTIVE_INTEGRITY_FAILURE` or invalid
input; the result carries the passport's canonical SHA-256.

## Claim boundary

A verified passport says each term behaved as the configuration says. It does
not say the objective is well chosen, that a safety/topology term constrains the
fit *correctly*, or that anything is readable. A consistency prior can preserve
the wrong ordering as effectively as the right one; see
[the Lasagna A/B/C design](lasagna-abc-protocol.md).

Model cards do not yet reference an objective audit; wiring it into
`scroliq-eval` preflight is a follow-up, not part of this change.
