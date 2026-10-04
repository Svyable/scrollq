# Blind controls — sealed-truth timing

**Status:** contract and tooling implemented 2026-10-04; **no blind run has been performed and no benchmark volume has been acquired.** The first registered benchmark ([NIST synthetic carbonized scroll](../artifacts/2026-10-04-nist-model-scroll/README.md)) is deliberately *unpinned*: its DOI, license evidence and byte inventory are not yet recorded, and `scroliq-blind-control` refuses to commit predictions against it until they are.

A blind control is only as credible as the order of events around it. The
prediction has to be fixed *before* the truth is visible, and the truth shown
afterwards has to be the truth that was sealed. `scroliq-blind-control` records
that order as a chain of create-only JSON artifacts, and `scroliq-passport`
carries the result as a `blind_control` stage.

It records **ordering and custody only**. It produces no detection or surface
score, and it does not make a control result evidence for any ancient-papyrus
claim.

## Truth roles

Every truth item in a benchmark manifest declares a role and an explicit
`training_eligible` flag. Nothing defaults.

| role | visible while building? | may tune thresholds/models? | rule |
|---|---|---|---|
| `development_truth` | yes | yes | listed in the commitment if used (`development_truth_used`) |
| `sealed_truth` | no — hidden until the prediction commitment exists | no | always `training_eligible: false`; a benchmark with any sealed truth is evaluation-only (`manifest.training_eligible` must be `false`) |

`assess_manifest` is the normative contract. It rejects unknown keys,
missing flags, a sealed item marked trainable, a trainable benchmark that
holds sealed truth, duplicate ids, a malformed DOI, a license marked `verified`
without evidence, and a seal commitment with nothing to seal. A manifest that is
well-formed but not yet acquired is *valid and unpinned*, never silently
accepted as ready.

`pin_status` is `pinned` only when the DOI is recorded, the license is
`verified` with an `evidence_url`, and an acquired-bytes `inventory` is present.
`ready_for_commit` additionally needs `seal_status: sealed`.

## Lifecycle

```bash
# 0. After downloading the CT yourself, hash exactly what you downloaded.
scroliq-blind-control inventory --root /data/ct --out out/inventory.json
#    Copy file_count / total_bytes / tree_sha256 into a NEW dated manifest,
#    with the DOI and the license evidence URL you actually read.
scroliq-blind-control validate --manifest M.json --require-pinned

# 1. Seal. The salt is private; the seal and sealed manifest are public.
scroliq-blind-control seal --manifest M.json --truth-root /secure/truth \
  --seal-out out/seal.json --manifest-out out/M.sealed.json \
  --salt-out /secure/salt.txt            # mode 0600; never commit it

# 2. Run the pipeline *without* the truth, then commit what it produced.
scroliq-blind-control commit --manifest out/M.sealed.json \
  --predictions out/predictions --detector-spec detector-spec.json \
  --pipeline-id geometry-v0 --out out/commitment.json

# 3. Bind the commitment file to a record someone else can observe.
git add out/commitment.json && git commit -m "Commit predictions" && git push
scroliq-blind-control anchor --commitment out/commitment.json \
  --git-repo . --out out/anchor.json

# 4. Reveal. Refuses (and writes nothing) unless the predictions are
#    byte-identical to the commitment and the truth matches the seal.
scroliq-blind-control reveal --manifest out/M.sealed.json \
  --commitment out/commitment.json --predictions out/predictions \
  --truth-root /secure/truth --salt-file /secure/salt.txt \
  --attested-by "Name" --attest-truth-unseen --out out/reveal.json

# 5. Verdict from the recorded chain, then attach it to the passport.
scroliq-blind-control report --manifest out/M.sealed.json \
  --commitment out/commitment.json --reveal out/reveal.json \
  --anchor out/anchor.json --out out/blind-control-report.json
scroliq-passport ... --blind-control out/blind-control-report.json
```

Every write is create-only; an existing file is never replaced. `reveal`
re-hashes the predictions **before** it reads a single truth byte, so a changed
prediction set never gets the truth opened.

For a passport on a benchmark volume that is not a volcomp scan, pass a stub
row such as `{"root": "<manifest volume.id>", "ok": false, "error": "not a
volcomp volume; scan-health score not applicable"}` as `--volumes`. The
`blind_control` stage binds to the exact `volume.id`, like the other stages.

## Verdicts

