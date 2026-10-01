# Do local scan metrics recover the documented protocol ordering? (2026-10-01)

**Short answer: no, not for these metrics.** Under the decision rule frozen in
[`docs/protocol-pairs-protocol.md`](../../docs/protocol-pairs-protocol.md) before any real-data metric
was computed, both primary metrics are **discordant** with the Challenge's
documented ordering of scan protocols. Effect sizes are small, only four
scroll pairs were testable, and this does **not** show that the metrics are
useless for other purposes. It does mean they cannot be promoted into the
diagnostic passport as a haze / layer-separability measure, and that the legacy
0–100 score must not be used to compare different scans of the same scroll.

## What was tested

For scrolls scanned under more than one protocol, the rescan's `transform.json`
registers it to the earlier scan. We sampled the same physical regions from both
scans on one common ~9 µm grid and asked whether the documented-better
(smaller-voxel) protocol scores higher on two intensity-scale-invariant metrics
(`otsu_eta`, `edge_sharpness`; definitions in the pre-registration). The
ordering is the project's own statement
(`scrollprize.org/docs/37_2026_open_problems.md`, villa `56d7c3a`); the test
checks concordance with it, nothing about readability.

## Files

| File | What it is |
|---|---|
| `discovery.json` | `scroliq-pairs --list`: every registered pair, its resolution and inclusion status. No metric computed. |
| `protocol-pairs.run1-underpowered.json`, `run1.log` | Run 1: pre-registered code. 5 / 9 / 7 / 3 regions accepted; 0 pairs reached the 12-region minimum. |
| `protocol-pairs.run2-d1-d2.json`, `run2.log` | Run 2: deviations D1, D2. 24 / 9 / 24 / 6 regions; 2 pairs included; verdict inconclusive (< 3 pairs). |
| **`protocol-pairs.json`, `run3.log`** | **Run 3 (reported below): D1–D4, `--candidate-factor 40`.** 24 regions in each of 4 pairs. |

## Result (run 3, pre-registered rule)

`d = metric(finer scan) − metric(coarser scan)`; the documented ordering predicts `d > 0`.
Typical levels, for scale: `otsu_eta` 0.74–0.82 (fine vs coarse differ by about
1–2 %); `edge_sharpness` 0.23–0.34.

| Pair (fine vs coarse, µm) | regions | metric | median d | regions d>0 | 95 % CI of median | half-step null | pair verdict |
|---|---|---|---|---|---|---|---|
| PHerc0139 (1.129 vs 2.399) | 24 | `otsu_eta` | -0.0081 | 5/24 | [-0.0163, -0.0022] | 0.0014 | discordant |
| PHerc0139 (1.129 vs 2.399) | 24 | `edge_sharpness` | -0.0757 | 0/24 | [-0.0919, -0.0633] | 0.0031 | discordant |
| PHerc0343P (2.215 vs 8.64) | 24 | `otsu_eta` | +0.0053 | 16/24 | [-0.0051, +0.0088] | 0.0022 | mixed |
| PHerc0343P (2.215 vs 8.64) | 24 | `edge_sharpness` | +0.0022 | 13/24 | [-0.0181, +0.0111] | 0.0030 | mixed |
| PHerc0814 (1.129 vs 2.399) | 24 | `otsu_eta` | -0.0109 | 1/24 | [-0.0176, -0.0083] | 0.0011 | discordant |
| PHerc0814 (1.129 vs 2.399) | 24 | `edge_sharpness` | -0.0229 | 1/24 | [-0.0397, -0.0155] | 0.0049 | discordant |
| PHercMANBp (1.129 vs 2.399) | 24 | `otsu_eta` | -0.0162 | 0/24 | [-0.0181, -0.0121] | 0.0028 | discordant |
| PHercMANBp (1.129 vs 2.399) | 24 | `edge_sharpness` | +0.0014 | 13/24 | [-0.0045, +0.0084] | 0.0037 | mixed |

Verdicts (`decide()` in `src/scrollq/protocol_pairs.py`, computed, not hand-written):

- `otsu_eta`: **discordant**, 3 of 4 pairs reverse the ordering (0139, 0814, MANBp); 0343P is mixed.
- `edge_sharpness`: **discordant**, 2 of 4 pairs reverse it (0139, 0814); 0343P and MANBp are mixed. This verdict sits
  exactly on the 50 % threshold, so it is the weaker of the two.

Every reversal occurs in the three 1.129 µm vs 2.4 µm pairs (on both metrics in
PHerc0139 and PHerc0814, on `otsu_eta` only in PHercMANBp). The one 8.6 µm vs
2.2 µm pair is indistinguishable from no effect. Each reversing effect is roughly 5–25×
larger than that pair's half-step resampling null, so the reversals are not
resampling noise.

## Controls

- **Determinism.** For every pair, run 2's accepted regions are a bit-identical
  prefix of run 3's (same centers, same metric values): raising the candidate
  budget only continued the same seeded sequence.
- **Lattice-geometry control (post-hoc arm, D4).** The primary comparison samples
  the fixed scan on its own aligned lattice and the moving scan on a rotated
  one, which could in principle bias interpolation. Re-running with both scans on
  aligned lattices and both on rotated lattices gives the same numbers
  (e.g. PHerc0139 `edge_sharpness`: −0.0757 primary, −0.0760 both aligned,
  −0.0758 both rotated). **The suspected artifact did not materialize.**

