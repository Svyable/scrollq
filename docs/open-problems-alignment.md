# ScrolIQ × Vesuvius Challenge Open Problems

ScrolIQ is evolving from a scan-quality leaderboard into a diagnostic layer for the full virtual-unwrapping pipeline.

The design target is the Vesuvius Challenge's **Open Problems: Why Reading Every Herculaneum Scroll Is Still a Challenge**, last updated July 10, 2026:

https://scrollprize.org/2026_open_problems

The central rule is simple:

> Diagnose the limiting stage with explicit evidence. Do not collapse unknown downstream state into one synthetic readiness score.

The existing ScrolIQ score remains useful, but it means one narrow thing: sampled CT health. It is not a surface, mesh, ink, or Grand Prize readiness score.

## Alignment map

| Challenge bottleneck | ScrolIQ role | Current state | Next measurable output |
|---|---|---|---|
| Local scan degradation / compressed regions | Scan diagnostics | Implemented: deterministic coordinate-preserving spatial sampling, real-voxel metrics, explicit missing/masked/read-failure states. Validation attempted: a pre-registered paired-protocol test (`scroliq-pairs`) found two candidate separability/sharpness metrics **discordant** with the documented protocol ordering on four registered pairs, so neither is promoted into the passport | Run the DLS 7.91 µm vs ESRF 2.4 µm pairs (host unreachable in the first run); try metrics that are not contrast-ratio histograms; separate voxel size from energy/propagation effects |
| Surface topology | Surface IQ | Partial: exact-scan surface-prediction CT support with bootstrap intervals via `scroliq-support` (all 22 First Letters scans) | Competing-surface ambiguity, topology-risk map, passport integration |
| Full recto submission coverage | Grand Prize coverage | Partial: declared reference-area accounting via `scroliq-recto-coverage`, plus provenance schema v3+ exact CT-root/commit binding and exact equality between ledger mesh IDs and submitted package mesh IDs | Independently validate that the frozen reference inventory itself contains the complete recto surface |
| Mesh connectivity | Mesh IQ | Partial: native TIFXYZ structure/provenance, mask-aware connected components and enclosed gaps, bbox/scale consistency, local edge jumps, severe normal reversals, quad-area distortion, per-triangle Jacobian singular-value isometry diagnostics, and optional fail-closed validation of the official VC3D `vc_tifxyz_selfcross` census via `scroliq-mesh` | CT support, sheet identity, merger/sheet-switch localization |
| Fiber connectivity | Fiber IQ | Implemented, not yet real-data validated: native VC3D `vc3d_fiber` JSON v1/v3/v4 plus CSV, strict persisted-span/config validation, SHA-256 provenance, native-trace/fallback/meeting-error summaries, and gap/sharp-turn review candidates via `scroliq-fiber`; opt-in CI gating | Pin and audit a public current fiber corpus; add CT-conditioned orientation/support evidence and cross-fiber connectivity |
| Winding annotations | Winding IQ | Partial: PointCollections v1 role/schema/numeric/provenance audit, collection-center axial coverage, and pre-fit umbilicus ray-order inversion review queue via `scroliq-winding`, run on the published PHercParis4 annotations (2/13,700 pairs inverted, both sub-voxel) with a measured injection-control recall (±3: 89.5%, ±5: 85.5%; ±2 undetectable by design) | Patch attachment, cross-collection graph/holonomy consistency, held-out constraint residuals, annotation-leverage map |
| Spiral fitting | Spiral IQ | Planned | Held-out constraint residuals, sensitivity, under-constrained regions |
| Label quality | Label IQ | Partial: label/segment coverage and `label_next` triage | Normal-direction label offset, snapping candidates, active-learning queue |
| Ink generalization and false positives | Ink IQ | Partial: exact-volume experiment manifest, train/evaluation spatial-overlap gate, checkpoint/seed provenance, held-out/run declarations, falsification-control coverage via `scroliq-ink-audit` | Attach measured offset/perturbation results, independent-checkpoint agreement, cross-scroll generalization |
| Data scale / reproducibility | Data Integrity | Partial: cloud reads, decode provenance, companion zarr-pyramid-audit; strict OME-Zarr v2 reader for the open bucket; declared-vs-stored chunk-size audit (one mismatch observed, in a non-prize volume) | Coordinate/provenance contract across all downstream artifacts |

