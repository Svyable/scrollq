# ScrolIQ × Vesuvius Challenge Open Problems

ScrolIQ is evolving from a scan-quality leaderboard into a diagnostic layer for the full virtual-unwrapping pipeline.

The design target is the Vesuvius Challenge's **Open Problems: Why Reading Every Herculaneum Scroll Is Still a Challenge**, last updated July 10, 2026:

https://scrollprize.org/2026_open_problems

The central rule is simple:

> Diagnose the limiting stage with explicit evidence. Do not collapse unknown downstream state into one synthetic readiness score.

The existing ScrollQ score remains useful, but it means one narrow thing: sampled CT health. It is not a surface, mesh, ink, or Grand Prize readiness score.

## Alignment map

| Challenge bottleneck | ScrolIQ role | Current state | Next measurable output |
|---|---|---|---|
| Local scan degradation / compressed regions | Scan diagnostics | Implemented: deterministic coordinate-preserving spatial sampling, real-voxel metrics, explicit missing/masked/read-failure states | Validate on real scrolls; add local layer-separability/decohesion proxies |
| Surface topology | Surface IQ | Planned | CT support, competing-surface ambiguity, topology-risk map |
| Mesh connectivity | Mesh IQ | Planned | Holes, mergers, self-intersections, sheet-switch risk, local distortion |
| Fiber connectivity | Fiber IQ | Planned | Continuity/orientation confidence and trace-break candidates |
| Winding annotations | Winding IQ | Partial: PointCollections v1 role/schema/numeric/provenance audit plus collection-center axial coverage via `scroliq-winding` | Patch attachment, graph/holonomy consistency, held-out constraint residuals, annotation-leverage map |
| Spiral fitting | Spiral IQ | Planned | Held-out constraint residuals, sensitivity, under-constrained regions |
| Label quality | Label IQ | Partial: label/segment coverage and `label_next` triage | Normal-direction label offset, snapping candidates, active-learning queue |
| Ink generalization and false positives | Ink IQ | Planned | Leakage audit, held-out validation, depth/perturbation stability, cross-scroll checks |
| Data scale / reproducibility | Data Integrity | Partial: cloud reads, decode provenance, companion zarr-pyramid-audit | Coordinate/provenance contract across all downstream artifacts |

## Diagnostic passport

`scroliq-passport` turns the current evidence for one volume into a machine-readable record organized around those bottlenecks.

```bash
scroliq-passport \
  --volumes artifacts/2026-09-30-scrollq/volumes.json \
  --coverage artifacts/2026-09-30-scrollq/coverage.json \
  --root PHerc0813 \
  --out out/PHerc0813.passport.json
```

A passport does **not** infer unmeasured stages from the scan-quality score. Today a typical result will contain:

- `data`: measured or partial, based on actual read/decode provenance;
- `scan`: measured, based on sampled level-0 voxels;
- `labels`: partial when coverage data is supplied;
- `winding`: partial when a structurally valid winding audit is explicitly bound to the exact selected volume; unbound/mismatched artifacts are excluded;
- `surface`, `mesh`, `fibers`, `spiral`, `ink`: `unknown` until direct evidence is supplied.

That asymmetry is intentional. It makes missing evidence visible instead of disguising it as confidence.


## Spatial scan map

`scroliq-scan-map` is the first diagnostic added after the passport contract. It samples a deterministic grid of L0 shards, decodes spread present inner chunks, and retains each observation's level-0 voxel bounding box.

The output also keeps missing shards, sparse/background shards, transport failures, and decode failures as explicit spatial records. A volume can therefore contain a mix of usable and problematic observations without those states disappearing into an average.

The current map is descriptive. It does not yet identify papyrus-layer separability, compression, or decohesion directly; those require validated local metrics against known-good and known-bad regions. This distinction is important for prize evidence: raw locality is implemented, while physical interpretation remains a validation task.

## Prize-oriented sequence

### 1. Surface IQ

Accept a CT volume plus surface prediction and/or tifxyz mesh. Produce spatial diagnostics for CT support, nearby competing surfaces, abrupt depth displacement, holes, suspicious bridges and mergers, normal discontinuity, self-intersection, sheet-switch risk, and parameterization distortion.

The success criterion is not a prettier score. It is evidence that the diagnostic identifies real failure regions which, when corrected, improve unwrapping.

### 2. Label IQ

Measure whether surface/fiber labels are physically localized on the feature they claim to annotate. Sample along local normals, estimate likely offsets, identify ambiguous regions, and emit a review queue ranked by uncertainty and downstream leverage.

### 3. Winding IQ

Audit the winding constraints before fitting. The implemented `scroliq-winding` layer can bind its report to the exact CT volume root so passports fail closed on cross-volume evidence. It checks the conventional VC3D PointCollections documents for parseability, exact-file SHA-256 provenance, role-consistent `wind_a` semantics, numeric sanity, and collection-center axial coverage. For a declared fit window it exposes empty z bands and the largest gap between collection centers as annotation-prioritization evidence, without pretending that structurally valid or axially present annotations are geometrically correct.

Next, attach those constraints to verified patches and the fitted coordinate system, reuse the upstream winding-graph machinery to detect inconsistent cycles / holonomy, and measure which regions remain under-constrained or high-leverage for another annotation.

### 4. Spiral IQ

Evaluate candidate spiral fits rather than merely producing them. Use held-out winding constraints, residual distributions, constraint sensitivity, deformation pathologies, and uncertainty in sparsely constrained regions.

### 5. Ink IQ

Make validation and false-positive mitigation reproducible. Check train/prediction overlap, checkpoint and pseudo-label lineage, random seeds, held-out performance, depth stability, local perturbation stability, and cross-scroll generalization.

### 6. VC3D integration

The end state is not a standalone dashboard. A ScrolIQ diagnostic should point to a region that can be opened directly in VC3D for inspection or correction, and corrections should be able to flow back into a new diagnostic pass.

## Grand Prize readiness

The final passport should be able to answer, with evidence, what prevents a candidate scroll from satisfying the 2027 Grand Prize requirements: complete recto coverage; valid per-column tifxyz meshes; low-distortion 2D parameterization; programmatic flattened renders; visible/legible ink across columns; no training/prediction leakage; reproducible training and inference provenance; held-out validation; documented human-input time; and VC3D-compatible outputs.

ScrolIQ should not decide whether a scroll is "good." It should expose the bottleneck that prevents the next verified step.
