# October: close one diagnostic-to-action loop

Working plan, 2026-10-02 UTC (October 1 in Chicago). No new scientific result
or community adoption is claimed here. This coordinates ScrolIQ and its
zarr-pyramid-audit companion without duplicating their responsibilities.

## Submission thesis and work limit

Lead with one demonstrable use: **help a reviewer identify and locate a real
surface failure before it enters unwrapping**. Zarr supplies input integrity;
ScrolIQ supplies the mesh review queue. O1 (blinded review) and O6 (usable
handoff) are the primary October track. O2–O4 remain exploratory and should
not delay a complete O1 result. O5's failed stability result remains published.

The official [criteria](https://scrollprize.org/prizes#progress-prizes), checked
2026-10-02, favour early availability, actual use, real-data results and useful
diagnosis. The page still named September 30; October's exact deadline is
**unconfirmed**. October 25 is our internal evidence-freeze target, not an
official deadline. Recheck the official page before submitting.

## What already exists; what is missing

The frozen [54-segment sample](../artifacts/2026-10-01-mesh-review-sample/)
already defines the experiment. Do not redraw it, change thresholds or replace
hard-to-load cases. The decision rule remains in
[the original protocol](mesh-review-protocol.md).

Missing evidence: independent labels, screenshot/CT support for confirmed
failures, an observed downstream action, and documented external use. Tests,
downloads, generated packets and our own runs do not establish adoption.

| Stage | Required evidence | Claim permitted |
|---|---|---|
| Release | Runnable key-free packet, exact scan references, instructions | Review workflow available |
| Review | Returned labels, reviewer/date/version, exposure disclosure | Review completed, including unclear cases |
| Validate | Frozen-key checksum, calibration, precision intervals, clean defect rate | Only the original rule's verdict |
| Act | Confirmed case with CT coordinates, before/after evidence and actual disposition | That particular diagnostic informed that action |
| Reuse | Consented independent run or public feedback URL | Documented use, not inferred adoption |

## Run the handoff now

From the repository root (standard library only):

```bash
mkdir -p out
python bin/mesh_review_packet.py --out out/mesh-review.zip
# Send only the ZIP to a reviewer after agreeing scope and attribution.
# Save their returned CSV separately; never edit the frozen sample.
python bin/mesh_review_score.py artifacts/2026-10-01-mesh-review-sample \
  --sheet out/returned-review.csv --require-complete --out out/review-result.json
```

ZIP creation refuses overwrite and checks the frozen sheet hash. The packet
contains the CSV and reviewer instructions, never the class key or reports.
The key remains public in the repository, so blinding is procedural.
The scorer rejects duplicate/unknown IDs, altered surface references and
key checksum mismatches. `--require-complete` exits nonzero for incomplete,
invalid or uncalibrated reviews. Preserve labels and input hashes even if
the outcome is negative. An `unclear` label is a completed review response,
not proof of a clean surface.

## Measure usefulness after the blind labels are locked

For each confirmed candidate, record the review ID, exact scan, CT XYZ,
evidence image/log, proposed action and observed disposition (accepted,
rejected, deferred, or not attempted). A diagnosis without an action remains
a diagnosis. Do not automatically repair or discard a mesh.

Compare against the existing manual VC3D workflow and relevant community mesh
checkers on the *same* cases and input versions. Record setup/review time,
load failures and unclear cases. Until a counterbalanced timed study is
pre-registered, these timings are descriptive; do not claim causal speedup.
Do not call the defect fraction in sampled clean meshes a false-negative
rate: mixed segments were excluded, so whole-corpus recall is not measured.
Before claiming superiority over a specific tool, pin and run that comparator.

## Calendar and stop rules

- Oct 1–7: release the packet, obtain permission for reviewer outreach, agree
  one reviewer and access setup. If no reviewer is available by Oct 7, mark
  O1 blocked; do not generate AI labels and call them independent validation.
- Oct 8–14: complete the frozen review; publish failures and unclear cases.
- Oct 15–21: document at least one confirmed case's disposition and attempt
  independent reproduction. This is a target, not an observed result.
- Oct 22–25: assemble a short evaluator walkthrough and immutable commands,
  input hashes, results, limitations and attribution for the actual outcome.
- After Oct 25: fix reproducibility blockers; avoid new feature scope. Verify
  the official deadline and obtain approval before submitting or contacting
  upstream maintainers/community members.

If enrichment fails, report that the present flag has not demonstrated useful
separation. Revise on a development set and reserve a new evaluation sample;
do not tune against these labels and present the same set as held out.
No prize amount or award is guaranteed by this plan.
