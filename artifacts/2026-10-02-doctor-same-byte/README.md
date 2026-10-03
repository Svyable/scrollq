# Same-byte Mesh IQ × TIFXYZ Doctor cross-validation — 2026-10-02

This campaign runs **ScrolIQ Mesh IQ and TIFXYZ Doctor evidence over the same
SHA-256-pinned TIFXYZ bytes**. It exists to test interoperability and catch
calibration mistakes, not to declare one tool superior.

The workflow pins TIFXYZ Doctor at
`5ca0444fb31863c8e02466316bf9e560cf567876`, downloads its 10-case public
real-data benchmark, verifies every input file against the rival manifest, and
then runs the current `audit_tifxyz()` on those exact bytes.

Frozen measurement run: GitHub Actions `37095038435`, commit
`fba4743a4dc8958b0bdd0e72f9b9517f7a5bd7e1`. A later workflow run
(`37095165144`) regenerated the same pinned-byte campaign and passed
`verify.py` against this frozen summary after ignoring only the run timestamp
and ScrolIQ commit SHA.

## Result

Input contract:

- **10** cases, **1,818,055 bytes** downloaded and SHA-256 verified.
- **4** cases have an enclosed-hole signal in the Doctor output and **6** do
  not, so an always-clean checker cannot pass the comparison.
- Benchmark roles are provenance labels, **not geometry ground truth**.

Shared topology:

| comparison | agreement |
|---|---:|
| enclosed-hole **presence** | **10 / 10** |
| single-component **presence** | **10 / 10** |
| Grand Prize overlap (PHerc0800 + PHerc1447), hole presence | **7 / 7** |
| exact enclosed-hole count | 6 / 10 |

The exact hole-count mismatch is expected to be treated separately: Mesh IQ
counts enclosed components of the invalid **vertex** grid, while the Doctor
result reports enclosed **face-lattice** holes. Presence is directly
comparable; raw component counts are not the same observable.

## The benchmark found and fixed a Mesh IQ bug

The first same-byte run had perfect topology-presence agreement but exposed
three spurious Mesh IQ `isometry-distortion` findings on official Villa
fixture controls. Mesh IQ had treated TIFXYZ `meta.scale` as a universal
physical edge-length contract.

That assumption was removed. Default isometry now normalizes by the observed
median 3D step in each parameter direction; callers can supply explicit
`--expected-spacing-x` and `--expected-spacing-y` only when such a physical
spacing contract is actually known.

After the fix:

- TIFXYZ Doctor reports all 10 cases below its symmetric-stretch review
  threshold.
- Mesh IQ has **0 isometry false-positive candidates** on those 10 cases.
- On the three official Villa controls, the two independent p95 measurements
  nearly coincide:

| case | Mesh IQ p95 | Doctor p95 |
|---|---:|---:|
| PHerc0172 20241113070770 | 1.03339 | 1.03217 |
| PHerc0172 20241113080880 | 1.02829 | 1.02808 |
| PHerc0172 20241113090990 | 1.02807 | 1.02758 |

This is a stronger outcome than merely preserving a favorable comparison: the
external benchmark changed our implementation and the post-fix run measures the
effect.

## Reproduce

```bash
python -m pip install .
python scripts/doctor_same_byte_benchmark.py --out /tmp/doctor-same-byte.json
python artifacts/2026-10-02-doctor-same-byte/verify.py \
  /tmp/doctor-same-byte.json \
  artifacts/2026-10-02-doctor-same-byte/summary.json
```

The scheduled/manual workflow is
`.github/workflows/doctor-same-byte.yml`.

## Claim boundary

- TIFXYZ Doctor's benchmark roles are not labels of correct/incorrect physical
  sheet geometry.
- Agreement on local topology does not prove sheet identity, recto coverage,
  or readable ink.
- The two tools have different scopes and thresholds; only directly comparable
  facts are treated as concordance.
- No downloaded Vesuvius TIFXYZ bytes are redistributed here; this directory
  contains derived evidence and reproduction code only.
