# October 2026 Vesuvius Progress Prize — form-specific preflight (NOT SUBMITTED)

Checked against the [official October form](https://docs.google.com/forms/d/e/1FAIpQLSc4flEfgK2nyjoczz2_U_XrIGMlgrnSknWatLqrFPnbtKfZwg/viewform) and [current prize rules](https://scrollprize.org/prizes) on 2026-10-13. Deadline: **2026-10-31 23:59 Pacific**. The Progress Prize is distinct from the 2027 Grand Prize and First Letters prizes. The $20,000 monthly best-submission award is competitive, not a payment for submitting.

**Submission gate:** No form has been submitted. Applicant identity, Discord name, team/rights attribution, terms acceptance and final factual review remain for the applicant. The form's agreement checkbox is a legal commitment and must not be checked autonomously.

## Exact form fields and prepared answers

**Email (required):** Applicant to supply. Do not infer from GitHub.

**Your full name (required):** Applicant to confirm public legal/submission identity; the repository's `pyproject.toml` lists author “Sven,” but that alone is not proof of sole authorship or prize entitlement.

**Team description (required):** Applicant to verify individual/team status and contributors before asserting any ownership or prize split. Suggested structure: “Submission lead: [confirmed identity]. Contributions by others: [verified names/roles or none].”

**Discord display name (optional):** Applicant to supply if applicable. Do not claim membership without evidence.

**URL of open-source/public contribution (required):**
- https://github.com/Svyable/scrollq
- https://github.com/Svyable/scrollq/blob/main/docs/SUBMISSION.md
- https://svyable.github.io/scrollq/progress.html

**What is your contribution? (required; applicant-review draft):**

> ScrolIQ is an MIT-licensed, reproducible diagnostic and evidence layer for the Vesuvius Challenge's virtual-unwrapping workflow. This submission focuses on public PHercParis4 winding annotations and VC3D fibers, with an independent PHerc0139 fiber replication. It is not a claim to have read new letters or unrolled a whole scroll.
>
> The practical bottleneck is deciding which winding, fiber and mesh evidence can be trusted and which exact points should be reviewed before using them downstream. ScrolIQ reads community-native inputs, records source hashes and format provenance, identifies potential winding inconsistencies and fiber discontinuities, and exports findings as VC3D-loadable review queues. Evidence is bound to its source CT/mesh/model/region when a binding can be established; missing or mismatched bindings remain unknown rather than being promoted to positive results.
>
> On published PHercParis4 annotations, the winding attachment run attached 2,111 of 2,232 points and flagged 6 of 16,074 constraints. A deliberately corrupted +2 winding control detected 194 of 200 injected errors. A separate audit covered all 136 fibers listed in the PHercParis4 public directory at the frozen census date, identifying 388 gap and 519 sharp-turn review candidates, with zero control-point/order mismatches. Independent CT support experiments reported AUC 0.775 for PHercParis4 and 0.760 for PHerc0139 under their preregistered comparisons; wrong-frame or displaced-fiber controls help test whether the signal is specific to the traced geometry.
>
> The contribution is the auditable handoff from independent diagnostic findings to specific reviewable objects in the production VC3D workflow, with negative controls and failure states preserved. The intended benefit is reducing time spent trusting stale or ambiguous evidence and directing manual review toward concrete locations. **We have not measured a downstream increase in legible text, corrected-surface accuracy, or probability of reading a scroll.** That remains the critical empirical next step. Reproduction instructions, committed artifacts, and limitations are linked in the reviewer map.

## Criteria-to-evidence crosswalk

| Official Progress Prize criterion | Existing evidence | Remaining weakness |
|---|---|---|
| Specific Challenge scroll data | PHercParis4 winding and 136-fiber census; PHerc0139 fiber controls in [reviewer map](SUBMISSION.md) | Some public fibers lack declared exact CT-volume identity |
| Clear implementation/demo | [CLI examples](../README.md), [VC3D review queues](review-queues.md), [real-data artifact links](SUBMISSION.md) | No independent judge-run recorded for this particular submission |
| Significant advantage over existing solutions | Source/region binding, fail-closed evidence passport, VC3D-native review queues, negative controls | **No controlled head-to-head downstream improvement** against existing reviewer workflow; do not claim one |
| Documentation/examples | [Reviewer map](SUBMISSION.md), [fiber audit](fiber-audit.md), [reproduction container](grand-prize-container.md) | Some experiments depend on public data hosts and a sizeable compute environment |
| Standard formats / modularity | VC3D PointCollections and vc3d_fiber JSON, TIFXYZ, Zarr/OME-Zarr and JSON CLI contracts | External consumers and adoption need independent confirmation |
| Early open source / community usage | Public MIT repository and dated artifacts | Actual external adoption and community feedback not independently evidenced |

## Evidence checks and precise limitations

- [PHercParis4 fiber census](../artifacts/2026-10-04-fiber-corpus-census/README.md): 136/136 as listed on 2026-10-04; 388 gaps and 519 sharp turns are **review candidates**, not 907 proven defects.
- [PHercParis4 CT support](../artifacts/2026-10-04-paris4-fiber-ct-support-run/README.md): AUC 0.775; volume association is **supported but not declared** by source metadata.
- [PHerc0139 replication](SUBMISSION.md): AUC 0.760; this is physical support evidence, not demonstrated sheet identity or improved unwrapping.
- [Review queues](review-queues.md): actual VC3D-compatible files and commands; no assertion that all flagged findings have been independently corrected.
- [Full reviewer map](SUBMISSION.md): explicitly lists future work separately from measured October evidence.

## Commercial and legal gate

1. Verify the applicant's identity, authorship, contributors and any team prize-sharing arrangement.
2. Reproduce the top real-data artifact links at the exact Git commit intended for submission; do not substitute synthetic examples.
3. Prefer one independent VC3D reviewer who labels a blinded subset of flagged and unflagged locations; measure time-to-review and confirmed defects against a baseline. **Not yet done.**
4. Check the form and rules again on submission day. Current rules emphasize early release, actual community use, demonstrated improvement, clear documentation, standard formats and modular integration.
5. Applicant alone reviews and accepts the form's Terms and Conditions. Awards are discretionary; methods must be open-source under a permissive license to receive a prize; payment details are due within 30 days of announcement.

**Decision:** The form answer is drafted and evidence-linked, but it is **not yet independently demonstrated to outperform existing workflow**. Avoid inventing downstream gains. A short blinded reviewer comparison is the best remaining evidence investment before 2026-10-31.
