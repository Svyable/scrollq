# Grand Prize ML release gate

`scroliq-model-release` is the pre-submission release gate for trained-model
artifacts. It exists because model provenance is much easier to make public and
auditable at each training stage than to reconstruct after a successful
full-scroll run.

The gate is deliberately narrower than `scroliq-provenance`: it validates the
**public release chain** for datasets, checkpoints, and experiment runs. The
final provenance graph then binds an accepted model release to the exact
eligible CT, prediction regions, held-out evidence, column renders, and reviewer
package.

## What it enforces

A release is blocked unless:

- the release itself is marked public and pins a public code repository plus an
  immutable 40-hex commit;
- every dataset has an immutable SHA-256, a public URL, and
  `CC-BY-NC-4.0`;
- every checkpoint has an immutable SHA-256 and public URL;
- when pseudo-labeling or iterative labeling is used, **every checkpoint** is
  also released under `CC-BY-NC-4.0`;
- pseudo-label / iterative-label datasets identify the checkpoint that produced
  them;
- every checkpoint identifies its training datasets and parent checkpoints;
- exactly one final checkpoint is named;
- every checkpoint has a public training run;
- the final checkpoint, and every checkpoint that produced pseudo-labels, has a
  public inference run;
- every stochastic run records a fixed integer seed;
- by default, every dataset/checkpoint path is present locally and hashes to the
  declared SHA-256.

The machine-readable contract is `models/release.schema.json`. The Python
validator performs the cross-record checks that JSON Schema alone cannot.

## Example

```json
{
  "schema_version": 1,
  "id": "ink-v3-public-release",
  "visibility": "public",
  "code": {
    "repository": "https://github.com/Svyable/scrollq",
    "commit": "0123456789abcdef0123456789abcdef01234567"
  },
  "pseudo_labeling": true,
  "datasets": [
    {
      "id": "ink-train-stage0",
      "role": "training",
      "public_url": "https://example.org/releases/ink-train-stage0.tar.zst",
      "license": "CC-BY-NC-4.0",
      "sha256": "<64 hex>",
      "path": "release/ink-train-stage0.tar.zst"
    },
    {
      "id": "ink-pseudo-stage1",
      "role": "pseudo-label",
      "public_url": "https://example.org/releases/ink-pseudo-stage1.tar.zst",
      "license": "CC-BY-NC-4.0",
      "sha256": "<64 hex>",
      "path": "release/ink-pseudo-stage1.tar.zst",
      "producer_checkpoint_id": "ink-stage0"
    }
  ],
  "checkpoints": [
    {
      "id": "ink-stage0",
      "role": "intermediate",
      "stage": 0,
      "public_url": "https://example.org/releases/ink-stage0.ckpt",
      "license": "CC-BY-NC-4.0",
      "sha256": "<64 hex>",
      "path": "release/ink-stage0.ckpt",
      "training_dataset_ids": ["ink-train-stage0"],
      "parent_checkpoint_ids": []
    },
    {
      "id": "ink-final",
      "role": "final",
      "stage": 1,
      "public_url": "https://example.org/releases/ink-final.ckpt",
      "license": "CC-BY-NC-4.0",
      "sha256": "<64 hex>",
      "path": "release/ink-final.ckpt",
      "training_dataset_ids": ["ink-train-stage0", "ink-pseudo-stage1"],
      "parent_checkpoint_ids": ["ink-stage0"]
    }
  ],
  "final_checkpoint_id": "ink-final",
  "runs": [
    {
      "id": "train-stage0",
      "kind": "training",
      "checkpoint_id": "ink-stage0",
      "public_url": "https://wandb.ai/example/train-stage0",
      "public": true,
      "stochastic": true,
      "random_seed": 17
    },
    {
      "id": "infer-pseudo-stage1",
      "kind": "inference",
      "checkpoint_id": "ink-stage0",
      "public_url": "https://wandb.ai/example/infer-pseudo-stage1",
      "public": true,
      "stochastic": false
    },
    {
      "id": "train-final",
      "kind": "training",
      "checkpoint_id": "ink-final",
      "public_url": "https://wandb.ai/example/train-final",
      "public": true,
      "stochastic": true,
      "random_seed": 17
    },
    {
      "id": "infer-final",
      "kind": "inference",
      "checkpoint_id": "ink-final",
      "public_url": "https://wandb.ai/example/infer-final",
      "public": true,
      "stochastic": false
    }
  ]
}
```

Run the byte-verifying gate from the directory containing the release artifacts:

```bash
scroliq-model-release \
  --manifest release/model-release.json \
  --root . \
  --out release/model-release.validation.json
```

For early planning only, `--metadata-only` validates the release graph without
requiring local artifact bytes. A metadata-only pass is **not** a substitute for
the byte-verifying gate used before submission.

## Relationship to embargoed discoveries

Generic training data, models, code, and experiment records that the prize
rules require to be public should be published independently of any embargoed
qualifying text discovery. Reviewer-facing renders, deciphered text, and other
submission-sensitive outputs belong under the private submission workflow
described in `EMBARGO.md`, not under `docs/` or committed `artifacts/`.

The official prize rules remain authoritative; this gate intentionally fails
closed on the subset that can be checked mechanically.
