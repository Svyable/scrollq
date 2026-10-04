# Fiber span test — pre-registration (October stretch goal O7)

**Status: frozen before any span-level data is read.**

The [2026-10-04 census](../2026-10-04-fiber-corpus-census/) found all 388 gap
candidates in the 79 fibers that contain fallback-interpolated spans. That is a
fiber-level co-occurrence. This test asks the sharper span-level question: inside
the fibers, do gaps sit in fallback spans more often than in native trace spans?

`spec.json` freezes the definitions, the decision rule, and two controls that run
on the real span structure. In the positive control, gaps are planted only in
fallback spans, and the decision must return SUPPORTED. In the null control,
gaps are drawn independently of mode, and the decision must return SUPPORTED in
at most 10 % of 200 replicates. If either control fails, the verdict is
`CONTROL FAILURE`.

`scripts/fiber_span_test.py` pins the SHA-256 of `spec.json` and refuses to run
if it changed. Its statistics are unit-tested on synthetic fibers
(`tests/test_fiber_span_test.py`) before the run. The run happens in GitHub
Actions (`.github/workflows/fiber-span-test.yml`), which is added in a later
commit than this pre-registration.

What the verdict can and cannot mean is listed in `interpretation_limits`. A
SUPPORTED result shows an association, not a cause; the descriptive mechanism arm
checks whether fallback spans are simply rendered with longer steps.
