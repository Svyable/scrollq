# DRAFT — not filed

Prepared for the maintainer (Sven) to review, reproduce and file if they agree.
`AGENTS.md` requires explicit approval before anything is opened upstream, and
villa's contributing guide asks for reports from a human who personally
reproduced the problem, so the checkbox below is deliberately **unchecked**.
Format mirrors `../2026-10-01-bucket-chunk-audit/UPSTREAM-ISSUE-DRAFT.md`.

---

**In one sentence:** In the open-data bucket, the PHerc0814 surface volume
`segments/20260226123353-auto_grown_20260226123353106/surface-volumes/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr`
has `.zarray` headers for all six pyramid levels but **no chunk objects at
all**, so every read silently returns the fill value `0`.

**I was trying to:** Run a header + listing integrity audit
(`zarr-pyramid-audit`, via `scrollq-health`) over every OME-Zarr root in
`s3://vesuvius-challenge-open-data`. This was the one root out of 957 that
failed.

**What happened:** Each level `0`–`5` contains exactly one object, `.zarray`.
Level 0 declares:

```
shape [116, 1940, 4620]   chunks [116, 128, 128]   dtype |u1
compressor null           fill_value 0             zarr_format 2
```

i.e. 16 × 37 = 592 chunk objects are expected at level 0 alone; 0 are stored.
Because a missing chunk is legal in Zarr v2 (it means "fill value"), zarr-python
and similar readers return an all-zero volume with no error.

**What I expected or needed:** Either the rendered surface-volume chunks, or
no `.zarray` headers (so the volume does not advertise data it lacks).

**Evidence / reproduction** (rechecked live 2026-10-04, no dependencies):

```bash
B=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com
R=PHerc0814/segments/20260226123353-auto_grown_20260226123353106/surface-volumes/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr
curl -s "$B/$R/0/.zarray"
for l in 0 1 2 3 4 5; do
  curl -s "$B/?list-type=2&prefix=$R/$l/" | grep -o '<KeyCount>[0-9]*</KeyCount>'
done   # every level: <KeyCount>1</KeyCount>  (only .zarray)
```

ScrolIQ's frozen verdict: `artifacts/2026-10-01-health-verdicts-fail-closed/do-not-train-pherc0814.json`
(`DO NOT TRAIN`, six high-severity `LEVEL_NO_CHUNKS`). First seen in the
2026-09-29 zarr-pyramid-audit bucket survey (957 roots, 956 clean).

- [ ] I personally encountered or reproduced this using the version and data stated above.

## Details

- Only this surface volume is affected in our survey. PHerc0814 is not one of
  the 2027 Grand Prize or First Letters eligible volumes.
- We do not know whether the render failed, the upload was interrupted, or the
  segment was intentionally withdrawn. Removing the headers or re-uploading
  the chunks would both stop silent all-zero reads.
