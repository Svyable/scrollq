# PHerc0139 fiber CT support — pre-registration (replication of O9)

**Status: frozen before any PHerc0139 CT voxel is read at a fiber position.**

This is the [PHercParis4 CT support design](../2026-10-04-paris4-fiber-ct-support-prereg/)
unchanged (groups, offsets, level, statistics, decision rule and wrong-frame
control), applied to the 411 PHerc0139 census fibers in
`20260102150214` (2.399 µm). Only the seeds and the inputs differ.

**Volume choice, disclosed:** no PHerc0139 volume passes the strict range check.
This one contains 407 of 411 fibers; the other 4 overshoot its last slice by at
most 7 voxels. Their out-of-bounds points are kept and read as 0, which counts
against the fibers.
