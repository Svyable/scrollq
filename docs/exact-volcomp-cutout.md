# Exact volcomp cutouts

`scroliq-cutout` extracts a bounded level-0 voxel box from the exact
`dl.ash2txt.org` volcomp Zarr v3 root used by ScrolIQ and ZPA.

The command is intentionally narrow. It exists so geometry and sheetness
experiments can bind a local CT array to the same exact eligible volume whose
metadata passed the ZPA integrity gate, rather than silently switching to a
same-scroll mirror or higher-resolution scan.

```bash
scroliq-cutout \
  --root community-uploads/forrest/volcomp/PHerc0800/volumes/20250521135224-8.640um-1.2m-116keV-masked.zarr \
  --lo 1200,2400,1800 \
  --hi 1233,2433,1833 \
  --out out/probe.npy
```

The output is a NumPy `.npy` array plus a same-stem JSON report. The report
records the exact root, requested and clipped ZYX bounds, chunk/shard counts,
the output SHA-256, and the complete ZPA `zpa-metadata-semantics-v1`
attestation.

## Fail-closed behavior

The reader accepts only the layout ScrolIQ actually knows how to interpret:

- level 0 is a three-dimensional `uint8` Zarr v3 array;
- the outer codec is `sharding_indexed`;
- the inner codec is `volcomp`;
- the shard index is stored at the end;
- the declared fill value is an integer uint8 value;
- a present CRC32C shard index must verify;
- every requested present chunk must read and decode to its declared shape.

A missing shard or inner chunk is not treated as a transport error: Zarr
semantics make it the declared fill value. An ambiguous existence check,
truncated range, malformed/corrupt index, failed decoder call, unsupported
layout, or non-PASS source audit aborts the extraction instead of fabricating
zeros.

The command also refuses to overwrite either the cutout or its JSON report.

## Prize use

For the 2027 Grand Prize pipeline, this is the bridge between exact-volume
provenance and local reconstruction experiments. A campaign can now record:

`eligible volume -> ZPA source attestation -> exact voxel box -> cutout SHA -> sheetness/geometry result`.

That chain does **not** prove that a surface coordinate is correct. Surface
identity, held-out recovery, flattening, ink, and legibility remain separate
evidence.
