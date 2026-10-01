# DRAFT — not filed

Prepared for the maintainer (Sven) to review, reproduce, and file against
`ScrollPrize/villa` if they agree. `AGENTS.md` requires explicit approval
before anything is opened upstream, and villa's `CONTRIBUTING.md` asks that
reports come from a human who personally reproduced the problem — the checkbox
below is deliberately **unchecked**.

Format follows villa's `.github/ISSUE_TEMPLATE/issue.md`.

---

**In one sentence:** In the open-data bucket, `PHerc0343P` volume
`20250521134555` (8.64 µm) level `0` stores 555 of its 8,543 chunk objects
(6.5 %) at 8× or 64× the size its `.zarray` declares, so a reader that honours
the metadata cannot decode those chunks.

**I was trying to:** Read the registered 8.64 µm ↔ 2.215 µm pair for
`PHerc0343P` from `s3://vesuvius-challenge-open-data` with a strict Zarr v2
reader, to compare the two scans on a common grid.

**Using:** `scroliq-chunk-audit` (this repo, PR #33; stdlib + `numpy` +
`requests`), bucket index `metadata.min.json` sha256-pinned in
`artifacts/2026-10-01-prize-targets/`, run 2026-10-01.

**What happened:** The volume's level-0 array declares

```
shape [5398, 5057, 5057]   chunks [128, 128, 128]   dtype |u1
compressor null            filters null              zarr_format 2
```

so every chunk object should be exactly 128³ = 2,097,152 bytes. Enumerating
the whole level (8,543 chunk objects) gives:

| object size | meaning | count |
|---|---|---|
| 2,097,152 | 128³ — correct | 7,988 |
| 16,777,216 | 256³ — 8× declared | 499 |
| 134,217,728 | 512³ — 64× declared | 56 |

The mismatched objects hold 14.8 GiB where the declared layout would hold
about 1.1 GiB. They are not isolated: the 8× objects sit in chunk indices
z 1–16, y 5–11, x 3–16 and the 64× objects in z 0–8, y 2–5, x 1–8, with
neighbouring keys (e.g. `0/0/3/2`, `0/0/3/3`, … consecutive x) all oversized.
Consecutive indices suggest mis-sized objects on the 128³ grid rather than a
coarser chunk grid, which would only populate every 2nd/4th index.
Levels 1–5 of the same volume are consistent, and so is the sibling 2.215 µm
volume `20260304131111`. Every object has `Last-Modified` 2026-03-04.

**What I expected or needed:** Every chunk object in an uncompressed array to
match `prod(chunks) × itemsize`, or the `.zarray` to describe what is stored.

**Evidence / reproduction:** No dependencies needed for the core observation:

```bash
B=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com
V=PHerc0343P/volumes/20250521134555-8.640um-1.2m-116keV-masked.zarr
curl -s  $B/$V/0/.zarray                                   # chunks [128,128,128], |u1, no compressor
curl -sI $B/$V/0/0/0/11 | grep -i content-length           # 2097152   (correct)
curl -sI $B/$V/0/11/7/10 | grep -i content-length          # 16777216  (256^3)
curl -sI $B/$V/0/0/3/2 | grep -i content-length            # 134217728 (512^3)
```

Full enumeration of the level (all 8,543 objects):

```bash
scroliq-chunk-audit --index artifacts/2026-10-01-prize-targets/metadata.min.json.gz \
  --volume 20250521134555 --full --out pherc0343p-full.json
```

Result committed as `pherc0343p-8.64um-full.json`. Across the whole bucket
(65 volumes, 390 levels, 942,696 sampled chunk objects) this is the only
mismatch found; an exhaustive pass over the 23 Grand Prize / First Letters
eligible volumes (4,228,772 objects) found none, so no prize target is
affected. See `chunk-audit.json` and `prize-volumes-full.json`.

- [ ] I personally encountered or reproduced this using the version and data stated above.

## Details

- We only tested our own strict reader, which rejects these chunks because
  their byte length contradicts the metadata. We did **not** test zarr-python,
  tensorstore, or VC3D, so we cannot say how other readers behave or whether
  VC3D has been silently mis-reading this region.
- The sampled audit can miss sparse defects elsewhere; "no mismatch" outside
  this volume means none was seen in ~8 listing pages per level (full pass only
  for the prize-eligible volumes).
- Possible cause (a guess, not verified): part of this level was written with
  a larger chunk shape and the metadata was not updated, or a merge step wrote
  concatenated blocks under 128³ keys. Re-uploading level 0 from the source
  would be the straightforward fix; the volume is not a prize target.
