# Grand Prize provenance manifest

`scroliq-provenance` validates one machine-readable provenance graph for a 2027 Grand Prize submission. Schema v5 (current) binds the eligible CT to a validated ZPA 1.3 source-attestation artifact and requires an explicit physical/model input contract for every model; v4 added deterministic held-out ink evidence, v3 bound the recto-coverage ledger, and held-out validation introduced in v2 remains required. Manifests with an older `schema_version` are rejected. It is intentionally strict about facts that can be checked mechanically; it does **not** claim that text is legible, that the recto surface is complete, or that a reported metric is sufficient for the prize.

The graph ties each submitted render back through the exact eligible CT volume, a hash-pinned and schema-validated ZPA source attestation, declared full-recto coverage inventory, surface, numbered tifxyz mesh, the model's physical input/preprocessing contract, ink checkpoint, training datasets, training/prediction regions, stochastic seeds, and public experiment runs. Each trained model must also carry public held-out validation evidence: public input and known-ground-truth URLs, an explicit validation region, a public evaluation run, numeric metrics, a hashed results artifact, and a machine-checkable training/validation exclusion proof. The graph also pins the code commit, Docker image digest, Zarr audit manifest digest, package file digests, documented human-input hours, and the full-scroll banner.

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
- the CT URI or ZPA report points at a different volume, the ZPA artifact is missing/tampered/invalid, its integrity is not `PASS`, or its source-attestation declaration differs from the validated report;
- code is not pinned to a public repository, immutable 40-hex commit, permissive license, and digest-pinned Docker image;
- documented human annotation/input exceeds 8 hours;
- a training dataset is not public under CC-BY-NC 4.0;
- pseudo-labeled datasets do not name the released producer checkpoint, or that producer checkpoint is not CC-BY-NC 4.0;
- a same-scroll alternate training source is higher resolution than the eligible scan, or omits the resolution needed to exclude that case;
- a trained model lacks its checkpoint digest, dataset references, physical input contract, hash-pinned public preprocessing profile, stochasticity declaration, required random seed, or public training/inference experiment run;
- a trained model's declared source voxel size does not match the eligible scan, its axes do not match the audited ZPA source axes, `resampling: none` changes voxel size, or its held-out window differs from the submitted model window;
- a trained model lacks public held-out validation against known ground truth, the validation protocol/results are incomplete, or same-volume training and held-out regions overlap;
- the required recto-coverage ledger fails its own accounting checks, pins a different code commit/CT root, or its mesh-ID set differs from the submitted mesh set;
- surfaces, meshes, or renders break lineage to `ct:eligible`;
- a mesh is not named `column_NN.tifxyz`, lacks the low-distortion-isometric flattening declaration, duplicates a column, or—when `--root-dir` is supplied—is not an unpacked TIFXYZ directory whose `meta.json` `target_volume` identifies the exact eligible CT;
- a render does not match its mesh filename stem/column, lacks a 1 cm scale-bar declaration, or is not tied to the pinned code commit;
- training and prediction regions overlap on the same eligible volume;
- the full-scroll banner does not enumerate all submitted renders with column numbers overlaid;
- `--root-dir` is supplied and any package file is missing, escapes the package root, or has the wrong SHA-256.

## Eligible CT source attestation (schema v5)

The `ct_volume.zarr_audit` record now names a package-relative ZPA artifact,
its SHA-256, the exact report root, required `PASS` integrity, and the
source-attestation values expected from that report:

```json
{
  "tool": "zarr-pyramid-audit",
  "path": "evidence/zpa-report.json",
  "sha256": "<artifact sha256>",
  "root": "PHerc0813/volumes/20250821151723.zarr",
  "integrity": "PASS",
  "source_attestation": {
    "algorithm": "zpa-metadata-semantics-v1",
    "state": "PRESENT",
    "metadata_semantics_sha256": "<64 hex>",
    "axes": ["z", "y", "x"]
  }
}
```

With `--root-dir`, ScrolIQ opens that exact artifact. It accepts either a
single ZPA audit report or a ZPA gate report containing exactly one matching
root, validates the embedded report using ZPA's own bundled schema, requires
`integrity: PASS`, and compares the root, semantic metadata digest, evidence
state, algorithm and axes to the provenance declaration.

The ZPA digest binds the parsed metadata semantics that were audited. It is
not represented as a raw CT-payload hash or object-store ETag. Payload/content
evidence remains a separate layer.

## Model physical input contract (schema v5)

Every model declares the physical source it expects and the preprocessing
artifact that turns that source into model input:

```json
{
  "axes": ["z", "y", "x"],
  "source_voxel_size_um": 9.362,
  "model_voxel_size_um": 9.362,
  "resampling": "none",
  "window_voxels_zyx": [17, 64, 64],
  "preprocessing_profile": {
    "public_url": "https://…/preprocessing.json",
    "sha256": "<64 hex>"
  }
}
```

