# Official recto baseline, CGAL smoothing and two CT-preprocessing re-checks — 2026-10-06

**Status:** one external checkpoint registered as a frozen geometry baseline
(unpinned, not run); one method held at WATCH for a clean-room experiment; two
re-checks with unchanged decisions. No scoring behaviour, training path, frozen
artifact or Grand Prize execution order changes.

Claims attributed to external projects come from the 2026-10-06 maintainer
briefing unless a line says it was read here. `huggingface.co` and
`cgal.org` are blocked by the build container's egress policy, so most of it
could not be re-read.

## 1. `scrollprize/surface_recto_3dunet` as a frozen reference

**Decision: INCLUDE AS A FROZEN REFERENCE (evaluation-only). Registered
unpinned:** [`artifacts/2026-10-06-recto-3dunet-reference/`](../../artifacts/2026-10-06-recto-3dunet-reference/README.md).

**What was checked here.** A web-search snippet of the model card confirms the
architecture (residual-encoder 3D U-Net with scSE, `ps256_bs2_msr_default`),
256³ z-scored 1-channel input, the Medial Surface Recall + Dice/CE loss, the
loader keys (`model`, `model_config`), its role in the Angelotti et al. (Nature,
2026) complete-unwrapping pipeline, and the training ancestry: PHerc0139, 1667,
0343P, 0500P2 and MAN Bp, ~116.5k train / ~2.4k validation patches. Epoch 3504,
the MIT checkpoint license and the CC BY-NC 4.0 tomography terms are relayed,
not read.

**Two corrections to the briefing.**

- *"ScrollQ's current surface hypothesis generator" does not exist.* ScrolIQ
  owns no surface backbone or checkpoint (see the SegWithU entry in
  [dismissed-and-deferred](dismissed-and-deferred.md)); it consumes published
  prediction volumes. So the first comparison is this checkpoint against those
  published surface sources on the same sealed crops. The "beat both" rule
  applies to any surface model ScrolIQ adopts later.
- *Ancestry already touches ScrolIQ's own evidence.* Most surface campaigns
  here read the published PHerc0139 `surface-recto-090.zarr`. PHerc0139 is a
  training scroll, so none of those results is held-out evidence for this
  model. PHerc0343 (a First Letters target) and the training scroll PHerc0343P
  must be confirmed as distinct objects before PHerc0343 counts as held-out.
  The 13 Grand Prize volumes are all scroll-disjoint by ID.

**Licensing is recorded in two fields:** `licenses.checkpoint` (MIT, relayed)
and `licenses.training_data` (CC BY-NC 4.0 tomography, relayed). The
checkpoint label never relicenses the scans.

**Smallest experiment and promotion gate.** These are in the artifact README:
one scroll-disjoint eligible volume, a crop set sealed before inference, a
fixed config, and geometry-only gates. The proof gate this strengthens is
*canonical-baseline / scroll-disjoint surface-model generalization*. Spurious
geometry is still possible from a learned predictor, so CT support and
topology gates apply to it unchanged.

**Self-evaluation:** applicability very high; impact high as a reference;
integration difficulty low once the checkpoint can be downloaded; evidence
quality high upstream; training leakage knowable at scroll level and not
below it; inference compute substantial (256³ 3D U-Net).

## 2. CGAL `Mesh_smoothing_3`

**Decision: WATCH the method; do not vendor, import, link or adapt the
implementation.** This updates the 2026-10-04 entry in
[dismissed-and-deferred](dismissed-and-deferred.md), which already refused
integration.

**What was checked here.** The package's
`package_info/Mesh_smoothing_3/license.txt` on CGAL `master` lists
`GPL (v3 or later)` and `MIT/X11 (BSD like)`, and its description reads "tools
for improving 3D meshes by iteratively relocating vertices". The briefing also
reports that without a commercial license the package is GPLv3+, that the
reference implementation is GPL-3.0, and that it is scheduled for CGAL 6.3
after an October 1 announcement. None of those three points was verified
here. GPL-encumbered stays the working assumption.

**A tension to resolve before any experiment.** The 2026-10-04 reading of
`package_info` was that the package targets **volumetric** (tetrahedral)
meshes, while ScrolIQ's sheets are surface/TIFXYZ meshes. A ScrolIQ experiment
would therefore be a clean-room *transfer* of the principle (fixed
connectivity, conformal-distortion objective, inversion barrier, projection
onto a constraint) to surfaces. It would not be a re-implementation of what
CGAL ships, and CGAL's results do not carry over as evidence.

**Smallest clean-room experiment** (not preregistered; written without
reading CGAL or reference-implementation source):

1. Freeze already-validated surfaces; pin their hashes.
2. Plant poor aspect ratios and near-inverted elements with connectivity
   unchanged.
3. Optimize vertex positions only, constrained to CT-derived tangent/support,
   with a displacement bound taken from independently estimated CT
   localization uncertainty, never from the current mesh.
4. Measure inversions, condition/aspect metrics, displacement from
   CT-supported papyrus, winding identity (`scroliq-winding-conservation`),
   patch-cycle consistency, and downstream flattening distortion. Ink never
   enters the objective.

**Promotion:** better conditioning with sheet identity unchanged and every
vertex within its CT uncertainty. The proof gate this strengthens is
*connectivity-preserving geometric conditioning*. The main risk is
hallucinated geometry: smoothing can "beautify" a poorly supported sheet. The
oracle must be CT support, not the mesh itself.

## 3. SPECTRE (CT foundation model) — re-check

**Decision: DISMISS for checkpoint incorporation (unchanged).** As relayed,
packaging improved (CLI, Transformers loading, nnU-Net integration), but the
code is MIT while the pretrained weights remain CC-BY-NC-SA with inherited
dataset restrictions. Packaging is not a capability change. Reconsider only
with permissive weights and a Vesuvius-specific held-out result.

## 4. Self-supervised CT denoising / Deep Pseudo-Proximal Map — re-check

**Decision: WATCH, not preprocessing adoption.** Neither offers a
permissively licensed, Vesuvius-relevant implementation with evidence. The
failure mode is specific to this problem: a denoiser can improve
conventional image-quality metrics while suppressing the micro-morphology
that carries carbon-ink signal. Reconsider only with raw projections in scope
and a physically independent ink benchmark (for example the
[NIST control](../../artifacts/2026-10-04-nist-model-scroll/README.md)).

## Process note

License review comes before technical enthusiasm. Both decisions that changed
today did so because of licensing or ancestry, not because of method quality.
