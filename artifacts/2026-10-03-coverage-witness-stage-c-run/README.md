# Coverage-witness Stage C observation

**Research-only fresh-holdout observation for issue #151.**

The scientific protocol is already frozen on main in:

`artifacts/2026-10-03-coverage-witness-stage-c-prereg/spec.json`

Stage C does not reuse the six Stage-B decision regions. It recomputes the
fresh six-center holdout selection from the original frozen 32-probe plan
before reading any prediction response.

For each 21×21, 31×31, and 41×41 artificial omission it:

1. removes the hidden TIFXYZ interior from all candidate-generation inputs;
2. fits degree-2 and degree-3 tensor polynomial surfaces to visible 51×51
   annulus geometry only;
3. withholds a two-cell visible collar to measure continuation reliability;
4. abstains wherever the two hidden predictions differ by more than 8 voxels
   or their analytic normals have absolute cosine below 0.9;
5. scans the independently published surface-m7 prediction plus exact CT only
   at consensus locations;
6. separates target and competing normal-ray runs using the already-frozen
   distance bands;
7. reveals the hidden reference only after candidates are fixed, for scoring.

A PASS remains experimental evidence, not a completeness claim. A FAIL is
preserved without retuning the fresh holdout.
