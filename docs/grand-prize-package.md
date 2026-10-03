# Deterministic Grand Prize submission package

`scroliq-package` turns a **passing schema-v5 Grand Prize provenance
manifest** into one reviewer-facing ZIP archive. It is intentionally the last
step after ZPA, mesh/coverage checks, model provenance, held-out ink validation,
render generation and banner generation.

It does not create missing scientific evidence. If `scroliq-provenance`
would fail on the exact package root, the archive is not produced.

## Build

```bash
scroliq-package build \
  --manifest submission/provenance.json \
  --root-dir submission \
  --out PHerc0813-grand-prize.zip
```

A successful build prints the archive SHA-256 and writes a companion
`PHerc0813-grand-prize.zip.sha256` file.

The builder includes only:

- the provenance manifest itself;
- the hash-pinned ZPA report named by `ct_volume.zarr_audit.path`;
- any package-local surface paths declared in `surfaces[]`;
- every submitted `column_NN.tifxyz` mesh, recursively and without
  repacking the directory internally;
- every matching column render;
- every local held-out-validation artifact;
- the full-scroll banner;
- the generated provenance validation report; and
- a generated package index.

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
- the graph SHA-256 in the validation report matches the package index; and
- every archive member uses the deterministic storage/timestamp contract.

## Archive contract v1

The archive format identifier is `zip-stored-deterministic-v1`.

Members are written in lexicographic path order with:

- `ZIP_STORED` rather than Deflate;
- timestamp `1980-01-01 00:00:00`;
- fixed POSIX regular-file mode `0644`;
- no symlinks or special filesystem entries; and
- no implicit directory entries.

Using stored members avoids zlib-version and compression-level differences and
does not waste CPU recompressing TIFF imagery that is commonly compressed
already. Building twice from identical bytes and the same manifest produces
the same ZIP bytes and therefore the same archive SHA-256.

The generated `_scroliq/submission-package.json` contains a SHA-256 and byte
length for every archived file other than the index itself, plus the
provenance-manifest SHA-256 and canonical provenance graph SHA-256.
`_scroliq/provenance.validation.json` is the exact fail-closed validation
result generated immediately before packaging.

## Safety and scope

Package-relative paths are required to remain under `--root-dir`. User
artifacts may not use the reserved top-level `_scroliq/` namespace.
Symlinks are rejected both for declared files and anywhere inside declared
directories such as TIFXYZ surfaces.

This is a packaging/reproducibility guarantee, not a claim that text is
legible or that the underlying scientific reconstruction is correct. Those
claims remain bound to the evidence referenced by the provenance graph.
