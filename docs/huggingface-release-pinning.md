# Immutable Hugging Face release pinning

`scroliq-hf-pin` converts a moving Hugging Face revision such as `main`
into an immutable repository commit plus a deterministic file inventory. It is
intended for external model and dataset evidence that will later feed
`scroliq-model-release`, `scroliq-eval`, or a Grand Prize provenance graph.

A Hub repository URL by itself is not a reproducibility anchor: `main` can
change after a campaign. Pin it before evaluation:

```bash
scroliq-hf-pin \
  --repo YoussefMoNader/ink-8um-v8in \
  --repo-type model \
  --revision main \
  --require-public \
  --require-file README.md \
  --out evidence/v8in.hf-pin.json
```

The report records the requested revision, the resolved 40-hex Hub repository
SHA, an immutable tree URL, the exact file inventory returned for that revision,
sizes and Git blob ids when exposed, and Git-LFS content SHA-256 values when the
Hub explicitly provides them.

## Fail-closed file requirements

Use `--require-public` for prize-release inputs; the command then fails when
the Hub reports the repository as private.

Use `--require-file PATH` when a campaign depends on a particular checkpoint,
script, config or manifest. The command fails if that path is absent.

Use `--require-sha256 PATH` when the campaign requires the Hub itself to expose
a 64-hex content SHA-256 for that file:

```bash
scroliq-hf-pin \
  --repo owner/model \
  --repo-type model \
  --require-file model.pt \
  --require-sha256 model.pt \
  --out evidence/model.hf-pin.json
```

If the Hub does not expose a content SHA-256, the command fails rather than
pretending a Git blob id or storage-system identifier is a file SHA-256. Download
the immutable file and hash its bytes with `scroliq-hash` instead.

## What a pin does not prove

A repository pin proves which Hub tree was observed. It does not prove that the
artifact is scientifically valid, prize-eligible, correctly licensed, free from
training/evaluation leakage, or produced by the declared experiment. Those are
separate gates.

For Grand Prize ML use, the intended chain is:

```text
scroliq-hf-pin
  -> local byte hashes / immutable external artifact identities
  -> scroliq-model-release
  -> scroliq-ink-validate + scroliq-eval
  -> scroliq-provenance
```

Keep the generated pin in a new dated evidence directory. Never rewrite an old
pin after the external repository changes; resolve the new revision into a new
artifact instead.
