# Cross-ply seam substitution preregistration

**Status: frozen after the spectrum-v1 development failure and before any PHerc0139 cross-ply frame response is read.**

The first CT-local identity descriptor failed cleanly: on all ten usable development
regions the adjacent-winding controls were *closer* than the same-sheet material
neighbors under the frozen aggregate angular spectrum. That descriptor is dismissed;
the untouched holdout is not being spent on it.

This experiment changes the physical question.

Instead of asking whether two papyrus patches have a similar texture distribution,
it asks whether the already-implemented cross-ply fiber frame remains continuous
across a local seam. For each of the same ten **development** centers, it samples a
64×64×9 tangent-frame CT slab from the known w035 surface and another from the
already-frozen adjacent winding. Two counterfactual slabs replace exactly one half
of the target slab with the adjacent-winding slab. The intact target slab is the
false-positive control.

The analyzer and thresholds are not chosen from PHerc0139 frame outputs. They are
the synthetic-tested `scroliq-fiber-frame` parameters already merged before this
preregistration: 16×16 tiles, sigma 1, coherence 0.35, two-mode separation 25°,
minimum mode share 0.15, and a 25° switch threshold.

Only the four tile-neighbor comparisons crossing the x=32 substitution seam count.
A group is detected when at least two seam comparisons exceed 25°. Both
target→wrong and wrong→target substitutions must clear the frozen gate, while intact
false positives must remain low.

The same ten development regions may be reused because this is method development;
the ten holdout regions remain unread. A development pass can only unlock a
separate holdout preregistration. A failure dismisses this seam statistic without
tuning it on holdout.

No ink and no surface-prediction values are read.
