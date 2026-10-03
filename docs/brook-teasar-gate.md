# Brook / CUDA TEASAR accelerator equivalence gate

**Status:** preregistered experiment; no ScrolIQ acceptance result yet. Set 2026-10-03.

## Why this exists

Brook is a CUDA-native implementation of TEASAR skeletonization with a
Kimimaro-compatible Python interface. Its parallelization strategy is directly
relevant to Vesuvius fiber work: connected components and distance transforms
are GPU-parallel, path tracing uses ring-style parallel work, long objects are
split into a second execution lane, and the sequential TEASAR dependency is
partly hidden by a speculative draft-ahead + verify step.

The published Brook 0.1.0 benchmark includes two Herculaneum papyrus-fiber CT
segmentations, not only connectomics data. Brook reports the same label IDs as
Kimimaro on its tested datasets, while total skeleton cable length differs by
0.5% to 7.9%; the largest differences were on the two scroll-fiber scans.
That combination — large speedup plus non-identical geometry on the target
domain — makes a simple backend swap inappropriate for prize work.

ScrolIQ therefore treats Brook as an **external accelerator candidate**. Speed
is useful only if the geometry and downstream constraints remain fit for the
same purpose.

Upstream references:

- Brook: https://github.com/giorgioangel/brook
- Brook 0.1.0 code commit:
  https://github.com/giorgioangel/brook/commit/4ff20298e4384ddae2123ec7dcbe697b54bec13a
- Brook documentation / benchmarks: https://giorgioangel.github.io/brook/
- Kimimaro: https://github.com/seung-lab/kimimaro
- Kimimaro issue found during Brook validation:
  https://github.com/seung-lab/kimimaro/issues/127
- Kimimaro soma fix:
  https://github.com/seung-lab/kimimaro/commit/c9e2e2c4c49a58a52836ea982642972663dfaaef
- Villa spiral track extraction:
  https://github.com/ScrollPrize/villa/blob/main/spiral-fitting/extract_surface_tracks.py

## Licensing / submission boundary

Brook 0.1.0 is GPL-3.0-only. ScrolIQ is MIT licensed, and the 2027 Grand Prize
requires the submitted reproducible pipeline code to be public under a
permissive open-source license.

That does **not** make Brook useless to the project. It does mean that ScrolIQ
must not silently turn Brook into a required submission dependency and then
claim the resulting pipeline is permissively licensed.

Until the licensing question is resolved, use Brook in one of these roles:

1. external benchmark / oracle for TEASAR behavior;
2. experimental accelerator whose outputs are compared with the accepted
   baseline and recorded by immutable hashes;
3. inspiration for a separately written permissive implementation of the
   algorithmic ideas, with no copying or mechanical translation of GPL source.

A future dual/permissive license from the Brook author would change this gate.
Record the exact license text and revision rather than relying on a project
name or package version.

## Frozen first comparison

The first ScrolIQ comparison should freeze:

| Component | Revision |
|---|---|
| Brook | `4ff20298e4384ddae2123ec7dcbe697b54bec13a` (0.1.0 code release) |
| Kimimaro baseline | `b7543fbb893fd0cbc8a9e81276daac3e2d78ca68` (5.8.5 release) |
| Kimimaro soma fix | `c9e2e2c4c49a58a52836ea982642972663dfaaef` |
| ScrolIQ gate | the commit containing this document |
| Input label volumes | exact paths + SHA-256 + voxel shape + dtype + anisotropy |

Kimimaro 5.8.1 must not be used as the only reference for soma-mode
equivalence because issue #127 identified unsigned-subtraction and path-order
bugs in that code path and #128 fixed them. Historical 5.8.1 results can still
be retained as a useful reproduction target when the exact old behavior is the
thing being compared.

## Gate A — environment and source identity

Record before timing or comparing geometry:

- exact Brook and Kimimaro commits / package versions;
- complete command or Python call and TEASAR parameters;
- random seeds for every stochastic stage around skeletonization;
- input label-volume SHA-256, shape, dtype and anisotropy;
- GPU model, driver, CUDA runtime/toolkit and VRAM;
- CPU model, worker count and host RAM;
- whether input and output remain on GPU or cross host memory;
- Brook memory mode (in-core, streaming, multi-GPU if used);
- wall-clock measurement protocol, warmups and repetitions.

Do not compare a one-core Kimimaro number with a many-core result without
reporting both. Performance claims must state the CPU worker count and GPU.

## Gate B — object-set and validity parity

For every frozen volume, require:

- identical set of nonzero label IDs returned by both backends;
- no missing or extra object in either arm;
- finite vertex coordinates and radii;
- vertices remain within the declared label-volume bounds after coordinate
  conversion;
