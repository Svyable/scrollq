# Geometry-only sheetness protocol planner

`scroliq-sheetness-plan` freezes the **where** of a sheetness experiment before
the Hessian response is computed.

The planner consumes only:

- native TIFXYZ geometry;
- a PASS ZPA report for the exact level-0 CT volume;
- an explicit source-volume token/binding URL;
- a requested sample count;
- explicit signed normal offsets;
- an explicit CT halo.

It never reads CT intensity and never reads a sheetness response.

## Why this exists

Choosing attractive surface locations after looking at a response field would
make the first Vesuvius benchmark difficult to interpret. The planner therefore
selects probes from geometry alone and records the selection rule.

It also refuses to invent a wrong-wrap control. A competing winding must come
from **independent geometry evidence**, because deriving a wrong-wrap point from
the same local sheetness field would contaminate the test of that field.

## Example

For the official PHerc0139 w035 reference used in the Challenge ink tutorial:

```bash
scroliq-sheetness-plan \
  --tifxyz ./20260317000000-on-20250728140407-9.362um.tifxyz \
  --zpa-report out/PHerc0139-20250728140407.zpa.json \
  --volume-root PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr \
  --surface-volume-token 20250728140407 \
  --binding-url https://scrollprize.org/tutorial5 \
  --samples 32 \
  --offsets=-8,-4,4,8 \
  --halo 8 \
  --out campaign/reference-plan.json
```

The offsets above are an **example invocation, not a built-in default**.
Campaign #105 must freeze its actual distances before any response score is
inspected. The command intentionally has no default offsets or halo.

## Surface selection

A TIFXYZ vertex is eligible when:

1. its XYZ coordinate is finite and follows the VC3D `Z > 0` validity
   convention;
2. an optional `mask.tif` keeps it;
3. its immediate grid neighbors are valid, so a centered local normal can be
   estimated;
4. all requested signed normal-offset probes plus the declared halo fit inside
   the audited level-0 CT shape.

For every eligible vertex the planner computes the unit cross product of the
centered TIFXYZ column and row tangents. Normal sign is arbitrary; downstream
comparison uses absolute cosine.

Eligible vertices are ordered lexicographically by TIFXYZ grid row/column.
The requested samples are deterministic even-quantile positions in that list.
No seed exists because no randomness is used.

## Output

Each planned group contains:

- TIFXYZ grid coordinate;
- continuous global XYZ surface coordinate;
- continuous global ZYX surface coordinate;
- reference normal in both XYZ and ZYX order;
- every signed offset and its continuous global coordinate;
- the recommended half-open level-0 CT bounding box for that group;
- a `wrong_wrap.status = pending-independent-geometry` marker.

The plan also hash-pins `x.tif`, `y.tif`, `z.tif`, `meta.json` and
`mask.tif` when present, plus the exact ZPA report and metadata-semantics
attestation.

## Source-frame binding

The planner requires the exact `surface_volume_token` to occur in the declared
`volume_root` and also in the TIFXYZ directory name or `meta.json`. It records
an external public `binding_url` as provenance.

For the first campaign, the official Challenge tutorial is the external binding:
it explicitly downloads
`20260317000000-on-20250728140407-9.362um.tifxyz` and renders it against
`20250728140407-9.362um-1.2m-113keV-masked.zarr`.

A filename token plus external reference is evidence for this campaign, not a
universal TIFXYZ coordinate-frame proof. Grand Prize transfer should prefer
surfaces with stronger machine-readable exact-volume binding where available.

## Next step

For each selected group:

1. supply a competing-sheet coordinate from independent geometry evidence;
2. extract the recorded box with `scroliq-ct-cutout`;
3. translate the frozen global probes into the local cutout frame;
4. freeze the v3 `scroliq-sheetness-eval` spec and its decision rule;
5. only then run `scroliq-sheetness`.

A planned artifact is not a successful experiment and does not establish sheet
identity, topology, ink, or readability.
