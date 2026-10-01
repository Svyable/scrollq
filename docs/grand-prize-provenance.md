# Grand Prize provenance manifest

`scroliq-provenance` validates one machine-readable provenance graph for a 2027 Grand Prize submission. Schema v3 binds the recto-coverage ledger into the fail-closed submission graph; held-out validation introduced in v2 remains required. It is intentionally strict about facts that can be checked mechanically; it does **not** claim that text is legible, that the recto surface is complete, or that a reported metric is sufficient for the prize.

The graph ties each submitted render back through the exact eligible CT volume, declared full-recto coverage inventory, surface, numbered tifxyz mesh, ink model/checkpoint, training datasets, training/prediction regions, stochastic seeds, and public experiment runs. Each trained model must also carry public held-out validation evidence: public input and known-ground-truth URLs, an explicit validation region, a public evaluation run, numeric metrics, a hashed results artifact, and a machine-checkable training/validation exclusion proof. The graph also pins the code commit, Docker image digest, Zarr audit manifest digest, package file digests, documented human-input hours, and the full-scroll banner.

## Usage

```bash
scroliq-provenance \
  --manifest submission/provenance.json \
  --root-dir submission \
  --out submission/provenance.validation.json
```

Exit code 0 means the manifest passed all implemented checks. Exit code 1 means at least one eligibility/provenance invariant failed. Use `--format github` in CI for workflow annotations.

The validator emits two hashes:

- `manifest_sha256`: SHA-256 of the exact JSON file bytes supplied to the CLI.
- `graph_sha256`: SHA-256 of canonical sorted-key JSON, useful as a content lock independent of whitespace.

Each render also gets a `render_chains` record in the validation report so a reviewer can trace:

```text
eligible CT
  -> surface
  -> column_NN.tifxyz
  -> column_NN render
  -> checkpoint
  -> training datasets
  -> training-region exclusion proof
  -> training/inference seeds
  -> public training/inference runs
```

## Fail-closed checks

The current validator rejects a manifest when any of these conditions is not proven:

- the scroll and exact CT volume do not match ScrolIQ's dated Grand Prize target manifest;
- the CT URI or zarr-pyramid-audit provenance points at a different volume;
- code is not pinned to a public repository, immutable 40-hex commit, permissive license, and digest-pinned Docker image;
- documented human annotation/input exceeds 8 hours;
- a training dataset is not public under CC-BY-NC 4.0;
- pseudo-labeled datasets do not name the released producer checkpoint, or that producer checkpoint is not CC-BY-NC 4.0;
- a same-scroll alternate training source is higher resolution than the eligible scan, or omits the resolution needed to exclude that case;
- a trained model lacks its checkpoint digest, dataset references, stochasticity declaration, required random seed, or public training/inference experiment run;
- a trained model lacks public held-out validation against known ground truth, the validation protocol/results are incomplete, or same-volume training and held-out regions overlap;
- the required recto-coverage ledger fails its own accounting checks, pins a different code commit/CT root, or its mesh-ID set differs from the submitted mesh set;
- surfaces, meshes, or renders break lineage to `ct:eligible`;
- a mesh is not named `column_NN.tifxyz`, lacks the low-distortion-isometric flattening declaration, or duplicates a column;
- a render does not match its mesh filename stem/column, lacks a 1 cm scale-bar declaration, or is not tied to the pinned code commit;
- training and prediction regions overlap on the same eligible volume;
- the full-scroll banner does not enumerate all submitted renders with column numbers overlaid;
- `--root-dir` is supplied and any package file is missing, escapes the package root, or has the wrong SHA-256.

## Region leakage semantics

Training, prediction, and held-out validation region sets use half-open level-0 voxel boxes:

```json
{
  "id": "regions:column-01",
  "role": "prediction",
  "volume_id": "20250821151723",
  "coordinate_space": "level0-voxel-index",
  "boxes": [
    {"start": [100, 200, 300], "stop": [200, 400, 600]}
  ]
}
```

Coordinates are `[z, y, x]`. A box covers `start <= coordinate < stop`. Boxes that only touch a boundary are disjoint; any positive-volume intersection is an eligibility failure. Prediction regions use `role: "prediction"`; held-out regions use `role: "validation"`. Training regions on other volumes are non-overlapping by construction, but their dataset source provenance is still checked for prohibited higher-resolution data from the submitted scroll.

This deliberately uses a simple coordinate primitive that can be independently reimplemented. More complex masks can be conservatively covered by boxes until a future schema version adds hashed sparse masks/polygons.

## Recto coverage binding

Schema v3 requires a nested `recto_coverage` manifest in the provenance graph. That object is validated by the same `audit_recto_coverage` implementation used by `scroliq-recto-coverage`.

The provenance gate then adds two cross-artifact invariants:

- `recto_coverage.volume_root` must match the exact `ct_volume.uri`;
- the coverage audit's `mesh_ids` must equal the provenance manifest's submitted `meshes` IDs exactly — no uncovered package mesh and no coverage-only phantom mesh.

The coverage manifest's `generated_by.code_commit` must also equal `code.commit`. Because the full nested coverage record participates in `graph_sha256`, its public reference artifact URL/SHA, area accounting, exclusion justification, and mesh bindings are content-locked with the rest of the submission graph.

This still does not prove that the upstream reference inventory found every physical papyrus fragment. It proves that the declared reference inventory is accounted for and cannot silently drift away from the submitted mesh package.

## Held-out validation evidence

Schema v2 introduced held-out validation; schema v3 retains it and requires at least one held-out validation record for every trained model in the manifest. A minimal record looks like:

```json
{
  "id": "validation:ink-v1",
  "model_id": "model:ink-v1",
  "protocol": "held-out",
  "region_set_id": "regions:held-out",
  "public_input_url": "https://…",
  "ground_truth_url": "https://…",
  "public_url": "https://…/results",
  "path": "validation/held-out-ink-v1.json",
  "sha256": "<64 hex>",
  "metrics": {"precision": 0.91, "recall": 0.87},
  "experiment_run": {"url": "https://wandb.ai/…", "public": true},
  "code_commit": "<same 40-hex commit as code.commit>"
}
```

`protocol` may be `held-out` or `k-fold`; k-fold records must declare `fold_count >= 2`. The validator does not impose a prize-performance threshold on the metric names or values. It verifies that numeric results exist, that the evidence is public and tied to the pinned code commit, and that any same-volume training and validation boxes are disjoint.

## CI gate

A submission pipeline can make the manifest a release gate:

```yaml
- name: Grand Prize provenance gate
  run: |
    scroliq-provenance \
      --manifest submission/provenance.json \
      --root-dir submission \
      --format github \
      --out submission/provenance.validation.json
```

Commit both the manifest and validation report with the submission artifacts. The manifest should be regenerated whenever the CT source, surface, mesh, render, checkpoint, training data, region split, seeds, experiment runs, code commit, Docker image, or package files change.

The official rules remain authoritative. This validator now requires held-out validation evidence and checks its lineage/exclusion invariants, but it does not judge whether the resulting performance is scientifically or papyrologically sufficient. Papyrological legibility, complete recto coverage, and the substantive adequacy of false-positive mitigation still require their own evidence and review.
