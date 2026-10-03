# Deterministic Grand Prize submission package

`scroliq-package` turns a **passing schema-v6 Grand Prize provenance
manifest** into one reviewer-facing ZIP archive. It is intentionally the last
step after ZPA, mesh/coverage checks, model provenance, held-out ink validation,
render generation and banner generation.

The package index is schema v2. The underlying archive-byte contract remains
`zip-stored-deterministic-v1`.

It does not create missing scientific evidence. If `scroliq-provenance`
would fail on the exact package root, or if required reviewer/reproduction
materials are missing or inconsistent, the archive is not produced.

## Build

Keep the reviewer materials inside the same staging root as the scientific
artifacts. The human-input log is machine-readable so its total can be checked
against `submission.human_input_hours`.

```json
{
  "schema_version": 1,
  "entries": [
    {
      "description": "Manual surface review and correction",
      "hours": 2.5
    }
  ]
}
```

Then build the package:

```bash
scroliq-package build \
  --manifest submission/provenance.json \
  --root-dir submission \
  --methodology METHODOLOGY.md \
  --system-requirements SYSTEM_REQUIREMENTS.md \
  --human-input-log human-input.json \
  --vc3d-workflow VC3D_WORKFLOW.md \
  --false-positive-mitigation FALSE_POSITIVES.md \
  --docker-run-command 'docker run --rm ghcr.io/OWNER/PIPELINE@sha256:<digest> ...' \
  --out PHerc0813-grand-prize.zip
```

The Docker command must invoke the **exact digest-pinned image** already named
by `code.docker_image` in the provenance manifest. A tag such as `:latest`
is rejected even if it points to the same image today.

A successful build prints the archive SHA-256 and writes a companion
`PHerc0813-grand-prize.zip.sha256` file. The builder refuses to overwrite an
existing archive or sidecar, so a frozen package cannot be silently replaced.

## Final reviewer contract

Before writing the ZIP, the builder independently enforces several requirements
that should not be left as prose-only claims:

- mesh and render column numbers must be exactly `1..N`, with no skipped
  number and the same sequence on both sides;
- the human-input ledger must contain non-negative entries, total no more than
  eight hours, and exactly reconcile to the provenance manifest's declared
  `submission.human_input_hours`;
- methodology, system requirements, VC3D workflow, and false-positive
  mitigation files must be non-empty UTF-8 text;
- the reproduction command must contain the exact digest-pinned Docker image
  from the provenance manifest; and
- every reviewer material is SHA-256 bound into the archive.

Those checks produce `_scroliq/reviewer-contract.json`. The contract records
the reviewer-file hashes, Docker image and copy-paste command, human-hours
reconciliation, and final contiguous column sequence.

## Included files

The builder includes only:

- the provenance manifest itself;
- the hash-pinned ZPA report named by `ct_volume.zarr_audit.path`;
- any package-local surface paths declared in `surfaces[]`;
- every submitted `column_NN.tifxyz` mesh, recursively and without
  repacking the directory internally;
- every matching column render and its hash-pinned physical scale-bar proof sidecar;
- every local held-out-validation artifact;
- the full-scroll banner and its hash-pinned render-set proof sidecar;
- methodology and system-requirements documentation;
- the machine-readable human-input log;
- the VC3D reproduction/workflow instructions;
- the false-positive mitigation note;
- the generated provenance validation report;
- the generated reviewer contract; and
- the generated package index.

Unrelated files sitting in the staging directory are deliberately excluded.

## Verify

```bash
scroliq-package verify PHerc0813-grand-prize.zip
```

Verification is self-contained. It does not need the original staging
directory. It checks that:

- the package index exists and uses the supported contract;
- no archive member is duplicated, missing or unindexed;
- every indexed member has the expected byte length and SHA-256;
- the embedded provenance manifest SHA-256 matches the package index;
- the embedded provenance validation report is parseable and says
  `eligible: true`;
- the graph SHA-256 in the validation report matches the package index;
- the embedded reviewer contract and all five reviewer materials match their
  recorded hashes;
- reviewer human-hours accounting is internally consistent and no more than
  eight hours;
- the reviewer Docker command uses its digest-pinned image;
- the archived mesh/render columns form one contiguous sequence starting at
  column 1; and
- every archive member uses lexicographic ordering plus the deterministic
  storage, timestamp, and POSIX file-mode contract.

## Archive contract v1 / package index schema v2

The archive format identifier is `zip-stored-deterministic-v1`.

Members are written in lexicographic path order with:

- `ZIP_STORED` rather than Deflate;
- timestamp `1980-01-01 00:00:00`;
- fixed POSIX regular-file mode `0644`;
- no symlinks or special filesystem entries; and
- no implicit directory entries.

Using stored members avoids zlib-version and compression-level differences and
does not waste CPU recompressing TIFF imagery that is commonly compressed
already. Building twice from identical bytes and the same manifest and reviewer
materials produces the same ZIP bytes and therefore the same archive SHA-256.

The generated `_scroliq/submission-package.json` contains a SHA-256 and byte
length for every archived file other than the index itself, plus the
provenance-manifest SHA-256, canonical provenance graph SHA-256, and reviewer
contract SHA-256. `_scroliq/provenance.validation.json` is the exact
fail-closed provenance result generated immediately before packaging.

## Safety and scope

Package-relative paths are required to remain under `--root-dir`. User
artifacts may not use the reserved top-level `_scroliq/` namespace.
Symlinks are rejected both for declared files and anywhere inside declared
directories such as TIFXYZ surfaces.

The reviewer contract proves that required evidence and reproduction
instructions are present, hashed, mutually consistent, and packaged. It does
**not** prove that the methodology is scientifically sufficient, that the VC3D
workflow is seamless in practice, that text is legible, or that the underlying
reconstruction is correct. Those claims remain bound to the empirical evidence
referenced by the provenance graph.