## Diagnostic passport

`scroliq-passport` turns the current evidence for one volume into a machine-readable record organized around those bottlenecks.

```bash
scroliq-passport \
  --volumes artifacts/2026-09-30-scrollq-n24-dense/volumes.json \
  --coverage artifacts/2026-09-30-scrollq-n24-dense/coverage.json \
  --scan-map artifacts/2026-09-30-spatial-scan-campaign/PHerc0813.scan-map.json \
  --root 20250821151723 \
  --out out/PHerc0813.passport.json
```

A passport does **not** infer unmeasured stages from the scan-quality score. Today a typical result will contain:

- `data`: measured or partial, based on actual read/decode provenance;
- `scan`: measured, based on sampled level-0 voxels;
- `labels`: partial when coverage data is supplied;
- `winding`: partial when a structurally valid winding audit is explicitly bound to the exact selected volume; unbound/mismatched artifacts are excluded;
- `mesh`: partial when a volume-bound native TIFXYZ audit is supplied;
- `fibers`: partial when a structurally valid `scroliq-fiber` report is explicitly bound to the exact selected volume; unbound/mismatched artifacts are excluded;
- `ink`: partial when a volume-bound leakage/provenance/control audit is supplied;
- `surface`, `spiral`: `unknown` until direct evidence is supplied.

That asymmetry is intentional. It makes missing evidence visible instead of disguising it as confidence.


## Spatial scan map

`scroliq-scan-map` is the first diagnostic added after the passport contract. It samples a deterministic grid of L0 shards, decodes spread present inner chunks, and retains each observation's level-0 voxel bounding box.

The output also keeps missing shards, sparse/background shards, transport failures, and decode failures as explicit spatial records. A volume can therefore contain a mix of usable and problematic observations without those states disappearing into an average.

The current map is descriptive. It does not yet identify papyrus-layer separability, compression, or decohesion directly; those require validated local metrics against known-good and known-bad regions. The first validation attempt (`artifacts/2026-10-01-protocol-pairs/`) was a negative result for two candidate metrics. This distinction is important for prize evidence: raw locality is implemented, while physical interpretation remains a validation task.

## Prize-oriented sequence

### 1. Surface IQ

Accept a CT volume plus surface prediction and/or tifxyz mesh. Produce spatial diagnostics for CT support, nearby competing surfaces, abrupt depth displacement, holes, suspicious bridges and mergers, normal discontinuity, self-intersection, sheet-switch risk, and parameterization distortion.

The success criterion is not a prettier score. It is evidence that the diagnostic identifies real failure regions which, when corrected, improve unwrapping.

### 2. Mesh IQ

The implemented `scroliq-mesh` layer consumes the Challenge's native TIFXYZ surface format directly. It preserves file hashes, applies upstream validity and mask conventions, and reports disconnected valid-grid components, enclosed invalid-grid components, stale bbox metadata, reciprocal-scale mismatches, abrupt edge-length jumps, severe neighboring-normal reversals, symmetric quad-area distortion, and local isometry from the singular values of each flat-to-3D triangle Jacobian. The latter catches area-preserving anisotropic stretch/compression that an area-only check cannot see. When supplied with `--selfcross-report`, the same audit validates the official VC3D census against the exact local TIFXYZ path/grid, blocks on non-adjacent transverse contacts, and preserves upstream coplanar/grazing semantics; long-edge quads skipped by `maxedge` remain partial evidence. Passing evidence is still partial because these checks do not prove CT support or correct winding identity.

Next, bind mesh vertices to local CT support and localize suspected mergers or sheet switches into reviewable VC3D coordinates.

### 3. Fiber IQ

