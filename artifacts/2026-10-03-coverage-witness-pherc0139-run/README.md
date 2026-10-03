# PHerc0139 coverage-witness deletion observation

**Research-only observation for issue #151.**

The scientific protocol is already frozen on `main` in:

`artifacts/2026-10-03-coverage-witness-pherc0139-prereg/spec.json`

This directory is the create-only measured output of that protocol.

The runner:

1. downloads the exact PHerc0139 w035 TIFXYZ named in the frozen spec;
2. verifies its frozen SHA-256 identities;
3. samples the independently published `surface-m7` prediction and exact
   masked CT using only the frozen ±2-voxel normal search;
4. measures independent witness support in all six frozen 41x41 windows;
5. applies the preregistered 21x21, 31x31 and 41x41 omissions;
6. applies the preregistered +20-voxel parallel-surface substitution;
7. evaluates nearest-surface distances at the frozen 4/8/12-voxel tolerances;
8. writes the measured result without changing a threshold or replacing a
   low-support patch.

A pass is **not** an INCLUDE decision. The frozen spec explicitly makes this
Stage A a necessary-but-insufficient calibration. The useful evidence is both
the preregistered decision and the descriptive distribution of independently
supported witness density across the frozen real-papyrus windows.

If Stage A is positive and witness support is broad enough to justify another
experiment, Stage B must be preregistered separately and extract witness
candidates without conditioning them on the known surface.
