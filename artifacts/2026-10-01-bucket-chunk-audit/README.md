# Open-bucket chunk-size audit (2026-10-01)

Do the stored chunk objects in `s3://vesuvius-challenge-open-data` match what
each array's `.zarray` declares? For an uncompressed Zarr v2 array every chunk
object must be exactly `prod(chunks) × itemsize` bytes, edge chunks included.
S3 listings carry object sizes, so the check downloads no chunks.

Tool: `scroliq-chunk-audit` (`src/scrollq/chunk_audit.py`). Input index:
`../2026-10-01-bucket-index/metadata.min.json.gz`.

## Results

| Pass | Scope | Chunk objects checked | Outcome |
|---|---|---|---|
| `chunk-audit.json` (sampled) | 65 bucket volumes, 390 levels | 942,696 | 383 levels consistent, **1 mismatch**, 6 not applicable (compressed: PHerc0172 `20241024131838`), 0 unverified |
| `prize-volumes-full.json` (every object) | the 23 Grand Prize / First Letters eligible volumes, 138 levels | 4,228,772 | all consistent |
| `pherc0343p-8.64um-full.json` (every object) | PHerc0343P `20250521134555`, 6 levels | level 0: 8,543 | **level 0 mismatch**, levels 1–5 consistent |

**The one mismatch:** PHerc0343P 8.64 µm level 0 declares 128³ chunks (2,097,152
bytes) but 555 of 8,543 chunk objects (6.5 %) are 8× (499 objects, 256³) or
64× (56 objects, 512³) that size, 14.8 GiB where the declared layout holds about
1.1 GiB. The sibling 2.215 µm volume is consistent. It is not a prize target. A
maintainer-ready, **unfiled** write-up is in `UPSTREAM-ISSUE-DRAFT.md`.

## Independent recheck (2026-10-01)

Before this finding is described to anyone as a data problem, it was re-derived
from the committed inputs by routes that do not share the audit tool's code:

| Route | Result |
|---|---|
| Fresh `scroliq-chunk-audit --full` on the committed index snapshot, diffed against `pherc0343p-8.64um-full.json` | identical (status, counts, size histogram, index hash) |
| Separate stdlib enumeration of the level-0 listing (`xml.etree`, no repository code) | 8,543 chunk objects; sizes 2,097,152 ×7,988, 16,777,216 ×499, 134,217,728 ×56 |
| HEAD `Content-Length` vs listing `Size`, 190 random objects (150 any + 40 oversize) | 0 disagreements |
| Full `GET` of one object of each oversize class | exactly 16,777,216 and 134,217,728 bytes |

**Known:** the stored object sizes contradict the declared chunk shape, and a
strict reader that checks byte length (ours) cannot decode those chunks.
**Not known:** the cause; how other readers (zarr-python, tensorstore, VC3D)
behave; whether the maintainers consider it a problem. Nothing has been
reported upstream. Treat it as an **observed mismatch**, not a confirmed
defect.

**Unknown is not absent.** The audit separates an HTTP 404 (absent) from an
unavailable object (network failure, 5xx, 403). An unavailable `.zattrs`,
`.zarray` or listing leaves the volume or level `unverified` with an
`unavailable:` detail and a non-zero exit; it is never read as "missing" or as
"corrupt". Covered by `tests/test_chunk_audit.py`.

## Method and limits

- **Positive control.** The mismatch was measured by hand first (HEAD requests on
  `0/11/7/10`: 16,777,216 bytes) and the audit must, and does, flag it.
- **Fail closed.** A level with no chunk objects checked is `unverified`, never
  `ok`. The first draft of this scan used a regex over the listing XML and
  silently checked **zero** objects in every level, reporting "0 mismatches over
  390 levels"; S3 inserts `ChecksumAlgorithm`/`ChecksumType` elements that the
  regex did not expect. It was caught because that run missed the hand-measured
  mismatch. The parser is now a real XML parser and `tests/test_chunk_audit.py`
  covers the true response shape.
- **Sampled mode** lists two pages from the start of each level plus six pages
  at random z positions. It can miss sparse mismatches; "ok" there means none was
  seen. Only the prize-eligible volumes were enumerated exhaustively.
- Only our own strict reader was used to confirm the effect; other readers
  (zarr-python, tensorstore, VC3D) were not tested.

## Reproduce

```bash
IDX=artifacts/2026-10-01-bucket-index/metadata.min.json.gz
scroliq-chunk-audit --index $IDX --out chunk-audit.json                       # sampled, ~30 s
scroliq-chunk-audit --index $IDX --volume 20250521134555 --full --out p.json  # one volume, exhaustive
```
