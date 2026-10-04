# PHerc0139 public fiber census — 2026-10-04 (November N4b, pulled into October)

`scripts/fiber_scroll_census.py --scroll PHerc0139`, run in GitHub Actions; the
workflow committed `summary.json` here create-only.

## Verdict: complete

| quantity | value |
|---|---|
| fibers listed / audited | **411 / 411** (Hugging Face `spiral/PHerc0139/fibers`) |
| annotator prefixes | lt 196 · kb 193 · dj 22 |
| detector control (synthetic 10× break planted in each fiber) | **411 / 411 detected** |
| line points / control points | 1,582,185 / 13,570 |
| spans | 13,159 (10,259 native, **2,900 fallback = 22 %**) |
| status | 155 pass · 256 caution · 0 fail |
| gap / sharp-turn candidates | 1,622 / 847 |
| control-line offsets / order inversions | 0 / 0 |
| manifest SHA-256 | `a0e03b30…9966009` |

**The fallback pattern replicates on a second scroll.** All 1,622 gap candidates
are in the 246 fibers that contain fallback spans; fibers without fallback spans
have **0**. This matches PHercParis4, where the span-level test came back SUPPORTED.

## Volume range check: NONE COMPATIBLE (a 7-voxel near miss)

Fiber points span x 2,881–23,696, y 2,437–21,936, **z 2,559–76,960**. No public
PHerc0139 volume contains them all. The closest is `20260102150214`
(2.399 µm, 78 keV, level 0 76,953 × 26,511 × 26,511): **407 of 411 fibers fit**,
and 4 reach z 76,959–76,960, 7 voxels past its last slice
(`kb_20260827T203445861_000020`, `lt_20260826T111759791_000002`,
`lt_20260827T094208872_000008`, `lt_20260828T094214123_000018`). The strict rule
reports NONE COMPATIBLE. The near miss is the reason the pre-registered PHerc0139
CT tests use this volume, and it is disclosed there.
