# Independent winding validation

**scroliq-winding-validate** evaluates a winding solver against a frozen,
independently established sparse set of physical turn relationships. It is
designed for the failure that ordinary mesh metrics miss: a locally plausible
surface or component that has been assigned to the neighbouring wrap.

The metric is deliberately pairwise. A solver is not penalized for choosing a
different arbitrary global turn-zero label. Each held-out relation instead
defines the physical quantity:

    delta_turns = turn(b) - turn(a)

The candidate reports its predicted value for that same relationship. The
evaluator records the signed integer error.

## Why this is separate from ray-order review

**scroliq-winding** can find suspicious annotation order around an umbilicus,
but a ray-order inversion is only a review cue: crushed or folded papyrus can
legitimately violate radial order. It is not independent truth.

Likewise, a candidate segmentation cannot grade its own winding assignment by
asking which neighbouring surface in that segmentation is closest. Such a test
can be useful diagnostically, but its reference inherits the same segmentation
errors the winding method is supposed to detect.

This validator therefore requires a separate reference artifact whose SHA-256
is frozen before candidate inference and whose author explicitly records that
candidate output was not observed before the freeze.

## Frozen specification

Schema v1 requires the exact volume root, base-voxel XYZ coordinates for both
endpoints of every sparse relation, signed pairwise turn-delta semantics, a
SHA-256-bound independent reference source, explicit declarations that the
reference was established without candidate output and frozen before candidate
output was observed, an explicit list of any relation IDs allowed to
participate in fitting, and a non-empty held-out target list disjoint from
those fit IDs.

Reference source kinds are intentionally narrow: manual-independent,
physical-ct, external-heldout, or challenge-ground-truth.

Example:

    {
      "schema_version": 1,
      "diagnostic": "winding-validation-spec",
      "status": "frozen-before-prediction",
      "volume_root": "PHercXXXX/volumes/<exact-eligible-volume>.zarr",
      "coordinate_system": "base_voxel_xyz",
      "turn_semantics": "signed_pairwise_delta_turns",
      "reference_evidence": {
        "source_kind": "manual-independent",
        "method": "two-reviewer sparse CT turn relations",
        "source_sha256": "<64-hex>",
        "established_without_candidate_output": true,
        "candidate_output_observed_before_freeze": false
      },
      "fit_relation_ids": ["fit-001"],
      "targets": [
        {
          "id": "hold-001",
          "region_id": "outer-left",
          "a": {
            "id": "anchor-a",
            "xyz": [100.0, 200.0, 300.0]
          },
          "b": {
            "id": "anchor-b",
            "xyz": [105.0, 205.0, 305.0]
          },
          "reference_delta_turns": 1
        }
      ]
    }

Before running the candidate, record the canonical spec hash:

    scroliq-winding-validate \
      --spec winding-validation-spec.json \
      --print-spec-hash

The candidate result must carry that exact hash.

## Candidate result

The evaluator accepts one row per held-out relationship. An ok row contains an
integer predicted_delta_turns. A pipeline may explicitly abstain with
suspended, report that correspondence cannot be established with unscorable,
or record a pipeline failed state. Missing rows are also tracked.

All four non-ok outcomes stay in the full held-out denominator. An algorithm
cannot improve its headline result by dropping hard regions.

Example:

    {
      "schema_version": 1,
      "diagnostic": "winding-validation-predictions",
      "volume_root": "PHercXXXX/volumes/<exact-eligible-volume>.zarr",
      "coordinate_system": "base_voxel_xyz",
      "turn_semantics": "signed_pairwise_delta_turns",
      "spec_sha256": "<hash printed above>",
      "candidate_method": "candidate-winding-solver",
      "candidate_artifact_sha256": "<64-hex>",
      "used_reference_ids": ["fit-001"],
      "predictions": [
        {
          "id": "hold-001",
          "status": "ok",
          "predicted_delta_turns": 0
        }
      ]
    }

Run:

    scroliq-winding-validate \
      --spec winding-validation-spec.json \
      --predictions candidate-winding.json \
      --out winding-validation-report.json

## Reported failure classes

For each scored relationship:

- **exact** — signed turn-separation error is 0.
- **catastrophic-one-wrap-hop** — absolute error is exactly 1 turn.
- **multi-wrap-error** — absolute error is 2 or more turns.

The report includes the signed error histogram, absolute error histogram,
all-target and scored-only exact rates, a scorable rate, separate suspended,
unscorable, failed, and missing counts, and median/max absolute turn error
among scored relationships.

A one-wrap error is called out separately because landing on an adjacent
papyrus turn can remain locally smooth, manifold and visually plausible while
being globally fatal to an unroll.

The command exits 0 only when every held-out relation is present, scorable,
and exact. Any winding error or incomplete target set exits 1. Invalid
provenance, scope, schema, or a changed spec exits 2.

## What this does not prove

A passing sparse validation does not establish full-scroll coverage, local mesh
quality, CT support, flattening quality, ink correctness, or legibility. It
also does not magically prove that the people or external process creating the
reference were independent: ScrolIQ verifies the frozen declaration, hashes,
volume binding and held-out IDs. The campaign must publish enough provenance
for reviewers to trust how the independent relation source was produced.

When candidate component IDs do not intrinsically correspond to the physical
reference endpoints, the adapter that derives each predicted_delta_turns value
should publish that correspondence separately.
