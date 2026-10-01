# Grand Prize provenance manifest

`scroliq-provenance` validates one machine-readable provenance graph for a 2027 Grand Prize submission. It is intentionally fail-closed for eligibility evidence that can be checked mechanically; it does **not** claim that text is legible or that the recto surface is complete.

The graph ties each submitted render back through the exact eligible CT volume, surface, numbered tifxyz mesh, ink model/checkpoint, training datasets, training/prediction regions, stochastic seeds, public experiment runs, and a pinned held-out ink-validation artifact. It also pins the code commit, Docker image digest, Zarr audit manifest digest, package file digests, documented human-input hours, and the full-scroll banner.

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
  -> held-out known-ground-truth validation + falsification controls
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
- surfaces, meshes, or renders break lineage to `ct:eligible`;
- a mesh is not named `column_NN.tifxyz`, lacks the low-distortion-isometric flattening declaration, or duplicates a column;
- a render does not match its mesh filename stem/column, lacks a 1 cm scale-bar declaration, or is not tied to the pinned code commit;
- training and prediction regions overlap on the same eligible volume;
- held-out ink validation is missing, does not use known ground truth, is not explicitly disjoint from training, lacks a model-window declaration or falsification control, does not match the submitted checkpoint, or lacks balanced-accuracy / false-positive evidence;
- the full-scroll banner does not enumerate all submitted renders with column numbers overlaid;
- `--root-dir` is supplied and any package file is missing, escapes the package root, or has the wrong SHA-256.

## Region leakage semantics

Region sets use half-open level-0 voxel boxes:

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

Coordinates are `[z, y, x]`. A box covers `start <= coordinate < stop`. Boxes that only touch a boundary are disjoint; any positive-volume intersection is an eligibility failure. Training regions on other volumes are non-overlapping by construction, but their dataset source provenance is still checked for prohibited higher-resolution data from the submitted scroll.

This deliberately uses a simple coordinate primitive that can be independently reimplemented. More complex masks can be conservatively covered by boxes until a future schema version adds hashed sparse masks/polygons.

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

The official rules remain authoritative. This validator captures machine-checkable provenance/eligibility requirements and now requires a pinned `scroliq-ink-validate` artifact for held-out known-ground-truth testing and false-positive controls. Papyrological legibility and complete recto coverage still require separate evidence.


## Held-out ink evidence (schema 2)

Schema 2 requires an `ink_validation` record that pins the output of `scroliq-ink-validate`. The manifest duplicates the critical fields so the graph can be checked even without the package directory: model/checkpoint, held-out split id, explicit no-overlap declaration, public known-ground-truth source, model window, falsification-control names, exact evaluated-array digest, balanced accuracy, false-positive rate, and both-class coverage.

When `--root-dir` is supplied, `scroliq-provenance` also hashes and parses the report file and cross-checks those fields against the manifest. A prose claim that validation happened is therefore not enough.
