# PHerc0139 coverage-witness preregistration v2

**Status: frozen before the v2 witness response is read.**

This is a protocol correction to the real-papyrus calibration in issue #151.
It does not erase, amend, or reinterpret the v1 result.

## Why v2 exists

The v1 experiment is preserved as **FAIL**. Its largest deletion was 41×41
material-grid vertices and its local evaluation window was also 41×41. That
left zero outside witnesses in the 41×41 arm, so the preregistered
`outside_stability` statistic was undefined.

The v1 data nevertheless showed:

- independent `surface-m7` support at all six preselected w035 regions;
- 686–1424 supported witnesses per 41×41 window;
- supported fractions of about 0.408–0.847;
- clean 21×21 and 31×31 omission controls under the frozen rule.

Those observations are not used to tune v2.

## The one protocol change

V2 changes only the evaluation window from **41×41 to 51×51** material-grid
vertices.

The following remain unchanged:

- exact PHerc0139 w035 TIFXYZ and exact 9.362 µm CT;
- independent published `surface-m7` model/source;
- all six deletion centers;
- deletion sizes 21×21, 31×31, and 41×41;
- normal association offsets `[-2,-1,0,+1,+2]`;
- prediction and masked-CT support rules;
- +20-voxel parallel-surface falsifier;
- distance tolerances 4/8/12 voxels;
- primary 8-voxel threshold;
- minimum witness count;
- every omission/substitution decision threshold.

A 51×51 window fits all six frozen centers and leaves a five-material-vertex
annulus around the largest deletion on every side, making the already-required
outside-stability statistic measurable.

## Claim boundary

A v2 pass would still be only a real-papyrus deletion calibration. It would not
show that the witness source can discover unknown omitted papyrus without help
from the reference surface.

Stage B, if justified, must be separately preregistered before extracting
unconditioned witness candidates.