| verdict | meaning | passport status |
|---|---|---|
| `sealed-order-anchored` | every check passes, the commitment is bound to an anchor that precedes the reveal, and custody is attested | `measured` |
| `sealed-order-self-asserted` | every hard check passes, but ordering rests on the author's own clock and/or custody is unattested (`weaknesses` says which) | `partial` |
| `awaiting-reveal` | committed, truth not yet visible | `partial` |
| `not-blind` | a violation (`violations` lists them): digest mismatch, other manifest or seal, predictions moved, or truth visible no later than the commitment | `blocked` |

The passport does not trust the verdict string. It re-derives the ordering from
the recorded timestamps and blocks a report whose verdict says "anchored" but
whose timing, anchor evidence or custody flag does not.

## What this does and does not prove

- **A hash fixes content, not time.** The time on a commitment is only as good as
  the clock that wrote it. That is why the verdict is split: without an anchor
  the order is *self-asserted*.
- **An anchor is third-party-observable, not tool-verified time.** For
  `git-commit` the tool verifies that the commitment file's bytes equal the
  committed blob. It cannot verify the commit date (author-controlled until a
  remote observes the push) or that the commit was published; both are listed in
  the anchor's `not_verified_by_tool`. An `external` anchor (e.g. an RFC 3161
  token) is recorded as declared; the tool verifies nothing about it. A reviewer
  checks the push time or the token.
- **Custody is an attestation, not a measurement.** `--attest-truth-unseen`
  records a named person attesting a fixed sentence. The tool cannot know whether
  anyone saw the truth earlier.
- **`development_truth_used` is a declaration.** The tool rejects naming a sealed
  item or an undeclared one there; it cannot know what the author actually looked
  at.
- **One commitment cannot prove geometry was frozen before the detector output
  was looked at.** If that ordering matters, commit the geometry on its own first
  and treat the detector run as a later, separate commitment. That two-step
  chain is not implemented.
- The seal is salted and publishes only item ids, so it neither leaks truth nor
  membership hashes, and it is bound to the acquired-bytes digest, so truth cannot
  be quietly paired with different CT.

### Relationship to existing machinery

This is **not** the generic prediction-hashing layer that
[was dismissed](research/dismissed-and-deferred.md#generic-prediction-hashing-for-ink).
For ink, exact evaluated-array identity stays with `scroliq-ink-validate`; the
commitment here reuses the existing `scroliq-hash` tree digest and adds only what
nothing else records — *when truth became visible relative to the prediction*.
`scroliq-segmentation-validate` also seals truth with a salted commitment, but it
commits to truth only and records no ordering against a prediction.

## First experiment: end-to-end blind reconstruction (draft protocol)

Goal: a physical positive control for
measured CT → segmentation → surface → flattening → rendering → ink localization,
where the writing existed on the physical object before tomography.

1. **Acquire and pin.** Download the volume, run `inventory`, record the DOI and
   the license evidence actually read, in a new dated manifest. Reconcile
   `volume.claimed` against the acquired bytes. Only the slice count is
   cross-checked automatically (a mismatch is a manifest warning); bit depth and
   voxel size must be checked by hand from the TIFF headers and the source's own
   metadata before they are treated as facts.
2. **Seal.** The custodian seals the known text and letter locations. Nobody
   building the pipeline holds the truth or the salt.
3. **Recover a surface without the text.** Run the current geometry pipeline.
   Geometry selection stays ink-blind (see
   [flattening selection](research/dismissed-and-deferred.md#selecting-flattening-by-ink-persistence-or-readability)).
4. **Render and detect.** Apply a deliberately simple, fixed intensity detector.
   Its definition, the primary metric, the pass/fail rule and every constant are
   written into the detector spec **before** the commitment; the spec's hash is
   part of the commitment, which is what freezes them. This document chooses none
   of those constants, because they depend on acquired data and a truth format
   that have not been seen.
5. **Commit, anchor, reveal, report** as above.
6. **Score** the revealed truth against the committed outputs. The scorer is not
   written yet: it needs the real truth format. It will be a task adapter that
   emits the common `scroliq-eval` region results, and the pass/fail rule it
   applies is the one frozen in step 4.

Any deviation from this plan is logged next to the run, not edited into it, and a
failed control is reported with the same prominence as a passed one.

### Claim limits (carried in every report)

- Evaluation-only: no training, tuning, threshold selection or early stopping may
  use this volume or its truth.
- Success is **not** validation of carbon-ink detection on ancient papyrus. The
  specimen differs in acquisition, resolution and ink chemistry, and lead supplies
  genuine absorption contrast.
- Success is not evidence that any Herculaneum model works; it shows only that the
  pipeline and proof machinery can recover a real hidden signal without
  manufacturing it.
