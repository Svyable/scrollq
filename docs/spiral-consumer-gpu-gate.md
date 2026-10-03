# Consumer-GPU Spiral adapter equivalence gate

**Status:** preregistered experiment; no ScrolIQ acceptance result yet. Set 2026-10-03.

## Why this exists

The public `spiral-fit-consumer-gpu` adapter reports that the official Vesuvius
Challenge Spiral fitter can run on a 12 GB consumer GPU by replacing two
fallback bottlenecks without changing their intended outputs:

- sparse-cache gathers are split/fused, with reported `torch.equal` parity;
- point-to-patch linking is spatially pruned, with reported identical links,
  annotations, ij coordinates, and distances.

This is operationally important to ScrolIQ because the Grand Prize proof
campaign requires a real, pinned Spiral baseline before downstream geometry
claims are credible. Faster execution is **not** itself prize evidence. The
adapter is accepted only as an execution substitute if ScrolIQ independently
reproduces semantic equivalence at the exact frozen revisions below.

## Frozen sources

| Component | Revision | Terms |
|---|---|---|
| adapter | `7jycwjmbfn-eng/spiral-fit-consumer-gpu@f189740211f462193973055a32e3269c03301587` | MIT |
| official fitter | `ScrollPrize/villa@7769da8cf2233310570608feecc127066a7c0c7c` | upstream repository terms |
| PHercParis4 Spiral data used by the adapter | public Vesuvius Challenge dataset | CC BY-NC 4.0; do not treat as unrestricted commercial data |

The adapter's own reproduction guide pins that `villa` revision. Do not
silently substitute current `villa/main`. A newer upstream revision requires
a new dated gate because source substitutions and equivalence assumptions may
have changed.

## Gate A — source and license identity

Before execution, record:

1. full Git commit hashes for adapter and `villa`;
2. SHA-256 for each adapter file actually injected;
3. `git diff --ignore-cr-at-eol --stat` for the `villa` checkout;
4. Python, PyTorch, Triton, CUDA/driver, GPU and host-RAM versions;
5. exact data roots and applicable Vesuvius data terms.

Fail closed if the adapter revision, upstream revision, injected files, or data
identity differ from the frozen manifest.

## Gate B — cache equivalence

Run the adapter's cache equivalence suite before any real fit. Preserve the
machine-readable/stdout result and environment manifest.

Acceptance:

- every scenario that has an upstream reference must satisfy exact
  `torch.equal` output parity;
- the >2 GiB/channel regression case must run;
- the oversized-gather case may demonstrate a capability beyond upstream, but
  it does **not** count as an equivalence comparison where upstream refuses.

Any non-equal comparable output rejects the adapter for the proof campaign.

## Gate C — point-to-patch link equivalence

Run the adapter's real-patch/real-point-collection linker comparison with both
hit policies. Preserve exact inputs or immutable input hashes.

Acceptance requires equality of:

- linked patch identity;
- `on_patch` annotations;
- ij coordinates;
- distances;
- output ordering where ordering is semantically consumed.

Runtime improvement is secondary and must be reported separately from parity.
A faster non-equivalent linker fails.

## Gate D — bounded real-fit A/B

Only after Gates A-C pass, run one bounded fit where stock upstream is feasible
on the same hardware. Freeze z-range, step count, seed/config, data hashes,
pool budgets and all other inputs before seeing the comparison.

Compare stock versus adapter on the same frozen held-out geometry specification
using `scroliq-geometry-validate`. Do not select the evaluation region from
either fit's output.

Required report:

- completion/failure status for both arms;
- wall clock, peak VRAM and peak host RSS;
- checkpoint SHA-256 for both arms;
- all frozen target predictions, including missing/failed targets;
- within-tolerance rate and predicted-only residual statistics;
- a deliberately displaced prediction control.

**Acceptance is semantic, not performance-based.** The adapter may enter the
Grand Prize baseline path only if Gates A-C pass and Gate D shows no
prize-relevant geometry regression under the preregistered metric. Performance
numbers cannot rescue a geometry failure.

## Leakage and false-ink boundary

This experiment is geometry-only. No ink render, OCR output, candidate letter,
or legibility judgment may be used to choose:

- cache/linker settings;
- z-range;
- held-out targets;
- fit checkpoint;
- acceptance threshold.

The adapter does not strengthen an ink claim and cannot turn a suggestive
texture into evidence of writing. Any later ink experiment must remain bound
to the separate ScrolIQ ink-validation and negative-control gates.

## Proof gate strengthened

A passing result strengthens the **baseline-runnability/reproducibility gate**
in the Grand Prize proof campaign. It does not establish sheet identity,
whole-scroll coverage, flattening quality, readability, or ink identity.

## Incorporation rule

Do not vendor the adapter into the `scrollq` package during this experiment.
Execute the immutable external revision against the immutable upstream
revision and bind outputs by hashes. Vendoring or rewriting is justified only
after independent equivalence succeeds and there is a concrete maintenance
benefit.

A failed gate remains a dated negative result. Do not relax parity requirements
after observing a failure.
