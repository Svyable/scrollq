# PHercParis4 fiber CT support — result (October stretch goal O9, step 2)

Run of the test frozen in [`../2026-10-04-paris4-fiber-ct-support-prereg/`](../2026-10-04-paris4-fiber-ct-support-prereg/)
(spec SHA-256 `e2b0f6ff…e79e42`, pushed in `8201ed7` before the run workflow
existed). Deviations: none.

- **Run 1** ([37169930475](https://github.com/Svyable/scrollq/actions/runs/37169930475), `03ec291`):
  verdict and numbers below, read from the job log. Its Actions artifact could
  not be fetched into the repo because of the development proxy.
- **Run 2** ([37170123443](https://github.com/Svyable/scrollq/actions/runs/37170123443), `255a3b1`):
  identical deterministic re-execution. The workflow committed `result.json`
  here create-only. Every number below was checked against both runs.

## Verdict: SUPPORTED (wrong-frame control passed)

Volume `PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr`,
level 1 (4.8 µm), 16 points per fiber, 136 fibers, 10,880 single-voxel range reads
(470 from absent chunks, i.e. masked background; 0 out of bounds).

| comparison against same-region background (R) | AUC | 95% CI (fiber-cluster bootstrap) |
|---|---:|---|
| fiber points (F) | **0.775** | 0.760 – 0.789 |
| fibers displaced ±272 µm (S) | 0.555 | — |
| specificity F − S | **0.221** | 0.207 – 0.233 |
| axis-swapped fibers (X, wrong frame) | 0.429 | 0.403 – 0.455 |

- **Per fiber:** 0 of 136 fibers have AUC ≤ 0.5 against their own background,
  against 38 of 136 displaced fibers (27.9%). With only 16 points per fiber, the
  per-fiber flag is a weak detector even though the pooled effect is strong.
  Treat it as a review cue.
- **Zero voxels:** 0.4% of fiber points, 5.5% of background points and 17.7% of
  axis-swapped points.

## What it means

The 136 public PHercParis4 fibers, read in the frame of 20260411134726, sit on
markedly denser material than nearby random points, and the effect is specific
to their traced positions. Together with the range check
(`../2026-10-04-paris4-fiber-binding/`), this is the first measured evidence for
which public volume the fibers belong to.

It is **not** a declared binding. The dataset names no volume, the two 7.91 µm
volumes cannot be checked, and a scan sharing this frame cannot be excluded.
Density is also not papyrus identity, fiber direction or sheet identity. CT
fiber direction is November N4(c).
