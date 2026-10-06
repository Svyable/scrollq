# Independent harvest-QC benchmark

`scroliq-harvest-qc` tests one question: does an outside surface-rejection
metric, such as those from `vesuvius-automesh`, catch an invalid surface that
ScrollQ's own gates miss, without rejecting any independently verified good
surface? It only evaluates surfaces. Nothing it reads may influence tracing.

## Why

`vesuvius-automesh` (MIT) harvests surface without manual annotation. It
seed-sweeps VC3D's `vc_grow_seg_from_seed`, rejects candidates with texture and
physical-surface gates, and then applies a separate topology re-gate. Its
published records include a cross-roll trace whose fiber-like texture passed
every texture gate but failed the surface-lock criterion. So "looks like
papyrus" is not evidence of correct sheet geometry. Those results are the
project's own reports and are **not reproduced here**.

## Protocol

1. **Freeze** a candidate-surface manifest (`freeze`, create-only) before any
   evaluator runs. Each surface records:
   - `sha256`
   - `scroll` / `volume_id` / `bbox_zyx`
   - `truth`: `verified_good`, or `invalid` with a `failure_class`
     (`wrong_wrap`, `cross_roll`, `drift_into_air`, `skim_no_lock`,
     `page_edge_runoff`, `other`)
   - a `truth_source` that is independent of every evaluator

   The manifest also fixes the ScrollQ gates (default `ct_seating`, `ordering`,
   `topology`, `seam`, `fiber`), the candidate metrics, and each metric's
   `calibration_scrolls`. It lists the `seed_regions` used to seed or calibrate
   any evaluator. A surface that intersects a seed region of the same volume is
   refused.
2. **Decide.** ScrollQ and each external evaluator submit one decisions file.
   It is bound to the frozen `spec_sha256`, declares
   `influenced_tracing: false`, names its tool and commit or version, and gives
   `accept` / `reject` / `unknown` per surface and gate. A missing decision
   counts as `unknown`.
3. **Evaluate** with the frozen rule (`evaluate`, create-only report).

A **blind spot** is an `invalid` surface that no ScrollQ gate rejects. A gate
returning `unknown` does not count as a rejection.

| Verdict | When |
|---|---|
| `REJECT_FALSE_REJECTS` | the metric rejected any `verified_good` surface, on any scroll |
| `NOT_EVALUABLE_LOSO` | outside its calibration scrolls, the metric has no `verified_good` surface or no `invalid` one |
| `INCOMPLETE` | an undecided surface outside its calibration scrolls, or no decisions file |
| `NO_NEW_COVERAGE` | it rejects no blind spot outside its calibration scrolls |
| `PROMOTE` | otherwise: it closes at least one blind spot with no false rejects |

The report also gives 2×2 agreement between each metric and each ScrollQ gate.

### Leave-one-scroll-out for texture QC

automesh's texture/coherence gate is calibrated against a human-verified render
of one known surface. A metric's decisions on surfaces from its own calibration
scrolls are reported but never count toward `PROMOTE`. Similarity to one known
papyrus texture therefore cannot become a universal definition of a valid page.
Until a texture metric earns `PROMOTE` on out-of-calibration scrolls, it stays
supporting evidence, not a hard gate.

### Provenance

automesh's code is MIT. Its inputs are not: scroll data is EduceLab / Vesuvius
Challenge material used under the Challenge data agreement, and the surface
predictions and VC3D tracer binaries come from the Villa stack. Record each
evaluator's tool commit in its decisions file. Bind data, checkpoint and tool
provenance separately in passports; never inherit a licence from code.

## Usage

```bash
scroliq-harvest-qc self-test
scroliq-harvest-qc freeze --spec harvest-spec.json --out artifacts/<date>-harvest-qc/spec.frozen.json
scroliq-harvest-qc evaluate --spec artifacts/<date>-harvest-qc/spec.frozen.json \
  --scrollq scrollq-decisions.json --candidate automesh-decisions.json \
  --out artifacts/<date>-harvest-qc/report.json
```

The built-in control must produce each verdict as designed, and must refuse
both a seed-overlapping surface and an evaluator that steered tracing.
Otherwise the report is `unverified`.

## Status

Machinery only. No frozen real corpus and no result yet. `PROMOTE` admits a
metric as supporting QC evidence. It does not prove that harvested area is
papyrus on the correct sheet, and it is never ink evidence.