The source voxel size must match ScrolIQ's dated eligible-volume manifest.
The model axes must match the validated ZPA source-attestation axes. When
`resampling` is `none`, model and source voxel sizes must be identical.
When resampling is explicit, both source and model voxel sizes remain visible
and the public hash-pinned preprocessing profile is the reproducible contract
for how the conversion occurs. The held-out ink report's
`model_window_voxels_zyx` must equal the submitted model window, preventing a
different evaluation receptive field from being quietly substituted.

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

Schema v3 (retained in v5) requires a nested `recto_coverage` manifest in the provenance graph. That object is validated by the same `audit_recto_coverage` implementation used by `scroliq-recto-coverage`.

The provenance gate then adds two cross-artifact invariants:

- `recto_coverage.volume_root` must match the exact `ct_volume.uri`;
- the coverage audit's `mesh_ids` must equal the provenance manifest's submitted `meshes` IDs exactly — no uncovered package mesh and no coverage-only phantom mesh.

The coverage manifest's `generated_by.code_commit` must also equal `code.commit`. Because the full nested coverage record participates in `graph_sha256`, its public reference artifact URL/SHA, area accounting, exclusion justification, and mesh bindings are content-locked with the rest of the submission graph.

This still does not prove that the upstream reference inventory found every physical papyrus fragment. It proves that the declared reference inventory is accounted for and cannot silently drift away from the submitted mesh package.

## Held-out validation evidence

Schema v2 introduced held-out validation; v3-v5 retain it and require at least one held-out validation record for every trained model in the manifest. A minimal v5 held-out record looks like:

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
  "code_commit": "<same 40-hex commit as code.commit>",
  "ink_evidence": {
    "tool": "scroliq-ink-validate",
    "model_checkpoint_sha256": "<the submitted model's sha256>",
    "split_id": "public-held-out-1",
    "held_out": true,
    "training_overlap": "none",
    "known_ground_truth": true,
    "ground_truth_source_url": "https://…",
    "model_window_voxels_zyx": [17, 64, 64],
    "control_names": ["normal-plus-3"],
    "evaluated_arrays_sha256": "<64 hex>",
    "metrics": {"balanced_accuracy": 0.9, "false_positive_rate": 0.05, "both_classes_present": true}
  }
}
```

`protocol` may be `held-out` or `k-fold`; k-fold records must declare `fold_count >= 2`. The validator does not impose a prize-performance threshold on the metric names or values. It verifies that numeric results exist, that the evidence is public and tied to the pinned code commit, and that any same-volume training and validation boxes are disjoint.

### Deterministic ink evidence (retained from schema v4)

Every held-out validation must carry an `ink_evidence` object produced by
`scroliq-ink-validate` (see [ink-validation.md](ink-validation.md)). The
validator fails closed (`GP_INK_EVIDENCE_*` codes) unless:

- `tool` is `scroliq-ink-validate` and `model_checkpoint_sha256` equals the
  submitted model's `sha256`;
- the split is declared held out, with `training_overlap: "none"`, known
  ground truth and a public `ground_truth_source_url`;
- `model_window_voxels_zyx` is a positive integer `[z, y, x]` window, so the
  hallucination risk of large windows is visible;
- at least one uniquely named falsification control is listed;
- `evaluated_arrays_sha256` pins the exact arrays evaluated;
- `metrics` include `balanced_accuracy`, `false_positive_rate` and
  `both_classes_present: true`.

With `--root-dir`, the validator also opens the `scroliq-ink-validate` report
at the record's `path` (it must stay inside the root), requires
`prize_evidence_ready: true`, and fails with `GP_INK_EVIDENCE_MISMATCH` if the
report's split, checkpoint, window, array digest, control names or metrics
differ from the manifest. Like the rest of the gate, this checks that the
evidence is complete and consistent; it sets no performance threshold.

## Package digests, including TIFXYZ directories

The Grand Prize mesh artifact is normally a directory-format TIFXYZ surface
(`column_NN.tifxyz/meta.json` plus `x.tif`, `y.tif`, and `z.tif`), not a
single regular file. Schema v5 accepts both regular files and directories for package paths.

Generate the manifest digest with:

```bash
scroliq-hash submission/column_01.tifxyz submission/column_01.tif submission/banner.tif
```

Regular files use the ordinary SHA-256 of their bytes. Directories use the
versioned `scroliq-directory-sha256-v1` tree digest: entries are sorted by
relative POSIX path; directories and files are tagged separately; each file
contributes its relative path, byte length, and ordinary SHA-256. Symlinks and
special filesystem entries are rejected. This makes the digest independent of
directory enumeration order while binding every file in the TIFXYZ surface.

When `--root-dir` is supplied, `scroliq-provenance` recomputes the same
digest directly from the unpacked submission directory and fails on any missing
or tampered content inside a declared TIFXYZ path.

For every unpacked TIFXYZ mesh, the local package gate also opens `meta.json` and records a `mesh_context_proofs` entry. The mesh must declare `format: "tifxyz"`, a positive finite 2D `scale`, and a VC3D `target_volume` containing the exact prize-eligible volume ID. A contradictory `scroll_source` is also rejected. These fields are evidence carried by the mesh itself, not inferred from the submission filename. This directly catches a column copied from another scan even if its manifest IDs and package filename were edited to look correct.

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
