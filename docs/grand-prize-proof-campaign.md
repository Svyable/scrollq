# Grand Prize proof campaign

**Status:** strategy protocol, not a result. Set 2026-10-02.

ScrolIQ's next objective is not another diagnostic family. It is to use the existing evidence system to produce one prize-relevant result that survives independent reproduction on one **exact 2027 Grand Prize volume**.

The 2027 Grand Prize still requires the whole eligible scroll surface to be unrolled, readable column renders, VC3D integration, reproducibility, train/prediction separation, and held-out validation. This campaign is the bridge from ScrolIQ's QA work to that deliverable.

## Competitive thesis

The community already has strong tools for individual jobs: TIFXYZ integrity and repair, self-intersection detection, spiral-fit evaluation, scan-quality analysis, data auditing, and ink validation. ScrolIQ should not claim those underlying ideas as unique.

The differentiated claim is the evidence contract across them:

> ScrolIQ makes independently produced evidence composable and submission-grade: every result is bound to the exact CT, mesh, model, checkpoint, and evaluation region it measures; cross-volume or stale evidence is excluded; leakage and missing evidence fail closed; and negative controls remain negative results rather than being upgraded into confidence.

That is a system claim, not an algorithm-novelty claim.

Useful prior art to acknowledge explicitly:

- [TIFXYZ Doctor](https://github.com/aviad12g/tifxyz-doctor)
- [tifxyz-repair](https://github.com/Nieuwlaar/tifxyz-repair)
- [windcheck](https://github.com/joe-carr-data/windcheck)
- [spiralcheck](https://github.com/Nicodol/spiralcheck)
- [scroll-data-audit](https://github.com/Bullo27/scroll-data-audit)
- [gp13-ink-detectability](https://github.com/flummoxjr/gp13-ink-detectability)
- the official [Vesuvius Challenge community-project index](https://scrollprize.org/community_projects)

## Target-selection gate

Do **not** choose the target from the legacy 0-100 scan-health ordering. The preregistered stability-v2 result showed that close ranks are not reliable enough for that.

A target can be frozen only when one exact prize-listed volume has a dated artifact demonstrating all of the following prerequisites:

1. **Exact-volume identity.** The CT root resolves to the official eligible volume ID. No higher-resolution substitute and no other scan of the same scroll.
2. **Input integrity.** ZPA evidence is present and non-UNKNOWN for the inputs actually consumed.
3. **Surface foothold.** At least one usable surface/mesh region exists on that exact volume, with CT support and geometry provenance sufficient to render.
4. **Held-out geometry path.** There is a way to withhold fit evidence by region/constraint and score the resulting prediction without name-level or geometric leakage.
5. **Ink-validation path.** Training and prediction regions can be made spatially disjoint, with an exact checkpoint, seed, evaluated arrays, and falsification controls.
6. **VC3D handoff.** The surface and review points can be opened in the production toolchain without conversion ambiguity.

There is deliberately no blended "best scroll" score. A candidate either clears these prerequisites or stays provisional.

## Minimum proof package

The first competitive proof should be small enough to finish and strong enough to falsify. It is complete only when the repository contains:

- a frozen target manifest naming the exact eligible CT volume;
- a hash-pinned surface/mesh artifact and its ScrolIQ Mesh IQ report;
- independently generated same-byte geometry evidence where an existing public tool is stronger than ScrolIQ;
- a held-out fit evaluation whose withheld region is demonstrably absent from fit inputs;
- a programmatic flattened render generated from that exact CT and mesh;
- an ink experiment manifest with exact checkpoint hash, fixed seed, train/eval boxes, and evaluated-array hashes;
- measured negative controls such as normal offsets, adjacent-winding controls, geometry perturbation, or an independent checkpoint, with missing controls left `partial`;
- a VC3D-loadable review queue for the strongest remaining geometry/fiber/winding uncertainties;
- one evidence passport that binds the above artifacts and rejects any mismatched identity.

The proof is **not** required to be a full Grand Prize submission. Its purpose is to establish that the integrated system produces a measurably better held-out surface/fit/ink result on an exact eligible volume. Full-scroll coverage comes after that result exists.

## Decision rule

Before running the experiment, freeze:

- the target volume ID;
- the held-out region or constraints;
- the primary geometry and/or ink metric;
- the baseline being compared;
- the pass/fail threshold;
- every allowed manual intervention and its logged duration.

A failed gate is a result. Publish it, preserve the artifact, and either change one preregistered variable in a new dated campaign or retarget. Do not rewrite the old campaign.

## Work that should pause

Until the first exact-volume proof package exists, new work should be deprioritized when it merely adds breadth.

In particular, do not add a new "IQ" layer unless it closes a failed gate in the target campaign, produces a reviewer-loadable artifact, or directly improves a held-out result. Prefer one strong comparison on real Grand Prize data over another census.

## Grand Prize transition

Once the proof package shows a real held-out advantage, extend the same contract rather than inventing a new submission format:

1. expand surface coverage toward 100% recto;
2. keep column-scale TIFXYZ meshes traceable to the exact CT;
3. render every column programmatically with scale bars;
4. carry model/checkpoint/train-eval provenance into every ink image;
5. maintain a single full-scroll banner and column mapping;
6. preserve the <=8-hour documented human-input budget;
7. package the complete pipeline in Docker and reproduce it from a clean environment.

The evidence passport then becomes the submission index rather than a separate QA product.
