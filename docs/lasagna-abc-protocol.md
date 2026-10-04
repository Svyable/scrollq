# Lasagna A/B/C: multi-sheet consistency vs effective-loss integrity

**Status:** WATCH, design draft. **Not frozen, not run.** Nothing below is a
result, and no Lasagna code was executed or modified in this repository.

Reported (maintainers' research note; **not independently verified here**):

- villa documentation now describes Lasagna as optimizing several stacked
  papyrus sheets jointly so they stay mutually consistent, rather than refining
  one surface, and it can drive fiber tracing;
- a public issue reports that the dense normal/spacing losses can be silently
  zeroed when no outer-shell mesh exists, which reportedly affects most Grand
  Prize-eligible scrolls that have no human segmentation.

A multi-sheet consistency prior is the right inductive bias for tightly
compressed regions, but the reported defect means a configured dense loss is not
evidence of an active one. We therefore **do not promote Lasagna because the
official README recommends it.** The experiment below decides whether it earns
a place, and its first gate is the effective-vs-configured check in
[the objective audit](objective-audit.md).

## Arms

All arms use the same region(s), CT, seeds, supervision and compute budget.

| Arm | Configuration | Objective-audit requirement |
| --- | --- | --- |
| **A** | independent-sheet refinement (no cross-sheet coupling) | sheet-level terms `active`; no dense terms configured |
| **B** | stacked Lasagna with the dense normal/spacing losses | dense terms `expect: active` with a `claim`, gradient evidence required |
| **C** | identical to B with the dense losses deliberately disabled | dense terms `expect: inactive`, and verified inactive |

An arm whose audit is `OBJECTIVE_INTEGRITY_FAILURE` is **invalid**: it is
recorded as a failed arm (its regions count as failed in the denominator, per
`scroliq-eval`), never as evidence about that configuration. In particular a B
whose dense terms were silently zero is not "B"; it is an unintended C.

## Region

A compressed region (or set of regions) is chosen from the *lowest inter-sheet
spacing stratum* of the frozen [geometry-strata](geometry-strata.md) spec,
before any arm is run, and the same regions are used by every arm. Held-out
annotations are excluded from every arm's supervision (leakage controls as in
[held-out geometry evaluation](heldout-geometry-evaluation.md)).

## Measurements per arm and region

| Measurement | Binding today |
| --- | --- |
| Effective-loss activation (counts, finite, nonzero, gradient norm) | `scroliq-objective-audit` — **exists**; needs the Lasagna loop instrumented (Task 0) |
| Held-out coverage | `scroliq-segmentation-validate` bidirectional coverage — **exists** |
| Inter-sheet ordering violations | umbilicus ray-order logic exists for *annotations* (`winding_geometry`); the **fitted-surface extension is not implemented** |
| Minimum inter-sheet spacing | **not implemented** for fitted sheets |
| Sheet switches | **not implemented**; fiber fingerprints/frame continuity are candidate detectors but still EXPERIMENT FURTHER |

The last three must exist, with positive controls, before the experiment can be
frozen. Do not substitute a proxy that was not tested on injected wrong-sheet
geometry.

## Decision rule (to be frozen, then computed, not judged)

Lasagna (B) is promoted only if **all** hold:

1. A, B and C all audit `OBJECTIVE_VERIFIED` (B active, C inactive).
2. Treating A as baseline and B as candidate, `scroliq-geometry-strata`
   passes on the held-out regions, with the compressed stratum designated hard.
3. B shows fewer ordering violations and fewer sheet switches than A, with
   intervals excluding zero, and no spacing floor violation.
4. B differs from C on held-out coverage with an interval excluding zero. If
   B ≈ C, the dense losses are not measurably doing anything, whatever the
   config says.

Ordering consistency alone earns no credit: a consistency prior can preserve a
wrong ordering as well as a right one, so held-out coverage and independent
controls decide.

## Before freezing

- **Task 0:** identify, in a pinned villa revision, where each dense loss term
  is evaluated and show counters can be recorded (`ObjectiveTracker`) without
  changing the objective.
- Pin the villa commit, config overrides, region IDs, seeds, thresholds and
  margin; commit them before any run.
- Implement and positive-control the three missing measurements above.

Deviations after the freeze are logged with date and reason in the results
artifact, never by editing the frozen constants, and keep earlier runs beside
later ones.

## Non-claims

No expectation about which arm wins is recorded. Compute is medium-high and
integration difficulty medium; geometry-hallucination risk is medium, because
a consistency prior is only as good as the ordering it enforces.
