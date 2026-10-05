# 2026-10-05 — Spiral baseline cloud execution manifest

`cloud_execution_manifest.json` freezes how the PHerc0826 bounded Spiral
reproduction will be executed on one NVIDIA L4. The recipe in
`../2026-10-03-spiral-baseline-target/` still defines what runs; it is bound
here by sha256, and `scroliq-spiral-cloud check` rejects any change to its
contract.

Runbook and rationale: [`docs/spiral-cloud-execution.md`](../../docs/spiral-cloud-execution.md).

## Pinned before any VM existed (read 2026-10-05)

| input | size | sha256 | source |
|---|---:|---|---|
| umbilicus `20250821151701-umbilicus-20260808113303.json` | 3,870 B | `fc9c54cdc0ea7f0e…` | open bucket `PHerc0826/representations/umbilicus/` |
| expected `spiral-scroll.json` | 240 B | `7e4234bb90eefde9…` | assembler @96d4f61 `scroll_spec`, 9.362 µm from the umbilicus metadata |
| `PHerc0826.lasagna.json` | 717 B | `183b9a0c936272b8…` | open bucket, Lasagna run `20250821151701-lasagna-20260419180421` |
| `.zattrs` / `.zgroup` / `2/.zarray` × nx, ny, grad_mag | — | in manifest | same run; group 2 scale = [4, 4, 4] = `lasagna_scale` |
| tracks DBM | 5,422,211,072 B | recorded at staging | size from the sidecar `db_signature` quoted by the assembler README |

All three group-2 arrays are uint8 `[4230, 2043, 2043]`, chunks `32³`, blosc/lz4.
That puts the dense size at 16.44 GiB each and 49.33 GiB in total, which the
storage budget uses as an upper bound for both the download and the resident
pools.

The public store names (`PHerc0826_nx.ome.zarr`, …) differ from villa's
conventional inputs (`lasagna_inputs/las_008_nx.ome.zarr`, …), which are what
`scroliq-spiral-preflight` checks. Staging renames them, and the manifest records
the mapping.

## Deliberately unresolved

`gcp.project`, `gcp.zone`, `gcp.image.name`, `gcp.evidence_bucket.name`,
`software.scrollq.commit`, `software.uv.version` and
`software.uv.linux_x86_64_tarball_sha256` are `null`. They are supplied to
`scroliq-spiral-cloud plan` at launch and recorded in its output. They are
never guessed.

## Estimates, labeled as such

The villa environment, uv cache, villa fit cache, run outputs and TIFXYZ sizes
are estimates; the manifest says which numbers are exact, upper bounds or
estimates. Stage 1 records the real villa freeze, and stage 3 records the real
Lasagna bytes and pool sizes.