| Pair | metric | primary | both aligned | both rotated |
|---|---|---|---|---|
| PHerc0139 | `otsu_eta` | -0.0081 | -0.0078 | -0.0083 |
| PHerc0139 | `edge_sharpness` | -0.0757 | -0.0760 | -0.0758 |
| PHerc0343P | `otsu_eta` | +0.0053 | +0.0053 | +0.0053 |
| PHerc0343P | `edge_sharpness` | +0.0022 | +0.0022 | +0.0021 |
| PHerc0814 | `otsu_eta` | -0.0109 | -0.0114 | -0.0111 |
| PHerc0814 | `edge_sharpness` | -0.0229 | -0.0226 | -0.0239 |
| PHercMANBp | `otsu_eta` | -0.0162 | -0.0162 | -0.0148 |
| PHercMANBp | `edge_sharpness` | +0.0014 | -0.0006 | +0.0020 |

- **Can-fail check.** `tests/test_protocol_pairs.py` builds registered synthetic
  scans of one analytic field and requires the paired difference to flip sign
  when the finer scan is the hazy one; a mutation test breaks the registration
  and requires the sampled cubes to decorrelate.

## The legacy score at matched scale (exploratory, not part of the verdict)

| Pair | legacy score: median d | regions d>0 | `grad_energy` median d | `dyn_range` median d |
|---|---|---|---|---|
| PHerc0139 | -0.04 | 12/24 | -0.76 | +21.5 |
| PHerc0343P | -7.50 | 0/24 | -1.89 | -34.5 |
| PHerc0814 | +0.32 | 15/24 | -0.16 | +3.0 |
| PHercMANBp | -0.95 | 7/24 | +0.02 | -10.0 |

The legacy 0–100 score does not rank the finer protocol higher in any consistent
way, and in PHerc0343P it scores the *coarser* scan higher in all 24 regions.
`dyn_range` flips sign across pairs, which points at scan-specific intensity
windowing rather than protocol quality. Practical consequence, consistent with
`AGENTS.md`: **do not compare ScrollQ scores across different scans of the same
scroll.**

## Deviations from the pre-registration

Logged per the deviation policy. None changes a metric definition, an acceptance
rule or the decision rule.

| | Change | Why |
|---|---|---|
| D1 | Draw region centers from the part of the fixed volume the rescan's footprint can contain; reject out-of-volume cubes before reading. | Run 1 accepted only 5 / 9 / 7 / 3 regions: the 1.129 µm rescans cover only ~4–5 % of their fixed volumes' field of view and rejected cubes were read before being rejected. |
| D2 | A chunk whose stored size contradicts the array metadata rejects that region instead of aborting the pair. | An observed declared-vs-stored size mismatch in PHerc0343P 8.64 µm level 0 (see `../2026-10-01-bucket-chunk-audit/`). 6 candidate regions were rejected for this reason. |
| D3 | `--candidate-factor 40` (default stays 8). | After run 2, PHerc0343P and PHercMANBp had 9 and 6 regions because ~95 % of random cubes fall outside the scroll mask; the cap, not the data, excluded them. |
| D4 | Added aligned / rotated lattice arms. | The half-step null cannot detect aligned-vs-rotated interpolation asymmetry. |

**Disclosure.** D1 and D2 were made before any metric value was examined. D3 and
D4 were decided **after** run 2's per-pair numbers were visible, including the
reversed signs for PHerc0139 and PHerc0814. D3 cannot change those two pairs
(their regions are identical in run 2 and run 3) and extends the others along the
same seeded sequence; its effect is to add two pairs, which moves the formal
verdict from "inconclusive (2 pairs)" to "discordant". Weigh the verdict
accordingly: the first two pairs already pointed the same way.

## Limits and what is not covered

- **Four independent pairs**, three of them the same protocol comparison
  (1.129 µm / 59 keV vs 2.4 µm / 78 keV). Regions inside a pair are spatially
  correlated; the replication unit is the pair.
- **The 7.91 µm DLS vs 2.4 µm ESRF pairs were not run**, including the PHercParis4
  pair the Open Problems page illustrates: their fixed scans live on
  `data.aws.ash2txt.org`, which this environment's egress policy refuses
  (`run failed` in `protocol-pairs.json`). Their outcome is **unknown**, not
  absent and not negative; they count automatically when `scroliq-pairs` runs
  where that host is reachable.
- **Confounded protocols.** Pairs differ in energy and propagation distance as
  well as voxel size; a discordant result cannot be attributed to one factor.
  A 59 keV and a 78 keV scan have different attenuation contrast, which these
  contrast-ratio metrics may track instead of haze.
- **Matched-scale sampling does not match noise**, and the pyramid's downsampling
  filter is undocumented in the bucket metadata. The finer scan is downsampled
  ~8.5× versus ~4× for the coarser one.
- **A documented ordering at native resolution need not hold at a matched coarse
  scale.** Haze acts on fine fiber structure the 9 µm grid averages away. That is
  an alternative reading of the same result, which this test cannot exclude.
- Registration residuals up to 50 µm were tolerated against ~0.6 mm cubes.

## Reproduce

```bash
IDX=artifacts/2026-10-01-bucket-index/metadata.min.json.gz
scroliq-pairs --index $IDX --list --out out/discovery.json
scroliq-pairs --index $IDX --candidate-factor 40 --out out/protocol-pairs.json   # ~40 min, ~2.9 GB read
scroliq-pairs --index $IDX --sensitivity --candidate-factor 40 --out out/sens.json
```