- each nonempty skeleton has valid edge indices;
- connected-component count and cycle count are recorded per object.

Any missing/extra label, malformed graph or out-of-bounds coordinate blocks
promotion for that dataset.

## Gate C — geometry comparison without pretending paths must be byte-identical

TEASAR can choose different equal-cost routes. Exact vertex equality is
therefore too strong, while cable length alone is too weak.

For each object, record at least:

- vertex and edge counts;
- endpoint and branch-point counts;
- total cable length and relative cable-length delta;
- symmetric nearest-geometry distance between the two skeletons, expressed in
  physical units from the declared anisotropy;
- p50, p95 and maximum symmetric distance;
- fraction of each skeleton within preregistered tolerances of the other;
- radius distribution deltas where both outputs provide radii.

Aggregate by object count **and** by cable length so thousands of tiny labels do
not hide a failure on a long fiber.

The acceptance thresholds must be frozen before the first target-domain result
is inspected. Do not tune a threshold to make Brook pass.

## Gate D — papyrus-fiber target-domain test

The promotion decision must include Herculaneum fiber labels, not just generic
connectomics volumes.

Freeze a target-domain set spanning:

- sparse and dense label fields;
- small and large 3-D shapes;
- at least one volume where long fibers dominate runtime;
- at least one case with many short labels;
- the two public papyrus-fiber benchmark cases used by Brook when their exact
  source identity can be independently recovered.

If the exact two Brook benchmark inputs cannot be recovered and hash-pinned,
treat the published numbers as context only and run a new public, reproducible
campaign on identified Vesuvius data.

## Gate E — downstream Vesuvius utility

A TEASAR result can be geometrically close yet still be worse for the actual
unwrapping task. For any candidate use in fiber constraints or spiral track
extraction, compare downstream outputs under frozen settings.

At minimum record:

- number of usable fiber/track constraints produced;
- failure/fallback counts;
- gap and sharp-turn findings from `scroliq-fiber` where the output can be
  represented in the accepted Fiber IQ contract;
- track-satisfaction counts / fractions for spiral-fitting experiments;
- held-out geometry residuals where `scroliq-geometry-validate` applies;
- wall clock, peak VRAM and peak host RSS.

No ink image, OCR result, candidate letterform or legibility judgment may be
used to choose TEASAR parameters or select the comparison region.

## Gate F — performance claim

Report speed only after Gates A-D have produced valid comparable outputs.

For each workload publish:

- median wall time after declared warmup;
- number of repetitions;
- throughput in labeled voxels/s and objects/s where meaningful;
- CPU workers / threads;
- peak VRAM and host RSS;
- transfer-inclusive and GPU-resident timings separately when both are useful.

The headline should name the comparison, e.g. “Brook 0.1.0 on RTX 4090 vs
Kimimaro 5.8.5 with 8 CPU workers”, not “GPU is 100× faster”.

## Promotion states

ScrolIQ should distinguish four outcomes:

- **rejected** — validity/object parity fails, or target-domain geometry exceeds
  frozen tolerances;
- **equivalent-for-tested-use** — geometry and downstream tests pass, but this
  says nothing about license suitability;
- **execution-accelerator-only** — useful for experiments/benchmarking but not a
  required Grand Prize pipeline dependency;
- **submission-eligible** — equivalence passes *and* the exact implementation
  dependency chain is compatible with the Grand Prize permissive-license
  requirement.

The last state requires an explicit license check at the pinned revision. A
performance result can never imply it.

## Relationship to Fiber IQ

This gate complements `scroliq-fiber`.

`scroliq-fiber` audits persisted VC3D fiber traces for schema/provenance,
fallback behavior, gaps, sharp turns and control-line consistency. This TEASAR
gate instead asks whether a skeletonization backend is a safe execution
substitute upstream of those persisted traces.

If Brook (or a future permissive CUDA TEASAR implementation) is used to produce
fiber constraints, the final evidence chain should preserve both:

1. backend equivalence / target-domain benchmark evidence from this gate; and
2. the normal exact-volume Fiber IQ artifact for the resulting trace.

## Next implementation step

Add a dependency-light `scroliq-teasar-compare` command that consumes two
backend-neutral skeleton manifests or SWC directories and emits the Gate B/C
metrics above. Keep Brook and Kimimaro themselves optional and external: the
comparison tool should not need either package installed to verify previously
generated artifacts.

A follow-on runner may execute the external backends in a controlled
environment, but it must write source, environment, input and output hashes so
the comparison remains independently replayable.
