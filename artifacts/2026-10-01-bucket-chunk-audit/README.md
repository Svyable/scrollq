# Open-bucket chunk-size audit (2026-10-01)

Do the stored chunk objects in `s3://vesuvius-challenge-open-data` match what
each array's `.zarray` declares? For an uncompressed Zarr v2 array every chunk
object must be exactly `prod(chunks) × itemsize` bytes, edge chunks included.
S3 listings carry object sizes, so the check downloads no chunks.

Tool: `scroliq-chunk-audit` (`src/scrollq/chunk_audit.py`). Input index:
`../2026-10-01-prize-targets/metadata.min.json.gz`.

## Results

| Pass | Scope | Chunk objects checked | Outcome |
|---|---|---|---|
| `chunk-audit.json` (sampled) | 65 bucket volumes, 390 levels | 942,696 | 383 levels consistent, **1 mismatch**, 6 not applicable (compressed: PHerc0172 `20241024131838`), 0 unverified |
| `prize-volumes-full.json` (every object) | the 23 Grand Prize / First Letters eligible volumes, 138 levels | 4,228,772 | all consistent |
| `pherc0343p-8.64um-full.json` (every object) | PHerc0343P `20250521134555`, 6 levels | level 0: 8,543 | **level 0 defective**, levels 1–5 consistent |

**The one defect:** PHerc0343P 8.64 µm level 0 declares 128³ chunks (2,097,152
bytes) but 555 of 8,543 chunk objects (6.5 %) are 8× (499 objects, 256³) or
64× (56 objects, 512³) that size, 14.8 GiB where the declared layout holds about
1.1 GiB. The sibling 2.215 µm volume is consistent. It is not a prize target. A
maintainer-ready, **unfiled** write-up is in `UPSTREAM-ISSUE-DRAFT.md`.

## Method and limits

- **Positive control.** The defect was measured by hand first (HEAD requests on
  `0/11/7/10`: 16,777,216 bytes) and the audit must, and does, flag it.
- **Fail closed.** A level with no chunk objects checked is `unverified`, never
  `ok`. The first draft of this scan used a regex over the listing XML and
  silently checked **zero** objects in every level, reporting "0 mismatches over
  390 levels"; S3 inserts `ChecksumAlgorithm`/`ChecksumType` elements that the
  regex did not expect. It was caught because that run missed the hand-measured
  defect. The parser is now a real XML parser and `tests/test_chunk_audit.py`
  covers the true response shape.
- **Sampled mode** lists two pages from the start of each level plus six pages
  at random z positions. It can miss sparse defects; "ok" there means none was
  seen. Only the prize-eligible volumes were enumerated exhaustively.
- Only our own strict reader was used to confirm the effect; other readers
  (zarr-python, tensorstore, VC3D) were not tested.

## Reproduce

```bash
IDX=artifacts/2026-10-01-prize-targets/metadata.min.json.gz
scroliq-chunk-audit --index $IDX --out chunk-audit.json                       # sampled, ~30 s
scroliq-chunk-audit --index $IDX --volume 20250521134555 --full --out p.json  # one volume, exhaustive
```