The implemented `scroliq-fiber` layer now consumes the VC3D-native persisted
fiber format directly (versions 1, 3 and 4), alongside the earlier CSV
interchange path. It validates control-point/span structure, current native
tracer metadata, persisted numeric configuration, exact input SHA-256,
interpolation goals/modes, native-trace acceptance errors, fallback/failure
codes and v4 span tags. Separately, it audits rendered line geometry for
relative gaps and abrupt turns. Fallback interpolation is reported as evidence
rather than automatically classified as a geometry defect. Review findings can
remain advisory or become an explicit pipeline gate with
`--fail-on-findings`.

This is format/provenance/geometry infrastructure, not yet evidence that a
specific trace follows one physical fiber or one sheet. Reports can now bind to
the exact CT root and enter the diagnostic passport; the passport fails closed
on missing or cross-volume binding and still marks the stage partial. The
repository does not currently contain a reproducible public June 2026 VC3D
fiber corpus run, so the next step is to pin one, then measure CT-conditioned
orientation/support and cross-fiber connectivity.

### 4. Label IQ

Measure whether surface/fiber labels are physically localized on the feature they claim to annotate. Sample along local normals, estimate likely offsets, identify ambiguous regions, and emit a review queue ranked by uncertainty and downstream leverage.

### 5. Winding IQ

Audit the winding constraints before fitting. The implemented `scroliq-winding` layer can bind its report to the exact CT volume root so passports fail closed on cross-volume evidence. It checks the conventional VC3D PointCollections documents for parseability, exact-file SHA-256 provenance, role-consistent `wind_a` semantics, numeric sanity, and collection-center axial coverage. For a declared fit window it exposes empty z bands and the largest gap between collection centers as annotation-prioritization evidence, without pretending that structurally valid or axially present annotations are geometrically correct. Given the dataset umbilicus, it also ranks annotated points whose winding numbers are out of radial order along rays from the scroll axis (winding gap ≥ 2, so the branch-cut convention cannot manufacture or hide an inversion); this is a review queue for likely mis-numbered annotations, not a verdict, because folding can legitimately break ray order.

Next, attach those constraints to verified patches and the fitted coordinate system, reuse the upstream winding-graph machinery to detect inconsistent cycles / holonomy, and measure which regions remain under-constrained or high-leverage for another annotation.

### 6. Spiral IQ

Evaluate candidate spiral fits rather than merely producing them. Use held-out winding constraints, residual distributions, constraint sensitivity, deformation pathologies, and uncertainty in sparsely constrained regions.

### 7. Ink IQ

The implemented `scroliq-ink-audit` makes the first validation layer fail closed. A manifest names the exact CT root, checkpoint plus SHA-256, seeds, train/evaluation ZYX boxes, held-out splits, run provenance, and falsification controls. Declared train/evaluation overlap fails the audit; missing controls remain visibly partial instead of being inferred.

Next, attach the actual measured outputs for normal-offset, adjacent-winding, geometry-perturbation, independent-checkpoint, and cross-scroll tests. A clean manifest is necessary evidence discipline, not proof that the model output is ink.

### 8. VC3D integration

The end state is not a standalone dashboard. A ScrolIQ diagnostic should point to a region that can be opened directly in VC3D for inspection or correction, and corrections should be able to flow back into a new diagnostic pass.

## Grand Prize readiness

The final passport should be able to answer, with evidence, what prevents a candidate scroll from satisfying the 2027 Grand Prize requirements. `scroliq-recto-coverage` now checks declared full-recto accounting, including detached patches and the strict <10% disconnected-outer-patch exception, while explicitly leaving independent reference-inventory completeness as upstream evidence. The remaining evidence chain includes valid per-column tifxyz meshes; low-distortion 2D parameterization; programmatic flattened renders; visible/legible ink across columns; no training/prediction leakage; reproducible training and inference provenance; held-out validation; documented human-input time; and VC3D-compatible outputs.

ScrolIQ should not decide whether a scroll is "good." It should expose the bottleneck that prevents the next verified step.
